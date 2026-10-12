"""
Metadata Extraction for Indian Judgment PDFs
=============================================
Pulls reliable case_name / court / case_no (and neutral citation) out of
the two PDF layouts in this corpus:

  1. Supreme Court Reports (SCR) layout -- the bulk-downloaded files named
     like '2023_10_1001_1009_EN.pdf'. The first page has a very regular
     header:

         [2023] 10 S.C.R. 1001 : 2023 INSC 600 1001
         HARI PRAKASH SHUKLA & ORS. A          <- 'A' is a margin letter
         v.
         THE STATE OF UTTAR PRADESH & ANR.
         (Civil Appeal No(s). 9697-9698 of 2014)

     The filename carries no party names, so they must come from here.

  2. Indian Kanoon layout -- files named like
     'Mrs_Jain_Babu_vs_K_J_Joseph_on_4_September_2008.PDF'. The filename
     already holds the parties (the on-page title is sometimes truncated
     with '...'), so the name comes from the filename, cleaned of junk.
     Court and case number come from the first pages.

Everything here is pure-Python (no faiss / pdfplumber import) so it can be
unit-tested and reused by both rag_pipeline.py and fix_index_metadata.py.
"""

import os
import re

UNKNOWN_COURT = "Unknown Court"
UNKNOWN_CASE_NO = "Unknown"


# ---------------------------------------------------------------------------
# CASE NAME -- filename route (Indian Kanoon layout)
# ---------------------------------------------------------------------------
def case_name_from_filename(filename: str) -> str:
    """'A_Sakthivel_vs_K_R_Navaneetha_Krishnan_on_29_April_2011.PDF'
        -> 'A Sakthivel vs K R Navaneetha Krishnan'

    Also strips scraper junk that sometimes ends up in Indian Kanoon file
    names, e.g. 'Cc_No_50605_16_' prefixes, '_Page_No_1_Of_24_Pages'
    suffixes, 'Noted_In_' prefixes and trailing '_Air_1958' reporter tags.
    """
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"_on_\d{1,2}_[A-Za-z]+_\d{4}$", "", stem)   # trailing date
    stem = re.sub(r"\s*\(\d+\)$", "", stem)                    # ' (1)' duplicate suffix
    stem = re.sub(r"_Page_No_\d+_Of_\d+_Pages$", "", stem, flags=re.I)
    stem = re.sub(r"_Air_\d{4}$", "", stem, flags=re.I)
    stem = re.sub(r"^Noted_In_", "", stem, flags=re.I)
    stem = re.sub(r"^(?:Cc|Ct|Crl|Ca|Cs)_No_[\d_]+?_(?=[A-Za-z])", "", stem, flags=re.I)
    return stem.replace("_", " ").strip()


# ---------------------------------------------------------------------------
# CASE NAME / CASE NO / NEUTRAL CITATION -- SCR header route
# ---------------------------------------------------------------------------
_MONTHS = ("JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|"
           "OCTOBER|NOVEMBER|DECEMBER")


def _strip_margin_letter(line: str) -> str:
    """SCR pages print a margin letter (A-H) at the start or end of some
    lines. Initials always carry a full stop ('S.R. KUMAR', 'A. SRINIVASULU')
    so a bare single capital A-H token is a margin marker, not part of a name.
    """
    line = line.strip()
    line = re.sub(r"^[A-H]\s+(?=\S)", "", line)
    line = re.sub(r"(?<=\S)\s+[A-H]$", "", line)
    return "" if re.fullmatch(r"[A-H]", line) else line.strip()


def _is_header_noise(line: str) -> bool:
    return bool(re.search(
        r"INSC|S\.C\.R|\bSCR\b|SUPREME COURT|CASE DETAILS|HEADNOTE|REPORTS|^\d+$",
        line, re.IGNORECASE))


def _is_case_no_line(line: str) -> bool:
    """'(Civil Appeal No. 4172 of 2023)', optionally with a margin letter
    before/after. A party line that merely starts with '(' -- e.g.
    '(SPL) & ANR.' -- is NOT a case-number line (it has no 'No')."""
    l = _strip_margin_letter(line)
    return l.startswith("(") and bool(re.search(r"\bNos?\b|\bD\.?\s?No", l, re.IGNORECASE))


def _is_end_of_parties(line: str) -> bool:
    return bool(
        _is_case_no_line(line) or line.startswith("[")
        or re.match(rf"^(?:{_MONTHS})\s+\d{{1,2}}\s*,", line, re.IGNORECASE)
    )


def _clean_party(raw_lines: list) -> str:
    """Join the party lines, drop margin letters / 'AND ORS.' tails, and
    title-case to match the style of the filename-derived names
    ('The State Of Uttar Pradesh')."""
    parts = [_strip_margin_letter(l) for l in raw_lines]
    s = " ".join(p for p in parts if p)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    # Drop trailing '& ORS.', '& ANR.', 'ETC. ETC.' -- they make the name long
    # and easy for the LLM to mis-copy, without helping identify the case.
    s = re.sub(r"[\s,]*(?:&|AND)\s+(?:ORS|ANR|OTHERS|ANOTHER)\.?\s*$", "", s, flags=re.I)
    s = re.sub(r"[\s,]*ETC\.?(?:\s*ETC\.?)?\s*$", "", s, flags=re.I)
    s = s.title()
    s = re.sub(r"'S\b", "'s", s)
    s = s.replace(" & ", " And ")
    return s.strip(" ,;")


def parse_scr_header(raw_head: str):
    """Parse the Supreme Court Reports first-page header.

    Returns {"case_name", "case_no", "neutral_citation", "court"} or None if
    the text doesn't look like an SCR header (so the caller can fall back).
    """
    lines = [l.strip() for l in raw_head.splitlines() if l.strip()]

    # Gate: genuine SCR pages open with '[2023] 10 S.C.R. 1001 : 2023 INSC 600'.
    # Without this, Indian Kanoon files (whose party block also contains a
    # 'Vs' line) would be mis-parsed as SCR.
    if not re.search(r"S\.C\.R\.|INSC", " ".join(lines[:3])):
        return None

    vi = None
    for i, l in enumerate(lines[:30]):
        if re.fullmatch(r"(?:v|vs|versus)\.?(?:\s+[A-H])?", l, flags=re.I):
            vi = i
            break
    if vi is None or vi == 0:
        return None

    # Petitioner side: walk upward from 'v.' until we hit citation/header noise
    pet = []
    for l in reversed(lines[max(0, vi - 4):vi]):
        if _is_header_noise(l):
            break
        pet.insert(0, l)

    # Respondent side: walk downward until the '(Civil Appeal No...)' line
    res, j = [], vi + 1
    while j < min(len(lines), vi + 7):
        if _is_end_of_parties(lines[j]):
            break
        res.append(lines[j])
        j += 1

    petitioner, respondent = _clean_party(pet), _clean_party(res)
    if not petitioner or not respondent:
        return None

    # Case number: the parenthesised line, possibly wrapped over 2-3 lines
    case_no = None
    if j < len(lines) and _is_case_no_line(lines[j]):
        buf, k = _strip_margin_letter(lines[j]), j
        while buf.count("(") > buf.count(")") and k < min(len(lines) - 1, j + 2):
            k += 1
            buf += " " + lines[k]
        buf = re.sub(r"\s+", " ", buf).strip()
        m_cn = re.match(r"^\((.*)\)\s*[A-H]?$", buf)
        case_no = (m_cn.group(1) if m_cn else buf.strip("() ")).strip()

    nc = re.search(r"(\d{4})\s+INSC\s+(\d+)", raw_head)
    return {
        "case_name": f"{petitioner} vs {respondent}",
        "case_no": case_no or UNKNOWN_CASE_NO,
        "neutral_citation": f"{nc.group(1)} INSC {nc.group(2)}" if nc else None,
        "court": "Supreme Court of India",
    }


# ---------------------------------------------------------------------------
# CASE NAME / CASE NO / DATE / BENCH -- tolerant SC bulk header parser
# ---------------------------------------------------------------------------
# parse_scr_header() above only works when the '[2023] 10 S.C.R. 1001' line is
# in the first 3 lines. Real bulk PDFs open with 5-8 margin letters (A..H) and
# a page number first, older ones (pre-2010) have NO S.C.R. line at all, and
# the OCR'd ones carry noise ('FEBRLARY 17, 2COO', "A'lD ORS."). The shape that
# IS stable across 2000-2023 is:
#
#     <margin letters / page no. / [YYYY] N S.C.R. nnn>   (any subset, any order)
#     PETITIONER (one or more ALL-CAPS lines)
#     v.
#     RESPONDENT (one or more ALL-CAPS lines)
#     (Civil Appeal No. 1234 of 2010)                      (absent in old files)
#     SEPTEMBER 7, 2010
#     [JUDGE, JUDGE AND JUDGE, JJ.]
#
# so anchor on the lone 'v.' line and walk outwards.
_SC_BULK_FILENAME = re.compile(r"^\d{4}_.*_EN\.pdf$", re.IGNORECASE)
_MONTH_LIST = [m.strip() for m in _MONTHS.split("|")]
_MONTH_NUM = {m: i + 1 for i, m in enumerate(_MONTH_LIST)}
_CITE_LINE = re.compile(r"S\.\s?C\.\s?R|\bSCR\b|INSC|SUPREME COURT REPORTS", re.IGNORECASE)


def _alpha_count(s: str) -> int:
    return sum(c.isalpha() for c in s)


def _upper_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


def _closest_month(word: str):
    import difflib
    m = difflib.get_close_matches(word.upper(), _MONTH_LIST, n=1, cutoff=0.7)
    return m[0] if m else None


_DATE_LINE = re.compile(r"^([A-Za-z]{4,10})\s+(\d{1,2})\s*[,.]?\s*(\S{3,5})\.?$")


def _parse_date_line(line: str):
    """'SEPTEMBER 07, 2010' (or OCR-damaged 'FEBRLARY 17, 2COO') ->
    (is_date_line, iso_date_or_None)."""
    m = _DATE_LINE.match(line.strip())
    if not m or not _closest_month(m.group(1)):
        return False, None
    year = (m.group(3).upper().replace("O", "0").replace("C", "0")
            .replace("I", "1").replace("L", "1"))
    month = _MONTH_NUM[_closest_month(m.group(1))]
    day = int(m.group(2))
    if re.fullmatch(r"(?:19|20)\d{2}", year) and 1 <= day <= 31:
        return True, f"{year}-{month:02d}-{day:02d}"
    return True, None


def _line_kind(line: str) -> str:
    if re.fullmatch(r"[A-Ha-h08]\s*[.,]?", line):
        return "margin"
    if re.fullmatch(r"\d{1,4}", line):
        return "pageno"
    if _CITE_LINE.search(line):
        return "cite"
    if _parse_date_line(line)[0]:
        return "date"
    if line.startswith("[") :
        return "bench"
    if line.startswith("(") and re.search(r"\bNos?\b|\bD\.?\s?No", line, re.IGNORECASE):
        return "caseno"
    if _alpha_count(line) < 3:
        return "junk"
    return "text"


def _fix_party_ocr(line: str) -> str:
    line = re.sub(r"\bA\W?[Il1]D\b", "AND", line)          # A"ID / A'lD -> AND
    return re.sub(r"^[^A-Za-z(]+", "", line).strip()


def parse_sc_header_tolerant(raw_head: str, filename: str = ""):
    """Tolerant version of parse_scr_header() for the bulk Supreme Court PDFs.

    Returns {"case_name", "case_no", "neutral_citation", "court",
    "decision_date", "bench", "scr_citation"} or None. Only applied to files
    named like '2023_10_1001_1009_EN.pdf' so Indian Kanoon layouts (which also
    contain a 'Vs' line) can never be mis-parsed by it.
    """
    if filename and not _SC_BULK_FILENAME.match(filename):
        return None
    lines = [l.strip() for l in raw_head.splitlines() if l.strip()]

    vi = next((i for i, l in enumerate(lines[:40])
               if re.fullmatch(r"(?:v|vs|versus)\.?(?:\s+[A-H])?", l, flags=re.I)), None)
    if vi is None:
        # Misc. petitions sometimes lose the 'v.' line: '[2014] 14 S.C.R 185',
        # then exactly two ALL-CAPS party lines. Re-insert a virtual 'v.'.
        ci = next((i for i, l in enumerate(lines[:12]) if _line_kind(l) == "cite"), None)
        if ci is not None:
            run = []
            for l in lines[ci + 1:ci + 5]:
                if _line_kind(l) != "text" or _upper_ratio(l) < 0.6:
                    break
                run.append(l)
            if len(run) == 2:
                lines = lines[:ci + 1] + [run[0], "v.", run[1]] + lines[ci + 3:]
                vi = ci + 2
    if vi is None or vi == 0:
        return None

    # petitioner: walk up from 'v.'
    pet, j = [], vi - 1
    while j >= 0 and len(pet) < 4:
        l = lines[j]
        k = _line_kind(l)
        if k in ("cite", "pageno", "date", "caseno", "bench"):
            break
        if k == "margin" or (k == "junk" and not pet):
            j -= 1
            continue
        if k == "junk" or _upper_ratio(l) < 0.6:
            break
        pet.insert(0, _fix_party_ocr(l))
        j -= 1

    # respondent: walk down from 'v.'
    res, j = [], vi + 1
    while j < min(len(lines), vi + 8) and len(res) < 4:
        l = lines[j]
        k = _line_kind(l)
        if k in ("cite", "pageno", "date", "caseno", "bench"):
            break
        if k == "margin" or (k == "junk" and not res):
            j += 1
            continue
        if k == "junk" or _upper_ratio(l) < 0.6:
            break
        res.append(_fix_party_ocr(l))
        j += 1

    petitioner, respondent = _clean_party(pet), _clean_party(res)
    if not petitioner or not respondent:
        return None

    # what follows the respondent: optional case no., date, bench
    case_no, decision_date, bench = None, None, None
    window = lines[j:j + 12]
    for idx, l in enumerate(window):
        k = _line_kind(l)
        if k == "caseno" and case_no is None:
            buf, n = _strip_margin_letter(l), idx
            while buf.count("(") > buf.count(")") and n + 1 < len(window) and n < idx + 2:
                n += 1
                buf += " " + window[n]
            buf = re.sub(r"\s+", " ", buf).strip()
            m_cn = re.match(r"^\((.*)\)\s*[A-H]?$", buf)
            case_no = (m_cn.group(1) if m_cn else buf.strip("() ")).strip()
        elif k == "date" and decision_date is None:
            decision_date = _parse_date_line(l)[1]
        elif k == "bench" and bench is None:
            buf, n = l, idx
            while "]" not in buf and n + 1 < len(window) and n < idx + 3:
                n += 1
                buf += " " + window[n]
            bench = re.sub(r"\s+", " ", buf).strip("[] ")
            break

    # gate: a genuine SC header has a bench line (or at least a date/case no.)
    if not (bench or decision_date or case_no):
        return None

    nc = re.search(r"(\d{4})\s+INSC\s+(\d+)", raw_head)
    sc = re.search(r"\[(\d{4})\]\s*(\d+)\s*S\.?C\.?R\.?\s*(\d+)?", raw_head)
    return {
        "case_name": f"{petitioner} vs {respondent}",
        "case_no": case_no or UNKNOWN_CASE_NO,
        "neutral_citation": f"{nc.group(1)} INSC {nc.group(2)}" if nc else None,
        "court": "Supreme Court of India",
        "decision_date": decision_date,
        "bench": bench,
        "scr_citation": (f"[{sc.group(1)}] {sc.group(2)} SCR" + (f" {sc.group(3)}" if sc.group(3) else "")) if sc else None,
    }


# ---------------------------------------------------------------------------
# DATE-ANCHORED FALLBACK -- for headers where OCR destroyed the 'v.' line
# ---------------------------------------------------------------------------
# Seen in the 2000-2008 volumes: 'v.' read as 'II.', '\I.', 'y.', 'V,' or lost
# entirely; month/year garbled ('FEBRt:ARY 25, 2000', '20GO', 'FEBRUARY IL 2003');
# bench line opened with '(' instead of '['. The DATE line is the most reliable
# anchor, so: find it, walk UP to collect the all-caps party block, and split
# petitioner / respondent at the first short noise line between two parties.
def _fuzzy_date(line: str, year_hint: str = ""):
    """Returns (matched, iso_or_partial_date) for a possibly OCR-damaged date line."""
    import difflib
    if len(line) > 30 or not re.search(r"\d", line):
        return False, None
    m = re.match(r"^\W*([A-Za-z][A-Za-z:;!|]{2,10})[\s,;.]+(.*)$", line)
    if not m:
        return False, None
    tok = re.sub(r"[^A-Za-z]", "", m.group(1)).upper()
    mon = difflib.get_close_matches(tok, _MONTH_LIST, n=1, cutoff=0.72) if len(tok) >= 4 else []
    if not mon:
        return False, None
    rest = m.group(2)
    dm = re.search(r"\b(\d{1,2})\b", rest)
    ym = re.search(r"(?:19|20)\d{2}", rest)
    year = ym.group(0) if ym else (year_hint if re.fullmatch(r"(?:19|20)\d{2}", year_hint or "") else None)
    month = _MONTH_NUM[mon[0]]
    if year and dm and 1 <= int(dm.group(1)) <= 31:
        return True, f"{year}-{month:02d}-{int(dm.group(1)):02d}"
    if year:
        return True, f"{year}-{month:02d}"
    return True, None


def _is_bench_like(line: str) -> bool:
    return bool(re.search(r"\bJJ?\b\.?\s*[\]\)]?\s*,?$|\bCJ\b|\bJJ\.", line)) or line[:1] in "[("


def parse_sc_header_date_anchored(raw_head: str, filename: str = ""):
    if filename and not _SC_BULK_FILENAME.match(filename):
        return None
    lines = [re.sub(r"^[·•.,'\"~\-_:;]+\s*", "", l.strip()) for l in raw_head.splitlines()]
    lines = [l for l in lines if l]
    year_hint = (re.match(r"(\d{4})_", filename) or [None, ""])[1] if filename else ""

    di, decision_date = None, None
    for i, l in enumerate(lines[:40]):
        ok, iso = _fuzzy_date(l, year_hint)
        if ok:
            di, decision_date = i, iso
            break
    if di is None:
        return None

    # walk up from the date collecting the party block (top -> bottom order after reverse)
    blk, case_no, i = [], None, di - 1
    while i >= 0 and len(blk) < 10:
        l = lines[i]
        k = _line_kind(l)
        if k in ("pageno", "cite"):
            break
        if k == "margin":
            i -= 1
            continue
        if k == "caseno":
            if case_no is None:
                buf = _strip_margin_letter(l)
                m_cn = re.match(r"^\((.*)\)\s*[A-H]?$", re.sub(r"\s+", " ", buf).strip())
                case_no = (m_cn.group(1) if m_cn else buf.strip("() ")).strip()
            i -= 1
            continue
        letters = _alpha_count(l)
        if letters >= 3 and _upper_ratio(l) >= 0.6 and not (letters <= 6 and re.search(r"[a-z]", l)):
            blk.insert(0, ("party", _fix_party_ocr(l)))
        elif letters <= 6 and len(l) <= 8:
            blk.insert(0, ("noise", l))          # 'II.', '\\I.', 'y.', 'RELi', stray marks
        else:
            break                                # headnote / prose -> block ended
        i -= 1

    # split at the first noise line that sits between two party lines
    first_party = next((n for n, (t, _) in enumerate(blk) if t == "party"), None)
    if first_party is None:
        return None
    split = next((n for n in range(first_party + 1, len(blk))
                  if blk[n][0] == "noise"
                  and any(t == "party" for t, _ in blk[n + 1:])), None)
    parties = [v for t, v in blk if t == "party"]
    if split is not None:
        pet = [v for t, v in blk[:split] if t == "party"]
        res = [v for t, v in blk[split + 1:] if t == "party"]
    elif len(parties) == 2:
        pet, res = parties[:1], parties[1:]
    elif len(parties) == 1 and re.match(r'^\W*IN RE\b|^\W*IN THE MATTER', parties[0], re.I):
        pet, res = parties, []
    else:
        return None

    petitioner = _clean_party(pet)
    respondent = _clean_party(res)
    if not petitioner or (res and not respondent):
        return None

    bench = None
    for idx in range(di + 1, min(len(lines), di + 5)):
        l = lines[idx]
        if _line_kind(l) == "margin":
            continue
        if _is_bench_like(l):
            buf, n = l, idx
            while not re.search(r"[\]\)]\s*,?$", buf) and n + 1 < len(lines) and n < idx + 3:
                n += 1
                if _line_kind(lines[n]) != "margin":
                    buf += " " + lines[n]
            bench = re.sub(r"\s+", " ", buf).strip("[]() j")
        break

    nc = re.search(r"(\d{4})\s+INSC\s+(\d+)", raw_head)
    sc = re.search(r"\[(\d{4})[\]\)j]?\s*(\d+)\s*S\.?C\.?R\.?\s*(\d+)?", raw_head)
    return {
        "case_name": f"{petitioner} vs {respondent}" if respondent else petitioner,
        "case_no": case_no or UNKNOWN_CASE_NO,
        "neutral_citation": f"{nc.group(1)} INSC {nc.group(2)}" if nc else None,
        "court": "Supreme Court of India",
        "decision_date": decision_date,
        "bench": bench,
        "scr_citation": (f"[{sc.group(1)}] {sc.group(2)} SCR" + (f" {sc.group(3)}" if sc.group(3) else "")) if sc else None,
    }


def parse_sc_running_head(raw_head: str, filename: str = ""):
    """Last resort for PDFs that begin mid-judgment (continuation pages) where the
    only identity is the running head 'MEERA SAHNI v. LT. GOVERNOR OF DELHI / & ORS.'.
    No date or bench is available from such pages."""
    if filename and not _SC_BULK_FILENAME.match(filename):
        return None
    lines = [l.strip() for l in raw_head.splitlines() if l.strip()]
    for i, l in enumerate(lines[:6]):
        m = re.match(r"^(.{3,60}?)\s+v\.?\s+(.{3,60})$", l)
        if not m or _upper_ratio(m.group(1)) < 0.6:
            continue
        pet, res = m.group(1), [m.group(2)]
        for nxt in lines[i + 1:i + 3]:
            if re.fullmatch(r"\d{1,4}", nxt):
                continue
            if _alpha_count(nxt) >= 3 and _upper_ratio(nxt) >= 0.6 and len(nxt) <= 40:
                res.append(nxt)
            else:
                break
        petitioner, respondent = _clean_party([_fix_party_ocr(pet)]), _clean_party([_fix_party_ocr(r) for r in res])
        if petitioner and respondent:
            return {"case_name": f"{petitioner} vs {respondent}", "case_no": UNKNOWN_CASE_NO,
                    "neutral_citation": None, "court": "Supreme Court of India",
                    "decision_date": None, "bench": None, "scr_citation": None}
    return None


# ---------------------------------------------------------------------------
# COURT -- Indian Kanoon layout (and fallback for anything not SCR)
# ---------------------------------------------------------------------------
_HC_STEMS = {
    "BOMBAY": "Bombay", "MADRAS": "Madras", "KERAL": "Kerala",
    "KARNATAK": "Karnataka", "DELHI": "Delhi", "CALCUTTA": "Calcutta",
    "ALLAHABAD": "Allahabad", "GUJARAT": "Gujarat", "PUNJAB": "Punjab and Haryana",
    "RAJASTHAN": "Rajasthan", "PATNA": "Patna", "ORISSA": "Orissa",
    "ODISHA": "Orissa", "ANDHRA": "Andhra Pradesh", "TELANGANA": "Telangana",
    "GAUHATI": "Gauhati", "HIMACHAL": "Himachal Pradesh",
    "JAMMU": "Jammu and Kashmir and Ladakh", "UTTARAKHAND": "Uttarakhand",
    "CHHATTISGARH": "Chhattisgarh", "JHARKHAND": "Jharkhand",
    "MADHYA": "Madhya Pradesh", "SIKKIM": "Sikkim", "MANIPUR": "Manipur",
    "MEGHALAYA": "Meghalaya", "TRIPURA": "Tripura",
}
# Reporter abbreviations in 'Equivalent citations:' lines -> High Court
_CITATION_HC_HINTS = [
    (r"\(DELHI\)|\bDLT\b|\bDRJ\b", "Delhi"),
    (r"\(KER\.?\)|\bKER\s?LT\b|\bKLT\b", "Kerala"),
    (r"\(KAR\.?\)|\bKAR\s?LJ\b", "Karnataka"),
    (r"ILR\s*\d+\s*MAD|\(MAD\.?\)|\bMLJ\b", "Madras"),
    (r"BOMCR|\(BOM\.?\)|\bMH\s?LJ\b|ALLMR", "Bombay"),
    (r"\(CAL\.?\)|\bCAL\s?LJ\b|CAL HN", "Calcutta"),
    (r"\(ALL\.?\)", "Allahabad"),
]
_TRIAL_CITIES = [("DELHI", "Delhi"), ("BENGALURU", "Bengaluru"),
                 ("BANGALORE", "Bengaluru"), ("MUMBAI", "Mumbai"),
                 ("CHENNAI", "Chennai"), ("KOLKATA", "Kolkata")]


def _hc_from_window(window: str):
    best = None
    for stem, label in _HC_STEMS.items():
        pos = window.find(stem)
        if pos != -1 and (best is None or pos < best[0]):
            best = (pos, label)
    return best[1] if best else None


def detect_court(head: str) -> str:
    """Best-effort court name from the first page(s). Returns a canonical
    label ('High Court of Madras', 'Supreme Court of India', ...) or
    'Unknown Court'. Never returns raw header text -- the old regex could
    swallow whole sentences ('...ADMIRALTY AND VICE ADMIRALTY JURISDICTION
    CHAMBER SUMMONS NO')."""
    h = re.sub(r"\s+", " ", head).upper()

    if re.search(r"IN THE SUPREME COURT|AIR\s+\d{4}\s+SUPREME COURT|\d{4}\s+AIR SCW", h):
        return "Supreme Court of India"

    if "NATIONAL COMPANY LAW APPELLATE TRIBUNAL" in h:
        return "National Company Law Appellate Tribunal"
    if "CUSTOMS, EXCISE" in h and "APPELLATE TRIBUNAL" in h:
        return "Customs, Excise and Service Tax Appellate Tribunal"
    if re.search(r"INCOME[\s-]*TAX APPELLATE TRIBUNAL", h):
        bench = re.search(r"([A-Z]+)\s+BENCH", h)
        return "Income Tax Appellate Tribunal" + (f" ({bench.group(1).title()} Bench)" if bench else "")

    if "IN THE COURT OF" in h:
        city = next((lab for key, lab in _TRIAL_CITIES if key in h), None)
        return f"Trial Court, {city}" if city else "Trial Court"

    m = re.search(r"HIGH COURT", h)
    if m:
        label = _hc_from_window(h[m.end(): m.end() + 70]) or _hc_from_window(h[max(0, m.start() - 30): m.start()])
        if label:
            return f"High Court of {label}"

    cit = re.search(r"EQUIVALENT CITATIONS:(.{0,400})", h)
    if cit:
        text = cit.group(1)
        if re.search(r"SUPREME COURT|\(SC\)|\bSCR\b", text):
            return "Supreme Court of India"
        for pat, label in _CITATION_HC_HINTS:
            if re.search(pat, text):
                return f"High Court of {label}"

    return UNKNOWN_COURT


# ---------------------------------------------------------------------------
# CASE NUMBER -- Indian Kanoon layout
# ---------------------------------------------------------------------------
_CASE_TYPES = (
    r"Crl\.?\s*R\.?\s*C\.?|Crl\.?\s*Rev\.?\s*Pet\.?|Crl\.?\s*A\.?|Crl\.?\s*M\.?\s*C\.?|"
    r"Criminal\s+(?:Writ\s+)?Petition|Criminal\s+Appeal|Criminal\s+Application|"
    r"Criminal\s+Complaint|Customs\s+Appeal|Company\s+Appeal\s*\(AT\)\s*\(Ins\)|"
    r"Civil\s+Appeal|Civil\s+Revision|Chamber\s+Summons|Original\s+Suit|"
    r"W\.?\s*P\.?(?:\s*\(C\))?|W\.?\s*A\.?|M\.?\s*F\.?\s*A\.?|R\.?\s*F\.?\s*A\.?|"
    r"I\.?\s*T\.?\s*A\.?|C\.?\s*C\.?|Ct\.?\s*Case|C\.?\s*Case|C\.?\s*S\.?|O\.?\s*S\.?"
)
_NUM = r"\d+(?:\s*[/,\-]\s*\d+)*"          # 9172 | 11985/2018 | 1162-1171
_CASE_NO_RE = re.compile(
    rf"\b((?:{_CASE_TYPES})\s*\.?\s*Nos?\.?\s*[:.\-]?\s*"
    rf"{_NUM}(?:\s*(?:to|&|and)\s*{_NUM})?(?:\s*/\s*[A-Za-z]+\s*/\s*\d{{4}})?(?:\s*of\s*\d{{4}})?)",
    re.IGNORECASE,
)


def detect_case_no(head: str) -> str:
    """First recognisable case-number string in the first page(s), or
    'Unknown'. Anchored on a known case-type token (Crl.R.C., W.P., CC No.,
    ITA No., Customs Appeal No., ...) so ordinary prose can't match -- the
    old regex once swallowed an entire unrelated paragraph."""
    h = re.sub(r"\s+", " ", head)
    for m in _CASE_NO_RE.finditer(h):
        cand = m.group(1).strip(" .,:;-")
        # needs a real number, and must not be a page counter ('Page No. 1 Of 24')
        if re.search(r"\d{2,}", cand) and not re.match(r"(?i)page", cand):
            return cand
    return UNKNOWN_CASE_NO


# ---------------------------------------------------------------------------
# PUBLIC ENTRY POINTS
# ---------------------------------------------------------------------------
def build_metadata(filename: str, raw_head: str = "", cleaned_text: str = "") -> dict:
    """raw_head   : first 1-2 pages as extracted, WITH line breaks intact
                    (needed for the SCR parser).
    cleaned_text : fully cleaned document text (fallback when raw_head is empty).
    """
    head = raw_head or cleaned_text[:3000]

    scr = None
    if raw_head:
        scr = (parse_scr_header(raw_head)
               or parse_sc_header_tolerant(raw_head, filename)
               or parse_sc_header_date_anchored(raw_head, filename)
               or parse_sc_running_head(raw_head, filename))
    if scr:
        out = {"filename": filename, "decision_date": None, "bench": None,
               "scr_citation": None, **scr}
        if out["case_no"] == UNKNOWN_CASE_NO:
            # older headers have no '(Civil Appeal No. ...)' line; the first
            # pages of the headnote usually still name the appeal
            out["case_no"] = detect_case_no(head)
        return out

    return {
        "filename": filename,
        "case_name": case_name_from_filename(filename),
        "court": detect_court(head),
        "case_no": detect_case_no(head),
        "neutral_citation": None,
        "decision_date": None,
        "bench": None,
        "scr_citation": None,
    }


def disambiguate_names(metas: list) -> int:
    """If two different documents end up with the same case_name (existence
    checks and passage lookups key on case_name, so they would merge),
    append the neutral citation / case number to tell them apart.
    Mutates the dicts in `metas`; returns how many names were changed."""
    by_name = {}
    for m in metas:
        by_name.setdefault(m["case_name"], []).append(m)
    changed = 0
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        for m in group:
            tag = (m.get("neutral_citation")
                   or (m["case_no"] if m["case_no"] != UNKNOWN_CASE_NO else None)
                   or os.path.splitext(m["filename"])[0])
            m["case_name"] = f"{name} ({tag})"
            changed += 1
    return changed