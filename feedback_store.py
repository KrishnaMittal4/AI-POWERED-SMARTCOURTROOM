"""Feedback persistence + bounded learning statistics for LEXAI."""
import json, os, sqlite3, threading
from datetime import datetime, timezone

_DB_PATH=os.getenv("FEEDBACK_DB_PATH","feedback.db")

class FeedbackStore:
    def __init__(self, db_path: str | None=None):
        self.db_path=db_path or _DB_PATH; self._lock=threading.Lock(); self._init_db()
    def _conn(self): return sqlite3.connect(self.db_path)
    def _init_db(self):
        with self._lock,self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT,
              rating INTEGER NOT NULL, comment TEXT, top_score REAL,
              weak_match INTEGER DEFAULT 0, not_found INTEGER DEFAULT 0,
              query_type TEXT DEFAULT 'mixed', reward REAL DEFAULT 0,
              correct_source TEXT, event_type TEXT DEFAULT 'answer_rating')""")
            # Migrate older local DBs safely.
            cols={r[1] for r in c.execute("PRAGMA table_info(feedback)").fetchall()}
            for name,ddl in [("query_type","TEXT DEFAULT 'mixed'"),("reward","REAL DEFAULT 0"),("correct_source","TEXT"),("event_type","TEXT DEFAULT 'answer_rating'")]:
                if name not in cols: c.execute(f"ALTER TABLE feedback ADD COLUMN {name} {ddl}")
            c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_qtype ON feedback(query_type)")
    def add(self,question,answer,sources=None,rating=1,comment=None,top_score=None,weak_match=False,not_found=False,query_type="mixed",reward=None,correct_source=None,event_type="answer_rating"):
        now=datetime.now(timezone.utc).isoformat(); sources_json=json.dumps(sources) if sources else None
        if reward is None:
            reward=float(rating)
            if not_found: reward-=0.35
            if weak_match: reward-=0.15
            if correct_source: reward+=0.35
            reward=max(-2.0,min(2.0,reward))
        # Persist to Supabase in production when available; local SQLite remains
        # the development fallback and fast learning cache.
        try:
            import supabase_repository as sb
            if sb.enabled() and sb.configured():
                row={"created_at":now,"question":question,"answer":answer,"sources":sources or [],"rating":int(rating),"comment":comment,"top_score":top_score,"weak_match":bool(weak_match),"not_found":bool(not_found),"query_type":query_type,"reward":float(reward),"correct_source":correct_source,"event_type":event_type}
                out=sb.insert("rag_feedback",row)
                return out[0].get("id",0) if out else 0
        except Exception:
            pass
        with self._lock,self._conn() as c:
            cur=c.execute("""INSERT INTO feedback(created_at,question,answer,sources,rating,comment,top_score,weak_match,not_found,query_type,reward,correct_source,event_type)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(now,question,answer,sources_json,int(rating),comment,top_score,int(weak_match),int(not_found),query_type,float(reward),correct_source,event_type))
            return cur.lastrowid
    def recent(self,limit=50):
        try:
            import supabase_repository as sb
            if sb.enabled() and sb.configured(): return sb.select("rag_feedback",order="created_at.desc",limit=limit)
        except Exception: pass
        with self._conn() as c:
            c.row_factory=sqlite3.Row; return [dict(r) for r in c.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT ?",(limit,)).fetchall()]
    def summary(self):
        rows=self.recent(5000); total=len(rows); up=sum(1 for r in rows if int(r.get("rating",0))==1); down=sum(1 for r in rows if int(r.get("rating",0))==-1)
        return {"total":total,"thumbs_up":up,"thumbs_down":down,"satisfaction_rate":round(up/total,3) if total else None,"learning_enabled":os.getenv("FEEDBACK_LEARNING_ENABLED","true").lower() in {"1","true","yes","on"}}

def _rows_for_learning():
    try:
        import supabase_repository as sb
        if sb.enabled() and sb.configured(): return sb.select("rag_feedback",order="created_at.desc",limit=2000)
    except Exception: pass
    try:
        with sqlite3.connect(_DB_PATH) as c:
            c.row_factory=sqlite3.Row; return [dict(r) for r in c.execute("SELECT * FROM feedback ORDER BY id DESC LIMIT 2000").fetchall()]
    except Exception: return []

def feedback_learning_stats(qtype):
    rows=[r for r in _rows_for_learning() if (r.get("query_type") or "mixed")==qtype and (r.get("event_type") or "answer_rating")=="answer_rating"]
    return {"total":len(rows),"up":sum(1 for r in rows if int(r.get("rating",0))>0),"down":sum(1 for r in rows if int(r.get("rating",0))<0),"reward_mean":sum(float(r.get("reward",0) or 0) for r in rows)/len(rows) if rows else 0.0}

def source_learning_stats(qtype,source_file):
    rows=[r for r in _rows_for_learning() if (r.get("query_type") or "mixed")==qtype and (r.get("correct_source") or "")==source_file]
    return {"total":len(rows),"positive":sum(1 for r in rows if float(r.get("reward",0) or 0)>0),"negative":sum(1 for r in rows if float(r.get("reward",0) or 0)<0)}
