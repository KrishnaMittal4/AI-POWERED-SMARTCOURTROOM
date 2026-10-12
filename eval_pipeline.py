"""
Evaluation Pipeline -- Precision@K, MRR, Citation Accuracy
=============================================================
Runs a labeled set of test queries against the RAG pipeline and reports:

  1. Precision@K       -- of the top-K retrieved chunks, what fraction
                           come from a document you've labeled as
                           actually relevant to the query?
  2. MRR                -- Mean Reciprocal Rank: on average, how far
                           down the ranking is the FIRST relevant hit?
                           (1.0 = always rank 1, 0.5 = usually rank 2, ...)
  3. Citation accuracy  -- of all citations the LLM generates across the
                           test set, what fraction are judged "Supported"
                           by the verification layer (Step 3), and what
                           fraction get flagged as unverifiable (Step 1)?

Retrieval metrics (1-2) need no Groq calls -- they only need the FAISS
index and embedding model, so they're fast/cheap to iterate on.
Citation accuracy (3) calls the full RAG + verification pipeline, so it
costs real Groq API calls -- keep TEST_QUERIES to a reasonable size
(8-15 queries is plenty for a report; more doesn't add much rigor for a
corpus this size).

Usage:
    python eval_pipeline.py                  # retrieval metrics only (fast)
    python eval_pipeline.py --full           # + citation accuracy (slower, uses Groq)
"""

import argparse
import json
import os
from typing import Optional
from dotenv import load_dotenv

from rag_pipeline import load_index, search, INDEX_DIR

load_dotenv()

# ---------------------------------------------------------------------------
# TEST QUERY SET
# ---------------------------------------------------------------------------
# Each entry needs:
#   query          -- the question to ask
#   relevant_files -- list of source_file names you (the human) judge to be
#                     genuinely relevant to answering this query. This is
#                     your ground truth -- there's no way to derive it
#                     automatically, you have to actually read the
#                     judgments and decide.
#
# The 7 starter queries below are pre-filled based on what we already
# confirmed while testing (7 of 8 docs are Section 138 NI Act cases,
# Orkay is the odd one out). REPLACE/EXPAND these once you've read your
# corpus -- aim for 8-15 total, and try to include a couple of ANSWERABLE
# single-document queries (easy for the retriever) alongside harder
# cross-document ones like the Section 138 query, plus at least one
# clearly UNANSWERABLE query (e.g. about a topic your corpus doesn't
# cover at all) to check the system correctly says "not found" rather
# than forcing an answer.
TEST_QUERIES = [
    {
        "query": "What are the requirements for prosecution under Section 138 of the Negotiable Instruments Act?",
        "relevant_files": [
            "Pawankumar_vs_Ashish_Enterprises_And_Another_on_30_August_1991.PDF",
            "Canbank_Financial_Services_Ltd_vs_Gitanjli_Motors_Ltd_And_Ors_on_6_January_1995.PDF",
            "A_Sakthivel_vs_K_R_Navaneetha_Krishnan_on_29_April_2011.PDF",
        ],
    },
    {
        "query": "Is a person liable under Section 138 if a cheque was issued on behalf of a firm rather than personally?",
        "relevant_files": ["A_Sakthivel_vs_K_R_Navaneetha_Krishnan_on_29_April_2011.PDF"],
    },
    {
        "query": "What notice period must be given to the drawer of a dishonoured cheque before criminal proceedings can be launched?",
        "relevant_files": ["Canbank_Financial_Services_Ltd_vs_Gitanjli_Motors_Ltd_And_Ors_on_6_January_1995.PDF"],
    },
    {
        "query": "What did the court decide in Mrs Jain Babu vs K J Joseph?",
        "relevant_files": ["Mrs_Jain_Babu_vs_K_J_Joseph_on_4_September_2008.PDF"],
    },
    {
        "query": "What precedent cases are cited within the Mrs Jain Babu vs K J Joseph judgment?",
        "relevant_files": ["Mrs_Jain_Babu_vs_K_J_Joseph_on_4_September_2008.PDF"],
    },
    {
        "query": "What was the outcome of Mr M Palanichamy vs Union Of India?",
        "relevant_files": ["Mr_M_Palanichamy_vs_Union_Of_India_on_31_July_2012.PDF"],
    },
    {
        # NOTE: Orkay is NOT about Section 138 (confirmed earlier while
        # testing) -- this query checks whether the retriever correctly
        # keeps Orkay OUT of a Section 138-specific query rather than
        # forcing it in just because it's in the corpus.
        "query": "What was the excise/customs issue in Orkay Industries vs State of Maharashtra?",
        "relevant_files": ["Orkay_Industries_Limited_Others_vs_The_State_Of_Maharashtra_Others_on_26_June_1998.PDF"],
    },
    {
        # Deliberately unanswerable -- your corpus has nothing on this.
        # A good system should say "not found," not force an answer.
        "query": "What does the corpus say about GST registration requirements for small businesses?",
        "relevant_files": [],
    },

    # -------------------------------------------------------------------
    # Added after expanding the corpus from 8 to 30 documents. These
    # cover the genuinely NEW legal domains the expanded corpus added --
    # income tax (ITAT), admiralty, insolvency (NCLAT), customs, labor/
    # ESI, a historical 1912 criminal conspiracy case, and a service-law
    # Supreme Court matter -- not just more Section 138 cheque-bounce
    # cases. Each relevant_files set was confirmed by actually reading
    # the opening pages of the PDF, not guessed from the filename alone.
    # -------------------------------------------------------------------
    {
        "query": "What was the dispute between Pearl Pens Pvt Ltd and Rajeev B about?",
        "relevant_files": ["Rajeev_B_vs_Pearl_Pens_Pvt_Ltd_on_25_August_2021.PDF"],
    },
    {
        "query": "What was the outcome of the criminal complaint in Vignesh D vs Smt Nirmala?",
        "relevant_files": ["Vignesh_D_vs_Smt_Nirmala_on_9_September_2022.PDF"],
    },
    {
        "query": "Is time of the essence in a property sale agreement, and what happens if the seller sells to a third party instead?",
        "relevant_files": ["Thomson_Press_India_Ltd_vs_Nanak_Builders_Investrs_P_Ltd_Ors_on_21_February_2013.PDF"],
    },
    {
        "query": "What issue did the Bombay High Court's admiralty jurisdiction address in the Mv Malaviya vessel arrest proceedings?",
        "relevant_files": ["Idbi_Bank_Ltd_vs_Mv_Malaviya_Thirty_Three_Imo_7809118_on_19_May_2020.PDF"],
    },
    {
        # NOTE: this 1912 Madras HC judgment concerns the conspiracy and
        # abetment-of-murder trial connected to the assassination of
        # Robert Ashe -- a genuinely distinct domain (colonial-era
        # criminal conspiracy law) from everything else in the corpus.
        "query": "What were the charges against the accused in the Muthukumaraswami Pillai conspiracy case, and were they convicted of abetting murder?",
        "relevant_files": ["Muthukumaraswami_Pillai_And_Seven_Ors_vs_King_Emperor_on_17_April_1912.PDF"],
    },
    {
        "query": "What did the Supreme Court decide about the jurisdiction of the Employees' Insurance Court in the Hyderabad Asbestos Cement case?",
        "relevant_files": ["Hyderabad_Asbestos_Cement_Products_Ltd_vs_The_Employees_Insurance_Court_Anr_on_2_December_1977.PDF"],
    },
    {
        "query": "What customs dispute did Hazel Mercantile Limited raise against the Commissioner of Customs, Kandla?",
        "relevant_files": ["Hazel_Mercantile_Limited_vs_Kandla_Customs_on_7_September_2026.PDF"],
    },
    {
        "query": "What did the NCLAT decide in the insolvency appeal filed by BSE Limited?",
        "relevant_files": ["Bse_Limited_vs_Mrudula_Brodie_Ors_Ors_on_24_March_2026.PDF"],
    },
    {
        "query": "What did the Income Tax Appellate Tribunal rule in the assessment appeal involving Agrawal Coal Corporation?",
        "relevant_files": ["The_Dcit1_1_Indore_vs_M_S_Agrawal_Coal_Corporation_P_Ltd_on_8_March_2017.PDF"],
    },
    {
        "query": "What did the Supreme Court rule in Nawal Kishore Sharma's case against the Union of India?",
        "relevant_files": ["Nawal_Kishore_Sharma_vs_Union_Of_India_Ors_on_7_August_2014.PDF"],
    },
    {
        # Second deliberately-unanswerable query, in a different domain
        # than the GST one above -- checks the system doesn't force an
        # answer regardless of WHICH unrelated topic is asked about.
        "query": "What does the corpus say about trademark infringement and passing off?",
        "relevant_files": [],
    },
]


# ---------------------------------------------------------------------------
# QUERIES FOR THE 80 SUPREME COURT (2023 SCR) JUDGMENTS
# ---------------------------------------------------------------------------
# Until now every labeled query targeted the original 30 documents, so 76% of
# the index (the SC bulk set) was never evaluated. Each query below is written
# from the judgment's own headnote and labeled with that one document -- skim
# the headnote of any you doubt (relevant_files are MY labels, not gospel).
BULK_QUERIES = [
    {"query": "What did the Supreme Court say about the right of forest inhabitants to be heard before land is declared reserved forest?",
     "relevant_files": ["2023_10_1001_1009_EN.pdf"]},
    {"query": "Does a Supreme Court order granting liberty to approach the High Court in review make a Special Leave Petition available again?",
     "relevant_files": ["2023_10_1010_1020_EN.pdf"]},
    {"query": "Was maize starch entitled to a sales tax exemption under the Tamil Nadu General Sales Tax Act?",
     "relevant_files": ["2023_10_101_116_EN.pdf"]},
    {"query": "Is a credit note issued by a manufacturer to an automobile dealer for replacing a defective part under warranty liable to sales tax?",
     "relevant_files": ["2023_10_1268_1346_EN.pdf"]},
    {"query": "Must a High Court consider cross objections filed for enhancement of compensation under Order 41 Rule 22 of the Code of Civil Procedure?",
     "relevant_files": ["2023_10_126_132_EN.pdf"]},
    {"query": "Can an Army soldier be convicted of culpable homicide not amounting to murder for shooting a fellow Lance Naik during an altercation over seniority?",
     "relevant_files": ["2023_10_1139_1146_EN.pdf"]},
    {"query": "Was revoking the Media One broadcasting permission on national security grounds a valid restriction on freedom of the press?",
     "relevant_files": ["2023_10_595_712_EN.pdf"]},
    {"query": "Is the Government of NCT of Delhi (Amendment) Ordinance 2023 constitutionally valid?",
     "relevant_files": ["2023_10_493_501_EN.pdf"]},
    {"query": "Was the extension of tenure of the Directors of the CBI and Enforcement Directorate valid under the Central Vigilance Commission Act amendment?",
     "relevant_files": ["2023_10_533_586_EN.pdf"]},
    {"query": "Does the Income Tax exemption for Sikkimese people unconstitutionally exclude Indians who settled in Sikkim?",
     "relevant_files": ["2023_10_289_367_EN.pdf"]},
    {"query": "When can bail be denied under the Unlawful Activities (Prevention) Act in the Bhima-Koregaon case?",
     "relevant_files": ["2023_10_867_912_EN.pdf"]},
    {"query": "Is a Reserve Bank of India employee with a disability entitled to reservation in promotion?",
     "relevant_files": ["2023_10_775_823_EN.pdf"]},
    {"query": "Can a Special Leave Petition be filed against an NCDRC appellate order when a writ remedy lies before the High Court?",
     "relevant_files": ["2023_10_1155_1173_EN.pdf"]},
    {"query": "How did the Supreme Court treat the Rajasthan Minor Mineral Concession Rules on the grant and renewal of mining leases?",
     "relevant_files": ["2023_11_1_18_EN.pdf"]},
]

# ---------------------------------------------------------------------------
# MORE UNANSWERABLE QUERIES (topics verified ABSENT from the corpus)
# ---------------------------------------------------------------------------
# The refusal thresholds (MIN/WEAK_RETRIEVAL_SCORE) were calibrated on just two
# unanswerable queries. These topics return zero keyword hits across all 105
# documents, which gives threshold_calibration() something real to work with.
# (The older GST query is NOT fully clean -- one judgment mentions the Goods
# and Services Tax -- so treat it as borderline.)
EXTRA_UNANSWERABLE = [
    {"query": "What does the corpus say about copyright infringement in films or music?", "relevant_files": []},
    {"query": "What do the judgments say about the regulation of cryptocurrency and bitcoin?", "relevant_files": []},
    {"query": "What is the legal position on asylum and refugee status for foreign nationals?", "relevant_files": []},
    {"query": "What does the corpus say about surrogacy and the rights of intended parents?", "relevant_files": []},
    {"query": "Is an airline liable for passenger injury under the Montreal Convention?", "relevant_files": []},
]

TEST_QUERIES = TEST_QUERIES + BULK_QUERIES + EXTRA_UNANSWERABLE


# ---------------------------------------------------------------------------
# RETRIEVAL METRICS
# ---------------------------------------------------------------------------
# Must match search()'s default max_per_doc: at most this many chunks from one
# document can appear in the top-k, which caps achievable chunk-level precision.
SEARCH_MAX_PER_DOC = 2

# Use the app's real refusal thresholds so the eval reflects actual behaviour.
try:
    from generate_answer import MIN_RETRIEVAL_SCORE, WEAK_RETRIEVAL_SCORE
except Exception:  # generate_answer needs groq etc.; fall back to env / defaults
    MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.54"))
    WEAK_RETRIEVAL_SCORE = float(os.getenv("WEAK_RETRIEVAL_SCORE", "0.55"))


def precision_at_k(retrieved_files: list, relevant_files: set, k: int) -> Optional[float]:
    """Standard chunk-level P@k: relevant chunks in the top-k, divided by k.

    (It used to divide by the number of chunks actually returned, so a query
    that returned only 2 chunks, both relevant, scored a perfect 1.00. Dividing
    by k means under-filled result lists are now penalised, not rewarded.)
    Returns None for deliberately-unanswerable queries (empty relevant set).
    """
    if not relevant_files:
        return None
    return sum(1 for f in retrieved_files[:k] if f in relevant_files) / k


def precision_ceiling(n_relevant: int, k: int, max_per_doc: int = SEARCH_MAX_PER_DOC) -> float:
    """Best P@k any system could score given the per-document cap. With one
    relevant document and a cap of 2 chunks/doc, P@3 can never exceed 0.67."""
    return min(k, n_relevant * max_per_doc) / k


def hit_at_k(retrieved_files: list, relevant_files: set, k: int) -> Optional[float]:
    """1.0 if ANY relevant document appears in the top-k, else 0.0."""
    if not relevant_files:
        return None
    return 1.0 if any(f in relevant_files for f in retrieved_files[:k]) else 0.0


def recall_at_k(retrieved_files: list, relevant_files: set, k: int) -> Optional[float]:
    """Document-level recall: fraction of the relevant documents found in the top-k."""
    if not relevant_files:
        return None
    return len(set(retrieved_files[:k]) & relevant_files) / len(relevant_files)


def reciprocal_rank(retrieved_files: list, relevant_files: set) -> Optional[float]:
    """1/rank of the first relevant hit, 0 if none found in the ranking."""
    if not relevant_files:
        return None
    for i, f in enumerate(retrieved_files, start=1):
        if f in relevant_files:
            return 1.0 / i
    return 0.0


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _is_bulk(relevant_files) -> bool:
    """True for queries labeled with the numbered Supreme Court bulk files."""
    return bool(relevant_files) and all(f.startswith("20") and f.endswith("_EN.pdf") for f in relevant_files)


def threshold_calibration(per_query: list) -> dict:
    """What would the app's MIN_RETRIEVAL_SCORE do on this query set, and what
    value would separate answerable from unanswerable queries best?

    Uses each query's top retrieval score -- the number the app compares to the
    threshold. Sweeps candidate thresholds and keeps the one that refuses the
    most unanswerable queries while wrongly refusing the fewest answerable ones.
    """
    ans = [q["max_retrieval_score"] for q in per_query if not q["is_unanswerable_check"]]
    una = [q["max_retrieval_score"] for q in per_query if q["is_unanswerable_check"]]
    if not ans or not una:
        return {}

    def outcome(t):
        return sum(1 for u in una if u < t), sum(1 for a in ans if a < t)  # (refused unans, wrongly refused ans)

    best_t, best_score = None, -1
    for i in range(30, 71):
        t = i / 100
        r_u, w_a = outcome(t)
        score = r_u + (len(ans) - w_a)
        if score > best_score:
            best_t, best_score = t, score
    # among equally good thresholds, report the middle of the plateau
    plateau = [i / 100 for i in range(30, 71)
               if (lambda r_u, w_a: r_u + (len(ans) - w_a))(*outcome(i / 100)) == best_score]
    best_t = plateau[len(plateau) // 2]

    cur_u, cur_a = outcome(MIN_RETRIEVAL_SCORE)
    bst_u, bst_a = outcome(best_t)
    return {
        "n_answerable": len(ans), "n_unanswerable": len(una),
        "answerable_top_score_min": round(min(ans), 3),
        "answerable_top_score_median": round(sorted(ans)[len(ans) // 2], 3),
        "unanswerable_top_score_max": round(max(una), 3),
        "unanswerable_top_score_median": round(sorted(una)[len(una) // 2], 3),
        "current_threshold": MIN_RETRIEVAL_SCORE,
        "current_unanswerable_refused": cur_u, "current_answerable_wrongly_refused": cur_a,
        "best_threshold": best_t,
        "best_unanswerable_refused": bst_u, "best_answerable_wrongly_refused": bst_a,
        "separable": max(una) < min(ans),
    }


def run_retrieval_eval(test_queries: list, index, records, embed_model, k: int = 3, rerank: bool = False, hybrid: bool = True) -> dict:
    per_query = []
    for item in test_queries:
        results = search(item["query"], index, records, embed_model, top_k=k, rerank=rerank, hybrid=hybrid)
        retrieved_files = [r["source_file"] for r in results]
        relevant = set(item["relevant_files"])

        p_at_k = precision_at_k(retrieved_files, relevant, k)
        ceiling = precision_ceiling(len(relevant), k) if relevant else None
        rr = reciprocal_rank(retrieved_files, relevant)

        # For deliberately-unanswerable queries (empty relevant_files), what we
        # want is a LOW top score so the app refuses -- see threshold_calibration().
        is_unanswerable_check = len(relevant) == 0
        max_score = max((r["score"] for r in results), default=0.0)

        per_query.append({
            "query": item["query"],
            "retrieved_files": retrieved_files,
            "retrieved_scores": [round(r["score"], 3) for r in results],
            "relevant_files": list(relevant),
            "slice": "unanswerable" if is_unanswerable_check else ("bulk_sc" if _is_bulk(relevant) else "original_30"),
            "n_results_returned": len(results),
            "precision_at_k": p_at_k,
            "precision_ceiling": ceiling,
            "normalized_precision": (p_at_k / ceiling) if (p_at_k is not None and ceiling) else None,
            "hit_at_k": hit_at_k(retrieved_files, relevant, k),
            "recall_at_k": recall_at_k(retrieved_files, relevant, k),
            "reciprocal_rank": rr,
            "is_unanswerable_check": is_unanswerable_check,
            "max_retrieval_score": round(max_score, 3),
        })

    scored = [q for q in per_query if q["precision_at_k"] is not None]

    def agg(rows):
        return {
            "n": len(rows),
            "precision_at_k": _mean(q["precision_at_k"] for q in rows),
            "normalized_precision": _mean(q["normalized_precision"] for q in rows),
            "hit_at_k": _mean(q["hit_at_k"] for q in rows),
            "recall_at_k": _mean(q["recall_at_k"] for q in rows),
            "mrr": _mean(q["reciprocal_rank"] for q in rows),
        }

    return {
        "per_query": per_query,
        "overall": agg(scored),
        "by_slice": {name: agg([q for q in scored if q["slice"] == name])
                     for name in ("original_30", "bulk_sc")},
        # kept for backward compatibility with older saved reports / scripts
        "avg_precision_at_k": _mean(q["precision_at_k"] for q in scored),
        "avg_mrr": _mean(q["reciprocal_rank"] for q in scored),
        "calibration": threshold_calibration(per_query),
        "k": k,
        "n_scored_queries": len(scored),
        "n_unanswerable_queries": len(per_query) - len(scored),
        "n_underfilled": sum(1 for q in per_query if q["n_results_returned"] < k),
    }


def _fmt(x):
    return "N/A" if x is None else f"{x:.3f}"


def print_retrieval_report(report: dict):
    k = report["k"]
    print(f"\n{'='*70}\nRETRIEVAL METRICS (k={k})\n{'='*70}")
    for q in report["per_query"]:
        print(f"\nQuery: {q['query']}")
        print(f"  Retrieved: {list(zip(q['retrieved_files'], q['retrieved_scores']))}")
        if q["is_unanswerable_check"]:
            s = q["max_retrieval_score"]
            if s < MIN_RETRIEVAL_SCORE:
                status = f"REFUSED by the app (below {MIN_RETRIEVAL_SCORE}) -- good"
            elif s < WEAK_RETRIEVAL_SCORE:
                status = f"answered but flagged WEAK (below {WEAK_RETRIEVAL_SCORE}) -- borderline"
            else:
                status = "ANSWERED CONFIDENTLY -- bad, the app would not refuse this"
            print(f"  [Unanswerable] top score = {s} -> {status}")
        else:
            warn = ""
            if q["max_retrieval_score"] < MIN_RETRIEVAL_SCORE:
                warn = f"   !! top score {q['max_retrieval_score']} < {MIN_RETRIEVAL_SCORE}: app would WRONGLY REFUSE"
            print(f"  Hit@{k}: {q['hit_at_k']:.0f}   P@{k}: {q['precision_at_k']:.2f} "
                  f"(max possible {q['precision_ceiling']:.2f})   RR: {q['reciprocal_rank']:.2f}{warn}")

    o = report["overall"]
    print(f"\n{'-'*70}\nOVERALL ({report['n_scored_queries']} scored queries, "
          f"{report['n_unanswerable_queries']} unanswerable)")
    print(f"  Hit@{k} (any relevant doc in top-{k}): {_fmt(o['hit_at_k'])}")
    print(f"  MRR:                                  {_fmt(o['mrr'])}")
    print(f"  Recall@{k} (doc level):                 {_fmt(o['recall_at_k'])}")
    print(f"  Precision@{k} (chunk level):            {_fmt(o['precision_at_k'])}")
    print(f"  Precision@{k} / achievable maximum:     {_fmt(o['normalized_precision'])}")
    print("\nBy corpus slice:")
    for name, label in (("original_30", "original 30 docs"), ("bulk_sc", "80 SC bulk docs")):
        a = report["by_slice"][name]
        if a["n"]:
            print(f"  {label:18} n={a['n']:2}  Hit@{k}={_fmt(a['hit_at_k'])}  MRR={_fmt(a['mrr'])}  "
                  f"P@{k}/max={_fmt(a['normalized_precision'])}")
    if report.get("n_underfilled"):
        print(f"\n  NOTE: {report['n_underfilled']} queries returned fewer than {k} chunks.")

    c = report.get("calibration")
    if c:
        print(f"\n{'-'*70}\nREFUSAL-THRESHOLD CALIBRATION (top retrieval score per query)")
        print(f"  Answerable queries:   min {c['answerable_top_score_min']}, median {c['answerable_top_score_median']}")
        print(f"  Unanswerable queries: max {c['unanswerable_top_score_max']}, median {c['unanswerable_top_score_median']}")
        print(f"  Current MIN_RETRIEVAL_SCORE={c['current_threshold']}: refuses "
              f"{c['current_unanswerable_refused']}/{c['n_unanswerable']} unanswerable, "
              f"wrongly refuses {c['current_answerable_wrongly_refused']}/{c['n_answerable']} answerable")
        print(f"  Best threshold on this set = {c['best_threshold']}: refuses "
              f"{c['best_unanswerable_refused']}/{c['n_unanswerable']} unanswerable, "
              f"wrongly refuses {c['best_answerable_wrongly_refused']}/{c['n_answerable']} answerable")
        if not c["separable"]:
            print("  (Score ranges overlap -- no single threshold separates them perfectly; "
                  "a score cutoff alone can't fix this, consider a reranker.)")


# ---------------------------------------------------------------------------
# CITATION ACCURACY (full pipeline, uses Groq -- run with --full)
# ---------------------------------------------------------------------------
def run_citation_accuracy_eval(test_queries: list, index, records, embed_model, client) -> dict:
    from generate_answer import answer_query

    total_citations = 0
    supported = 0
    partial = 0
    not_supported = 0
    disputed = 0  # Groq and Gemini gave DIFFERENT verdicts -- see combine_verifier_verdicts()
    unverifiable = 0
    details = []

    for item in test_queries:
        result = answer_query(item["query"], index, records, embed_model, client, top_k=3, verify=True)
        verification = result.get("verification")
        if not verification:
            continue

        unverifiable += len(verification.get("unverifiable_citations", []))
        for c in verification.get("citations", []):
            total_citations += 1
            verdict = c["passage_support"].get("verdict", "unclear")
            if verdict == "yes":
                supported += 1
            elif verdict == "partial":
                partial += 1
            elif verdict == "disputed":
                # NOT the same as "not supported" -- this means the two
                # independent verifier models (Groq, Gemini) disagreed.
                # Bucketing it with genuine not-supported citations would
                # hide a real and reportable signal (cross-model
                # disagreement), not just miscategorize a count.
                disputed += 1
            else:
                not_supported += 1

        details.append({
            "query": item["query"],
            "answer": result["answer"],
            "verification": verification,
        })

    n = total_citations if total_citations else 1
    return {
        "total_citations": total_citations,
        "supported": supported,
        "partial": partial,
        "not_supported": not_supported,
        "disputed": disputed,
        "unverifiable_flagged": unverifiable,
        "support_rate": supported / n,
        "partial_rate": partial / n,
        "not_supported_rate": not_supported / n,
        "disputed_rate": disputed / n,
        "details": details,
    }


def print_citation_report(report: dict):
    print(f"\n{'='*70}\nCITATION ACCURACY\n{'='*70}")
    print(f"Total citations checked: {report['total_citations']}")
    print(f"  Supported:      {report['supported']}  ({report['support_rate']*100:.1f}%)")
    print(f"  Partial:        {report['partial']}  ({report['partial_rate']*100:.1f}%)")
    print(f"  Not supported:  {report['not_supported']}  ({report['not_supported_rate']*100:.1f}%)")
    if report.get("disputed", 0) > 0:
        print(f"  Disputed (Groq vs Gemini disagreed): {report['disputed']}  ({report['disputed_rate']*100:.1f}%)")
    print(f"  Unverifiable citations flagged (Step 1, not in corpus as own doc): {report['unverifiable_flagged']}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Also run citation accuracy eval (calls Groq -- slower, costs API usage)")
    parser.add_argument("--k", type=int, default=3, help="top-K for retrieval metrics")
    parser.add_argument("--rerank", action="store_true",
                        help="Enable Cross-Encoder re-ranking stage (scores top candidates with cross-encoder)")
    parser.add_argument("--no-hybrid", action="store_true",
                        help="Disable BM25 hybrid search and use pure FAISS dense retrieval")
    parser.add_argument("--save", type=str, default=None,
                        help="Optional path to save the full report as JSON, e.g. eval_results.json")
    args = parser.parse_args()

    print("Loading saved FAISS index...")
    index, records, model_name = load_index(INDEX_DIR)

    from rag_pipeline import load_embedding_model
    embed_model = load_embedding_model(model_name)

    mode_desc = "Hybrid (BM25 + FAISS)" if not args.no_hybrid else "Pure FAISS Dense"
    if args.rerank:
        mode_desc += " + Cross-Encoder Re-ranker"
    print(f"Retrieval mode: {mode_desc}\n")

    retrieval_report = run_retrieval_eval(
        TEST_QUERIES, index, records, embed_model, k=args.k,
        rerank=args.rerank, hybrid=not args.no_hybrid
    )
    print_retrieval_report(retrieval_report)

    full_report = {"retrieval": retrieval_report}

    if args.full:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY not set -- needed for --full citation accuracy eval.")
        from groq import Groq
        client = Groq(api_key=groq_key)

        citation_report = run_citation_accuracy_eval(TEST_QUERIES, index, records, embed_model, client)
        print_citation_report(citation_report)
        full_report["citation_accuracy"] = citation_report

    if args.save:
        with open(args.save, "w") as f:
            json.dump(full_report, f, indent=2, default=str)
        print(f"\nFull report saved to {args.save}")