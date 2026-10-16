"""Free-tier optimized single-run Case Intelligence Engine."""
import hashlib, json, os, re, sqlite3, time
from fastapi import HTTPException
from case_workspace import DB_PATH, assert_case, list_documents
import supabase_repository as sb
from llm_router import route_task, GROQ_FALLBACK_MODEL


def init_case_engine_db():
    if sb.enabled(): return
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS case_intelligence_cache(
          case_id TEXT NOT NULL, user_id INTEGER NOT NULL, document_fingerprint TEXT NOT NULL,
          payload TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(case_id,user_id))"""); db.commit()


def _fingerprint(user_id, case_id):
    docs=list_documents(user_id,case_id)
    raw='|'.join(f"{d.get('id')}:{d.get('size_bytes')}:{d.get('created_at','')}" for d in docs)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_intelligence(user_id,case_id):
    assert_case(user_id,case_id); fp=_fingerprint(user_id,case_id)
    if sb.enabled():
        row=sb.cache_get(user_id,case_id,'case_intelligence')
        if not row:return {'status':'missing','stale':True,'intelligence':None}
        data=row.get('payload'); stale=row.get('fingerprint')!=fp
        return {'status':'stale' if stale else 'ready','stale':stale,'updated_at':row.get('updated_at'),'intelligence':data}
    with sqlite3.connect(DB_PATH) as db: row=db.execute('SELECT document_fingerprint,payload,updated_at FROM case_intelligence_cache WHERE case_id=? AND user_id=?',(case_id,user_id)).fetchone()
    if not row:return {'status':'missing','stale':True,'intelligence':None}
    try:data=json.loads(row[1])
    except Exception:data=None
    stale=row[0]!=fp; return {'status':'stale' if stale else 'ready','stale':stale,'updated_at':row[2],'intelligence':data}


def _compact_context(user_id,case_id,embed,reranker,max_chars=12000):
    from private_case_rag import get_case_index,_paths
    from rag_pipeline import search
    idx,recs=get_case_index(user_id,case_id,embed); base,_=_paths(user_id,case_id)
    queries=[
      'material facts parties incident dates chronology procedural history',
      'evidence witness statement CCTV medical forensic documentary exhibits',
      'contradictions inconsistent statements disputed facts timeline conflict',
      'legal issues sections acts statutes offences claims relief'
    ]
    chosen=[]; seen=set()
    for q in queries:
        hits=search(q,idx,recs,embed,top_k=5,rerank=reranker is not None,reranker_model=reranker,bm25_index_dir=str(base))
        for h in hits:
            key=(h.get('source_file'),h.get('raw_text') or h.get('text'))
            if key not in seen: seen.add(key); chosen.append(h)
    parts=[]; total=0
    for h in chosen:
        page=next((r.get('page') for r in recs if r.get('source_file')==h.get('source_file') and r.get('raw_text')==h.get('raw_text')),None)
        txt=(h.get('raw_text') or h.get('text') or '')[:1800]
        block=f"SOURCE: {h.get('source_file')} | PAGE: {page or '-'}\n{txt}"
        if total+len(block)>max_chars:break
        parts.append(block); total+=len(block)
    return '\n\n'.join(parts)


def _parse(raw):
    raw=(raw or '').strip()
    try:return json.loads(raw)
    except Exception:pass
    m=re.search(r'\{.*\}',raw,re.S)
    if m:
        try:return json.loads(m.group(0))
        except Exception:pass
    raise HTTPException(502,'The AI returned malformed structured analysis. Please retry Analyze Case.')


def analyze_once(user_id,case_id,client,embed,reranker):
    assert_case(user_id,case_id)
    if not list_documents(user_id,case_id):raise HTTPException(400,'Upload at least one private case PDF first.')
    context=_compact_context(user_id,case_id,embed,reranker,int(os.getenv('CASE_INTELLIGENCE_MAX_CHARS','12000')))
    if not context:raise HTTPException(400,'No extractable case text was found.')
    schema='''{"summary":"","parties":[{"name":"","role":"","source_file":"","page":null}],"important_facts":[{"fact":"","source_file":"","page":null}],"legal_issues":[{"issue":"","basis":"","source_file":"","page":null}],"timeline":[{"date":"","time":null,"event":"","source_file":"","page":null}],"evidence":[{"label":"","type":"testimonial|digital|documentary|forensic|physical|other","summary":"","supports":"prosecution|defence|neutral|unknown","source_file":"","page":null,"caveat":""}],"claims":[{"topic":"","claim":"","source_file":"","page":null}],"contradictions":[{"issue":"","statement_a":"","source_a":"","page_a":null,"statement_b":"","source_b":"","page_b":null,"severity":"low|medium|high","explanation":""}],"statutes":[{"provision":"","context":"","source_file":"","page":null}],"unresolved_questions":[]}'''
    prompt=("You are LEXAI Case Intelligence. Analyze ONLY supplied source-grounded excerpts. "
      "Do not invent facts, dates, parties, statutes, evidence or citations. If information is absent, omit it or add an unresolved question. "
      "Only mark a contradiction when supplied sources genuinely conflict. Keep output concise. Return ONE valid JSON object only matching this schema:\n"
      +schema+"\n\nCASE EXCERPTS:\n"+context)
    # Free-tier routing: Gemini Flash-Lite handles structured case extraction first;
    # Groq is only the resilience fallback, preserving Groq TPM for interactive Q&A.
    result=route_task('case_intelligence', prompt, purpose='extract', groq_client=client, temperature=.1)
    if not result.get('ok'):
        raise HTTPException(502, f"Case Intelligence providers unavailable: {result.get('error','unknown provider error')}")
    data=_parse(result.get('text',''))
    data['_generation']={
        'provider':result.get('provider'),'model':result.get('model'),
        'fallback_reason':result.get('fallback_reason'),
        'resilience_fallback':result.get('resilience_fallback',False),
    }
    for k in ('parties','important_facts','legal_issues','timeline','evidence','claims','contradictions','statutes','unresolved_questions'):data.setdefault(k,[])
    data.setdefault('summary','')
    fp=_fingerprint(user_id,case_id); now=int(time.time())
    if sb.enabled(): sb.cache_set(user_id,case_id,'case_intelligence',fp,data)
    else:
        with sqlite3.connect(DB_PATH) as db:
            db.execute('INSERT OR REPLACE INTO case_intelligence_cache(case_id,user_id,document_fingerprint,payload,updated_at) VALUES(?,?,?,?,?)',(case_id,user_id,fp,json.dumps(data,ensure_ascii=False),now));db.commit()
    return {'status':'ready','stale':False,'updated_at':now,'intelligence':data}


def section(user_id,case_id,kind):
    c=get_intelligence(user_id,case_id)
    if c.get('status')!='ready' or not c.get('intelligence'):
        raise HTTPException(409,'Analyze or update the case first. This section uses saved Case Intelligence and makes no additional AI call.')
    if kind not in {'timeline','evidence','contradictions'}:raise HTTPException(400,'Unknown analysis type.')
    return {'items':c['intelligence'].get(kind,[]),'cached':True}


def brief(user_id,case_id):
    c=get_intelligence(user_id,case_id)
    if c.get('status')!='ready' or not c.get('intelligence'):
        raise HTTPException(409,'Analyze or update the case first. Case Brief is rendered from saved intelligence without another AI call.')
    x=c['intelligence']
    return {'case_summary':x.get('summary',''),'parties':x.get('parties',[]),'material_facts':x.get('important_facts',[]),'legal_issues':x.get('legal_issues',[]),'timeline':x.get('timeline',[]),'statutes':x.get('statutes',[]),'key_evidence':x.get('evidence',[]),'contradictions':x.get('contradictions',[]),'unresolved_questions':x.get('unresolved_questions',[]),'generated_from_cache':True}
