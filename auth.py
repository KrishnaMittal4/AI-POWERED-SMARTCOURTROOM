"""Local account authentication for Smart Courtroom.

Uses SQLite, PBKDF2-HMAC-SHA256 password hashing and signed bearer tokens using
only Python's standard library. Set AUTH_SECRET to a long random value in
production; tokens are invalidated if that secret changes.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
import supabase_repository as sb

DB_PATH = Path(os.getenv("AUTH_DB_PATH", "users.db"))
TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
_lock = threading.Lock()


def _secret() -> bytes:
    value = os.getenv("AUTH_SECRET", "")
    if not value:
        # Development fallback. Production deployments should always set this.
        value = "smart-courtroom-development-secret-change-me"
    return value.encode()


def init_auth_db():
    if sb.enabled():
        if not sb.configured(): raise RuntimeError("Supabase persistence selected but server credentials are missing.")
        return
    with _lock, sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, created_at INTEGER NOT NULL
        )"""); db.commit()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, expected = encoded.split("$", 3)
        if algo != "pbkdf2_sha256": return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except Exception:
        return False


def create_user(name: str, email: str, password: str):
    email=email.strip().lower(); name=name.strip()
    if sb.enabled():
        if sb.select('lexai_users', {'email':email}, limit=1): raise HTTPException(409,'An account with this email already exists.')
        uid=str(__import__('uuid').uuid4())
        row=sb.insert('lexai_users', {'external_user_id':uid,'name':name,'email':email,'password_hash':_hash_password(password)})[0]
        return {'id':row['external_user_id'],'name':name,'email':email}
    try:
        with _lock, sqlite3.connect(DB_PATH) as db:
            cur=db.execute("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",(name,email,_hash_password(password),int(time.time())));db.commit()
            return {'id':cur.lastrowid,'name':name,'email':email}
    except sqlite3.IntegrityError: raise HTTPException(409,'An account with this email already exists.')

def authenticate(email: str, password: str):
    email=email.strip().lower()
    if sb.enabled():
        rows=sb.select('lexai_users', {'email':email}, limit=1)
        if not rows or not _verify_password(password, rows[0].get('password_hash') or ''): raise HTTPException(401,'Incorrect email or password.')
        r=rows[0]; return {'id':r['external_user_id'],'name':r.get('name') or 'User','email':r['email']}
    with sqlite3.connect(DB_PATH) as db: row=db.execute("SELECT id,name,email,password_hash FROM users WHERE email=?",(email,)).fetchone()
    if not row or not _verify_password(password,row[3]): raise HTTPException(401,'Incorrect email or password.')
    return {'id':row[0],'name':row[1],'email':row[2]}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def make_token(user: dict) -> str:
    payload = {"sub": user["id"], "email": user["email"], "name": user["name"], "exp": int(time.time()) + TOKEN_TTL}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_token(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected): raise ValueError()
        payload = json.loads(_unb64(body))
        if int(payload["exp"]) < int(time.time()): raise ValueError()
        return {"id": payload["sub"], "name": payload["name"], "email": payload["email"]}
    except Exception:
        raise HTTPException(status_code=401, detail="Your session is invalid or has expired. Please sign in again.")


def current_user(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in is required.")
    return parse_token(header.split(" ", 1)[1].strip())
