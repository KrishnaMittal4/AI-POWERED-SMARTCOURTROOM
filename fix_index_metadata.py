"""
fix_index_metadata.py -- repair an EXISTING index without re-embedding
=======================================================================
Applies three fixes to index_store/ in place:

  1. Removes exact-duplicate documents (e.g. 'X_dup2.pdf' identical to
     'X.pdf'): their chunks and FAISS vectors are dropped.
  2. Replaces numeric-ID case names ('2023 10 1001 1009 EN') with real
     party names parsed from each judgment's header, and cleans junk out
     of filename-derived names.
  3. Re-detects court and case number with the rules in
     metadata_extraction.py.

No embedding model or internet access is needed: chunk text is unchanged,
so the stored vectors stay valid. They are read back out of the FAISS
index (IndexFlatIP supports reconstruct) and the index is rebuilt without
the duplicate rows.

Usage (from the project root):
    python fix_index_metadata.py              # fix index + move duplicate PDFs aside
    python fix_index_metadata.py --dry-run    # report only, change nothing
    python fix_index_metadata.py --keep-pdfs  # fix index but leave PDFs where they are

The old index is backed up to index_store_backup_<timestamp>/ first.
Duplicate PDFs are MOVED (not deleted) to judgments/_duplicates/, which
build_corpus ignores because it only globs the top level.
"""

import argparse
import hashlib
import os
import shutil
import time
from collections import OrderedDict

import faiss
import numpy as np

from metadata_extraction import build_metadata, disambiguate_names
from rag_pipeline import (INDEX_DIR, JUDGMENTS_DIR, build_contextual_header,
                          build_faiss_index, load_index, read_raw_head, save_index)


def find_pdf(filename: str):
    for folder in (JUDGMENTS_DIR, "judgments_bulk"):
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return path
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-pdfs", action="store_true")
    ap.add_argument("--reembed", action="store_true",
                    help="re-embed every chunk whose text header changed (slow on CPU, "
                         "but vectors then match the corrected case names exactly)")
    args = ap.parse_args()

    index, records, model_name = load_index(INDEX_DIR)
    assert index.ntotal == len(records), (
        f"index has {index.ntotal} vectors but records.pkl has {len(records)} rows -- "
        f"refusing to touch a corrupt index")
    print(f"Loaded index: {len(records)} chunks, model={model_name}")

    # ---- group chunk rows by document, preserving filename order -----------
    by_file = OrderedDict()
    for row, r in enumerate(records):
        by_file.setdefault(r["source_file"], []).append(row)

    # ---- 1. duplicate detection (same hash of the document's chunk text) ---
    seen, duplicates = {}, []          # duplicates: (dup_file, original_file)
    for fname in sorted(by_file):      # 'X.pdf' sorts before 'X_dup2.pdf'
        digest = hashlib.sha256(
            "\n".join(records[i]["text"] for i in by_file[fname]).encode("utf-8")
        ).hexdigest()
        if digest in seen:
            duplicates.append((fname, seen[digest]))
        else:
            seen[digest] = fname
    dup_files = {d for d, _ in duplicates}
    for d, o in duplicates:
        print(f"  duplicate: {d}  == {o}")

    # ---- 2+3. recompute metadata for every kept document -------------------
    metas, missing, heads = {}, [], {}
    for fname in by_file:
        if fname in dup_files:
            continue
        pdf = find_pdf(fname)
        raw_head = read_raw_head(pdf) if pdf else ""
        if not pdf:
            missing.append(fname)
        first_chunk = records[by_file[fname][0]]["text"]
        metas[fname] = build_metadata(fname, raw_head=raw_head, cleaned_text=first_chunk)
        heads[fname] = raw_head
    if missing:
        print(f"  WARNING: PDF not found for {len(missing)} files "
              f"(metadata falls back to filename + first chunk): {missing[:3]}...")
    renamed = disambiguate_names(list(metas.values()))

    # ---- apply -------------------------------------------------------------
    keep_rows = [i for i, r in enumerate(records) if r["source_file"] not in dup_files]
    new_records = []
    for i in keep_rows:
        r = dict(records[i])
        m = metas[r["source_file"]]
        r["case_name"], r["court"], r["case_no"] = m["case_name"], m["court"], m["case_no"]
        r["neutral_citation"] = m.get("neutral_citation")
        r["decision_date"] = m.get("decision_date")
        r["bench"] = m.get("bench")
        r["scr_citation"] = m.get("scr_citation")
        # The '[Case: ... | Court: ...]' header is baked into `text` (it feeds
        # BM25, the cross-encoder and the LLM prompt), so it must be rebuilt too,
        # otherwise the old numeric name keeps showing up there.
        if r.get("raw_text") is not None:
            header = build_contextual_header(m)
            r["text"] = f"{header}\n{r['raw_text']}" if header else r["raw_text"]
        new_records.append(r)

    # ---- report ------------------------------------------------------------
    n_docs = len(metas)
    unk_court = sum(1 for m in metas.values() if m["court"] == "Unknown Court")
    unk_no = sum(1 for m in metas.values() if m["case_no"] == "Unknown")
    id_names = sum(1 for m in metas.values() if m["case_name"].replace(" ", "").isdigit()
                   or m["case_name"].endswith(" EN"))
    print(f"\nDocuments: {len(by_file)} -> {n_docs} (removed {len(dup_files)} duplicates)")
    print(f"Chunks:    {len(records)} -> {len(new_records)}")
    print(f"Names still numeric-ID style: {id_names}/{n_docs}")
    print(f"Court unknown:    {unk_court}/{n_docs} docs")
    print(f"Case no unknown:  {unk_no}/{n_docs} docs")
    print(f"Name collisions disambiguated: {renamed}")

    # first-page text of every document whose name is STILL numeric, so the
    # header parser can be extended for whatever layout those use
    leftover = [f for f, m in metas.items()
                if m["case_name"].replace(" ", "").isdigit() or m["case_name"].endswith(" EN")]
    if leftover:
        with open("remaining_numeric_names.txt", "w", encoding="utf-8") as fh:
            for f in leftover:
                fh.write("=" * 70 + f"\nFILE: {f}\n")
                lines = [l.strip() for l in heads.get(f, "").splitlines() if l.strip()][:16]
                fh.write("\n".join(f"  {i:2}: {l!r}" for i, l in enumerate(lines)) or "  (no text extracted)")
                fh.write("\n")
        print(f"Wrote remaining_numeric_names.txt ({len(leftover)} documents)")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    # ---- rebuild FAISS without the duplicate rows --------------------------
    if args.reembed:
        from rag_pipeline import load_embedding_model
        print(f"\nRe-embedding {len(new_records)} chunks with '{model_name}' (this takes a while)...")
        model = load_embedding_model(model_name)
        new_vectors = np.ascontiguousarray(model.encode(
            [r["text"] for r in new_records], batch_size=128, show_progress_bar=True,
            convert_to_numpy=True, normalize_embeddings=True), dtype="float32")
    else:
        vectors = index.reconstruct_n(0, index.ntotal)        # (N, dim) float32
        new_vectors = np.ascontiguousarray(vectors[keep_rows], dtype="float32")
    new_index = build_faiss_index(new_vectors)
    assert new_index.ntotal == len(new_records)

    # sanity: every kept vector must still retrieve itself as its own top hit
    probe = np.random.default_rng(0).choice(len(new_records), size=min(50, len(new_records)), replace=False)
    probe = probe.astype(np.intp)  # ensure compatible dtype with FAISS returned indices
    _, hits = new_index.search(new_vectors[probe], 1)
    # hits[:, 0] contains the nearest-neighbour index for each probe row (in probe
    # order).  A vector must retrieve ITSELF as its own nearest neighbour.
    # Check element-wise (probe[i] should equal hits[i, 0]), not set equality,
    # because each row should map back to its own original position.
    assert (hits[:, 0] == probe).all(), "self-retrieval check failed -- aborting"

    # ---- back up, then save ------------------------------------------------
    backup = f"{INDEX_DIR}_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(INDEX_DIR, backup)
    print(f"\nBacked up old index -> {backup}/")
    # bm25.pkl is only reloaded when its record count matches, so a stale one
    # (same count, different text) would silently survive. Force a rebuild.
    stale_bm25 = os.path.join(INDEX_DIR, "bm25.pkl")
    if os.path.exists(stale_bm25):
        os.remove(stale_bm25)
    save_index(new_index, new_records, model_name, INDEX_DIR)

    # ---- park duplicate PDFs ----------------------------------------------
    if not args.keep_pdfs:
        dest = os.path.join(JUDGMENTS_DIR, "_duplicates")
        for d in sorted(dup_files):
            src = find_pdf(d)
            if src:
                os.makedirs(dest, exist_ok=True)
                shutil.move(src, os.path.join(dest, d))
                print(f"  moved {d} -> {dest}/")
    print("\nDone. Re-run eval_pipeline.py to measure the effect (step 5).")


if __name__ == "__main__":
    main()