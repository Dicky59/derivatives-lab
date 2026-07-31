"""Daily underlying price history for backtest outcome measurement.

Surface snapshots are twice-daily and only days old, but the UNDERLYING price
series exists for years — so realized-outcome machinery can be verified against
real market history today, even though surface-derived signals can't be
backtested far back yet.
"""
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv          # <-- add
from pathlib import Path                # <-- add

# Load .env from repo root so APCA keys are available (same as other scripts)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")   # <-- add

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed


def fetch_daily_bars(symbol, start, end=None, feed=DataFeed.IEX):
    """
    Daily bars for `symbol` between start and end (datetimes or 'YYYY-MM-DD').
    Free tier => IEX feed. Returns a DataFrame indexed by date with a 'close' col.
    """
    key = os.environ["APCA_API_KEY_ID"]
    sec = os.environ["APCA_API_SECRET_KEY"]
    client = StockHistoricalDataClient(key, sec)

    if isinstance(start, str):
        start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    if end is None:
        end = datetime.now(timezone.utc)
    elif isinstance(end, str):
        end = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)

    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=start, end=end, feed=feed)
    bars = client.get_stock_bars(req).df
    if bars.empty:
        return pd.DataFrame(columns=["close"])
    # df is multi-indexed (symbol, timestamp); flatten to date -> close
    bars = bars.reset_index()
    out = pd.DataFrame({
        "date": pd.to_datetime(bars["timestamp"]).dt.tz_convert("UTC").dt.date,
        "close": bars["close"].astype(float),
    }).set_index("date").sort_index()
    return out


def realized_vol_over(prices, start_date, horizon_days):
    """
    Annualized realized vol of daily log-returns over the `horizon_days` trading
    days STRICTLY AFTER start_date. Returns None if not enough forward data.

    prices: DataFrame indexed by date with 'close' (from fetch_daily_bars).
    """
    dates = list(prices.index)
    future = [d for d in dates if d > start_date]
    if len(future) < horizon_days + 1:
        return None                       # forward window runs off the data
    window = future[:horizon_days]
    closes = prices.loc[window, "close"].values
    if len(closes) < 2:
        return None
    rets = np.diff(np.log(closes))
    return float(np.std(rets) * np.sqrt(252))