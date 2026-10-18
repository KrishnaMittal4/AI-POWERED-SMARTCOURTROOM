"""BNS ↔ IPC, BNSS ↔ CrPC, and BSA ↔ IEA Transition Lens.

Provides instantaneous cross-reference mapping and deep comparative analysis
between pre-2024 Indian criminal statutes and the new criminal laws effective July 1, 2024:
- Bharatiya Nyaya Sanhita (BNS), 2023 <-> Indian Penal Code (IPC), 1860
- Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023 <-> Code of Criminal Procedure (CrPC), 1973
- Bharatiya Sakshya Adhiniyam (BSA), 2023 <-> Indian Evidence Act (IEA), 1872
"""
from __future__ import annotations

import re
from typing import Optional, Dict, Any, List

TRANSITION_MAP: List[Dict[str, Any]] = [
    {
        "old_act": "IPC", "old_section": "302",
        "new_act": "BNS", "new_section": "103",
        "title": "Punishment for Murder",
        "category": "Offences Affecting Life",
        "key_changes": "Section 103(2) introduces dedicated capital punishment / life imprisonment for mob lynching or murder by 5+ persons on grounds of race, caste, sex, or language.",
        "bailable": False, "cognizable": True,
        "keywords": ["302", "103", "murder", "hatya", "lynching", "killing"]
    },
    {
        "old_act": "IPC", "old_section": "420",
        "new_act": "BNS", "new_section": "318(4)",
        "title": "Cheating and Dishonestly Inducing Delivery of Property",
        "category": "Offences Against Property",
        "key_changes": "Moved to Section 318(4). Retains up to 7 years imprisonment and fine. Stricter definitions for digital cheating and fraudulent inducement.",
        "bailable": False, "cognizable": True,
        "keywords": ["420", "318", "cheating", "fraud", "dhokhadhadi", "420 ipc", "scam"]
    },
    {
        "old_act": "IPC", "old_section": "304A",
        "new_act": "BNS", "new_section": "106(1) and 106(2)",
        "title": "Causing Death by Negligence (Hit-and-Run)",
        "category": "Offences Affecting Life",
        "key_changes": "106(1) provides up to 5 years for rash/negligent act. 106(2) provides up to 10 years imprisonment and fine for hit-and-run where offender fails to report to police/magistrate promptly.",
        "bailable": False, "cognizable": True,
        "keywords": ["304a", "106", "hit and run", "rash driving", "negligence", "accident"]
    },
    {
        "old_act": "IPC", "old_section": "375 / 376",
        "new_act": "BNS", "new_section": "63 / 64",
        "title": "Rape and Punishment for Rape",
        "category": "Offences Against Women and Children",
        "key_changes": "Section 69 introduces a specific offence for sexual intercourse by deceitful means or false promise of employment/promotion/marriage.",
        "bailable": False, "cognizable": True,
        "keywords": ["376", "375", "64", "63", "69", "rape", "false promise of marriage", "women"]
    },
    {
        "old_act": "IPC", "old_section": "378 / 379",
        "new_act": "BNS", "new_section": "303",
        "title": "Theft and Punishment for Theft",
        "category": "Offences Against Property",
        "key_changes": "Community service introduced as an alternative punishment for first-time petty theft where stolen property value is under Rs 5,000 upon return.",
        "bailable": False, "cognizable": True,
        "keywords": ["378", "379", "303", "theft", "chori", "stealing", "community service"]
    },
    {
        "old_act": "IPC", "old_section": "498A",
        "new_act": "BNS", "new_section": "85 / 86",
        "title": "Cruelty by Husband or Relatives of Husband",
        "category": "Offences Against Women",
        "key_changes": "Section 85 covers cruelty with up to 3 years imprisonment. Section 86 defines cruelty comprehensively including physical and mental harassment for dowry.",
        "bailable": False, "cognizable": True,
        "keywords": ["498a", "85", "86", "dowry", "cruelty", "matrimonial", "domestic"]
    },
    {
        "old_act": "IPC", "old_section": "124A",
        "new_act": "BNS", "new_section": "152",
        "title": "Acts Endangering Sovereignty, Unity and Integrity of India (Replacing Sedition)",
        "category": "Offences Against the State",
        "key_changes": "Word 'Sedition' (Rajdroh) is deleted. Replaced with Section 152 penalizing acts endangering sovereignty, unity, and integrity of India (Deshdroh). Punishment increased up to 7 years or life imprisonment.",
        "bailable": False, "cognizable": True,
        "keywords": ["124a", "152", "sedition", "rajdroh", "deshdroh", "sovereignty", "anti national"]
    },
    {
        "old_act": "IPC", "old_section": "506",
        "new_act": "BNS", "new_section": "351",
        "title": "Criminal Intimidation",
        "category": "Criminal Intimidation and Insult",
        "key_changes": "Section 351(2) and 351(3) streamline definitions for threats to cause death/grievous hurt or impute unchastity to a woman.",
        "bailable": True, "cognizable": False,
        "keywords": ["506", "351", "intimidation", "threat", "dhamki"]
    },
    {
        "old_act": "IPC", "old_section": "319 / 323",
        "new_act": "BNS", "new_section": "114 / 115",
        "title": "Hurt and Voluntarily Causing Hurt",
        "category": "Offences Affecting Life and Body",
        "key_changes": "Community service option included for minor simple hurt. Grievous hurt classified under Section 116 / 117.",
        "bailable": True, "cognizable": False,
        "keywords": ["323", "319", "115", "114", "hurt", "marpeet", "assault"]
    },
    {
        "old_act": "IPC", "old_section": "405 / 406",
        "new_act": "BNS", "new_section": "316",
        "title": "Criminal Breach of Trust",
        "category": "Offences Against Property",
        "key_changes": "Defined in Section 316. Punishment up to 5 years imprisonment or fine or both under Section 316(2).",
        "bailable": False, "cognizable": True,
        "keywords": ["406", "405", "316", "breach of trust", "amanat"]
    },
    {
        "old_act": "CrPC", "old_section": "154",
        "new_act": "BNSS", "new_section": "173",
        "title": "Information in Cognizable Cases (Zero FIR & e-FIR)",
        "category": "Criminal Procedure & Police Powers",
        "key_changes": "Explicit statutory recognition of Zero FIR and e-FIR (electronic reporting with signature within 3 days). Preliminary inquiry permitted up to 14 days for offences punishable between 3-7 years.",
        "bailable": None, "cognizable": None,
        "keywords": ["154", "173", "fir", "zero fir", "e-fir", "police complaint"]
    },
    {
        "old_act": "CrPC", "old_section": "437 / 439",
        "new_act": "BNSS", "new_section": "480 / 483",
        "title": "Bail in Non-Bailable Offences & High Court/Sessions Powers",
        "category": "Bail & Personal Liberty",
        "key_changes": "Section 479 BNSS introduces progressive relief for first-time undertrial prisoners: release on personal bond after serving 1/3rd of the maximum sentence (excluding offences with life imprisonment/death).",
        "bailable": None, "cognizable": None,
        "keywords": ["437", "439", "479", "480", "483", "bail", "zamanat", "regular bail", "undertrial"]
    },
    {
        "old_act": "CrPC", "old_section": "438",
        "new_act": "BNSS", "new_section": "482",
        "title": "Direction for Grant of Anticipatory Bail",
        "category": "Bail & Personal Liberty",
        "key_changes": "Provisions for pre-arrest anticipatory bail retained with strict conditions regarding non-tampering and reporting to investigation officers.",
        "bailable": None, "cognizable": None,
        "keywords": ["438", "482", "anticipatory bail", "pre-arrest bail", "agrim zamanat"]
    },
    {
        "old_act": "CrPC", "old_section": "167",
        "new_act": "BNSS", "new_section": "187",
        "title": "Procedure when Investigation cannot be completed in 24 Hours (Remand)",
        "category": "Police Powers & Custody",
        "key_changes": "Police custody of 15 days can now be granted in parts or blocks across the first 40 or 60 days of the total 60/90 days detention period, altering the previous unbroken 15-day rule.",
        "bailable": None, "cognizable": None,
        "keywords": ["167", "187", "remand", "police custody", "judicial custody"]
    },
    {
        "old_act": "CrPC", "old_section": "41A",
        "new_act": "BNSS", "new_section": "35(3)",
        "title": "Notice of Appearance before Police Officer (Arnesh Kumar rule)",
        "category": "Arrest Procedures",
        "key_changes": "Notice of appearance mandatory prior to arrest for offences punishable with imprisonment of 7 years or less, codifying the Arnesh Kumar safeguards.",
        "bailable": None, "cognizable": None,
        "keywords": ["41a", "35(3)", "notice of appearance", "arnesh kumar", "arrest safeguard"]
    },
    {
        "old_act": "IEA", "old_section": "65B",
        "new_act": "BSA", "new_section": "61 & 63",
        "title": "Admissibility of Electronic Records / Digital Evidence",
        "category": "Evidence & Digital Forensics",
        "key_changes": "Section 61 recognizes electronic and digital records as primary evidence on par with physical documents. Section 63 streamlines the mandatory certificate procedure for electronic records.",
        "bailable": None, "cognizable": None,
        "keywords": ["65b", "61", "63", "electronic evidence", "digital evidence", "call records", "whatsapp evidence"]
    },
]

def quick_search_transition(query: str) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return TRANSITION_MAP[:6]
    tokens = [t for t in re.split(r"[\s,\-/]+", q) if t]
    scored = []
    for item in TRANSITION_MAP:
        score = 0
        searchable_text = f"{item['old_act']} {item['old_section']} {item['new_act']} {item['new_section']} {item['title']} {item['key_changes']} {' '.join(item['keywords'])}".lower()
        for t in tokens:
            if t == item["old_section"].lower() or t == item["new_section"].lower():
                score += 15
            elif t in item["keywords"]:
                score += 8
            elif t in searchable_text:
                score += 3
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item for _, item in scored]
    return results[:8] if results else []

def analyze_transition_with_llm(query: str, groq_client=None) -> Dict[str, Any]:
    from llm_router import route_task
    import json
    prompt = f"""You are a Supreme Court of India legal scholar and expert in the 2024 New Criminal Laws transition:
1. Bharatiya Nyaya Sanhita (BNS) 2023 vs Indian Penal Code (IPC) 1860
2. Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 vs Code of Criminal Procedure (CrPC) 1973
3. Bharatiya Sakshya Adhiniyam (BSA) 2023 vs Indian Evidence Act (IEA) 1872

USER QUERY / LEGAL SECTION:
"{query.strip()[:2000]}"

Compare the old law with the new 2024 law in detail.
Return ONLY a valid JSON object matching this schema:
{{
  "query": "{query.strip()[:200]}",
  "old_provision": {{
    "act": "IPC / CrPC / IEA",
    "section": "Section number under old law",
    "title": "Title of provision"
  }},
  "new_provision": {{
    "act": "BNS / BNSS / BSA",
    "section": "Section number under new 2024 law",
    "title": "Title of provision under new law"
  }},
  "bailable_status": "Bailable / Non-Bailable / Discretionary",
  "cognizable_status": "Cognizable / Non-Cognizable",
  "punishment_comparison": "Exact comparison between old punishment vs new 2024 punishment",
  "key_substantive_changes": [
    "Specific change 1 introduced in 2024",
    "Specific change 2"
  ],
  "procedural_impact": "How police, prosecutors, or defense advocates must now handle this case (bail, remand, electronic filing, etc.)",
  "transitional_application": "Which law applies? (Offences committed before July 1, 2024 are tried under IPC/CrPC via Art 20(1) Constitution; offences after July 1, 2024 under BNS/BNSS)."
}}"""
    system_prompt = "You are a master Indian Criminal Law jurist specializing in BNS, BNSS, BSA transitions. Return strictly valid JSON only."
    try:
        llm = route_task("advocate", prompt, purpose="reason", groq_client=groq_client, system_prompt=system_prompt, max_tokens=1800, temperature=0.1)
        if llm.get("ok"):
            raw = (llm.get("text") or "").strip()
            if raw.startswith("```json"): raw = raw[7:]
            elif raw.startswith("```"): raw = raw[3:]
            if raw.endswith("```"): raw = raw[:-3]
            raw = raw.strip()
            try:
                parsed = json.loads(raw)
                parsed["status"] = "ok"
                parsed["provider"] = llm.get("provider")
                return parsed
            except Exception:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    parsed["status"] = "ok"
                    parsed["provider"] = llm.get("provider")
                    return parsed
    except Exception as exc:
        print(f"[bns_lens] LLM error: {exc}")

    quick = quick_search_transition(query)
    match = quick[0] if quick else TRANSITION_MAP[0]
    return {
        "status": "ok",
        "provider": "local_database",
        "query": query,
        "old_provision": {"act": match["old_act"], "section": match["old_section"], "title": match["title"]},
        "new_provision": {"act": match["new_act"], "section": match["new_section"], "title": match["title"]},
        "bailable_status": "Non-Bailable" if match.get("bailable") is False else "Bailable",
        "cognizable_status": "Cognizable" if match.get("cognizable") is True else "Non-Cognizable",
        "punishment_comparison": "Statutory updates applied under the 2024 penal framework.",
        "key_substantive_changes": [match["key_changes"]],
        "procedural_impact": "Statutory compliance required under BNSS 2023 procedures.",
        "transitional_application": "Offences committed prior to 1 July 2024 continue under IPC/CrPC as per Article 20(1) of the Constitution."
    }
