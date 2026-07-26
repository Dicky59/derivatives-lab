from pathlib import Path

from alpaca.data.enums import DataFeed, OptionsFeed

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# Each entry tracks when it was added so universe history has no silent gaps.
UNIVERSE = [
    {"symbol": "SPY", "added": "2026-07-26"},
]

OPTIONS_FEED = OptionsFeed.INDICATIVE  # free tier; OPRA requires a subscription
STOCK_FEED = DataFeed.IEX  # free tier; SIP requires a subscription

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0  # doubles each retry: 1s, 2s, 4s

RISK_FREE_RATE = 0.039  # PLACEHOLDER flat short rate (~3mo T-bill, ~3.9% as of 2026-07); refine to a real curve later
DIVIDEND_YIELD = 0.012  # PLACEHOLDER flat SPY dividend yield; refine later
