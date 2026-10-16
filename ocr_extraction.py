"""Shared PDF extraction with optional, page-level OCR fallback.

Native text extraction always runs first. OCR is attempted only for pages whose
native text fails a conservative quality check. OCR dependencies are optional:
PyMuPDF + pytesseract + a system Tesseract installation are required only when
OCR is actually needed.
"""
from __future__ import annotations
import os, re
from dataclasses import dataclass, asdict

try:
    import pymupdf
except ImportError:
    try: import fitz as pymupdf
    except ImportError: pymupdf = None

OCR_ENABLED = os.getenv("OCR_ENABLED", "true").lower() in {"1","true","yes","on"}
OCR_MIN_CHARS = int(os.getenv("OCR_MIN_CHARS", "80"))
OCR_MIN_ALPHA_RATIO = float(os.getenv("OCR_MIN_ALPHA_RATIO", "0.45"))
OCR_DPI = int(os.getenv("OCR_DPI", "220"))
OCR_LANG = os.getenv("OCR_LANG", "eng")

@dataclass
class PageExtraction:
    page: int
    text: str
    extraction_method: str
    quality_ok: bool
    warning: str | None = None


def text_quality_ok(text: str) -> bool:
    s = re.sub(r"\s+", " ", text or "").strip()
    if len(s) < OCR_MIN_CHARS: return False
    visible = [c for c in s if not c.isspace()]
    if not visible: return False
    alpha = sum(c.isalpha() for c in visible) / len(visible)
    return alpha >= OCR_MIN_ALPHA_RATIO


def _ocr_page(page) -> tuple[str, str | None]:
    if not OCR_ENABLED: return "", "OCR disabled"
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "", "OCR dependencies unavailable (install pytesseract and Pillow)"
    try:
        pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return (pytesseract.image_to_string(img, lang=OCR_LANG) or ""), None
    except Exception as exc:
        return "", f"OCR failed: {type(exc).__name__}: {exc}"


def extract_pdf_pages(pdf_path: str) -> tuple[list[dict], dict]:
    """Return page records and a summary. Does not make OCR a hard dependency."""
    if pymupdf is None:
        return [], {"pages":0,"native_pages":0,"ocr_pages":0,"failed_pages":[],"method":"unavailable","warning":"PyMuPDF unavailable"}
    out=[]; native=ocr=0; failed=[]
    with pymupdf.open(pdf_path) as doc:
        for idx,page in enumerate(doc,1):
            native_text = page.get_text() or ""
            if text_quality_ok(native_text):
                rec=PageExtraction(idx,native_text,"native",True); native += 1
            else:
                ocr_text, warning = _ocr_page(page)
                if text_quality_ok(ocr_text):
                    rec=PageExtraction(idx,ocr_text,"ocr",True,warning); ocr += 1
                elif native_text.strip():
                    rec=PageExtraction(idx,native_text,"native-low-quality",False,warning or "Low-quality native text; OCR did not recover better text")
                    native += 1; failed.append(idx)
                else:
                    rec=PageExtraction(idx,"","unreadable",False,warning or "No extractable text")
                    failed.append(idx)
            out.append(asdict(rec))
    method = "mixed" if native and ocr else ("ocr" if ocr else "native")
    return out,{"pages":len(out),"native_pages":native,"ocr_pages":ocr,"failed_pages":failed,"method":method,"ocr_enabled":OCR_ENABLED}


def extract_text_and_head_with_ocr(pdf_path: str, head_pages: int=2):
    pages, summary = extract_pdf_pages(pdf_path)
    full="\n".join(p["text"] for p in pages if p["text"])
    head="\n".join(p["text"] for p in pages[:head_pages] if p["text"])
    return full, head, pages, summary
