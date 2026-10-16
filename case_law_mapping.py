"""LEXAI final-step Case -> Issue -> Evidence -> Law mapping.
Grounds each issue in private case provenance and retrieves global authorities.
"""
import hashlib, json, re, sqlite3, time
from fastapi import HTTPException
from case_workspace import DB_PATH, assert_case, list_documents
import supabase_repository as sb
from case_engine import get_intelligence
from rag_pipeline import search
from llm_router import route_task, GROQ_FALLBACK_MODEL


def init_issue_map_db():
    if sb.enabled(): return
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS case_issue_map_cache(
          case_id TEXT NOT NULL, user_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
          payload TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(case_id,user_id))"""); db.commit()


def _fingerprint(user_id, case_id):
    docs=list_documents(user_id,case_id)
    raw='|'.join(f"{d.get('id')}:{d.get('size_bytes')}:{d.get('created_at','')}" for d in docs)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_issue_map(user_id, case_id):
    assert_case(user_id,case_id); fp=_fingerprint(user_id,case_id)
    if sb.enabled():
        row=sb.cache_get(user_id,case_id,'issue_map')
        if not row:return {'status':'missing','stale':True,'issue_map':None}
        data=row.get('payload'); stale=row.get('fingerprint')!=fp
        return {'status':'stale' if stale else 'ready','stale':stale,'updated_at':row.get('updated_at'),'issue_map':data}
    with sqlite3.connect(DB_PATH) as db: row=db.execute('SELECT fingerprint,payload,updated_at FROM case_issue_map_cache WHERE case_id=? AND user_id=?',(case_id,user_id)).fetchone()
    if not row:return {'status':'missing','stale':True,'issue_map':None}
    try:data=json.loads(row[1])
    except Exception:data=None
    stale=row[0]!=fp; return {'status':'stale' if stale else 'ready','stale':stale,'updated_at':row[2],'issue_map':data}


def _terms(text):
    stop={'which','that','this','with','from','into','under','whether','where','when','what','have','been','were','their','there','case','issue','legal','court','section','act'}
    return {x for x in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(x)>3 and x not in stop}


def _private_support(issue, intel, limit=5):
    q=_terms(issue); pool=[]
    for kind in ('evidence','important_facts','claims','contradictions','statutes'):
        for x in intel.get(kind,[]) or []:
            blob=' '.join(str(v) for v in x.values() if v is not None)
            score=len(q & _terms(blob))
            if score:
                item={'kind':kind,'score':score,'source_file':x.get('source_file') or x.get('source_a'),
                      'page':x.get('page') or x.get('page_a'),'text':x.get('summary') or x.get('fact') or x.get('claim') or x.get('issue') or x.get('provision') or blob[:500]}
                pool.append(item)
    pool.sort(key=lambda z:z['score'],reverse=True)
    return pool[:limit]


def _authority_candidates(issue, index, records, embed, reranker, top_k=8):
    if index is None or not records:
        return []
    hits=search(issue,index,records,embed,top_k=top_k,rerank=reranker is not None,reranker_model=reranker)
    out=[]
    for h in hits:
        out.append({'case_name':h.get('case_name') or h.get('source_file'),'source_file':h.get('source_file'),
                    'page':h.get('page'),'score':round(float(h.get('rerank_score',h.get('score',0)) or 0),4),
                    'passage':(h.get('raw_text') or h.get('text') or '')[:1400],
                    'legal_role':h.get('legal_role') or h.get('role') or 'UNKNOWN'})
    return out


def _classify_authorities(issue, candidates, client):
    if not candidates:return {'supporting':[],'contrary':[],'related':[]}
    compact=[{'id':i,'case_name':x['case_name'],'source_file':x['source_file'],'passage':x['passage']} for i,x in enumerate(candidates)]
    prompt='''You are LEXAI authority mapper. For the stated legal issue, classify ONLY the supplied judgment passages. Do not invent holdings or cases. A passage may be supporting, contrary/distinguishable, related/neutral, or unclear. Return strict JSON: {"items":[{"id":0,"stance":"supporting|contrary|related|unclear","reason":"brief source-grounded reason"}]}. Treat party submissions as uncertain unless the passage clearly states the court's reasoning/holding.\nISSUE: '''+issue+'\nCANDIDATES:\n'+json.dumps(compact,ensure_ascii=False)
    result=route_task('issue_map',prompt,purpose='extract',groq_client=client,temperature=.0)
    by={i:x for i,x in enumerate(candidates)}; groups={'supporting':[],'contrary':[],'related':[]}
    if result.get('ok'):
        raw=result.get('text',''); m=re.search(r'\{.*\}',raw,re.S)
        try:data=json.loads(m.group(0) if m else raw)
        except Exception:data={'items':[]}
        for row in data.get('items',[]):
            try:i=int(row.get('id'))
            except Exception:continue
            if i not in by:continue
            stance=row.get('stance','related'); stance='contrary' if stance=='contrary' else ('supporting' if stance=='supporting' else 'related')
            item={**by[i],'reason':row.get('reason','')}; groups[stance].append(item)
    used={x['source_file'] for g in groups.values() for x in g}
    for x in candidates:
        if x['source_file'] not in used: groups['related'].append({**x,'reason':'Retrieved as relevant; stance not independently established.'})
    return groups


def build_issue_map(user_id,case_id,client,embed,reranker,index,records):
    from private_case_rag import _ensure_embed_model
    embed=_ensure_embed_model(embed)
    assert_case(user_id,case_id)
    c=get_intelligence(user_id,case_id)
    if c.get('status')!='ready' or not c.get('intelligence'):
        raise HTTPException(409,'Analyze or update Case Intelligence first.')
    intel=c['intelligence']; issues=intel.get('legal_issues',[]) or []
    if not issues: raise HTTPException(409,'No legal issues were extracted from this case. Re-analyze the case or add clearer source material.')
    mapped=[]
    for raw in issues[:8]:
        issue=raw.get('issue') if isinstance(raw,dict) else str(raw)
        if not issue:continue
        evidence=_private_support(issue,intel)
        candidates=_authority_candidates(issue,index,records,embed,reranker,8)
        auth=_classify_authorities(issue,candidates,client)
        mapped.append({'issue':issue,'basis':raw.get('basis','') if isinstance(raw,dict) else '',
                       'issue_source':{'source_file':raw.get('source_file'),'page':raw.get('page')} if isinstance(raw,dict) else {},
                       'case_evidence':evidence,'supporting_authorities':auth['supporting'][:4],
                       'contrary_authorities':auth['contrary'][:4],'related_authorities':auth['related'][:4],
                       'provenance_complete':bool(evidence)})
    payload={'issues':mapped,'global_corpus_enabled':bool(index is not None and records),'disclaimer':('Authority stance is AI-assisted and passage-grounded; later precedent treatment must be checked in an authoritative citator.' if index is not None and records else 'Global judgment research corpus is not enabled in this deployment. Private case evidence and issues remain available; authority mapping is intentionally unavailable.')}
    fp=_fingerprint(user_id,case_id); now=int(time.time())
    if sb.enabled(): sb.cache_set(user_id,case_id,'issue_map',fp,payload)
    else:
        with sqlite3.connect(DB_PATH) as db:
            db.execute('INSERT OR REPLACE INTO case_issue_map_cache(case_id,user_id,fingerprint,payload,updated_at) VALUES(?,?,?,?,?)',(case_id,user_id,fp,json.dumps(payload,ensure_ascii=False),now));db.commit()
    return {'status':'ready','stale':False,'updated_at':now,'issue_map':payload}
