"""Minimal server-side Supabase persistence for LEXAI.

Uses Supabase PostgREST + Storage HTTP APIs with a backend-only secret/service
key. No Supabase credential is ever sent to the browser.
"""
from __future__ import annotations
import json, os, tempfile, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path
from fastapi import HTTPException


def enabled() -> bool:
    return os.getenv("LEXAI_STORAGE_BACKEND", "local").lower() == "supabase"


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY")))


def _base() -> str:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL is not configured")
    return url


def _key() -> str:
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY") or ""
    if not key:
        raise RuntimeError("Supabase server secret is not configured")
    return key


def _headers(extra=None):
    key = _key()
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra: h.update(extra)
    return h


def _request(method: str, url: str, data=None, headers=None, timeout=30):
    body = None
    if data is not None:
        body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or _headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if not raw: return None
            ctype = r.headers.get("content-type", "")
            return json.loads(raw) if "json" in ctype else raw
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:1200]
        raise RuntimeError(f"Supabase {method} failed ({e.code}): {detail}") from e


def _rest(table: str, query: str = "") -> str:
    return f"{_base()}/rest/v1/{table}{('?' + query) if query else ''}"


def _eq(value) -> str:
    return urllib.parse.quote(f"eq.{value}", safe="")


def select(table, filters=None, columns="*", order=None, limit=None):
    parts=[f"select={urllib.parse.quote(columns, safe='*,()')}"]
    for k,v in (filters or {}).items(): parts.append(f"{urllib.parse.quote(k)}={_eq(v)}")
    if order: parts.append(f"order={urllib.parse.quote(order, safe='.,')}")
    if limit: parts.append(f"limit={int(limit)}")
    return _request("GET", _rest(table, "&".join(parts))) or []


def insert(table, row, upsert=False, on_conflict=None):
    q = f"on_conflict={urllib.parse.quote(on_conflict)}" if on_conflict else ""
    prefer = "return=representation" + (",resolution=merge-duplicates" if upsert else "")
    return _request("POST", _rest(table,q), row, _headers({"Prefer":prefer})) or []


def update(table, filters, patch):
    q="&".join(f"{urllib.parse.quote(k)}={_eq(v)}" for k,v in filters.items())
    return _request("PATCH", _rest(table,q), patch, _headers({"Prefer":"return=representation"})) or []


def delete(table, filters):
    q="&".join(f"{urllib.parse.quote(k)}={_eq(v)}" for k,v in filters.items())
    return _request("DELETE", _rest(table,q), None, _headers({"Prefer":"return=representation"})) or []


def storage_bucket():
    return os.getenv("SUPABASE_STORAGE_BUCKET", "lexai-private")


def upload_object(path: str, data: bytes, content_type="application/pdf"):
    quoted=urllib.parse.quote(path, safe="/")
    url=f"{_base()}/storage/v1/object/{storage_bucket()}/{quoted}"
    h=_headers({"Content-Type":content_type,"x-upsert":"true"})
    return _request("POST",url,data,h,60)


def download_object(path: str) -> bytes:
    quoted=urllib.parse.quote(path, safe="/")
    return _request("GET",f"{_base()}/storage/v1/object/{storage_bucket()}/{quoted}",None,_headers(),60)


def delete_objects(paths):
    if not paths:return
    _request("DELETE",f"{_base()}/storage/v1/object/{storage_bucket()}",{"prefixes":list(paths)},_headers(),30)


def materialize_object(path: str, suffix=".pdf") -> Path:
    root=Path(os.getenv("LEXAI_TEMP_ROOT", tempfile.gettempdir()))/"lexai_supabase_cache"
    root.mkdir(parents=True,exist_ok=True)
    dest=root/f"{uuid.uuid5(uuid.NAMESPACE_URL,path).hex}{suffix}"
    if not dest.exists(): dest.write_bytes(download_object(path))
    return dest


def ensure_user(external_user_id, email=None, name=None):
    rows=select("lexai_users",{"external_user_id":str(external_user_id)},limit=1)
    if rows:
        patch={}
        if email and rows[0].get("email")!=email: patch["email"]=email
        if name and rows[0].get("name")!=name: patch["name"]=name
        if patch: update("lexai_users",{"id":rows[0]["id"]},patch); rows[0].update(patch)
        return rows[0]
    row={"external_user_id":str(external_user_id),"email":email,"name":name}
    return insert("lexai_users",row)[0]


def user_uuid(external_user_id):
    rows=select("lexai_users",{"external_user_id":str(external_user_id)},limit=1)
    if not rows: raise HTTPException(401,"User persistence record is missing.")
    return rows[0]["id"]


def health():
    if not enabled(): return {"backend":"local","configured":True}
    if not configured(): return {"backend":"supabase","configured":False}
    try:
        select("lexai_users",limit=1)
        return {"backend":"supabase","configured":True,"reachable":True,"bucket":storage_bucket()}
    except Exception as e:
        return {"backend":"supabase","configured":True,"reachable":False,"error":str(e)[:240],"bucket":storage_bucket()}

def cache_get(external_user_id, case_id, kind):
    uid=user_uuid(external_user_id); rows=select('case_runtime_cache',{'user_id':uid,'case_id':case_id,'kind':kind},limit=1)
    return rows[0] if rows else None

def cache_set(external_user_id, case_id, kind, fingerprint, payload):
    uid=user_uuid(external_user_id)
    row={'user_id':uid,'case_id':case_id,'kind':kind,'fingerprint':fingerprint,'payload':payload}
    rows=insert('case_runtime_cache',row,upsert=True,on_conflict='user_id,case_id,kind')
    return rows[0] if rows else row

def cache_delete_case(external_user_id, case_id):
    uid=user_uuid(external_user_id); return delete('case_runtime_cache',{'user_id':uid,'case_id':case_id})

def replace_case_chunks(external_user_id, case_id, records):
    """Persist extracted private chunks for provenance/recovery; retrieval still uses local FAISS cache."""
    if not enabled(): return
    uid=user_uuid(external_user_id)
    delete('document_chunks',{'user_id':uid,'case_id':case_id})
    rows=[]
    for i,r in enumerate(records):
        did=r.get('document_id')
        if not did: continue
        rows.append({'user_id':uid,'case_id':case_id,'document_id':did,'page_number':r.get('page'),'chunk_index':i,
                     'text':r.get('raw_text') or r.get('text') or '', 'case_role':r.get('case_role') or 'OTHER',
                     'role_confidence':r.get('case_role_confidence'), 'metadata':{'source_file':r.get('source_file'),'extraction_method':r.get('extraction_method'),'quality_ok':r.get('extraction_quality_ok')}})
    for start in range(0,len(rows),150):
        _request('POST',_rest('document_chunks'),rows[start:start+150],_headers({'Prefer':'return=minimal'}),60)
