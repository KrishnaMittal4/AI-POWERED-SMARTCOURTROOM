import json
import time
import requests
from io import BytesIO

BASE_URL = "https://ai-powered-smartcourtroom.onrender.com"

def log(tag, ok, msg):
    symbol = "[OK]" if ok else "[FAIL]"
    print(f"{symbol} [{tag}] {msg}", flush=True)

def run_tests():
    print(f"=== Testing All Deployed Features on {BASE_URL} ===\n", flush=True)
    session = requests.Session()

    # 1. Health check
    try:
        r = session.get(f"{BASE_URL}/health", timeout=60)
        data = r.json()
        log("HEALTH", r.status_code == 200, f"Status: {r.status_code}, render_free_mode: {data.get('render_free_mode')}, Supabase: {data.get('storage',{}).get('supabase',{}).get('reachable')}")
    except Exception as e:
        log("HEALTH", False, f"Failed: {e}")
        return

    # 2. Auth: Sign up
    token = None
    user_id = None
    email = f"audit_{int(time.time())}@lexaitest.in"
    try:
        r = session.post(f"{BASE_URL}/auth/signup", json={"name": "Audit Counsel", "email": email, "password": "Password123!"}, timeout=30)
        ok = r.status_code == 200 and "token" in r.json()
        if ok:
            token = r.json()["token"]
            user_id = r.json()["user"]["id"]
            log("AUTH_SIGNUP", True, f"User ID: {user_id}")
        else:
            log("AUTH_SIGNUP", False, f"Status {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log("AUTH_SIGNUP", False, f"Failed: {e}")

    # 3. Auth: Login
    try:
        r = session.post(f"{BASE_URL}/auth/login", json={"email": email, "password": "Password123!"}, timeout=30)
        ok = r.status_code == 200 and "token" in r.json()
        log("AUTH_LOGIN", ok, f"Status: {r.status_code}")
    except Exception as e:
        log("AUTH_LOGIN", False, f"Failed: {e}")

    # 4. Auth: Me
    headers = {"Authorization": "Bearer " + token}
    try:
        r = session.get(f"{BASE_URL}/auth/me", headers=headers, timeout=30)
        ok = r.status_code == 200 and r.json().get("user", {}).get("email") == email
        log("AUTH_ME", ok, f"Status: {r.status_code}")
    except Exception as e:
        log("AUTH_ME", False, f"Failed: {e}")

    # 5. Main Chat: General AI Mode
    try:
        r = session.post(f"{BASE_URL}/query/general", json={"question": "What are the essentials for dishonour of cheque under Section 138 of Negotiable Instruments Act?", "top_k": 3, "verify": False}, headers=headers, timeout=60)
        ok = r.status_code == 200 and "answer" in r.json()
        ans = r.json().get("answer", "")
        log("CHAT_GENERAL_AI", ok, f"Status: {r.status_code}, Answer length: {len(ans)} chars")
    except Exception as e:
        log("CHAT_GENERAL_AI", False, f"Failed: {e}")

    # 6. Precedent Check
    try:
        r = session.get(f"{BASE_URL}/precedent/check", params={"case_name": "Dashrath Rupsingh Rathod v. State of Maharashtra"}, headers=headers, timeout=60)
        ok = r.status_code == 200
        data = r.json() if ok else {}
        log("PRECEDENT_CHECK", ok, f"Status: {r.status_code}, Status: {data.get('status')}, Note: {data.get('status_note','')[:80]}")
    except Exception as e:
        log("PRECEDENT_CHECK", False, f"Failed: {e}")

    # 7. Ratio vs Obiter Dissection
    try:
        passage = "It is well settled that dishonour of a cheque for insufficiency of funds attracts criminal liability under Section 138. The drawer cannot escape liability merely by asserting lack of malicious intent. We observed in passing that commercial transactions require strict fiscal discipline."
        r = session.post(f"{BASE_URL}/analyze/ratio-obiter", json={"case_name": "Standard Traders v. State", "passage": passage}, headers=headers, timeout=60)
        ok = r.status_code == 200 and ("ratio_decidendi" in r.json() or "ratio" in r.json())
        data = r.json() if ok else {}
        log("RATIO_OBITER", ok, f"Status: {r.status_code}, Ratio: {data.get('ratio_decidendi', data.get('ratio',''))[:60]}...")
    except Exception as e:
        log("RATIO_OBITER", False, f"Failed: {e}")

    # 8. Legal Drafting Templates & Generation
    try:
        r = session.get(f"{BASE_URL}/draft/templates", headers=headers, timeout=30)
        templates = r.json()
        log("DRAFT_TEMPLATES", r.status_code == 200 and len(templates) > 0, f"Available templates: {len(templates)}")

        r2 = session.post(f"{BASE_URL}/draft/generate", json={
            "draft_type": "ni_act_138",
            "facts": "Complainant supplied textiles worth Rs 8,50,000. Accused issued cheque no 440211 which was dishonoured with remark Funds Insufficient. Statutory notice dated 12/03/2024 served on 15/03/2024 was not complied within 15 days.",
            "petitioner": "Vikas Textiles Pvt Ltd",
            "respondent": "Sunil Sharma, Proprietor Sharma Garments",
            "citations": ["Dalmia Cement Ltd v. Galaxy Traders 2001"]
        }, headers=headers, timeout=60)
        ok2 = r2.status_code == 200 and ("draft" in r2.json() or "content" in r2.json() or "title" in r2.json())
        data2 = r2.json() if ok2 else {}
        draft_text = data2.get("draft", data2.get("content", ""))
        log("LEGAL_DRAFT_GEN", ok2, f"Status: {r2.status_code}, Draft length: {len(draft_text)} chars")
    except Exception as e:
        log("LEGAL_DRAFT", False, f"Failed: {e}")

    # 9. Citizen Advice
    try:
        r = session.post(f"{BASE_URL}/citizen-advice", json={"incident": "I purchased an air conditioner online from a major retailer that stopped working after 3 days. The retailer refused replacement or refund saying warranty is from manufacturer, but manufacturer service center has been closed."}, headers=headers, timeout=60)
        ok = r.status_code == 200 and ("legal_rights" in r.json() or "steps" in r.json() or "summary" in r.json() or "action_plan" in r.json())
        data = r.json() if ok else {}
        log("CITIZEN_ADVICE", ok, f"Status: {r.status_code}, Keys: {list(data.keys())}")
    except Exception as e:
        log("CITIZEN_ADVICE", False, f"Failed: {e}")

    # 10. Global Moot Court Simulation
    try:
        r = session.post(f"{BASE_URL}/moot-court", json={"dispute": "Whether an online intermediary is entitled to safe harbour under Section 79 of IT Act when its automated recommendation algorithm amplifies defamatory content."}, headers=headers, timeout=75)
        ok = r.status_code == 200 and ("petitioner_argument" in r.json() or "bench_verdict" in r.json())
        data = r.json() if ok else {}
        log("MOOT_COURT_SIMULATION", ok, f"Status: {r.status_code}, Verdict length: {len(data.get('bench_verdict',''))} chars")
    except Exception as e:
        log("MOOT_COURT_SIMULATION", False, f"Failed: {e}")

    # 11. Case Workspace: Create Case
    case_id = None
    try:
        r = session.post(f"{BASE_URL}/cases", json={"title": "M/s Apex v. M/s Zenith", "description": "Section 138 NI Act complaint proceedings"}, headers=headers, timeout=30)
        ok = r.status_code == 200 and "case" in r.json()
        if ok:
            case_id = r.json()["case"]["id"]
            log("CASE_CREATE", True, f"Created case: {case_id}")
        else:
            log("CASE_CREATE", False, f"Status: {r.status_code}")
    except Exception as e:
        log("CASE_CREATE", False, f"Failed: {e}")

    if not case_id:
        print("Stopping case workspace tests: no case created.")
        return

    # 12. Case Workspace: Upload Case Document (PDF)
    doc_id = None
    try:
        # Create a valid minimal PDF with case facts
        pdf_bytes = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj\n"
            b"4 0 obj<</Length 180>>stream\n"
            b"BT /F1 12 Tf 50 700 Td (IN THE COURT OF METROPOLITAN MAGISTRATE AT NEW DELHI) Tj "
            b"0 -20 Td (COMPLAINT UNDER SECTION 138 NEGOTIABLE INSTRUMENTS ACT) Tj "
            b"0 -20 Td (Complainant: M/s Apex Corporation. Accused: M/s Zenith Enterprises) Tj "
            b"0 -20 Td (Cheque No 123456 dated 10-01-2024 for Rs 15,00,000 returned unpaid.) Tj "
            b"0 -20 Td (Statutory Demand Notice served on 22-01-2024. No payment received within 15 days.) Tj ET\n"
            b"endstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000212 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n440\n%%EOF"
        )
        files = [('files', ('complaint_138.pdf', BytesIO(pdf_bytes), 'application/pdf'))]
        r = session.post(f"{BASE_URL}/cases/{case_id}/documents", files=files, headers=headers, timeout=60)
        ok = r.status_code == 200 and len(r.json().get("documents", [])) > 0
        docs = r.json().get("documents", []) if ok else []
        if docs:
            doc_id = docs[0].get("id")
        log("CASE_UPLOAD_DOC", ok, f"Uploaded {len(docs)} doc(s), doc_id: {doc_id}")
    except Exception as e:
        log("CASE_UPLOAD_DOC", False, f"Failed: {e}")

    # 13. Case Workspace: List Documents
    try:
        r = session.get(f"{BASE_URL}/cases/{case_id}/documents", headers=headers, timeout=30)
        docs = r.json().get("documents", [])
        log("CASE_LIST_DOCS", r.status_code == 200 and len(docs) > 0, f"Found {len(docs)} documents")
    except Exception as e:
        log("CASE_LIST_DOCS", False, f"Failed: {e}")

    # 14. Case Workspace: Analyze Case (Case Intelligence)
    try:
        print("Running Case Intelligence Analysis (lazy model load + Gemini extract)...", flush=True)
        r = session.post(f"{BASE_URL}/cases/{case_id}/intelligence/analyze", headers=headers, timeout=120)
        ok = r.status_code == 200
        data = r.json() if ok else {}
        log("CASE_ANALYZE", ok, f"Status: {r.status_code}, Summary: {data.get('summary','')[:60]}..., Evidence items: {len(data.get('evidence',[]))}")
    except Exception as e:
        log("CASE_ANALYZE", False, f"Failed: {e}")

    # 15. Case Workspace: Get Case Intelligence Sections
    try:
        r = session.get(f"{BASE_URL}/cases/{case_id}/intelligence", headers=headers, timeout=30)
        ok = r.status_code == 200
        intel = r.json() if ok else {}
        log("CASE_GET_INTEL", ok, f"Status: {r.status_code}, Has timeline: {len(intel.get('timeline',[]))}, Has issues: {len(intel.get('legal_issues',[]))}")
    except Exception as e:
        log("CASE_GET_INTEL", False, f"Failed: {e}")

    # 16. Case Workspace: Ask LEXAI (mode=case)
    try:
        r = session.post(f"{BASE_URL}/cases/{case_id}/query", json={"question": "What is the cheque amount and date in this complaint?", "mode": "case", "top_k": 3, "verify": True}, headers=headers, timeout=60)
        ok = r.status_code == 200 and "answer" in r.json()
        ans = r.json().get("answer", "") if ok else ""
        log("CASE_ASK_LEXAI", ok, f"Status: {r.status_code}, Answer: {ans[:75]}...")
    except Exception as e:
        log("CASE_ASK_LEXAI", False, f"Failed: {e}")

    # 17. Case Workspace: Build Cited Argument
    try:
        r = session.post(f"{BASE_URL}/cases/{case_id}/argument", json={"side": "prosecution", "issue": "Accused failed to pay cheque amount within 15 days of statutory notice"}, headers=headers, timeout=60)
        ok = r.status_code == 200 and ("argument" in r.json() or "text" in r.json() or "heading" in r.json())
        data = r.json() if ok else {}
        arg_text = data.get("argument", data.get("text", ""))
        log("CASE_ARGUMENT", ok, f"Status: {r.status_code}, Argument length: {len(arg_text)} chars")
    except Exception as e:
        log("CASE_ARGUMENT", False, f"Failed: {e}")

    # 18. Case Workspace: Build Issue Map
    try:
        r = session.post(f"{BASE_URL}/cases/{case_id}/issue-map/build", headers=headers, timeout=60)
        ok = r.status_code == 200 and ("issues" in r.json() or "nodes" in r.json() or "issue_map" in r.json())
        log("CASE_ISSUE_MAP", ok, f"Status: {r.status_code}, Keys: {list(r.json().keys()) if ok else r.text[:100]}")
    except Exception as e:
        log("CASE_ISSUE_MAP", False, f"Failed: {e}")

    # 19. Case Workspace: Case Brief
    try:
        r = session.post(f"{BASE_URL}/cases/{case_id}/brief", headers=headers, timeout=60)
        ok = r.status_code == 200 and ("brief" in r.json() or "content" in r.json() or "text" in r.json())
        log("CASE_BRIEF", ok, f"Status: {r.status_code}")
    except Exception as e:
        log("CASE_BRIEF", False, f"Failed: {e}")

    # 20. Case Workspace: Case Moot Court
    try:
        r = session.post(f"{BASE_URL}/cases/{case_id}/moot-court", json={"issue": "Whether statutory notice was properly served under Section 138"}, headers=headers, timeout=60)
        ok = r.status_code == 200 and ("petitioner_argument" in r.json() or "bench_verdict" in r.json())
        log("CASE_MOOT_COURT", ok, f"Status: {r.status_code}")
    except Exception as e:
        log("CASE_MOOT_COURT", False, f"Failed: {e}")

    # 21. Research Notebook Notes (Add, List, Delete)
    try:
        r_add = session.post(f"{BASE_URL}/cases/{case_id}/notes", json={"title": "Service of Notice Proof", "content": "Postal receipt and tracking report confirm delivery on 22 Jan 2024.", "kind": "note"}, headers=headers, timeout=30)
        note_id = r_add.json().get("note", {}).get("id")
        log("CASE_NOTE_ADD", r_add.status_code == 200 and note_id is not None, f"Created note: {note_id}")

        r_list = session.get(f"{BASE_URL}/cases/{case_id}/notes", headers=headers, timeout=30)
        notes = r_list.json().get("notes", [])
        log("CASE_NOTE_LIST", r_list.status_code == 200 and len(notes) > 0, f"Found {len(notes)} notes")

        if note_id:
            r_del = session.delete(f"{BASE_URL}/cases/{case_id}/notes/{note_id}", headers=headers, timeout=30)
            log("CASE_NOTE_DELETE", r_del.status_code == 200, f"Deleted note: {note_id}")
    except Exception as e:
        log("CASE_NOTES", False, f"Failed: {e}")

    # 22. Case Workspace: Delete Case
    try:
        r = session.delete(f"{BASE_URL}/cases/{case_id}", headers=headers, timeout=30)
        ok = r.status_code == 200 and r.json().get("ok")
        log("CASE_DELETE", ok, f"Status: {r.status_code}")
    except Exception as e:
        log("CASE_DELETE", False, f"Failed: {e}")

    print("\n=== End-to-End Audit Completed ===", flush=True)

if __name__ == "__main__":
    run_tests()
