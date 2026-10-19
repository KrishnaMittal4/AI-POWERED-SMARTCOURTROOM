"""
Moot Court Adversarial Debate Engine
====================================
Simulates an adversarial courtroom trial with 3 AI agents:
1. Petitioner Counsel (Groq)  - Establishes legal grounds & cites supporting precedents
2. Respondent Counsel (Groq)  - Rebuts claims, distinguishes precedents & raises defense
3. Presiding Bench (Gemini)   - Delivers reasoned judicial order, ratio decidendi & disposition

Leverages:
- Dual-perspective FAISS vector retrieval (Prosecution vs. Defense passages)
- Groq (openai/gpt-oss-20b) for rapid counsel arguments
- Gemini 3.8 Flash for judicial reasoning, with truthful Groq resilience fallback
- Graceful fallbacks so neither API downtime halts the courtroom
"""

import json
import logging
import os
import re
from typing import Optional
from groq import Groq

logger = logging.getLogger(__name__)

from llm_router import (
    GEMINI_REASONING_MODEL as GEMINI_MODEL,
    GROQ_PRIMARY_MODEL as PRIMARY_GROQ_MODEL,
    GROQ_FALLBACK_MODEL as FALLBACK_GROQ_MODEL,
    gemini_then_groq, route_task, gemini_configured,
)


def _format_passages(sources: list) -> str:
    lines = []
    for i, s in enumerate(sources, 1):
        name = s.get("case_name") or s.get("source_file") or f"Case #{i}"
        court = s.get("court", "Court")
        text = s.get("text", "").strip()[:500]
        lines.append(f"[{i}] {name} ({court}):\n\"{text}\"")
    return "\n\n".join(lines) if lines else "No specific corpus passages retrieved."


def _retrieve_for_perspective(query: str, index, records, embed_model, top_k: int = 4) -> list:
    """Retrieve top passages from FAISS for a given query string."""
    if index is None or not records or embed_model is None:
        return []
    try:
        qvec = embed_model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")
        scores, ids = index.search(qvec, top_k)
        results = []
        for score, idx in zip(scores[0], ids[0]):
            if 0 <= idx < len(records):
                r = records[idx]
                results.append({
                    "case_name": r.get("case_name"),
                    "source_file": r.get("source_file"),
                    "court": r.get("court"),
                    "text": r.get("raw_text", r.get("text", "")),
                    "score": float(score),
                })
        return results
    except Exception as e:
        logger.error(f"Error retrieving for perspective '{query}': {e}")
        return []


def _call_groq(client: Groq, prompt: str, system_prompt: str, max_tokens: int = 700) -> tuple[str, str]:
    """Moot Court generation: Gemini primary, Groq fallback with a safe output budget."""
    result = route_task(
        "moot", prompt, groq_client=client, system_prompt=system_prompt,
        purpose="reason", max_tokens=min(max_tokens, 700), temperature=0.2,
    )
    if result.get("ok"):
        label = f"{str(result.get('provider','ai')).title()} ({result.get('model','configured model')})"
        if result.get("fallback_used"):
            label += " [fallback]"
        return result.get("text", ""), label
    logger.warning("Moot Court providers unavailable: %s", result.get("error"))
    return "Oral submission placed on record based on the written brief.", "Provider unavailable"


def _call_gemini_or_fallback(prompt: str, system_prompt: str, groq_client: Optional[Groq] = None) -> tuple[str, dict]:
    result = route_task(
        "moot", prompt, groq_client=groq_client, system_prompt=system_prompt,
        purpose="reason", max_tokens=700, temperature=0.2,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "No LLM available for Presiding Judge."))
    meta = {
        "provider": result.get("provider"), "model": result.get("model"),
        "fallback_reason": result.get("fallback_reason"),
        "resilience_fallback": result.get("fallback_used", False),
        "token_budget": result.get("token_budget"), "latency_ms": result.get("latency_ms"),
    }
    return result.get("text", ""), meta


def run_moot_court_debate(
    dispute: str,
    index=None,
    records: list = None,
    embed_model=None,
    groq_client: Groq = None,
    use_graph: bool = True,
) -> dict:
    """
    Executes an adversarial courtroom debate.
    Uses LangGraph StateGraph orchestration by default, falling back to
    imperative execution if needed.
    """
    if not groq_client and not gemini_configured():
        raise ValueError("Configure GEMINI_API_KEY or GROQ_API_KEY for Moot Court.")

    if use_graph:
        try:
            from graphs.moot_court_graph import run_moot_court_graph
            return run_moot_court_graph(
                dispute=dispute,
                index=index,
                records=records,
                embed_model=embed_model,
                groq_client=groq_client,
            )
        except Exception as e:
            logger.warning("LangGraph Moot Court execution error, proceeding with procedural fallback: %s", e)

    # 1. Dual Retrieval from FAISS (0 LLM cost)
    petitioner_passages = _retrieve_for_perspective(
        f"{dispute} liability violation strict interpretation maintainable",
        index, records, embed_model, top_k=3
    )
    respondent_passages = _retrieve_for_perspective(
        f"{dispute} not liable exception defense quash distinguished lack of evidence",
        index, records, embed_model, top_k=3
    )

    petitioner_docs_text = _format_passages(petitioner_passages)
    respondent_docs_text = _format_passages(respondent_passages)

    # 2. Stage 1: Petitioner Counsel (Prosecution/Petitioner)
    petitioner_system = """You are Senior Advocate for the Petitioner/Prosecution in a prestigious High Court / Supreme Court bench.
Your task:
- Argue forcefully in favor of the Petitioner based on the statutory scheme and judicial precedents.
- Structure your submission clearly with:
  1. Primary Contention (The core violation/claim)
  2. Legal Foundation & Statutory Mandate
  3. Precedents & Corpus Evidentiary Support (Cite cases provided accurately)
  4. Prayer / Relief Sought
Be formal, authoritative, and persuasive in common law courtroom tradition.
Keep length to 350-450 words."""

    petitioner_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

RELEVANT SUPPORTING PRECEDENTS & PASSAGES IN CORPUS:
{petitioner_docs_text}

Present the Petitioner's opening oral submission to the Bench:"""

    petitioner_argument, pet_model = _call_groq(groq_client, petitioner_prompt, petitioner_system)

    # 3. Stage 2: Respondent Counsel (Defense/Accused)
    respondent_system = """You are Senior Advocate for the Respondent/Defense in this High Court / Supreme Court bench.
Your task:
- Directly rebut the Petitioner's contentions.
- Distinguish the precedents cited by the Petitioner on facts and ratio.
- Argue exceptions, bona fides, lack of statutory ingredients, or contrary judicial authorities.
- Structure your submission clearly with:
  1. Preliminary Objections / Counter-Plea
  2. Rebuttal & Distinguishing of Petitioner's Authorities
  3. Defense Precedents & Statutory Safeguards (Cite cases provided)
  4. Prayer for Dismissal / Relief
Be sharp, forensic, and respectful of the Bench.
Keep length to 350-450 words."""

    respondent_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

PETITIONER COUNSEL'S SUBMISSION:
{petitioner_argument}

RELEVANT DEFENSE PRECEDENTS & PASSAGES IN CORPUS:
{respondent_docs_text}

Present the Respondent's counter-submission and rebuttal to the Bench:"""

    respondent_argument, resp_model = _call_groq(groq_client, respondent_prompt, respondent_system)

    # 4. Stage 3: The Presiding Bench (Judicial Order)
    judge_system = """You are the Presiding Chief Justice of the Division Bench.
Deliver a reasoned judicial interim order / final judgment on the submissions.
Format your response with the following structured sections:
1. BENCH ASSESSMENT: Brief judicial evaluation of Petitioner's arguments and Respondent's counter-pleas.
2. DELIBERATION ON PRECEDENTS: Critical analysis of how the cited authorities apply or are distinguished.
3. RATIO DECIDENDI: The authoritative legal test or principle enunciated by this Bench (bolded and numbered).
4. FINAL DISPOSITION: Explicitly state the outcome (e.g. "Petition Allowed", "Petition Dismissed", "Criminal Proceedings Quashed", or "Interim Stay Granted") with brief directions.

Maintain judicial gravitas, impartiality, and legal rigor. Length: 400-550 words."""

    judge_prompt = f"""CASE TITLE / DISPUTE:
{dispute}

SUBMISSIONS OF PETITIONER COUNSEL:
{petitioner_argument}

SUBMISSIONS OF RESPONDENT COUNSEL:
{respondent_argument}

CORPUS AUTHORITIES REFERENCED:
Petitioner authorities:
{petitioner_docs_text}

Respondent authorities:
{respondent_docs_text}

Deliver the official reasoned Judicial Order of the Bench:"""

    judge_verdict, judge_meta = _call_gemini_or_fallback(judge_prompt, judge_system, groq_client=groq_client)

    # Determine winning side & disposition summary
    disposition = "Disposed with Directions"
    lower_verdict = judge_verdict.lower()
    if any(k in lower_verdict for k in ["petition allowed", "relief granted", "petitioner's argument is well-founded", "proceedings quashed", "quashing the complaint"]):
        disposition = "Petition Allowed (In Favor of Petitioner)"
        winner = "Petitioner"
    elif any(k in lower_verdict for k in ["petition dismissed", "no merit in the petition", "respondent's contention is upheld", "complaint is maintainable"]):
        disposition = "Petition Dismissed (In Favor of Respondent)"
        winner = "Respondent"
    else:
        winner = "Balanced / Directions Issued"

    return {
        "dispute": dispute,
        "petitioner": {
            "counsel": "Senior Counsel for Petitioner",
            "model": pet_model,
            "argument": petitioner_argument,
            "citations": petitioner_passages,
        },
        "respondent": {
            "counsel": "Senior Counsel for Respondent",
            "model": resp_model,
            "argument": respondent_argument,
            "citations": respondent_passages,
        },
        "bench": {
            "bench_title": "Division Bench / High Court",
            "model": f"{judge_meta['provider'].title()} ({judge_meta['model']})",
            "provider": judge_meta["provider"],
            "fallback_reason": judge_meta.get("fallback_reason"),
            "verdict": judge_verdict,
            "disposition": disposition,
            "prevailing_party": winner,
        },
    }


def answer_interlocutory_query(
    dispute: str,
    target_counsel: str,
    counsel_argument: str,
    judge_question: str,
    citations: list = None,
    groq_client: Groq = None,
) -> dict:
    """Answers an interactive question posed from the Bench to a specific Counsel."""
    if not groq_client and not gemini_configured():
        raise ValueError("Configure GEMINI_API_KEY or GROQ_API_KEY.")

    is_petitioner = target_counsel.lower() == "petitioner"
    counsel_title = "Senior Counsel for Petitioner" if is_petitioner else "Senior Counsel for Respondent"
    passages_text = _format_passages(citations or [])

    system_prompt = f"""You are {counsel_title} appearing before a Division Bench in an ongoing court hearing.
The Presiding Judge has directly posed a pointed interlocutory question from the Bench.
Your instructions:
1. Address the Bench with courtroom respect ("May it please Your Lordship / Learned Bench...").
2. Answer the Judge's specific query directly, incisively, and authoritatively.
3. Defend your client's stance, reconciling any statutory objections, limitations, or evidentiary hurdles.
4. Keep the response forensic, persuasive, and under 260 words."""

    user_prompt = f"""CASE DISPUTE / FACTS:
{dispute}

YOUR RECORDED ORAL SUBMISSION:
{counsel_argument}

RECORD AUTHORITIES:
{passages_text}

QUESTION POSED TO YOU FROM THE BENCH:
"{judge_question}"

Deliver your immediate oral response to the Bench:"""

    response_text, model_used = _call_groq(groq_client, user_prompt, system_prompt, max_tokens=1000)

    return {
        "target_counsel": "petitioner" if is_petitioner else "respondent",
        "counsel_title": counsel_title,
        "judge_question": judge_question,
        "response": response_text,
        "model": model_used,
    }


def reply_human_counsel(
    dispute: str,
    user_role: str,
    user_reply: str,
    round_number: int = 2,
    prior_exchange: list = None,
    index=None,
    records: list = None,
    embed_model=None,
    groq_client: Groq = None,
) -> dict:
    """
    Handles a follow-up reply/rebuttal from the Human Advocate in an ongoing session.
    Returns the AI opponent's counter-rebuttal and a brief bench interjection.
    prior_exchange: list of {'role': 'human'|'ai', 'text': str} for context.
    """
    if not groq_client and not gemini_configured():
        raise ValueError("Configure GEMINI_API_KEY or GROQ_API_KEY.")

    user_is_petitioner = user_role.lower() == "petitioner"
    opp_role_name = "Respondent" if user_is_petitioner else "Petitioner"
    user_role_name = "Petitioner" if user_is_petitioner else "Respondent"

    # Build conversational history for context
    history_text = ""
    if prior_exchange:
        for turn in prior_exchange[-6:]:  # last 3 exchanges for context
            prefix = f"HUMAN ({user_role_name.upper()})" if turn["role"] == "human" else f"AI OPPONENT ({opp_role_name.upper()})"
            history_text += f"\n{prefix}:\n{turn['text']}\n"

    # Retrieve fresh passages for the reply
    opp_query = (
        f"{dispute} not liable exception defense quash distinguished lack of evidence"
        if user_is_petitioner
        else f"{dispute} liability violation strict interpretation maintainable statutory breach"
    )
    opp_passages = _retrieve_for_perspective(opp_query, index, records, embed_model, top_k=2)
    opp_docs_text = _format_passages(opp_passages)

    # AI Opponent generates a pointed rebuttal to the human's latest reply
    opp_system = f"""You are Senior Advocate for the {opp_role_name} in an ongoing courtroom debate (Round {round_number}).
The Human Advocate for the {user_role_name} has just delivered a follow-up submission.
Your task:
- Address the Bench formally.
- Directly counter the Human Counsel's latest reply point-by-point.
- Cite any fresh authority from the corpus passages if helpful.
- Keep your counter-rebuttal sharp, incisive, and under 250 words.
- Start with "May it please the Bench, my learned friend's submission in reply is flawed on the following grounds…" or similar."""

    opp_prompt = f"""DISPUTE:
{dispute}

PRIOR EXCHANGE (for context):
{history_text}

HUMAN COUNSEL'S LATEST REPLY ({user_role_name.upper()}):
{user_reply}

SUPPORTING PASSAGES FOR {opp_role_name.upper()} SIDE:
{opp_docs_text}

Deliver your pointed counter-rebuttal to the Bench:"""

    opponent_reply, opp_model = _call_groq(groq_client, opp_prompt, opp_system, max_tokens=900)

    # Bench delivers a brief interjection / judicial observation
    bench_system = """You are the Presiding Chief Justice of the Division Bench during an ongoing oral hearing.
The advocates have just exchanged a further round of submissions.
Deliver a brief judicial interjection (1-3 sentences) that:
- Acknowledges both counsels' latest submissions.
- Poses ONE pointed judicial observation or hypothetical to sharpen the legal issue.
- Maintains judicial impartiality.
Keep it under 80 words. Use formal judicial tone."""

    bench_prompt = f"""DISPUTE: {dispute}

HUMAN COUNSEL'S LATEST REPLY:
{user_reply}

OPPOSING COUNSEL'S COUNTER-REBUTTAL:
{opponent_reply}

Deliver your brief judicial interjection:"""

    bench_observation, bench_meta = _call_gemini_or_fallback(bench_prompt, bench_system, groq_client=groq_client)

    return {
        "round": round_number,
        "user_role": user_role_name.lower(),
        "human_reply": user_reply,
        "opponent_rebuttal": opponent_reply,
        "opponent_model": opp_model,
        "bench_observation": bench_observation,
        "bench_model": f"{bench_meta['provider'].title()} ({bench_meta['model']})",
        "bench_provider": bench_meta["provider"],
        "bench_fallback_reason": bench_meta.get("fallback_reason"),
    }


def run_human_counsel_debate(
    dispute: str,
    user_role: str,
    user_argument: str,
    index=None,
    records: list = None,
    embed_model=None,
    groq_client: Groq = None,
) -> dict:
    """
    Executes 'Step In As Counsel' mode:
    1. Human Advocate presents oral argument for user_role (petitioner or respondent).
    2. Opposing AI Counsel generates direct forensic rebuttal.
    3. Presiding Bench evaluates both sides, pronounces judicial verdict,
       and delivers an Advocacy Scorecard with constructive critique.
    """
    if not groq_client and not gemini_configured():
        raise ValueError("Configure GEMINI_API_KEY or GROQ_API_KEY for Moot Court.")

    user_is_petitioner = user_role.lower() == "petitioner"
    opp_role_name = "Respondent" if user_is_petitioner else "Petitioner"
    user_role_name = "Petitioner" if user_is_petitioner else "Respondent"

    # 1. Retrieve supporting passages for AI Opponent
    if user_is_petitioner:
        # User is Petitioner; AI is Respondent Defense
        opp_query = f"{dispute} not liable exception defense quash distinguished lack of evidence"
    else:
        # User is Respondent; AI is Petitioner Prosecution
        opp_query = f"{dispute} liability violation strict interpretation maintainable statutory breach"

    opp_passages = _retrieve_for_perspective(opp_query, index, records, embed_model, top_k=3)
    opp_docs_text = _format_passages(opp_passages)

    # 2. Generate Opposing Counsel's submission
    if user_is_petitioner:
        opp_system = """You are Senior Advocate for the Respondent/Defense appearing before a High Court / Supreme Court bench.
The Human Senior Advocate for the Petitioner has just delivered their opening oral submissions.
Your task:
- Address the Bench formally and respectfully.
- Directly attack and dismantle the Petitioner Counsel's arguments point-by-point.
- Distinguish the authorities or assumptions relied upon by Petitioner.
- Highlight missing statutory ingredients, bona fides of the Respondent, or exceptions under law.
- Formally pray for dismissal of the petition with costs.
Length: 350-450 words. Be sharp, incisive, and forensic."""
        opp_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

HUMAN PETITIONER COUNSEL'S ORAL SUBMISSIONS:
{user_argument}

RELEVANT DEFENSE PRECEDENTS IN CORPUS:
{opp_docs_text}

Present the Respondent's direct counter-argument and rebuttal to the Bench:"""
    else:
        opp_system = """You are Senior Advocate for the Petitioner/Prosecution appearing before a High Court / Supreme Court bench.
The Human Senior Advocate for the Respondent has just raised preliminary objections and defenses.
Your task:
- Address the Bench formally and respectfully.
- Directly rebut the defense pleas raised by Respondent Counsel.
- Establish prima facie liability, statutory mandate, and why defenses are matters for trial.
- Cite the supporting precedents and pray for relief / continuation of proceedings.
Length: 350-450 words. Be forceful, authoritative, and persuasive."""
        opp_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

HUMAN RESPONDENT COUNSEL'S DEFENSE SUBMISSION:
{user_argument}

RELEVANT PROSECUTION PRECEDENTS IN CORPUS:
{opp_docs_text}

Present the Petitioner's opening oral submission and rebuttal of defense pleas to the Bench:"""

    opponent_argument, opp_model = _call_groq(groq_client, opp_prompt, opp_system)

    # 3. Presiding Bench Assessment & Advocacy Scorecard
    bench_system = f"""You are the Presiding Chief Justice of the Division Bench.
A Human Advocate has stepped in as Counsel for the {user_role_name}, facing Senior Counsel for the {opp_role_name} (AI opponent).

Deliver two distinct sections in your response:

---CRITIQUE_JSON---
{{
  "statutory_precision": <number 1-10 rating accuracy of legal concepts & statutes cited>,
  "precedents_score": <number 1-10 rating relevance and handling of case law>,
  "courtroom_etiquette": <number 1-10 rating persuasiveness, decorum, and forensic structure>,
  "total_score": <sum out of 30>,
  "grade": "<Distinction (27-30) / First Class (22-26) / Upper Second (18-21) / Needs Revision (<18)>",
  "winner": "<Petitioner or Respondent>",
  "disposition": "<e.g. Petition Allowed / Petition Dismissed / Interim Relief Granted>",
  "strengths": [
    "<Specific strength 1 of the Human Counsel's argument>",
    "<Specific strength 2 of the Human Counsel's argument>"
  ],
  "vulnerabilities": [
    "<Key statutory gap or weakness in the Human Counsel's argument>",
    "<Point where opposing counsel gained the advantage>"
  ],
  "bench_guidance": "<2-3 sentences of direct practical advice from the Chief Justice for improving this advocate's courtroom submissions>"
}}
---END_CRITIQUE_JSON---

---JUDICIAL_ORDER---
[Deliver the official reasoned Judicial Order of the Bench in 350-450 words:
1. BENCH ASSESSMENT OF SUBMISSIONS
2. RATIO DECIDENDI
3. FINAL OPERATIVE ORDER & DIRECTIONS]
---END_JUDICIAL_ORDER---"""

    bench_prompt = f"""CASE TITLE / PROPOSITION:
{dispute}

HUMAN ADVOCATE'S SUBMISSION ({user_role_name.upper()}):
{user_argument}

OPPOSING COUNSEL'S SUBMISSION ({opp_role_name.upper()}):
{opponent_argument}

AUTHORITIES CITED ON RECORD:
{opp_docs_text}

Evaluate both submissions, generate the Scorecard JSON, and pronounce the Judicial Order:"""

    raw_bench, bench_meta = _call_gemini_or_fallback(bench_prompt, bench_system, groq_client=groq_client)

    # 4. Parse Scorecard JSON & Judicial Order
    scorecard = {
        "statutory_precision": 8,
        "precedents_score": 7,
        "courtroom_etiquette": 8,
        "total_score": 23,
        "grade": "First Class (23/30)",
        "winner": user_role_name if "allowed" in raw_bench.lower() else opp_role_name,
        "disposition": "Disposed with Directions",
        "strengths": ["Well-structured opening submission", "Clear articulation of client's position"],
        "vulnerabilities": ["Could engage more deeply with specific statutory exceptions", "Anticipate counter-precedents more robustly"],
        "bench_guidance": "Frame your primary statutory contention within the first two sentences to seize immediate judicial attention.",
    }

    judicial_order = raw_bench

    # Extract JSON block if present
    json_match = re.search(r"---CRITIQUE_JSON---\s*(.*?)\s*---END_CRITIQUE_JSON---", raw_bench, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1).strip())
            scorecard.update(parsed)
        except Exception as e:
            logger.warning(f"Failed to parse critique JSON: {e}")

    # Extract Order block if present
    order_match = re.search(r"---JUDICIAL_ORDER---\s*(.*?)(?:---END_JUDICIAL_ORDER---|$)", raw_bench, re.DOTALL)
    if order_match:
        judicial_order = order_match.group(1).strip()
    elif json_match:
        # Strip out the json block
        judicial_order = re.sub(r"---CRITIQUE_JSON---\s*.*?\s*---END_CRITIQUE_JSON---", "", raw_bench, flags=re.DOTALL).strip()

    winner = scorecard.get("winner", user_role_name)
    disposition = scorecard.get("disposition", "Petition Disposed with Directions")

    petitioner_data = {
        "counsel": "Senior Counsel for Petitioner" + (" (You · Human Advocate)" if user_is_petitioner else " (AI Opponent)"),
        "is_human": user_is_petitioner,
        "model": "Human Advocate" if user_is_petitioner else opp_model,
        "argument": user_argument if user_is_petitioner else opponent_argument,
        "citations": [] if user_is_petitioner else opp_passages,
    }

    respondent_data = {
        "counsel": "Senior Counsel for Respondent" + (" (You · Human Advocate)" if not user_is_petitioner else " (AI Opponent)"),
        "is_human": not user_is_petitioner,
        "model": "Human Advocate" if not user_is_petitioner else opp_model,
        "argument": user_argument if not user_is_petitioner else opponent_argument,
        "citations": [] if not user_is_petitioner else opp_passages,
    }

    return {
        "mode": "human_vs_ai",
        "dispute": dispute,
        "user_role": user_role_name.lower(),
        "petitioner": petitioner_data,
        "respondent": respondent_data,
        "bench": {
            "bench_title": "Division Bench / High Court",
            "model": f"{bench_meta['provider'].title()} ({bench_meta['model']})",
            "provider": bench_meta["provider"],
            "fallback_reason": bench_meta.get("fallback_reason"),
            "verdict": judicial_order,
            "disposition": disposition,
            "prevailing_party": winner,
        },
        "scorecard": scorecard,
    }

