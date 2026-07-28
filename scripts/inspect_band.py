"""One-off: inspect the IV band and Alpaca cross-check on a derived snapshot."""
import duckdb

con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
path = "data/derived/date=2026-07-28/enriched_20260728T142857Z.parquet"

# First: what expiries even exist, and how many ok rows each has?
print("=== Available expiries (nearest first) ===")
print(con.execute(f"""
    SELECT expiry, count(*) AS ok_contracts
    FROM read_parquet('{path}')
    WHERE status='ok'
    GROUP BY expiry
    ORDER BY expiry
    LIMIT 10
""").df().to_string(index=False))

# Pick the nearest expiry programmatically and reuse it
nearest = con.execute(f"""
    SELECT min(expiry) FROM read_parquet('{path}')
    WHERE status='ok' AND expiry > CURRENT_DATE
""").fetchone()[0]
print(f"\nNearest future expiry: {nearest}")

print("\n=== ATM band, nearest expiry ===")
print(con.execute(f"""
    SELECT strike, "right",
           round(iv_bid,4) AS iv_bid,
           round(iv_mid,4) AS iv_mid,
           round(iv_ask,4) AS iv_ask,
           round(iv_ask - iv_bid, 4) AS band_width
    FROM read_parquet('{path}')
    WHERE status='ok' AND abs(strike - 737) < 8 AND expiry = '{nearest}'
    ORDER BY strike, "right"
""").df().to_string(index=False))

print("\n=== Ours vs Alpaca, nearest expiry ===")
print(con.execute(f"""
    SELECT strike, "right",
           round(iv_mid,4)   AS our_iv,
           round(iv,4)       AS alpaca_iv,
           round(delta_bs,4) AS our_delta,
           round(delta,4)    AS alpaca_delta
    FROM read_parquet('{path}')
    WHERE status='ok' AND abs(strike - 737) < 8
      AND expiry = '{nearest}' AND iv IS NOT NULL
    ORDER BY strike, "right"
""").df().to_string(index=False))