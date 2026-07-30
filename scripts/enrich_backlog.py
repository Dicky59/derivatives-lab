"""Enrich every raw snapshot that doesn't yet have a derived counterpart."""
import glob
from pathlib import Path
import subprocess
import sys

raw = sorted(glob.glob("data/snapshots/date=*/snapshot_*.parquet"))
enriched = {Path(p).name.replace("enriched_", "")
            for p in glob.glob("data/derived/date=*/enriched_*.parquet")}

missing = [p for p in raw
           if Path(p).name.replace("snapshot_", "") not in enriched]

print(f"{len(raw)} raw, {len(enriched)} derived, {len(missing)} to enrich:\n")
for p in missing:
    print(f"  enriching {Path(p).name} ...")
    subprocess.run([sys.executable, "src/analytics/enrich.py", "--file", p], check=True)
print("\nBacklog enrichment complete.")