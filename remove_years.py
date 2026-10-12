"""
remove_years.py -- drop all Supreme Court bulk judgments from a range of years
from the index (and move their PDFs aside), without re-embedding anything.

    python remove_years.py --from 2000 --to 2006 --dry-run    # report only
    python remove_years.py --from 2000 --to 2006              # do it

What it does
  1. Selects documents named like '2003_2003_1_1011_1018_EN.pdf' whose FIRST
     number (the year) is in the range. Indian Kanoon files are never touched.
  2. Keeps the matching FAISS vectors for the remaining chunks (no re-embedding).
  3. Backs up index_store/ to index_store_backup_<timestamp>/ first.
  4. Deletes the stale bm25.pkl so BM25 is rebuilt from the remaining chunks.
  5. MOVES the PDFs to judgments/_removed/ (not deleted -- delete that folder
     yourself once you are happy).
Restart the backend afterwards (it holds the old index in memory).
"""
import argparse, os, re, shutil, time
from collections import Counter

import numpy as np

from rag_pipeline import (INDEX_DIR, JUDGMENTS_DIR, build_faiss_index,
                          load_index, save_index)

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="y0", type=int, required=True)
ap.add_argument("--to", dest="y1", type=int, required=True)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--keep-pdfs", action="store_true", help="do not move the PDF files")
args = ap.parse_args()

index, records, model_name = load_index(INDEX_DIR)
assert index.ntotal == len(records), "index and records disagree -- refusing to touch it"


def year_of(fn):
    m = re.match(r"^(\d{4})_.*_EN\.pdf$", fn, re.I)
    return int(m.group(1)) if m else None


drop_files = {r["source_file"] for r in records
              if (y := year_of(r["source_file"])) is not None and args.y0 <= y <= args.y1}
keep_rows = [i for i, r in enumerate(records) if r["source_file"] not in drop_files]
per_year = Counter(year_of(f) for f in drop_files)

print(f"Index now:    {len(records)} chunks, {len({r['source_file'] for r in records})} documents")
print(f"Removing {args.y0}-{args.y1}: {len(drop_files)} documents, {len(records) - len(keep_rows)} chunks")
print("  per year:", dict(sorted(per_year.items())))
print(f"Index after:  {len(keep_rows)} chunks, "
      f"{len({records[i]['source_file'] for i in keep_rows})} documents")

if args.dry_run or not drop_files:
    print("\n--dry-run: nothing written." if args.dry_run else "\nNothing to remove.")
    raise SystemExit

vectors = index.reconstruct_n(0, index.ntotal)
new_vectors = np.ascontiguousarray(vectors[keep_rows], dtype="float32")
new_records = [records[i] for i in keep_rows]
new_index = build_faiss_index(new_vectors)
assert new_index.ntotal == len(new_records)

probe = np.random.default_rng(0).choice(len(new_records), size=min(50, len(new_records)),
                                        replace=False).astype(np.intp)
_, hits = new_index.search(new_vectors[probe], 1)
assert (hits[:, 0] == probe).all(), "self-retrieval check failed -- aborting, nothing written"

backup = f"{INDEX_DIR}_backup_{time.strftime('%Y%m%d_%H%M%S')}"
shutil.copytree(INDEX_DIR, backup)
print(f"\nBacked up old index -> {backup}/")
stale = os.path.join(INDEX_DIR, "bm25.pkl")
if os.path.exists(stale):
    os.remove(stale)
save_index(new_index, new_records, model_name, INDEX_DIR)

if not args.keep_pdfs:
    dest = os.path.join(JUDGMENTS_DIR, "_removed")
    moved = 0
    for fn in sorted(drop_files):
        for folder in (JUDGMENTS_DIR, "judgments_bulk"):
            src = os.path.join(folder, fn)
            if os.path.exists(src):
                os.makedirs(dest, exist_ok=True)
                shutil.move(src, os.path.join(dest, fn))
                moved += 1
                break
    print(f"Moved {moved} PDFs -> {dest}/  (delete that folder when you are sure)")
print("\nDone. Restart the backend, then re-run eval_pipeline.py.")
