"""
index_report.py -- summarise index_store/ into two small files you can share.

Reads faiss.index, records.pkl and bm25.pkl (never modifies them) and writes:
  index_report.json     corpus-level stats and health checks
  index_manifest.csv    one row per document (filename, case_name, court, case_no, chunks)
No chunk text and no embeddings are written, so both files are tiny.

Run from your project root (same folder as rag_pipeline.py):
    python index_report.py
    python index_report.py --index-dir index_store_backup_20261005_152032
"""
import argparse, csv, json, os, pickle, re, statistics as st
from collections import Counter


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(len(vals) * p))] if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", default=os.environ.get("INDEX_DIR", "index_store"))
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()

    rec_path = os.path.join(a.index_dir, "records.pkl")
    with open(rec_path, "rb") as f:
        data = pickle.load(f)
    records, model_name = data["records"], data.get("model_name")

    rep = {"index_dir": a.index_dir, "embedding_model": model_name,
           "n_chunks": len(records)}

    # ---- FAISS (optional import) ----
    try:
        import faiss
        idx = faiss.read_index(os.path.join(a.index_dir, "faiss.index"))
        rep["faiss"] = {"ntotal": idx.ntotal, "dim": idx.d,
                        "type": type(idx).__name__,
                        "matches_records": idx.ntotal == len(records)}
        # sanity: vectors should be L2-normalised (inner product == cosine)
        import numpy as np
        step = max(1, idx.ntotal // 200)
        norms = [float(np.linalg.norm(idx.reconstruct(i))) for i in range(0, idx.ntotal, step)]
        rep["faiss"]["sample_norm_min"] = round(min(norms), 4)
        rep["faiss"]["sample_norm_max"] = round(max(norms), 4)
    except Exception as e:
        rep["faiss"] = {"error": str(e)}

    # ---- BM25 (only need its record count) ----
    try:
        with open(os.path.join(a.index_dir, "bm25.pkl"), "rb") as f:
            b = pickle.load(f)
        rep["bm25"] = {"n_records": b.get("n_records"),
                       "matches_records": b.get("n_records") == len(records)}
    except Exception as e:
        rep["bm25"] = {"error": str(e)}

    # ---- per-document aggregation ----
    docs = {}
    for r in records:
        d = docs.setdefault(r["source_file"], {
            "filename": r["source_file"], "case_name": r.get("case_name"),
            "court": r.get("court"), "case_no": r.get("case_no"),
            "chunks": 0, "words": 0})
        d["chunks"] += 1
        d["words"] += len((r.get("raw_text") or r.get("text") or "").split())

    def kind(fn):
        if re.match(r"\d{4}_.*_EN\.pdf$", fn, re.I): return "sc_bulk"
        return "indian_kanoon_or_other"

    for d in docs.values():
        d["kind"] = kind(d["filename"])
        m = re.match(r"(\d{4})_", d["filename"])
        d["year"] = m.group(1) if m else ""

    cs = [d["chunks"] for d in docs.values()]
    rep["n_documents"] = len(docs)
    rep["chunks_per_doc"] = {"min": min(cs), "median": st.median(cs),
                             "p95": pct(cs, 0.95), "max": max(cs),
                             "mean": round(st.mean(cs), 1)}
    rep["top10_docs_by_chunks"] = [(d["filename"], d["chunks"]) for d in
                                   sorted(docs.values(), key=lambda x: -x["chunks"])[:10]]
    rep["by_kind"] = dict(Counter(d["kind"] for d in docs.values()))
    rep["sc_bulk_by_year"] = dict(sorted(Counter(d["year"] for d in docs.values() if d["year"]).items()))
    rep["courts_top15"] = Counter(d["court"] for d in docs.values()).most_common(15)

    # ---- metadata quality ----
    unknown_court = sum(1 for d in docs.values() if d["court"] in (None, "Unknown Court"))
    unknown_no = sum(1 for d in docs.values() if d["case_no"] in (None, "Unknown"))
    numeric_names = sum(1 for d in docs.values()
                        if re.fullmatch(r"[\d\s]+(EN)?", d["case_name"] or ""))
    name_counts = Counter(d["case_name"] for d in docs.values())
    rep["metadata_quality"] = {
        "unknown_court_docs": unknown_court,
        "unknown_case_no_docs": unknown_no,
        "numeric_id_case_names": numeric_names,
        "duplicate_case_names": sum(1 for n, c in name_counts.items() if c > 1),
        "docs_with_neutral_citation": sum(1 for r in {r["source_file"]: r for r in records}.values()
                                          if r.get("neutral_citation")),
    }

    # ---- chunk health ----
    lens = [len((r.get("raw_text") or r.get("text") or "").split()) for r in records]
    rep["chunk_words"] = {"min": min(lens), "median": st.median(lens), "max": max(lens),
                          "under_20_words": sum(1 for l in lens if l < 20)}
    ids = Counter(r["chunk_id"] for r in records)
    rep["duplicate_chunk_ids"] = sum(1 for c in ids.values() if c > 1)
    rep["empty_text_docs"] = [d["filename"] for d in docs.values() if d["words"] == 0][:20]

    os.makedirs(a.out_dir, exist_ok=True)
    with open(os.path.join(a.out_dir, "index_report.json"), "w") as f:
        json.dump(rep, f, indent=2, default=str)
    with open(os.path.join(a.out_dir, "index_manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "kind", "year", "case_name", "court",
                                          "case_no", "chunks", "words"])
        w.writeheader()
        for d in sorted(docs.values(), key=lambda x: x["filename"]):
            w.writerow({k: d[k] for k in w.fieldnames})

    print(json.dumps(rep, indent=2, default=str))
    print(f"\nWrote index_report.json and index_manifest.csv to '{a.out_dir}'")


if __name__ == "__main__":
    main()
