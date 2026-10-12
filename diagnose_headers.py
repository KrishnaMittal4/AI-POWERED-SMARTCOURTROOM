"""
diagnose_headers.py -- show WHY parse_scr_header() fails on the numeric-name PDFs.

Samples 2 failing PDFs for each of several years, prints the parser result and
the first ~22 lines of page 1 (repr() so hidden characters are visible), and
saves everything to header_samples.txt (a few KB). Read-only.

Run from your project root (next to rag_pipeline.py):
    python diagnose_headers.py
"""
import os, pickle, re, sys

from metadata_extraction import parse_scr_header
from rag_pipeline import INDEX_DIR, JUDGMENTS_DIR, read_raw_head

YEARS = ["2000", "2005", "2010", "2015", "2018", "2020", "2023"]
PER_YEAR = 2
LINES = 22


def find_pdf(fn):
    for folder in (JUDGMENTS_DIR, "judgments_bulk", os.path.join("data", "pdfs")):
        p = os.path.join(folder, fn)
        if os.path.exists(p):
            return p
    return None


with open(os.path.join(INDEX_DIR, "records.pkl"), "rb") as f:
    records = pickle.load(f)["records"]

failing = {}
for r in records:
    fn = r["source_file"]
    if re.fullmatch(r"[\d\s]+(EN)?", r.get("case_name") or "") and fn not in failing:
        failing[fn] = r

by_year = {}
for fn in sorted(failing):
    m = re.match(r"(\d{4})_", fn)
    if m:
        by_year.setdefault(m.group(1), []).append(fn)

out = []
for y in YEARS:
    for fn in by_year.get(y, [])[:PER_YEAR]:
        path = find_pdf(fn)
        out.append("=" * 78)
        out.append(f"FILE: {fn}   (year {y})")
        if not path:
            out.append("  PDF not found in judgments/, judgments_bulk/ or data/pdfs/")
            continue
        head = read_raw_head(path)
        parsed = parse_scr_header(head) if head else None
        out.append(f"parse_scr_header -> {parsed}")
        if not head:
            out.append("  (no text extracted from first 2 pages -- scanned image?)")
            continue
        for i, line in enumerate([l for l in head.splitlines() if l.strip()][:LINES]):
            out.append(f"  {i:2}: {line.strip()!r}")

text = "\n".join(out)
with open("header_samples.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)
print("\nSaved header_samples.txt -- please upload that file.")
