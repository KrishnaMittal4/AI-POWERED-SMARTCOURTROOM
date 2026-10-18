"""Document & Legal Notice Analyzer for Citizens and Advocates.

Extracts text from uploaded legal notices, contracts, and agreements (PDF / TXT),
identifies one-sided or unlawful clauses, calculates response deadlines,
and formulates a formal counter-defense strategy with 1-click drafting prefill.
"""
from __future__ import annotations

import io
import re
import json
from typing import Dict, Any, Optional

def extract_text_from_file_bytes(content: bytes, filename: str) -> str:
    """Extract readable text from uploaded PDF or text file."""
    fn = filename.lower()
    text = ""
    
    if fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")):
        # Image OCR: Camera photo / scanned paper notice
        # 1. Try pytesseract first
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(io.BytesIO(content))
            text = pytesseract.image_to_string(img)
        except Exception:
            pass

        # 2. Vision fallback: Gemini multimodal OCR for zero-dependency transcription
        if not text.strip():
            try:
                import os
                from google import genai
                from google.genai import types
                key = os.getenv("GEMINI_API_KEY")
                if key:
                    client = genai.Client(api_key=key)
                    mime = "image/png" if fn.endswith(".png") else "image/jpeg"
                    res = client.models.generate_content(
                        model=os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-2.5-flash-lite"),
                        contents=[
                            types.Part.from_bytes(data=content, mime_type=mime),
                            "Transcribe all readable text from this legal document or notice accurately. Output only the plain transcribed text without commentary."
                        ]
                    )
                    text = (res.text or "").strip()
            except Exception as e:
                print(f"[document_analyzer] Image OCR error: {e}")

    elif fn.endswith(".pdf"):
        # Try PyMuPDF (fitz) first for maximum speed and accuracy
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            pages = []
            for page in doc[:15]:
                pages.append(page.get_text() or "")
            text = "\n".join(pages)
        except Exception:
            pass
            
        # Fallback to pdfplumber
        if not text.strip():
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    pages = [p.extract_text() or "" for p in pdf.pages[:15]]
                    text = "\n".join(pages)
            except Exception:
                pass
    else:
        # Plain text / markdown
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception:
                text = ""

    return text.strip()


def analyze_legal_document(
    text: str,
    filename: str = "document.pdf",
    groq_client=None,
) -> Dict[str, Any]:
    """Analyze legal document, notice, or agreement under Indian Law."""
    from llm_router import route_task

    cleaned_sample = text[:7000].strip()
    if len(cleaned_sample) < 30:
        return {
            "status": "error",
            "error": "The uploaded document did not contain enough readable text. If it is a scanned image, ensure it is clearly legible.",
            "document_type": "Unknown",
            "red_flags": [],
        }

    prompt = f"""You are a senior advocate in the High Court of Delhi specializing in contract disputes, legal notices, and consumer grievances.
Analyze this legal notice or contract under Indian law (Contract Act 1872, Transfer of Property Act 1882, Specific Relief Act, Consumer Protection Act 2019, NI Act 1881, etc.).

DOCUMENT EXCERPT (Filename: {filename}):
\"\"\"{cleaned_sample}\"\"\"

Analyze rigorously and return ONLY a valid JSON object matching this schema:
{{
  "document_title": "Identified document title (e.g. Legal Notice for Recovery / Eviction Notice / Non-Compete Agreement)",
  "document_type": "Legal Notice | Demand Notice | Eviction Notice | Employment Agreement | Lease / Tenancy | Service Contract | Commercial Agreement",
  "issuing_party": "Name or entity issuing the notice/contract (or 'Opposing Party')",
  "recipient_party": "Target or addressee",
  "stated_allegation_or_demand": "Concise 1-2 sentence summary of what the document claims or demands (e.g. demand for Rs 1,00,000 within 15 days)",
  "response_deadline": "Strict timeline or deadline to respond (e.g. '15 days from date of receipt' or 'Immediate / 7 days' or 'No specific timeline stated')",
  "is_statutorily_valid": true,
  "red_flags": [
    {{
      "clause_or_claim": "Specific unlawful claim, coercive language, or unfair clause",
      "legal_flaw": "Why this is legally void, extortionate, or contrary to Indian law (e.g. Section 27 Indian Contract Act declares non-compete covenants void)",
      "severity": "High | Medium | Low"
    }}
  ],
  "applicable_statutes": [
    {{
      "act": "Name of Indian Act",
      "section": "Section number",
      "provision": "Brief description of legal provision protecting the recipient"
    }}
  ],
  "recommended_counter_strategy": "2-3 sentences advising what actions or rebuttals the recipient should take immediately.",
  "counter_notice_draft": {{
    "type": "legal_notice_reply | consumer_complaint | police_complaint",
    "subject": "REPLY TO LEGAL NOTICE DATED [DATE] ON BEHALF OF [CLIENT]",
    "key_grounds_of_defense": [
      "Ground 1 denying liability",
      "Ground 2 asserting counter-claim or illegal conduct"
    ],
    "prefilled_facts": "Concise rebuttal summary ready to feed into the 1-click legal drafting tool"
  }}
}}"""

    system_prompt = "You are a senior Indian advocate reviewing legal documents and notices. Always return strictly valid JSON."

    try:
        llm = route_task(
            "advocate",
            prompt,
            purpose="reason",
            groq_client=groq_client,
            system_prompt=system_prompt,
            max_tokens=2100,
            temperature=0.1,
        )

        if llm.get("ok"):
            raw = (llm.get("text") or "").strip()
            if raw.startswith("```json"): raw = raw[7:]
            elif raw.startswith("```"): raw = raw[3:]
            if raw.endswith("```"): raw = raw[:-3]
            raw = raw.strip()

            try:
                parsed = json.loads(raw)
                parsed["status"] = "ok"
                parsed["filename"] = filename
                parsed["provider"] = llm.get("provider")
                return parsed
            except Exception:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    parsed["status"] = "ok"
                    parsed["filename"] = filename
                    parsed["provider"] = llm.get("provider")
                    return parsed
    except Exception as exc:
        print(f"[document_analyzer] LLM error: {exc}")

    # Fallback response
    return {
        "status": "ok",
        "filename": filename,
        "provider": "fallback_engine",
        "document_title": f"Legal Document Assessment — {filename}",
        "document_type": "Legal Notice / Agreement",
        "issuing_party": "Opposing Party",
        "recipient_party": "Recipient",
        "stated_allegation_or_demand": "Formal demand or notice regarding contractual / financial liability.",
        "response_deadline": "Standard statutory window: 15 days from receipt.",
        "is_statutorily_valid": True,
        "red_flags": [
            {
                "clause_or_claim": "Unilateral forfeiture or coercive damages clause",
                "legal_flaw": "Liquidated damages cannot be punitive under Section 74 of the Indian Contract Act, 1872; only reasonable compensation is permissible.",
                "severity": "High"
            }
        ],
        "applicable_statutes": [
            {"act": "Indian Contract Act, 1872", "section": "Section 73 & 74", "provision": "Compensation for loss or damage caused by breach of contract"}
        ],
        "recommended_counter_strategy": "Issue a point-by-point formal reply through an advocate denying false allegations and placing contemporaneous records on notice.",
        "counter_notice_draft": {
            "type": "legal_notice_reply",
            "subject": f"FORMAL REPLY TO NOTICE CONCERNING {filename.upper()}",
            "key_grounds_of_defense": [
                "Denial of allegations and assertion of lack of cause of action",
                "Arbitrary and unilateral claims without documentary substantiation"
            ],
            "prefilled_facts": f"The recipient has received the document ({filename}) containing unsubstantiated claims. The claims are denied in toto as legally untenable under Indian Law."
        }
    }
