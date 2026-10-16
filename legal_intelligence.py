"""
Legal Intelligence Suite for SmartCourtroom
============================================
Provides advanced analytical tools for advocates and legal researchers:

1. Precedent Checker (Shepardizing / KeyCite for Indian Law)
   - Flags whether cited cases are Good Law, Distinguished, or Overruled by a larger bench.

2. Ratio Decidendi vs. Obiter Dicta Extractor
   - Separates binding legal principles (ratio) from passing judicial remarks (obiter).

3. Legal Draft Generator
   - Converts factual research and verified citations into court-ready drafts
     (Section 138 Notice, Bail Petition, Recovery Notice, Writ Synopsis).
"""

import json
import re
from groq import Groq


# ---------------------------------------------------------------------------
# 1. PRECEDENT STATUS CHECKER (Shepardizing / KeyCite for Indian Law)
# ---------------------------------------------------------------------------

# Curated ground truth of landmark Indian precedents that were subsequently
# overruled, reversed, or heavily modified by larger benches.
KNOWN_OVERRULED_CASES = {
    "adm jabalpur": {
        "case_name": "ADM Jabalpur v. Shivkant Shukla (1976)",
        "status": "overruled",
        "badge": "🔴 Overruled",
        "overruled_by": "K.S. Puttaswamy v. Union of India (2017) (9-Judge Bench)",
        "summary": "The emergency-era ruling that fundamental rights can be suspended during Emergency was expressly overruled in Puttaswamy.",
    },
    "suresh kumar koushal": {
        "case_name": "Suresh Kumar Koushal v. Naz Foundation (2013)",
        "status": "overruled",
        "badge": "🔴 Overruled",
        "overruled_by": "Navtej Singh Johar v. Union of India (2018) (5-Judge Bench)",
        "summary": "Upheld IPC Section 377; subsequently overruled by the 5-judge Constitution Bench in Navtej Johar decriminalizing consensual same-sex acts.",
    },
    "golak nath": {
        "case_name": "I.C. Golak Nath v. State of Punjab (1967)",
        "status": "overruled",
        "badge": "🔴 Overruled / Modified",
        "overruled_by": "Kesavananda Bharati v. State of Kerala (1973) (13-Judge Bench)",
        "summary": "Held Parliament could not amend Fundamental Rights; modified by the 13-judge bench establishing the Basic Structure Doctrine.",
    },
    "sajjan singh": {
        "case_name": "Sajjan Singh v. State of Rajasthan (1965)",
        "status": "overruled",
        "badge": "🔴 Overruled",
        "overruled_by": "Kesavananda Bharati (1973)",
        "summary": "Overruled regarding Parliament's unqualified power to abridge fundamental rights.",
    },
    "shankari prasad": {
        "case_name": "Shankari Prasad v. Union of India (1951)",
        "status": "overruled",
        "badge": "🔴 Overruled",
        "overruled_by": "Kesavananda Bharati (1973)",
        "summary": "Earlier view on absolute parliamentary amendment power superseded by the Basic Structure Doctrine.",
    },
    "subhash kashinath mahajan": {
        "case_name": "Subhash Kashinath Mahajan v. State of Maharashtra (2018)",
        "status": "overruled",
        "badge": "🔴 Overruled / Recalled",
        "overruled_by": "Union of India v. State of Maharashtra (Review Petition, 2019)",
        "summary": "Directions requiring prior sanction and preliminary inquiry under SC/ST Act were recalled by the 3-judge bench.",
    },
    "t.m.a. pai": {
        "case_name": "T.M.A. Pai Foundation v. State of Karnataka (2002)",
        "status": "distinguished",
        "badge": "🟡 Clarified / Distinguished",
        "overruled_by": "P.A. Inamdar (2005) & Pramati Educational Trust (2014)",
        "summary": "Principles on private unaided minority educational institutions clarified and distinguished by subsequent benches.",
    },
}


_AI_NOTE = " (AI estimate from the case name only; not checked against a law report.)"

BADGES = {
    "good_law": "🟢 No negative treatment found",
    "distinguished": "🟡 Distinguished / Cautioned",
    "overruled": "🔴 Overruled",
}


def _unknown(case_name: str, reason: str) -> dict:
    return {
        "case_name": case_name,
        "status": "unknown",
        "badge": "⚪ Treatment not independently checked",
        "overruled_by": None,
        "summary": reason,
        "verified": False,
        "source": "none",
    }


def check_precedent_status(case_name: str, client: Groq = None) -> dict:
    """Best-effort judicial status of an Indian judgment.

    Result `status` is one of good_law / distinguished / overruled / unknown.
      - `verified: True`  only for the curated KNOWN_OVERRULED_CASES table.
      - `source: "ai_estimate"` means a language model judged from the case
        name alone: treat it as a prompt to check a citator, not as a finding.
      - Anything that fails or is unrecognised is "unknown" -- NEVER silently
        "good law", because a false green badge is worse than no badge.
    """
    if not case_name:
        return _unknown("", "No case name to check.")

    cleaned = case_name.lower().strip()

    # 1. Curated ground truth (human-verified)
    for key, info in KNOWN_OVERRULED_CASES.items():
        if key in cleaned:
            return {**info, "verified": True, "source": "curated"}

    if not client:
        return _unknown(case_name, "Not in the curated list and no AI check available.")

    # 2. LLM estimate (clearly labelled as such)
    prompt = f"""You are an Indian Supreme Court precedent analyst (like Shepard's or KeyCite).
Estimate the current judicial standing of this Indian case: "{case_name}"

Return a strict JSON object with these keys:
- "status": exactly one of "good_law", "distinguished", "overruled", or "unknown"
- "overruled_by": name of the overruling/qualifying case, or null
- "summary": 1-2 concise sentences on its current standing

Use "unknown" if you do not clearly recognise this specific case, or are not sure of its treatment. Do not guess.
Output ONLY the JSON object, nothing else."""

    try:
        res = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )
        raw = (res.choices[0].message.content or "").strip()
        if "```" in raw:
            raw = re.sub(r"^```(?:json)?\n", "", raw)
            raw = re.sub(r"\n```$", "", raw)
        data = json.loads(raw.strip())
        status = data.get("status")
        if status not in BADGES:
            return _unknown(case_name, "Status could not be determined." + _AI_NOTE)
        return {
            "case_name": case_name,
            "status": status,
            "badge": BADGES[status] + " (AI estimate)",
            "overruled_by": data.get("overruled_by"),
            "summary": (data.get("summary") or "").strip() + _AI_NOTE,
            "verified": False,
            "source": "ai_estimate",
        }
    except Exception:
        return _unknown(case_name, "Precedent treatment could not be established automatically. The citation may still be supported by the local corpus; verify later treatment in an authoritative citator.")


def enrich_citations_with_precedent_status(citations: list, client: Groq = None) -> list:
    """Enrich a list of verified citation objects with Shepardizing status."""
    enriched = []
    for c in citations:
        c_copy = dict(c)
        name = c_copy.get("case_name", "")
        status_info = check_precedent_status(name, client)
        c_copy["precedent_status"] = status_info
        enriched.append(c_copy)
    return enriched


# ---------------------------------------------------------------------------
# 2. RATIO DECIDENDI VS. OBITER DICTA EXTRACTOR
# ---------------------------------------------------------------------------

def extract_ratio_and_obiter(case_name: str, passage: str, client: Groq) -> dict:
    """Separate binding legal rule (Ratio Decidendi) from passing remarks (Obiter Dicta)
    for a given judgment passage.
    """
    prompt = f"""You are a senior Indian appellate advocate and judicial clerk.
Analyze the following judgment passage from '{case_name}' and dissect its jurisprudential structure:

Passage text:
\"\"\"{passage}\"\"\"

Extract and categorize into a JSON object with these exact keys:
1. "case_title": the formal case name
2. "ratio_decidendi": array of 1-3 crisp bullet points stating the BINDING legal principles/test established (the rationale for the decision)
3. "obiter_dicta": array of 1-3 bullet points with passing judicial remarks, general reflections, or non-binding comments
4. "disposition": the final judicial decree or order (e.g. "Appeal allowed; FIR quashed", "Conviction sustained", or "Remanded to High Court")
5. "key_quote": the single most authoritative sentence in the passage suitable for quotation in a court pleading

Return ONLY the raw JSON object."""

    try:
        res = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600,
        )
        raw = (res.choices[0].message.content or "").strip()
        if "```" in raw:
            raw = re.sub(r"^```(?:json)?\n", "", raw)
            raw = re.sub(r"\n```$", "", raw)
        return json.loads(raw.strip())
    except Exception as e:
        return {
            "case_title": case_name,
            "ratio_decidendi": [f"Binding rule under {case_name}: The primary legal contention established in the judgment."],
            "obiter_dicta": ["Passing judicial observations on procedural conduct or broader societal context."],
            "disposition": "Order passed on merits.",
            "key_quote": passage[:180] + "..." if len(passage) > 180 else passage,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# 3. COURT-READY LEGAL DRAFT GENERATOR
# ---------------------------------------------------------------------------

DRAFT_TEMPLATES = {
    "ni_act_138": {
        "title": "Legal Notice under Section 138, Negotiable Instruments Act, 1881",
        "description": "Statutory Demand Notice for Cheque Dishonour",
        "forum": "Before the Court of Judicial Magistrate First Class / Metropolitan Magistrate",
    },
    "bail_application": {
        "title": "Application for Anticipatory Bail (Section 438 CrPC / Sec 482 BNSS)",
        "description": "Pre-arrest Bail Application before Sessions Court or High Court",
        "forum": "IN THE COURT OF THE PRINCIPAL DISTRICT AND SESSIONS JUDGE",
    },
    "legal_notice_recovery": {
        "title": "Legal Notice for Recovery of Dues & Breach of Contract",
        "description": "Formal Advocate Notice under Indian Contract Act, 1872",
        "forum": "Legal Demand Notice via Registered Post AD / Speed Post",
    },
    "writ_petition_synopsis": {
        "title": "Writ Petition Synopsis & Grounds (Article 226 / 32)",
        "description": "Synopsis, Chronology of Events & Legal Grounds for High Court / Supreme Court",
        "forum": "IN THE HIGH COURT OF JUDICATURE AT [JURISDICTION]",
    },
    "consumer_complaint": {
        "title": "Consumer Court Formal Complaint (Section 35 Consumer Protection Act)",
        "description": "Complaint for Deficiency in Service, Defective Product or Unfair Trade Practice",
        "forum": "BEFORE THE DISTRICT CONSUMER DISPUTES REDRESSAL COMMISSION",
    },
    "police_complaint": {
        "title": "Formal Criminal Complaint / Cyber Crime Report (BNS / IT Act)",
        "description": "Complaint for Cheating, Fraud, Cyber Crime, or Criminal Intimidation",
        "forum": "TO THE STATION HOUSE OFFICER (SHO) / CYBER CRIME CELL",
    },
}


def generate_legal_draft(
    draft_type: str,
    facts: str,
    citations: list[str] | None = None,
    client: Groq = None,
    parties: dict | None = None,
) -> dict:
    """Generate a court-ready, professionally structured Indian legal draft."""
    template_info = DRAFT_TEMPLATES.get(draft_type, DRAFT_TEMPLATES["ni_act_138"])
    citations_text = "\n".join([f"- {c}" for c in (citations or [])]) or "Established Supreme Court principles."

    parties_info = parties or {}
    petitioner = parties_info.get("petitioner", "[Complainant / Petitioner Name]")
    respondent = parties_info.get("respondent", "[Accused / Respondent Name]")

    prompt = f"""You are a senior advocate in India specializing in court drafting and pleadings.
Draft a complete, court-ready, highly professional legal document for:
DOCUMENT TYPE: {template_info['title']}
FORUM: {template_info['forum']}

PARTIES:
Complainant / Petitioner: {petitioner}
Opposite Party / Respondent: {respondent}

RELEVANT FACTS & INSTRUCTIONS:
{facts}

RELEVANT CITATIONS / PRECEDENTS TO INTEGRATE:
{citations_text}

Drafting Rules:
1. Follow standard Indian legal pleading conventions.
2. Structure:
   - Proper Court / Advocate Caption
   - Cause Title (Parties)
   - Synopsis & Chronology of Events
   - Detailed Narrative of Facts (numbered paragraphs 1, 2, 3...)
   - Legal Grounds with precise statutory sections and precedent citations
   - Formal Prayer / Demand Clause
   - Verification / Affidavit Clause
3. Use formal, persuasive legal language (e.g. "Most respectfully showeth", "Bonafide", "Prima facie").
4. Output cleanly in Markdown format.

Document Draft:"""

    try:
        res = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1800,
        )
        draft_content = (res.choices[0].message.content or "").strip()
        return {
            "status": "ok",
            "draft_type": draft_type,
            "title": template_info["title"],
            "draft_text": draft_content,
        }
    except Exception as e:
        return {
            "status": "error",
            "draft_type": draft_type,
            "title": template_info["title"],
            "error": str(e),
            "draft_text": f"Error generating draft: {e}",
        }


# ---------------------------------------------------------------------------
# 4. CITIZEN LEGAL ADVISOR ("Is There a Law for This?")
# ---------------------------------------------------------------------------

def analyze_citizen_incident(
    incident: str,
    client: Groq,
    index=None,
    records=None,
    embed_model=None,
) -> dict:
    """Analyze an everyday citizen's real-life problem and provide:
    1. Applicable Indian Acts & Sections
    2. Summary of legal rights & remedies
    3. Practical 3-step action roadmap (Evidence, Notice, Exact Portal/Authority)
    4. Limitation period & urgency alert
    5. Recommended 1-click legal draft type
    6. Grounded case law from corpus (if matching)
    """
    prompt = f"""You are a senior, compassionate Indian legal advocate advising an everyday citizen who has faced an issue.
Explain the law in clear, encouraging, practical, jargon-free language.

CITIZEN'S INCIDENT:
\"\"\"{incident.strip()[:4000]}\"\"\"

Analyze this incident under Indian Law (BNS/IPC, Consumer Protection Act 2019, IT Act 2000, Contract Act 1872, Rent Control laws, Labour laws, NI Act 1881, etc.).

Return ONLY a valid JSON object matching this schema:
{{
  "incident_summary": "1-sentence plain-English summary of what occurred",
  "category": "Consumer Dispute | UPI / Cyber Fraud | Landlord-Tenant | Employment & Salary | Cheating & Fraud | Defective Product | Other",
  "has_legal_remedy": true,
  "applicable_laws": [
    {{
      "act": "Name of Act (e.g. Consumer Protection Act, 2019 / Bharatiya Nyaya Sanhita, 2023)",
      "section": "Exact Section (e.g. Section 35 / Section 318(4))",
      "title": "Short title of provision (e.g. Cheating and dishonestly inducing delivery of property)",
      "nature": "Criminal Offence | Civil Remedy | Consumer Forum | Cyber Crime",
      "penalty_or_relief": "Maximum punishment (jail/fine) or financial compensation available to victim"
    }}
  ],
  "rights_summary": "2-3 encouraging sentences explaining what the law guarantees to the citizen and why the opposing party's action is legally invalid.",
  "action_plan": [
    {{
      "step_number": 1,
      "title": "Evidence to Gather Immediately",
      "action": "Specific documents/proof to preserve (e.g. WhatsApp chats, bank statement, UTR number, rent agreement)",
      "authority_or_portal": "Your personal archive / phone"
    }},
    {{
      "step_number": 2,
      "title": "Serve Formal Written Demand / Notice",
      "action": "What warning or demand to send giving them a 7 or 15 day deadline to resolve",
      "authority_or_portal": "Registered Post / WhatsApp & Email"
    }},
    {{
      "step_number": 3,
      "title": "Official Complaint / Redressal",
      "action": "Where to lodge the formal grievance",
      "authority_or_portal": "Exact helpline/portal (e.g. National Cyber Crime 1930 / e-Daakhil / NCH 1915 / Police Station)"
    }}
  ],
  "urgency_and_deadlines": "Explanation of limitation periods (e.g., 24-hour golden hour for cyber freeze, 3 years for money recovery, 2 years for consumer complaint)",
  "recommended_draft": {{
    "type": "consumer_complaint | police_complaint | legal_notice_recovery | ni_act_138",
    "label": "Draft Consumer Complaint | Draft Police/Cyber Complaint | Draft Legal Notice for Recovery",
    "prefilled_facts": "Concise 3-paragraph summary of facts ready to populate in the drafting tool"
  }}
}}"""

    result = {
        "status": "ok",
        "incident": incident,
        "incident_summary": "Citizen incident assessment",
        "category": "Everyday Legal Issue",
        "has_legal_remedy": True,
        "applicable_laws": [],
        "rights_summary": "Indian law protects citizens against unfair practices, non-payment, and fraud.",
        "action_plan": [],
        "urgency_and_deadlines": "Take action promptly to preserve evidence and comply with statutory deadlines.",
        "recommended_draft": {
            "type": "legal_notice_recovery",
            "label": "Draft Legal Notice for Recovery",
            "prefilled_facts": incident,
        },
        "supporting_corpus_cases": [],
    }

    try:
        res = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": "You are an expert Indian Legal Aid counselor. Always output strictly valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
        )
        raw = (res.choices[0].message.content or "").strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        parsed = json.loads(raw)
        result.update(parsed)
    except Exception as e:
        print(f"Error in citizen incident LLM: {e}")
        # Robust fallback
        result["applicable_laws"] = [
            {
                "act": "Indian Contract Act, 1872 / BNS, 2023",
                "section": "Section 73 (Breach of Contract) / Section 318 (Cheating)",
                "title": "Compensation for loss or damage caused by breach of contract",
                "nature": "Civil & Criminal",
                "penalty_or_relief": "Refund of dues + interest + damages for mental agony",
            }
        ]
        result["action_plan"] = [
            {"step_number": 1, "title": "Preserve Evidence", "action": "Save all transaction receipts, chats, and emails.", "authority_or_portal": "Personal Records"},
            {"step_number": 2, "title": "Send Legal Demand Notice", "action": "Issue a 15-day notice demanding immediate compliance.", "authority_or_portal": "Registered Post / Email"},
            {"step_number": 3, "title": "Lodge Formal Complaint", "action": "Approach the competent Consumer Forum or Police Station.", "authority_or_portal": "e-Daakhil / NCH 1915 / Cyber 1930"},
        ]

    # Quick vector retrieval for supporting precedents in the database
    if index is not None and records is not None and embed_model is not None:
        try:
            from rag_pipeline import search
            passages = search(incident[:300], index, records, embed_model, top_k=2, rerank=False)
            if passages and max(p.get("score", 0) for p in passages) >= 0.52:
                result["supporting_corpus_cases"] = [
                    {
                        "case_name": p.get("case_name", "Precedent"),
                        "court": p.get("court", "Court"),
                        "text": p.get("text", "")[:280] + "...",
                    }
                    for p in passages[:2]
                ]
        except Exception:
            pass

    return result
