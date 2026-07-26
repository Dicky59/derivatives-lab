"""European Black–Scholes–Merton pricing (with continuous dividend yield)."""
import numpy as np
from scipy.stats import norm


def bs_price(S, K, T, r, sigma, q=0.0, option_type="call"):
    """
    Black–Scholes–Merton price for a European option.

    S     : spot price of the underlying
    K     : strike price
    T     : time to expiry, in YEARS
    r     : risk-free rate (continuous, annualized), e.g. 0.04
    sigma : volatility (annualized), e.g. 0.20
    q     : continuous dividend yield, e.g. 0.012 for SPY
    option_type : "call" or "put"
    """
    # Guard the degenerate case: at/after expiry, value is just intrinsic.
    if T <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return intrinsic

    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif option_type == "put":
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
    else:
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

def bs_greeks(S, K, T, r, sigma, q=0.0, option_type="call"):
    """
    Analytical Black–Scholes–Merton greeks (European).
    Returns a dict: delta, gamma, vega, theta, rho.

    Conventions:
      - vega  is per 1 percentage-point vol move (divided by 100)
      - theta is per calendar DAY (divided by 365)
      - rho   is per 1 percentage-point rate move (divided by 100)
    """
    if T <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}

    sqrtT = np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT

    pdf_d1 = norm.pdf(d1)               # N'(d1) — the bell curve
    disc_q = np.exp(-q * T)
    disc_r = np.exp(-r * T)

    # Gamma and vega are identical for calls and puts
    gamma = disc_q * pdf_d1 / (S * sigma * sqrtT)
    vega  = S * disc_q * pdf_d1 * sqrtT / 100.0     # per 1 vol point

    if option_type == "call":
        delta = disc_q * norm.cdf(d1)
        theta = (-S * disc_q * pdf_d1 * sigma / (2 * sqrtT)
                 - r * K * disc_r * norm.cdf(d2)
                 + q * S * disc_q * norm.cdf(d1)) / 365.0
        rho   = K * T * disc_r * norm.cdf(d2) / 100.0
    elif option_type == "put":
        delta = -disc_q * norm.cdf(-d1)
        theta = (-S * disc_q * pdf_d1 * sigma / (2 * sqrtT)
                 + r * K * disc_r * norm.cdf(-d2)
                 - q * S * disc_q * norm.cdf(-d1)) / 365.0
        rho   = -K * T * disc_r * norm.cdf(-d2) / 100.0
    else:
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}

if __name__ == "__main__":
    import numpy as np

    S, K, T, r, sigma, q = 100, 100, 1.0, 0.05, 0.20, 0.0
    call = bs_price(S, K, T, r, sigma, q, "call")
    put  = bs_price(S, K, T, r, sigma, q, "put")
    print(f"Call: {call:.4f}")
    print(f"Put:  {put:.4f}")

    lhs = call - put
    rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
    print(f"C - P      = {lhs:.6f}")
    print(f"parity RHS = {rhs:.6f}")
    print(f"match: {np.isclose(lhs, rhs)}")
    print("\n--- Greeks vs finite-difference check ---")
    S, K, T, r, sigma, q = 100, 100, 1.0, 0.05, 0.20, 0.0
    g = bs_greeks(S, K, T, r, sigma, q, "call")

    h = 0.01  # small bump

    # Delta: bump spot up and down, measure price slope
    fd_delta = (bs_price(S+h, K, T, r, sigma, q, "call")
                - bs_price(S-h, K, T, r, sigma, q, "call")) / (2*h)

    # Vega: bump sigma by 0.0001, scale to per-1-point (×0.0001... so /100 to match)
    fd_vega = (bs_price(S, K, T, r, sigma+1e-4, q, "call")
               - bs_price(S, K, T, r, sigma-1e-4, q, "call")) / (2e-4) / 100.0

    # Theta: bump T by one day forward (price decays as T shrinks)
    fd_theta = (bs_price(S, K, T-1/365, r, sigma, q, "call")
                - bs_price(S, K, T, r, sigma, q, "call"))

    print(f"delta: analytic {g['delta']:.6f}  fd {fd_delta:.6f}")
    print(f"vega:  analytic {g['vega']:.6f}  fd {fd_vega:.6f}")
    print(f"theta: analytic {g['theta']:.6f}  fd {fd_theta:.6f}")