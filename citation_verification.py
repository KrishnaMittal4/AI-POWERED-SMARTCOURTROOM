"""
Citation Verification
======================
Implements the 3 checks from the project's core USP: don't blindly trust
the LLM's citations -- verify them against the actual corpus.

    1. EXISTENCE        -- does the cited case actually exist in our corpus?
    2. METADATA MATCH    -- does the case number mentioned match our records?
    3. PASSAGE SUPPORT    -- does the retrieved passage actually support the claim?
                            (checked with a second, cheap LLM call acting as a judge
                            -- and, when GEMINI_API_KEY is set, cross-checked with a
                            SECOND, independently-trained model: see
                            check_passage_support_gemini() below. Two models from
                            different vendors/training lineages agreeing is a much
                            stronger signal than two sizes of the same model family
                            agreeing with each other.)

Usage: called automatically from generate_answer.py after generation.
"""

import os
import re
from groq import Groq
from legal_judgment_intelligence import classify_legal_role
from product_readiness import evidence_strength, verification_overview

# Cheap/fast model for the verification pass -- doesn't need to be as
# strong as the generation model, just needs to judge entailment.
from llm_router import (
    GEMINI_VERIFY_MODEL as GEMINI_MODEL,
    GROQ_VERIFY_MODEL as VERIFIER_MODEL,
    GROQ_SECONDARY_VERIFY_MODEL as SECONDARY_GROQ_MODEL,
    call_gemini,
)

# Second, independent verifier model (different vendor/training lineage
# than the Groq-hosted OSS models above). Optional: only used if
# GEMINI_API_KEY is set in the environment -- everything falls back to
# Groq-only verification if it's missing or the call fails, so this is
# purely additive and never breaks the pipeline.
# NOTE: deliberately NOT read as a module-level constant here. A
# module-level `os.getenv("GEMINI_API_KEY")` would be evaluated the
# instant this file is imported -- which, depending on import order in
# the file that imports it, can happen BEFORE that file's own
# load_dotenv() call has actually populated os.environ, silently
# freezing this to None forever regardless of what's in .env. Reading it
# inside check_passage_support_gemini() at call time sidesteps that
# import-order trap entirely.

# Connector/common words to ignore when comparing case names by word-overlap.
# Without this, "Dinesan v. Baby" and "Mrs Jain Babu vs K J Joseph" share the
# word "vs" and would incorrectly be treated as a match.
_STOPWORDS = {"vs", "v", "and", "the", "of", "or", "others", "ors", "ltd",
              "limited", "state", "no", "on", "another", "anr", "etc"}


def _normalize(s: str) -> str:
    """Lowercase, drop punctuation, and collapse whitespace so that
    'Mrs. Jain Babu v. K.J. Joseph' and 'Mrs Jain Babu vs K J Joseph'
    (same case, different punctuation/abbreviation style -- the LLM and
    our filename-derived metadata rarely format it identically) compare
    equal.
    """
    s = s.lower()
    s = re.sub(r"[.\-,]", " ", s)
    s = re.sub(r"\bversus\b", "vs", s)
    s = re.sub(r"\bv\b", "vs", s)  # lone "v" (from "v." after stripping the dot) -> "vs"
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# STEP 1: EXISTENCE -- extract cited case names from the answer, check
# they actually exist in our corpus (catches hallucinated case names)
# ---------------------------------------------------------------------------
def extract_cited_case_names(answer_text: str, known_case_names: list) -> tuple[list, list]:
    """Find which known corpus case names are actually mentioned in the
    generated answer. A citation that ISN'T in known_case_names but LOOKS
    like a case citation (e.g. 'X v. Y') is flagged separately as
    unverifiable.
    """
    # Strip 【...】-style bracketed tags before pattern-scanning for new
    # citations. LLMs sometimes lift a repeated document header straight
    # out of the retrieved passage text and paste it in as a bracketed
    # source tag -- that's a formatting artifact, not a fresh citation,
    # and scanning it as prose creates noisy duplicate false positives.
    bracket_tags = re.findall(r"【([^】]+)】", answer_text)
    scan_text = re.sub(r"【[^】]*】", " ", answer_text)

    normalized_answer = _normalize(answer_text)  # full text, punctuation-insensitive match
    found = []
    for name in set(known_case_names):
        if name and _normalize(name) in normalized_answer:
            found.append(name)

    # Also look for "X v. Y" / "X vs Y" style patterns not in our corpus
    # at all -- these are the dangerous hallucinated citations.
    # Handles both regular spaces and non-breaking spaces (\u202f, \xa0)
    # that LLMs sometimes emit around "v."
    # NOTE: character class includes "/" to allow the common Indian
    # citation abbreviation "M/s" (Messrs, used before company names),
    # e.g. "M/s Bhaskar Industries Ltd. v. M/s Bhiwani Denim..." -- this
    # was previously dropped silently since "/" wasn't in the class.
    CITATION_RE = r"([A-Z][A-Za-z./,&\s]{2,40}\s+v\.?s?\.?\s+[A-Z][A-Za-z./,&\s]{2,40})"
    vs_pattern = re.findall(
        CITATION_RE, scan_text.replace("\u202f", " ").replace("\xa0", " ")
    )
    # Bracketed tags can still contain a genuine "X v. Y" pattern (just in
    # a different spot); check those too, but keep them in a separate pass
    # since they're often just a repeat of the source doc's own header.
    for tag in bracket_tags:
        vs_pattern.extend(re.findall(CITATION_RE, tag))

    unverifiable = []
    seen_normalized = set()
    for candidate in vs_pattern:
        candidate_clean = candidate.strip()
        candidate_norm = _normalize(candidate_clean)
        if not candidate_clean or candidate_norm in seen_normalized:
            continue  # skip empty/duplicate candidates (e.g. repeated header artifacts)

        # A candidate is considered verified if EITHER side of "v./vs" shares
        # any word with a known case name -- catches abbreviated forms like
        # "Kumar v. Suresh" matching the full name "Ramesh Kumar" -- OR if
        # its normalized form is a substring of any known name (catches
        # truncated fragments like "... on" from a cut-off header).
        #
        # Tokens shorter than 3 characters are excluded from the overlap
        # check. Single-letter tokens are very often initials ("K." in
        # "K. Venugopalan", "R." in "Navaneetha Krishnan R.") that
        # coincidentally collide between two completely unrelated case
        # names -- without this filter, a hallucinated citation sharing
        # nothing but a stray initial with a real corpus case is wrongly
        # treated as "matched" and silently dropped instead of being
        # flagged as unverifiable.
        candidate_words = {w for w in re.findall(r"[a-z]+", candidate_norm) if len(w) >= 3} - _STOPWORDS
        is_matched = any(
            (candidate_words & ({w for w in re.findall(r"[a-z]+", _normalize(n)) if len(w) >= 3} - _STOPWORDS))
            or (candidate_norm and candidate_norm in _normalize(n))
            for n in known_case_names
        )
        if not is_matched:
            unverifiable.append(candidate_clean)
            seen_normalized.add(candidate_norm)

    return found, unverifiable


def check_existence(cited_name: str, records: list) -> dict:
    matches = [r for r in records if r["case_name"] == cited_name]
    return {
        "cited_name": cited_name,
        "exists_in_corpus": len(matches) > 0,
        "matched_files": list({m["source_file"] for m in matches}),
    }


# ---------------------------------------------------------------------------
# STEP 2: METADATA CONSISTENCY -- does the case number mentioned in the
# answer (if any) match what's actually on record for that case?
# ---------------------------------------------------------------------------
def check_metadata_consistency(answer_text: str, cited_name: str, records: list) -> dict:
    record_matches = [r for r in records if r["case_name"] == cited_name]
    if not record_matches:
        return {"checked": False, "reason": "case not in corpus, see existence check"}

    true_case_no = record_matches[0]["case_no"]

    # crude check: does the true case number (or its digits) appear
    # somewhere near the citation in the answer text?
    if true_case_no != "Unknown" and true_case_no.lower() in answer_text.lower():
        return {"checked": True, "consistent": True, "expected_case_no": true_case_no}

    # fallback: just check the numeric part matches, in case formatting differs
    digits = re.findall(r"\d+", true_case_no)
    if digits and any(d in answer_text for d in digits):
        return {"checked": True, "consistent": True, "expected_case_no": true_case_no}

    return {
        "checked": True,
        "consistent": None,  # not confirmed, not necessarily wrong -- answer may just not restate it
        "expected_case_no": true_case_no,
        "note": "Case number not restated in answer -- not an error by itself, just unconfirmed.",
    }


# ---------------------------------------------------------------------------
# STEP 3: PASSAGE SUPPORT -- ask a cheap LLM to judge whether the passage
# actually supports the claim attributed to it
# ---------------------------------------------------------------------------
def _extract_claim_segment(answer_text: str, cited_name: str) -> str:
    """Isolate just the portion of the answer that actually makes a claim
    about cited_name, instead of handing the ENTIRE (possibly multi-case)
    answer to the fact-checker as "the claim". Without this, a passage
    for one case gets judged against claims made about OTHER cases in
    the same answer (e.g. a markdown table with one row per case) and
    will almost always fail -- not because the citation is wrong, but
    because the scope of what's being checked is wrong.

    Falls back to the full answer_text if no segment can be isolated
    (e.g. a short prose answer that never repeats the case name per line).
    """
    name_words = set(re.findall(r"[a-z]+", _normalize(cited_name))) - _STOPWORDS
    if not name_words:
        return answer_text

    def mentions_name(segment: str) -> bool:
        seg_norm = _normalize(segment)
        seg_words = set(re.findall(r"[a-z]+", seg_norm)) - _STOPWORDS
        # Require most of the case's distinctive words to appear (not just
        # one, to avoid matching on a single common surname elsewhere).
        return len(name_words & seg_words) >= max(1, len(name_words) - 1)

    # Try line-level first -- handles markdown tables (one case per row)
    # and single-line bullet points, which is how these answers are
    # usually formatted.
    lines = [l for l in answer_text.split("\n") if l.strip()]
    matched = [l for l in lines if mentions_name(l)]
    if matched:
        return "\n".join(matched)[:2000]

    # Fall back to sentence-level for prose answers that don't repeat the
    # case name on its own line.
    sentences = re.split(r"(?<=[.!?])\s+", answer_text)
    matched = [s for s in sentences if mentions_name(s)]
    if matched:
        return " ".join(matched)[:2000]

    # Last resort: nothing isolated a specific segment -- use the whole
    # answer rather than checking against nothing.
    return answer_text


def _build_judge_prompt(cited_name: str, combined_passage: str, claim_segment: str) -> str:
    """Shared prompt builder -- both verifier models (Groq and Gemini) are
    asked the EXACT same question over the EXACT same passage/claim pair,
    so any disagreement between them reflects a genuine difference in
    judgment, not a difference in what each model was even asked.
    """
    return f"""You are a strict fact-checker for a legal RAG system. \
You will be shown a PASSAGE and a CLAIM.

IMPORTANT: it has ALREADY been confirmed, by separate metadata lookup, \
that this PASSAGE comes from the case "{cited_name}". Do NOT re-check or \
comment on whether the passage names, identifies, or announces itself as \
that case -- assume that part is correct even if the passage text itself \
never repeats the case name (most excerpts from the middle of a judgment \
won't). A passage can fully support a claim without literally saying the \
case's own name in it.

Your ONLY job: does the CONTENT of the passage -- the facts, reasoning, \
or quoted language in it -- actually support the substance of the CLAIM \
below? If the passage's own text contains, quotes, or closely paraphrases \
the same holding/fact as the claim, that is SUPPORTED, even if worded \
differently or if the passage also discusses other precedents, other \
named parties, or additional context alongside it.

PASSAGE (confirmed to be from "{cited_name}"):
{combined_passage}

CLAIM (the portion of the generated answer specifically about "{cited_name}"):
{claim_segment}

Respond in EXACTLY this format:
SUPPORTED: yes|no|partial
REASON: <one short sentence>"""


def _parse_verdict(verdict_text: str) -> tuple[str, str]:
    supported_match = re.search(r"SUPPORTED:\s*(yes|no|partial)", verdict_text, re.IGNORECASE)
    reason_match = re.search(r"REASON:\s*(.+)", verdict_text, re.IGNORECASE)
    verdict = supported_match.group(1).lower() if supported_match else "unclear"
    reason = reason_match.group(1).strip() if reason_match else verdict_text
    return verdict, reason


def _get_passage_and_claim(cited_name: str, answer_text: str, retrieved_passages: list, records: list):
    """Shared retrieval of the passage text + claim segment, used by both
    verifier models so they're judging the identical input.
    """
    passage_texts = [p["text"] for p in retrieved_passages if p["case_name"] == cited_name]
    if not passage_texts:
        passage_texts = [r["text"] for r in records if r["case_name"] == cited_name][:2]
    if not passage_texts:
        return None, None

    combined_passage = "\n---\n".join(passage_texts[:2])  # cap length
    claim_segment = _extract_claim_segment(answer_text, cited_name)
    return combined_passage, claim_segment


def check_passage_support(cited_name: str, answer_text: str, retrieved_passages: list, records: list, client: Groq) -> dict:
    # Use the ACTUAL passage(s) retrieved and shown to the generation
    # model for this case -- not just any chunk from the full corpus.
    # Using the wrong chunk (e.g. the document's opening header, which is
    # what you'd get by grabbing "the first chunk for this case_name")
    # means the generator can be perfectly accurate about deep-document
    # reasoning while the verifier always fails it, because it's checking
    # against unrelated text the generator never even saw.
    combined_passage, claim_segment = _get_passage_and_claim(cited_name, answer_text, retrieved_passages, records)
    if combined_passage is None:
        return {"checked": False, "reason": "no retrieved passage available for this case"}

    judge_prompt = _build_judge_prompt(cited_name, combined_passage, claim_segment) # type: ignore

    response = client.chat.completions.create(
        model=VERIFIER_MODEL,
        messages=[{"role": "user", "content": judge_prompt}],
        temperature=0,
    )
    verdict_text = (response.choices[0].message.content or "").strip()
    verdict, reason = _parse_verdict(verdict_text)

    return {"checked": True, "verdict": verdict, "reason": reason}


def check_passage_support_secondary(cited_name: str, answer_text: str, retrieved_passages: list, records: list, client: Groq) -> dict:
    """Independent Gemini cross-check with centralized retry policy; Groq only as resilience fallback."""
    combined_passage, claim_segment = _get_passage_and_claim(cited_name, answer_text, retrieved_passages, records)
    if combined_passage is None:
        return {"checked": False, "reason": "no retrieved passage available for this case", "provider": "none"}

    judge_prompt = _build_judge_prompt(cited_name, combined_passage, claim_segment)
    gemini = call_gemini(judge_prompt, purpose="verify")
    if gemini.get("ok"):
        verdict, reason = _parse_verdict(gemini.get("text", ""))
        return {
            "checked": True, "verdict": verdict, "reason": reason,
            "provider": "gemini", "model": gemini.get("model", GEMINI_MODEL),
            "gemini_attempts": gemini.get("attempts", 1), "independent_provider": True,
        }

    gemini_error = gemini.get("error", "Gemini unavailable")
    try:
        response = client.chat.completions.create(
            model=SECONDARY_GROQ_MODEL,
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0,
        )
        verdict, reason = _parse_verdict((response.choices[0].message.content or "").strip())
        return {
            "checked": True, "verdict": verdict, "reason": reason,
            "provider": "groq_fallback", "model": SECONDARY_GROQ_MODEL,
            "fallback_reason": gemini_error, "gemini_attempts": gemini.get("attempts", 0),
            "independent_provider": False,
        }
    except Exception as exc:
        return {
            "checked": False,
            "reason": f"Secondary verification unavailable. Gemini: {gemini_error}; Groq fallback: {exc}",
            "provider": "none", "gemini_attempts": gemini.get("attempts", 0),
            "independent_provider": False,
        }

def combine_verifier_verdicts(groq_support: dict, secondary_support: dict) -> dict:
    """Merge the two independent verdicts into one. If Gemini wasn't
    checked (no key / call failed), just pass Groq's verdict through
    unchanged -- existing behavior for anyone not using the Gemini
    cross-check is completely unaffected. If both ran: agreement raises
    confidence, disagreement is surfaced explicitly as "disputed" rather
    than silently picking one side -- that disagreement is itself a
    useful, reportable signal, not noise to hide.
    """
    if not secondary_support.get("checked"):
        combined = dict(groq_support)
        combined["gemini_checked"] = False
        # Keep the skip/failure reason (e.g. "GEMINI_API_KEY not set", or
        # a network/quota error) separate from Groq's own reason, so the
        # UI can show *why* the cross-check didn't run instead of just
        # silently omitting it.
        combined["gemini_skip_reason"] = secondary_support.get("reason", "")
        return combined

    groq_verdict = groq_support.get("verdict", "unclear")
    gemini_verdict = secondary_support.get("verdict", "unclear")

    if groq_verdict == gemini_verdict:
        return {
            "checked": True,
            "verdict": groq_verdict,
            "reason": groq_support.get("reason", ""),
            "gemini_checked": True,
            "agreement": True,
            "gemini_reason": secondary_support.get("reason", ""),
            "secondary_provider": secondary_support.get("provider", "gemini"),
            "secondary_model": secondary_support.get("model", GEMINI_MODEL),
            "fallback_reason": secondary_support.get("fallback_reason"),
            "gemini_attempts": secondary_support.get("gemini_attempts", 0),
            "independent_provider": secondary_support.get("independent_provider", False),
        }

    return {
        "checked": True,
        "verdict": "disputed",
        "reason": (
            f"Groq ({VERIFIER_MODEL}) said '{groq_verdict}': {groq_support.get('reason', '')} | "
            f"Secondary ({secondary_support.get('model', GEMINI_MODEL)}) said '{gemini_verdict}': {secondary_support.get('reason', '')}"
        ),
        "gemini_checked": True,
        "agreement": False,
        "groq_verdict": groq_verdict,
        "gemini_verdict": gemini_verdict,
        "secondary_provider": secondary_support.get("provider", "gemini"),
        "secondary_model": secondary_support.get("model", GEMINI_MODEL),
        "fallback_reason": secondary_support.get("fallback_reason"),
        "gemini_attempts": secondary_support.get("gemini_attempts", 0),
        "independent_provider": secondary_support.get("independent_provider", False),
    }


# ---------------------------------------------------------------------------
# V4.4: ATTRIBUTION-AWARE VERIFICATION
# ---------------------------------------------------------------------------
_COURT_CLAIM_RE = re.compile(
    r"\b(?:court|supreme court|high court|bench|it)\s+(?:held|holds|observed|found|ruled|concluded|decided|reasoned)\b|"
    r"\b(?:held|holding|ratio decidendi|the court's view|court's reasoning)\b",
    re.I,
)
_PARTY_CLAIM_RE = re.compile(
    r"\b(?:counsel|petitioner|appellant|respondent|party)\s+(?:submitted|contended|argued|urged|claimed)\b",
    re.I,
)
_COURT_ROLES = {"COURT_REASONING", "RATIO", "FINAL_ORDER"}
_PARTY_ROLES = {"PETITIONER_ARGUMENT", "RESPONDENT_ARGUMENT"}


def check_attribution(cited_name: str, answer_text: str, retrieved_passages: list, records: list) -> dict:
    """Check whether the generated claim attributes a proposition to the right speaker.

    This is deliberately deterministic and conservative. It does not decide whether
    the proposition is legally correct (passage_support already does that). It asks
    only whether wording such as "the Court held" is backed by a passage classified
    as court reasoning/ratio/order rather than a party submission.
    """
    claim = _extract_claim_segment(answer_text, cited_name)
    passage_rows = [p for p in retrieved_passages if p.get("case_name") == cited_name]
    if not passage_rows:
        passage_rows = [r for r in records if r.get("case_name") == cited_name][:2]
    if not passage_rows:
        return {"checked": False, "status": "uncertain", "reason": "No passage was available for attribution checking."}

    classified = []
    for row in passage_rows[:3]:
        role = row.get("legal_role")
        confidence = row.get("legal_role_confidence")
        if not role:
            info = classify_legal_role(row.get("raw_text") or row.get("text") or "")
            role, confidence = info["role"], info["confidence"]
        classified.append({"role": role or "UNKNOWN", "confidence": float(confidence or 0.0)})

    roles = [x["role"] for x in classified]
    best_conf = max((x["confidence"] for x in classified), default=0.0)
    claims_court = bool(_COURT_CLAIM_RE.search(claim or ""))
    claims_party = bool(_PARTY_CLAIM_RE.search(claim or ""))
    has_court = any(r in _COURT_ROLES for r in roles)
    has_party = any(r in _PARTY_ROLES for r in roles)

    base = {
        "checked": True,
        "claim_type": "court_holding" if claims_court else "party_submission" if claims_party else "neutral",
        "passage_roles": roles,
        "role_confidence": round(best_conf, 3),
    }
    if claims_court and has_party and not has_court:
        return {**base, "status": "mismatch", "reason": "The answer attributes the proposition to the Court, but the supporting passage is classified as a party submission."}
    if claims_court and has_court:
        return {**base, "status": "supported", "reason": "The Court attribution is supported by a court-reasoning, ratio, or final-order passage."}
    if claims_party and has_party:
        return {**base, "status": "supported", "reason": "The party attribution matches a petitioner/appellant/respondent argument passage."}
    if claims_party and has_court and not has_party:
        return {**base, "status": "mismatch", "reason": "The answer presents the proposition as a party submission, but the supporting passage is classified as the Court's reasoning or holding."}
    return {**base, "status": "uncertain", "reason": "The passage supports review, but speaker attribution cannot be established confidently from its legal-role metadata."}

# ---------------------------------------------------------------------------
# MAIN ENTRY POINT -- runs all 3 checks for every citation found
# ---------------------------------------------------------------------------
def verify_answer(answer_text: str, retrieved_passages: list, records: list, client: Groq) -> dict:
    known_case_names = [r["case_name"] for r in records]
    cited_names, unverifiable_citations = extract_cited_case_names(answer_text, known_case_names)

    report = {"citations": [], "unverifiable_citations": unverifiable_citations}

    for name in cited_names:
        existence = check_existence(name, records)
        metadata = check_metadata_consistency(answer_text, name, records)
        groq_support = check_passage_support(name, answer_text, retrieved_passages, records, client)
        secondary_support = check_passage_support_secondary(name, answer_text, retrieved_passages, records, client)
        support = combine_verifier_verdicts(groq_support, secondary_support)
        attribution = check_attribution(name, answer_text, retrieved_passages, records)

        citation = {
            "case_name": name,
            "existence": existence,
            "metadata": metadata,
            "passage_support": support,
            "attribution": attribution,
        }
        citation["evidence_strength"] = evidence_strength(citation)
        report["citations"].append(citation)

    report["overview"] = verification_overview(report["citations"])
    return report


def pretty_print_verification(report: dict):
    print("\n--- CITATION VERIFICATION ---")
    if report["unverifiable_citations"]:
        print(f"⚠ Citation-like text found that doesn't match any corpus case: "
              f"{report['unverifiable_citations']}")

    for c in report["citations"]:
        print(f"\n  Case: {c['case_name']}")
        print(f"    [Existence]  in corpus: {c['existence']['exists_in_corpus']} "
              f"(files: {c['existence']['matched_files']})")

        meta = c["metadata"]
        if meta.get("checked"):
            print(f"    [Metadata]   consistent: {meta.get('consistent')} "
                  f"(expected case no: {meta.get('expected_case_no')})")
        else:
            print(f"    [Metadata]   not checked: {meta.get('reason')}")

        support = c["passage_support"]
        attribution = c.get("attribution", {})
        if support.get("checked"):
            print(f"    [Support]    verdict: {support['verdict']} -- {support['reason']}")
            if support.get("gemini_checked"):
                agree_label = "agree" if support.get("agreement") else "DISAGREE"
                print(f"    [Cross-check] Groq vs Gemini: {agree_label}")
        else:
            print(f"    [Support]    not checked: {support.get('reason')}")
        if attribution.get("checked"):
            print(f"    [Attribution] {attribution.get('status')}: {attribution.get('reason')}")