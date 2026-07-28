"""Smoke test: confirm the package imports cleanly under pytest."""
from src.pricing.black_scholes import bs_price, bs_greeks
from src.pricing.implied_vol import implied_vol


def test_pricing_imports():
    # If the imports above resolved, the package is visible to pytest.
    price = bs_price(100, 100, 1.0, 0.05, 0.20, 0.0, "call")
    assert round(price, 4) == 10.4506


def test_iv_roundtrip():
    price = bs_price(100, 100, 1.0, 0.05, 0.20, 0.0, "call")
    recovered = implied_vol(price, 100, 100, 1.0, 0.05, 0.0, "call")
    assert abs(recovered - 0.20) < 1e-6