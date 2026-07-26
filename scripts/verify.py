"""Read-back check: proves a written snapshot is queryable and Hive partitioning works.

Usage:
    python scripts/verify.py                  # verifies the most recent snapshot file
    python scripts/verify.py <path/to/file>    # verifies a specific snapshot file
"""

import sys
from pathlib import Path

import duckdb

import config


def find_latest_snapshot() -> Path:
    files = sorted(config.DATA_DIR.glob("snapshots/date=*/snapshot_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No snapshot files found under {config.DATA_DIR / 'snapshots'}")
    return files[-1]


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_snapshot()
    if not target.exists():
        raise FileNotFoundError(f"Snapshot file not found: {target}")

    all_partitions_glob = str(config.DATA_DIR / "snapshots" / "*" / "*.parquet")

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    total_rows = con.execute(
        "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning = true)", [all_partitions_glob]
    ).fetchone()[0]

    print(f"Target file: {target}")
    print(f"Total rows across all date= partitions: {total_rows}")

    sample = con.execute("SELECT * FROM read_parquet(?) LIMIT 3", [str(target)]).fetchdf()
    print("\nSample rows from target file:")
    print(sample.to_string())


if __name__ == "__main__":
    main()
