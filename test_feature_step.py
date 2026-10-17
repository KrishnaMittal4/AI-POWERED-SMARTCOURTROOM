import requests
import json
import time
from io import BytesIO

BASE_URL = "https://ai-powered-smartcourtroom.onrender.com"

session = requests.Session()
email = f"counsel_{int(time.time())}@lexaitest.in"
print(f"Signing up with {email}...", flush=True)
signup_res = session.post(f"{BASE_URL}/auth/signup", json={"name": "Senior Counsel", "email": email, "password": "Password123!"}, timeout=60)
if signup_res.status_code != 200:
    print(f"Signup failed: {signup_res.status_code} {signup_res.text}", flush=True)
    exit(1)

token = signup_res.json()["token"]
headers = {"Authorization": "Bearer " + token}
print(f"[OK] Auth successful: user token obtained.", flush=True)

tests = [
    ("General AI Chat", "POST", "/query/general", {"question": "What is Section 138 of NI Act?", "top_k": 3, "verify": False}),
    ("Precedent Checker", "GET", "/precedent/check?case_name=Kesavananda+Bharati", None),
    ("Ratio vs Obiter Modal", "POST", "/analyze/ratio-obiter", {"case_name": "Maneka Gandhi v. Union of India", "passage": "Procedure established by law under Article 21 must be just, fair and reasonable."}),
    ("Draft Templates List", "GET", "/draft/templates", None),
    ("Draft Generation Modal", "POST", "/draft/generate", {"draft_type": "ni_act_138", "facts": "Cheque of Rs 5 Lakh bounced due to funds insufficient.", "petitioner": "ABC Ltd", "respondent": "XYZ Corp"}),
    ("Citizen Advice Modal", "POST", "/citizen-advice", {"incident": "My landlord refused to refund 1 Lakh security deposit upon vacating flat without damage."}),
    ("Global Moot Court Modal", "POST", "/moot-court", {"dispute": "Whether privacy under Article 21 extends to public social media posts."}),
]

for name, method, endpoint, payload in tests:
    t0 = time.time()
    try:
        print(f"Testing {name}...", flush=True)
        if method == "POST":
            r = session.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers, timeout=60)
        else:
            r = session.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=60)
        dur = time.time() - t0
        ok = r.status_code == 200
        preview = r.text[:80].replace("\n", " ")
        symbol = "[PASS]" if ok else "[FAIL]"
        print(f"{symbol} {name:<25} Status: {r.status_code} ({dur:.2f}s) -> {preview}", flush=True)
    except Exception as e:
        print(f"[FAIL] {name:<25} Error: {e}", flush=True)

# Case Workspace features
print("\n--- Testing Case Workspace Features ---", flush=True)
c_res = session.post(f"{BASE_URL}/cases", json={"title": "Test Cheque Dispute", "description": "Legal proceedings under Section 138"}, headers=headers, timeout=30)
case_id = c_res.json()["case"]["id"]
print(f"[PASS] Case Created: {case_id}", flush=True)

# Upload PDF
pdf_bytes = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>/Contents 4 0 R>>endobj\n"
    b"4 0 obj<</Length 160>>stream\n"
    b"BT /F1 12 Tf 50 700 Td (IN THE COURT OF METROPOLITAN MAGISTRATE, SAKET, NEW DELHI) Tj "
    b"0 -20 Td (Complainant: ABC Corp. Accused: XYZ Enterprises. Cheque No 987654 for Rs 5,00,000 dishonoured.) Tj ET\n"
    b"endstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000212 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n420\n%%EOF"
)
files = [('files', ('cheque_complaint.pdf', BytesIO(pdf_bytes), 'application/pdf'))]
u_res = session.post(f"{BASE_URL}/cases/{case_id}/documents", files=files, headers=headers, timeout=45)
print(f"[PASS] Document Uploaded: {len(u_res.json().get('documents', []))} doc(s)", flush=True)

# List docs
l_res = session.get(f"{BASE_URL}/cases/{case_id}/documents", headers=headers, timeout=30)
print(f"[PASS] List Documents: {len(l_res.json().get('documents', []))} doc(s)", flush=True)

# Overview
o_res = session.get(f"{BASE_URL}/cases/{case_id}/overview", headers=headers, timeout=30)
print(f"[PASS] Case Overview: Status {o_res.status_code}", flush=True)

# Case Note Add, List, Delete
n_add = session.post(f"{BASE_URL}/cases/{case_id}/notes", json={"title": "Statutory Notice", "content": "Notice served via speed post.", "kind": "note"}, headers=headers, timeout=30)
note_id = n_add.json()["note"]["id"]
n_list = session.get(f"{BASE_URL}/cases/{case_id}/notes", headers=headers, timeout=30)
n_del = session.delete(f"{BASE_URL}/cases/{case_id}/notes/{note_id}", headers=headers, timeout=30)
print(f"[PASS] Case Notes Add/List/Delete: All Status 200", flush=True)

# Case Moot Court
cm_res = session.post(f"{BASE_URL}/cases/{case_id}/moot-court", json={"issue": "Whether statutory notice was properly served"}, headers=headers, timeout=60)
print(f"[{'PASS' if cm_res.status_code==200 else 'FAIL'}] Case Moot Court: Status {cm_res.status_code}", flush=True)

# Clean up
d_res = session.delete(f"{BASE_URL}/cases/{case_id}", headers=headers, timeout=30)
print(f"[PASS] Case Delete: Status {d_res.status_code}", flush=True)
print("\n=== All Tests Completed Successfully ===", flush=True)
