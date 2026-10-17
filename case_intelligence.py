"""Persistent case notes and higher-level case intelligence for LEXAI."""
import json, re, sqlite3, time, uuid
from fastapi import HTTPException
from case_workspace import DB_PATH, assert_case, list_documents
from private_case_rag import _page_records, ask_case


def init_intelligence_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS case_notes(id TEXT PRIMARY KEY, case_id TEXT NOT NULL, user_id INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'note', created_at INTEGER NOT NULL)''')
        db.commit()

def list_notes(user_id, case_id):
    assert_case(user_id, case_id)
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute('SELECT id,title,content,kind,created_at FROM case_notes WHERE case_id=? AND user_id=? ORDER BY created_at DESC',(case_id,user_id)).fetchall()
    return [dict(zip(['id','title','content','kind','created_at'],r)) for r in rows]

def add_note(user_id, case_id, title, content, kind='note'):
    assert_case(user_id,case_id); nid=uuid.uuid4().hex; now=int(time.time())
    with sqlite3.connect(DB_PATH) as db:
        db.execute('INSERT INTO case_notes VALUES(?,?,?,?,?,?,?)',(nid,case_id,user_id,title.strip()[:200],content.strip(),kind[:40],now)); db.commit()
    return {'id':nid,'title':title.strip()[:200],'content':content.strip(),'kind':kind[:40],'created_at':now}

def delete_note(user_id,case_id,note_id):
    assert_case(user_id,case_id)
    with sqlite3.connect(DB_PATH) as db:
        cur=db.execute('DELETE FROM case_notes WHERE id=? AND case_id=? AND user_id=?',(note_id,case_id,user_id)); db.commit()
    if not cur.rowcount: raise HTTPException(404,'Research note not found.')

def overview(user_id,case_id):
    c=assert_case(user_id,case_id); docs=list_documents(user_id,case_id); notes=list_notes(user_id,case_id)
    return {'case':c,'document_count':len(docs),'note_count':len(notes),'documents':docs[:5],'recent_notes':notes[:4]}

def _json_from_llm(client, system, prompt):
    resp=client.chat.completions.create(model='openai/gpt-oss-20b',messages=[{'role':'system','content':system},{'role':'user','content':prompt}],temperature=.1,max_tokens=2400)
    text=(resp.choices[0].message.content or '').strip(); m=re.search(r'\{.*\}',text,re.S)
    if not m: raise HTTPException(502,'The intelligence model returned an invalid structured response.')
    try:return json.loads(m.group(0))
    except Exception: raise HTTPException(502,'Could not parse the intelligence response.')

def _case_material(user_id,case_id,max_chars=30000):
    recs=_page_records(user_id,case_id)
    if not recs: raise HTTPException(400,'Upload extractable case PDFs first.')
    return '\n\n'.join(f"SOURCE: {r['source_file']} p.{r['page']}\n{r['raw_text']}" for r in recs)[:max_chars]

def build_argument(user_id,case_id,side,issue,client,embed,reranker,gidx,grecs):
    q=f'{issue}. Find case evidence and Indian legal precedents relevant to the {side} position.'
    # Use 'both' only when the global judgment index is available; degrade gracefully in production.
    _mode = 'both' if gidx is not None else 'case'
    rag=ask_case(user_id,case_id,q,_mode,5,True,embed,reranker,client,gidx,grecs)
    src='\n\n'.join(f"[{i+1}] {s.get('scope')} | {s.get('source_file')} | p.{s.get('page') or '-'}\n{s.get('text','')}" for i,s in enumerate(rag.get('sources',[])))
    data=_json_from_llm(client,'You are an Indian legal research assistant. Use ONLY supplied sources. Never invent statutes, facts, cases, quotations or citations. Return JSON only.',f'''Build a {side} argument on: {issue}\nSOURCES:\n{src}\nReturn {{"issue":"","position":"","primary_argument":"","supporting_evidence":[{{"point":"","citation":""}}],"precedents":[{{"point":"","citation":""}}],"counterargument":"","rebuttal":"","limitations":""}}. If support is absent say so.''')
    data['retrieval_sources']=rag.get('sources',[]); return data

def build_brief(user_id,case_id,client):
    material=_case_material(user_id,case_id)
    return _json_from_llm(client,'You create neutral Indian legal case briefs from supplied private documents only. Do not infer missing facts. Every material assertion should carry source filename and page. Return JSON only.',f'''CASE MATERIAL:\n{material}\nReturn {{"case_summary":"","parties":[{{"name":"","role":"","citation":""}}],"material_facts":[{{"fact":"","citation":""}}],"procedural_history":[{{"event":"","citation":""}}],"legal_issues":[""],"statutes":[{{"provision":"","citation":""}}],"key_evidence":[{{"item":"","citation":""}}],"contradictions":[{{"issue":"","citation":""}}],"unresolved_questions":[""]}}.''')
