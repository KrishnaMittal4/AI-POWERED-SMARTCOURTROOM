"""
Find Similar Cases
==================
"Judgments like this one", grouped by DOCUMENT.

Why grouped: the index is chunk-level and document sizes are wildly uneven
(median 39 chunks, max 2,212). A plain top-k over chunks lets one huge judgment
fill the whole list, so every candidate chunk is collapsed to its document and
documents are ranked by their single best-matching chunk. Document length
therefore cannot crowd out other cases.

Two ways to build the query vector:
  * passage  -- embed a piece of text (e.g. a retrieved passage the user is reading)
  * document -- the centroid of the judgment's own chunk vectors, read straight
                back out of FAISS (no embedding model call). Very long
                judgments are sampled evenly (MAX_CENTROID_CHUNKS) so the
                centroid stays cheap and is not dominated by one section.

Pure numpy + FAISS; no LLM calls, so it costs no Groq quota.
"""

import numpy as np

MAX_CENTROID_CHUNKS = 64     # chunks sampled per document for the centroid
MATCH_WINDOW = 500           # "matching chunks" = how many of the top-N chunk hits fall in a document
SNIPPET_CHARS = 420

_DOC_CACHE: dict = {}


def _doc_codes(records: list):
    """(codes, names): integer document code per record row, and code -> source_file.
    Cached per record list; rebuilt automatically after an upload/delete."""
    key = (id(records), len(records))
    hit = _DOC_CACHE.get(key)
    if hit:
        return hit
    names, lookup, codes = [], {}, np.empty(len(records), dtype=np.int32)
    for i, r in enumerate(records):
        f = r.get("source_file", "")
        c = lookup.get(f)
        if c is None:
            c = lookup[f] = len(names)
            names.append(f)
        codes[i] = c
    _DOC_CACHE.clear()          # keep only the live index's mapping
    _DOC_CACHE[key] = (codes, names)
    return codes, names


class UnknownDocument(Exception):
    pass


def _document_vector(index, records, source_file: str) -> np.ndarray:
    rows = [i for i, r in enumerate(records) if r.get("source_file") == source_file]
    if not rows:
        raise UnknownDocument(source_file)
    if len(rows) > MAX_CENTROID_CHUNKS:
        pick = np.linspace(0, len(rows) - 1, MAX_CENTROID_CHUNKS).round().astype(int)
        rows = [rows[i] for i in pick]
    vecs = np.vstack([index.reconstruct(int(i)) for i in rows]).astype("float32")
    centroid = vecs.mean(axis=0)
    norm = np.linalg.norm(centroid)
    return (centroid / norm if norm else centroid).reshape(1, -1).astype("float32")


def find_similar(index, records, embed_model, *, source_file: str | None = None,
                 text: str | None = None, limit: int = 8) -> dict:
    """Return up to `limit` distinct judgments most similar to the query,
    excluding `source_file` itself. Give `text` for a passage-based search,
    or only `source_file` for a whole-judgment search."""
    text = (text or "").strip()
    if text:
        basis = "passage"
        qvec = np.asarray(
            embed_model.encode([text], normalize_embeddings=True, convert_to_numpy=True)
        ).astype("float32")
    elif source_file:
        basis = "document"
        qvec = _document_vector(index, records, source_file)
    else:
        raise ValueError("Give either `text` or `source_file`.")

    n = min(index.ntotal, len(records))
    scores, ids = index.search(qvec, n)          # exact search over every chunk
    scores, ids = scores[0], ids[0]
    ok = (ids >= 0) & (ids < len(records))
    scores, ids = scores[ok], ids[ok]

    codes, names = _doc_codes(records)
    hit_codes = codes[ids]
    if source_file:
        self_code = names.index(source_file) if source_file in names else -1
        keep = hit_codes != self_code
        scores, ids, hit_codes = scores[keep], ids[keep], hit_codes[keep]

    if len(ids) == 0:
        return {"basis": basis, "source_file": source_file, "results": []}

    # first occurrence of each document in the (descending) ranking = its best chunk
    _, first = np.unique(hit_codes, return_index=True)
    first = np.sort(first)[:limit]
    window = np.bincount(hit_codes[:MATCH_WINDOW], minlength=len(names))

    results = []
    for pos in first:
        r = records[int(ids[pos])]
        text_out = r.get("raw_text", r.get("text", ""))
        results.append({
            "source_file": r.get("source_file"),
            "case_name": r.get("case_name"),
            "case_no": r.get("case_no"),
            "court": r.get("court"),
            "decision_date": r.get("decision_date"),
            "score": float(scores[pos]),                     # best chunk similarity
            "matched_chunks": int(window[hit_codes[pos]]),   # strong hits inside the top MATCH_WINDOW chunks
            "snippet": text_out[:SNIPPET_CHARS] + ("…" if len(text_out) > SNIPPET_CHARS else ""),
            "text": text_out,
        })
    return {"basis": basis, "source_file": source_file, "results": results}
