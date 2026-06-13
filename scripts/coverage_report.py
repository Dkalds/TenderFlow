"""Print coverage breakdown by file, sorted by percent_covered ascending."""

import json
from pathlib import Path

d = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
files = sorted(d["files"].items(), key=lambda x: x[1]["summary"]["percent_covered"])
total = d["totals"]

print(f"\n{'=' * 60}")
print(
    f"TOTAL: {total['percent_covered']:.1f}% ({total['covered_lines']}/{total['num_statements']} statements)"
)
print(f"{'=' * 60}\n")

print(f"{'%':>5}  {'Stmts':>5}  File")
print(f"{'---':>5}  {'-----':>5}  ----")
for path, info in files:
    s = info["summary"]
    pct = s["percent_covered"]
    stmts = s["num_statements"]
    if stmts < 5:
        continue
    marker = "  <-- LOW" if pct < 50 else ""
    print(f"{pct:5.1f}  {stmts:5d}  {path}{marker}")
