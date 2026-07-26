"""M0: single-shot options-chain snapshot collector.

Captures one snapshot timestamp across the configured universe: underlying price
plus the full option chain, flattened to one row per contract, written as a new
append-only Parquet file. Run this once per invocation; cadence is driven
externally (e.g. Windows Task Scheduler), not by an internal loop.
"""

import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config

from alpaca.common.exceptions import APIError
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, StockLatestTradeRequest

OCC_SYMBOL_RE = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<right>[CP])(?P<strike>\d{8})$")


class AuthenticationError(Exception):
    pass


def setup_logging() -> logging.Logger:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("collector")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.FileHandler(config.LOG_DIR / "collector.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


def load_credentials(logger: logging.Logger) -> tuple[str, str]:
    load_dotenv(config.BASE_DIR / ".env")
    key_id = os.environ.get("APCA_API_KEY_ID", "").strip()
    secret_key = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if not key_id or not secret_key:
        logger.error("Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY — set them in .env before running.")
        sys.exit(1)
    return key_id, secret_key


def call_with_retries(func, *, logger: logging.Logger, description: str):
    last_exc = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return func()
        except APIError as exc:
            if exc.status_code in (401, 403):
                raise AuthenticationError(
                    f"Authentication failed ({exc.status_code}) while {description}"
                ) from exc
            last_exc = exc
            logger.warning("Attempt %d/%d failed while %s: %s", attempt, config.MAX_RETRIES, description, exc)
        except Exception as exc:  # network errors, timeouts, etc.
            last_exc = exc
            logger.warning("Attempt %d/%d failed while %s: %s", attempt, config.MAX_RETRIES, description, exc)
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    raise last_exc


def parse_occ_symbol(symbol: str) -> tuple[date, float, str]:
    match = OCC_SYMBOL_RE.match(symbol)
    if not match:
        raise ValueError(f"unparseable OCC option symbol: {symbol}")
    yy, mm, dd = int(match["yy"]), int(match["mm"]), int(match["dd"])
    expiry = date(2000 + yy, mm, dd)
    right = "call" if match["right"] == "C" else "put"
    strike = int(match["strike"]) / 1000.0
    return expiry, strike, right


def fetch_underlying_price(stock_client: StockHistoricalDataClient, symbol: str, logger: logging.Logger):
    def _do():
        req = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=config.STOCK_FEED)
        result = stock_client.get_stock_latest_trade(req)
        return result[symbol].price

    try:
        return call_with_retries(_do, logger=logger, description=f"fetching underlying price for {symbol}")
    except AuthenticationError:
        raise
    except Exception as exc:
        logger.warning(
            "Underlying price fetch failed for %s after retries — writing null underlying_price "
            "(this snapshot is compromised for IV purposes): %s",
            symbol,
            exc,
        )
        return None


def fetch_option_chain(option_client: OptionHistoricalDataClient, symbol: str, logger: logging.Logger):
    def _do():
        req = OptionChainRequest(underlying_symbol=symbol, feed=config.OPTIONS_FEED)
        return option_client.get_option_chain(req)

    return call_with_retries(_do, logger=logger, description=f"fetching option chain for {symbol}")


def flatten_snapshot(
    option_symbol: str,
    snapshot,
    underlying_symbol: str,
    underlying_price,
    snapshot_ts: datetime,
    logger: logging.Logger,
):
    try:
        expiry, strike, right = parse_occ_symbol(option_symbol)
    except ValueError as exc:
        logger.warning("Skipping contract with unparseable symbol: %s", exc)
        return None

    quote = getattr(snapshot, "latest_quote", None)
    trade = getattr(snapshot, "latest_trade", None)
    greeks = getattr(snapshot, "greeks", None)

    return {
        "snapshot_ts_utc": snapshot_ts,
        "underlying_symbol": underlying_symbol,
        "underlying_price": underlying_price,
        "option_symbol": option_symbol,
        "expiry": expiry,
        "strike": strike,
        "right": right,
        "bid": getattr(quote, "bid_price", None),
        "ask": getattr(quote, "ask_price", None),
        "bid_size": getattr(quote, "bid_size", None),
        "ask_size": getattr(quote, "ask_size", None),
        "last": getattr(trade, "price", None),
        # Not exposed by OptionsSnapshot in alpaca-py 0.43.5 (no daily-volume field on
        # the market-data snapshot) — left null rather than mislabeling last-trade size.
        "volume": None,
        # Not exposed by the market-data snapshot endpoint at all; would require a
        # separate TradingClient.get_option_contracts() join. Left null for M0.
        "open_interest": None,
        "iv": getattr(snapshot, "implied_volatility", None),
        "delta": getattr(greeks, "delta", None),
        "gamma": getattr(greeks, "gamma", None),
        "theta": getattr(greeks, "theta", None),
        "vega": getattr(greeks, "vega", None),
        "rho": getattr(greeks, "rho", None),
        "quote_ts": getattr(quote, "timestamp", None),
        "feed": config.OPTIONS_FEED.value,
    }


def write_snapshot(df: pd.DataFrame, snapshot_ts: datetime) -> Path:
    date_str = snapshot_ts.strftime("%Y-%m-%d")
    ts_str = snapshot_ts.strftime("%Y%m%dT%H%M%SZ")
    partition_dir = config.DATA_DIR / "snapshots" / f"date={date_str}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    out_path = partition_dir / f"snapshot_{ts_str}.parquet"
    df.to_parquet(out_path, engine="pyarrow", index=False)
    return out_path


def run_snapshot(logger: logging.Logger) -> None:
    key_id, secret_key = load_credentials(logger)
    option_client = OptionHistoricalDataClient(key_id, secret_key)
    stock_client = StockHistoricalDataClient(key_id, secret_key)

    snapshot_ts = datetime.now(timezone.utc)
    rows = []
    per_ticker_counts: dict[str, int] = {}
    failed_tickers: list[str] = []

    for entry in config.UNIVERSE:
        symbol = entry["symbol"]
        underlying_price = fetch_underlying_price(stock_client, symbol, logger)

        try:
            chain = fetch_option_chain(option_client, symbol, logger)
        except AuthenticationError:
            raise
        except Exception as exc:
            logger.error("Failed to fetch option chain for %s after retries — skipping ticker: %s", symbol, exc)
            failed_tickers.append(symbol)
            per_ticker_counts[symbol] = 0
            continue

        if not chain:
            logger.warning("Empty option chain returned for %s — skipping", symbol)
            failed_tickers.append(symbol)
            per_ticker_counts[symbol] = 0
            continue

        count = 0
        for option_symbol, contract_snapshot in chain.items():
            row = flatten_snapshot(option_symbol, contract_snapshot, symbol, underlying_price, snapshot_ts, logger)
            if row is not None:
                rows.append(row)
                count += 1
        per_ticker_counts[symbol] = count

    if not rows:
        logger.error("No contract rows collected this run — nothing written. Failed tickers: %s", failed_tickers)
        sys.exit(1)

    df = pd.DataFrame(rows)
    df["snapshot_ts_utc"] = pd.to_datetime(df["snapshot_ts_utc"], utc=True)
    df["quote_ts"] = pd.to_datetime(df["quote_ts"], utc=True)
    out_path = write_snapshot(df, snapshot_ts)

    summary = ", ".join(f"{sym}={cnt}" for sym, cnt in per_ticker_counts.items())
    logger.info(
        "Snapshot %s complete | contracts: %s | total=%d | wrote %s | failed=%s",
        snapshot_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        summary,
        len(df),
        out_path,
        failed_tickers or "none",
    )


def main() -> None:
    logger = setup_logging()
    try:
        run_snapshot(logger)
    except AuthenticationError as exc:
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
