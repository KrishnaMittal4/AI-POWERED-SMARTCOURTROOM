"""Free-tier optimized single-run Case Intelligence Engine."""
import hashlib, json, os, re, sqlite3, time
from fastapi import HTTPException
from case_workspace import DB_PATH, assert_case, list_documents
import supabase_repository as sb
from llm_router import route_task, call_groq, call_gemini, GROQ_FALLBACK_MODEL
from rag_pipeline import search


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
    from private_case_rag import get_case_index,_paths,_ensure_embed_model
    # Disable re-ranker in low-memory / Render free mode to cut latency
    if os.getenv('LEXAI_LOW_MEMORY_MODE','false').lower() in {'1','true','yes','on'}:
        reranker = None
    embed=_ensure_embed_model(embed)
    idx,recs=get_case_index(user_id,case_id,embed); base,_=_paths(user_id,case_id)
    queries=[
      'material facts parties incident dates chronology',
      'evidence witness statement documentary exhibits',
      'contradictions inconsistent statements disputed facts',
      'legal issues sections acts statutes offences claims relief'
    ]
    chosen=[]; seen=set()
    for q in queries:
        try:
            hits=search(q,idx,recs,embed,top_k=4,rerank=reranker is not None,reranker_model=reranker,bm25_index_dir=str(base))
        except Exception:
            hits=search(q,idx,recs,embed,top_k=4,rerank=False,reranker_model=None,bm25_index_dir=str(base))
        for h in hits:
            key=(h.get('source_file'),h.get('raw_text') or h.get('text'))
            if key not in seen: seen.add(key); chosen.append(h)
    parts=[]; total=0
    for h in chosen:
        page=next((r.get('page') for r in recs if r.get('source_file')==h.get('source_file') and r.get('raw_text')==h.get('raw_text')),None)
        txt=(h.get('raw_text') or h.get('text') or '')[:1500]
        block=f"SOURCE: {h.get('source_file')} | PAGE: {page or '-'}\n{txt}"
        if total+len(block)>max_chars:break
        parts.append(block); total+=len(block)
    return '\n\n'.join(parts)


def _extract_json_candidate(raw):
    """Extract the most likely JSON object from provider output."""
    text=(raw or '').strip().lstrip('\ufeff')
    text=re.sub(r'^```(?:json|javascript|js)?\s*', '', text, flags=re.I)
    text=re.sub(r'\s*```\s*$', '', text).strip()
    start=text.find('{')
    if start < 0: return text
    depth=0; in_string=False; escape=False
    for i,ch in enumerate(text[start:], start=start):
        if in_string:
            if escape: escape=False
            elif ch=='\\': escape=True
            elif ch=='"': in_string=False
            continue
        if ch=='"': in_string=True
        elif ch=='{': depth+=1
        elif ch=='}':
            depth-=1
            if depth==0: return text[start:i+1]
    return text[start:]


def _repair_json_text(raw):
    """Conservative repair for common LLM JSON mistakes; never executes provider text."""
    text=_extract_json_candidate(raw)
    text=text.replace('“','"').replace('”','"').replace('’',"'").replace('‘',"'")
    text=re.sub(r',\s*([}\]])', r'\1', text)
    opens=[]; in_string=False; escape=False
    for ch in text:
        if in_string:
            if escape: escape=False
            elif ch=='\\': escape=True
            elif ch=='"': in_string=False
            continue
        if ch=='"': in_string=True
        elif ch in '{[': opens.append(ch)
        elif ch=='}' and opens and opens[-1]=='{': opens.pop()
        elif ch==']' and opens and opens[-1]=='[': opens.pop()
    if in_string: text+='"'
    for ch in reversed(opens): text += '}' if ch=='{' else ']'
    return text


def _parse_structured(raw):
    candidate=_extract_json_candidate(raw)
    try: return json.loads(candidate), False
    except Exception:
        repaired=_repair_json_text(raw)
        try: return json.loads(repaired), True
        except Exception as exc: raise ValueError(str(exc)) from exc


def _first_present(data, *keys):
    for key in keys:
        if key in data and data.get(key) not in (None, '', [], {}):
            return data.get(key)
    return None


def _as_list(value):
    if value is None: return []
    if isinstance(value, list): return value
    if isinstance(value, dict): return [value]
    return [value] if str(value).strip() else []


def _pick(item, *keys, default=''):
    if not isinstance(item, dict): return default
    for key in keys:
        value=item.get(key)
        if value not in (None, ''): return value
    return default


def _normalize_timeline(items):
    out=[]
    for raw in _as_list(items):
        if isinstance(raw, str): raw={'event':raw}
        if not isinstance(raw, dict): continue
        event=_pick(raw,'event','description','fact','action','detail','text')
        if not str(event).strip(): continue
        out.append({
            'date':_pick(raw,'date','event_date','when','day'),
            'time':_pick(raw,'time','event_time', default=None),
            'event':str(event).strip(),
            'source_file':_pick(raw,'source_file','source','document','filename','file'),
            'page':_pick(raw,'page','page_number','source_page', default=None),
        })
    return out


def _normalize_evidence(items):
    out=[]
    allowed={'testimonial','documentary','digital','forensic','physical','other'}
    for raw in _as_list(items):
        if isinstance(raw, str): raw={'summary':raw,'label':'Evidence item'}
        if not isinstance(raw, dict): continue
        summary=_pick(raw,'summary','description','item','evidence','text','fact')
        label=_pick(raw,'label','title','name','item') or (str(summary)[:80] if summary else 'Evidence item')
        if not str(summary or label).strip(): continue
        typ=str(_pick(raw,'type','evidence_type','category','role',default='other')).lower().replace('_',' ')
        aliases={'witness':'testimonial','witness statement':'testimonial','financial':'documentary','financial evidence':'documentary','electronic':'digital','electronic evidence':'digital','documentary evidence':'documentary','medical':'forensic','medical evidence':'forensic'}
        typ=aliases.get(typ,typ)
        if typ not in allowed: typ='other'
        out.append({
            'label':str(label).strip(), 'type':typ, 'summary':str(summary or label).strip(),
            'supports':str(_pick(raw,'supports','side','position',default='unknown')).lower(),
            'source_file':_pick(raw,'source_file','source','document','filename','file'),
            'page':_pick(raw,'page','page_number','source_page', default=None),
            'caveat':_pick(raw,'caveat','limitation','warning','qualification'),
        })
    return out


def _normalize_contradictions(items):
    out=[]
    for raw in _as_list(items):
        if isinstance(raw, str): raw={'issue':raw}
        if not isinstance(raw, dict): continue
        issue=_pick(raw,'issue','title','conflict','description','inconsistency')
        a=_pick(raw,'statement_a','claim_a','first_statement','source_a_text','a')
        b=_pick(raw,'statement_b','claim_b','second_statement','source_b_text','b')
        if not str(issue or a or b).strip(): continue
        out.append({
            'issue':str(issue or 'Potential inconsistency').strip(),
            'statement_a':str(a or '').strip(), 'source_a':_pick(raw,'source_a','document_a','source1','first_source'),
            'page_a':_pick(raw,'page_a','source_a_page','page1', default=None),
            'statement_b':str(b or '').strip(), 'source_b':_pick(raw,'source_b','document_b','source2','second_source'),
            'page_b':_pick(raw,'page_b','source_b_page','page2', default=None),
            'severity':str(_pick(raw,'severity','level',default='medium')).lower(),
            'explanation':_pick(raw,'explanation','why_it_matters','reason','analysis'),
        })
    return out


def _normalize_issues(items):
    out=[]
    for raw in _as_list(items):
        if isinstance(raw, str): raw={'issue':raw}
        if not isinstance(raw, dict): continue
        issue=_pick(raw,'issue','title','question','legal_issue','name','description')
        if not str(issue).strip(): continue
        out.append({
            'issue':str(issue).strip(),
            'basis':_pick(raw,'basis','reason','description','context'),
            'source_file':_pick(raw,'source_file','source','document','filename','file'),
            'page':_pick(raw,'page','page_number','source_page', default=None),
        })
    return out


def _normalize_intelligence(data):
    if not isinstance(data, dict): data={}
    # Accept common provider/schema variants instead of silently dropping useful arrays.
    data['summary']=str(_first_present(data,'summary','case_summary','executive_summary','overview') or '').strip()
    data['parties']=_as_list(_first_present(data,'parties','persons','participants'))
    data['important_facts']=_as_list(_first_present(data,'important_facts','material_facts','facts','key_facts'))
    data['legal_issues']=_normalize_issues(_first_present(data,'legal_issues','issues','key_issues','questions_of_law','issues_of_law'))
    data['timeline']=_normalize_timeline(_first_present(data,'timeline','timeline_events','events','chronology','procedural_history'))
    data['evidence']=_normalize_evidence(_first_present(data,'evidence','key_evidence','evidence_items','exhibits','supporting_evidence'))
    data['claims']=_as_list(_first_present(data,'claims','allegations','contentions'))
    data['contradictions']=_normalize_contradictions(_first_present(data,'contradictions','conflicts','inconsistencies','discrepancies'))
    data['statutes']=_as_list(_first_present(data,'statutes','provisions','legal_provisions','sections'))
    data['unresolved_questions']=_as_list(_first_present(data,'unresolved_questions','questions','open_questions','unknowns'))
    return data


def _structured_children_empty(data):
    return not any(data.get(k) for k in ('timeline','evidence','legal_issues'))


def _targeted_structure_fallback(context, client, previous_result):
    """One compact fallback call only when a rich summary exists but all child collections vanished."""
    schema='{"timeline":[{"date":"","time":null,"event":"","source_file":"","page":null}],"evidence":[{"label":"","type":"testimonial|digital|documentary|forensic|physical|other","summary":"","supports":"neutral|unknown|prosecution|defence","source_file":"","page":null,"caveat":""}],"contradictions":[{"issue":"","statement_a":"","source_a":"","page_a":null,"statement_b":"","source_b":"","page_b":null,"severity":"low|medium|high","explanation":""}],"legal_issues":[{"issue":"","basis":"","source_file":"","page":null}]}'
    prompt=("Extract ONLY the four structured collections below from the supplied case excerpts. Use only facts explicitly present. "
            "For judgments, court findings/orders may be documentary evidence and procedural events. If no genuine contradiction exists, return an empty contradictions array. "
            "Return one JSON object only. Schema:\n"+schema+"\n\nCASE EXCERPTS:\n"+context[:9000])
    result=route_task('case_intelligence', prompt, purpose='extract', groq_client=client, temperature=0.0, max_tokens=min(1000,int(os.getenv('TOKENS_CASE_INTELLIGENCE','1400'))))
    if not result.get('ok'): return None, result
    try:
        parsed,repaired=_parse_structured(result.get('text',''))
        normalized=_normalize_intelligence(parsed)
        return {k:normalized.get(k,[]) for k in ('timeline','evidence','contradictions','legal_issues')}, {**result,'local_repair':repaired}
    except Exception as exc:
        return None,{**result,'parse_error':str(exc)}


def _structured_repair_fallback(raw, schema, client, failed_provider):
    repair_prompt=('Repair the following malformed Case Intelligence output into ONE valid JSON object. Do not add facts, dates, parties, statutes, evidence, citations or conclusions that are not already present. Use empty arrays for missing sections. Return JSON only. Required schema:\n'+schema+'\n\nMALFORMED OUTPUT:\n'+(raw or '')[:10000])
    if failed_provider=='gemini':
        result=call_groq(client, repair_prompt, system_prompt='You repair JSON structure only. Never invent legal or factual content.', max_tokens=700, temperature=0.0)
    else:
        result=call_gemini(repair_prompt, purpose='extract', max_tokens=1400, temperature=0.0)
    if not result.get('ok'): return None, result
    try:
        data,repaired=_parse_structured(result.get('text',''))
        return _normalize_intelligence(data), {**result,'local_repair':repaired}
    except Exception as exc:
        return None, {**result,'parse_error':str(exc)}


def analyze_once(user_id,case_id,client,embed,reranker):
    from private_case_rag import _ensure_embed_model
    embed=_ensure_embed_model(embed)
    assert_case(user_id,case_id)
    if not list_documents(user_id,case_id): raise HTTPException(400,'Upload at least one private case PDF first.')
    context=_compact_context(user_id,case_id,embed,reranker,int(os.getenv('CASE_INTELLIGENCE_MAX_CHARS','10000')))
    if not context: raise HTTPException(400,'No extractable case text was found.')
    schema='{"summary":"","parties":[{"name":"","role":"","source_file":"","page":null}],"important_facts":[{"fact":"","source_file":"","page":null}],"legal_issues":[{"issue":"","basis":"","source_file":"","page":null}],"timeline":[{"date":"","time":null,"event":"","source_file":"","page":null}],"evidence":[{"label":"","type":"testimonial|digital|documentary|forensic|physical|other","summary":"","supports":"prosecution|defence|neutral|unknown","source_file":"","page":null,"caveat":""}],"claims":[{"topic":"","claim":"","source_file":"","page":null}],"contradictions":[{"issue":"","statement_a":"","source_a":"","page_a":null,"statement_b":"","source_b":"","page_b":null,"severity":"low|medium|high","explanation":""}],"statutes":[{"provision":"","context":"","source_file":"","page":null}],"unresolved_questions":[]}'
    prompt=("You are LEXAI Case Intelligence. Analyze ONLY supplied source-grounded excerpts. Do not invent facts, dates, parties, statutes, evidence or citations. If information is absent, use an empty array or add an unresolved question. Only mark a contradiction when supplied sources genuinely conflict. Keep values concise so the JSON completes within the output budget. Return ONE valid JSON object only. Do not use markdown fences or prose. Schema:\n"+schema+"\n\nCASE EXCERPTS:\n"+context)
    result=route_task('case_intelligence', prompt, purpose='extract', groq_client=client, temperature=.1, max_tokens=int(os.getenv('TOKENS_CASE_INTELLIGENCE','1400')))
    if not result.get('ok'):
        raise HTTPException(502, detail={'code':'provider_unavailable','message':'Case Intelligence providers are temporarily unavailable. Private Q&A and evidence verification remain available.','retryable':True})
    raw=result.get('text',''); warnings=[]
    try:
        data,locally_repaired=_parse_structured(raw); data=_normalize_intelligence(data)
        if locally_repaired: warnings.append('Provider JSON required local structural repair.')
    except Exception:
        data,repair_meta=_structured_repair_fallback(raw,schema,client,result.get('provider'))
        if data is None:
            data=_normalize_intelligence({'summary':'Advanced structured analysis could not be fully parsed. Private document Q&A and evidence verification remain available.'})
            warnings.append('Structured analysis was incomplete after local repair and alternate-provider repair. Empty sections were preserved safely.')
            repair_meta=repair_meta or {}
        else:
            warnings.append('Structured output was repaired by the alternate AI provider without adding new facts.')
        result={**result,'repair_provider':repair_meta.get('provider'),'repair_model':repair_meta.get('model')}
    # A substantial summary with no timeline/evidence/issues is almost always a schema-loss problem,
    # not a legitimately complete analysis. Attempt one compact targeted extraction.
    if data.get('summary') and len(data.get('summary','')) >= 80 and _structured_children_empty(data):
        recovered,recovery_meta=_targeted_structure_fallback(context,client,result)
        if recovered:
            for key in ('timeline','evidence','contradictions','legal_issues'):
                if not data.get(key) and recovered.get(key): data[key]=recovered[key]
            if any(recovered.get(k) for k in ('timeline','evidence','legal_issues')):
                warnings.append('Structured child sections were recovered with a targeted extraction pass.')
                result={**result,'structure_recovery_provider':recovery_meta.get('provider'),'structure_recovery_model':recovery_meta.get('model')}
        if _structured_children_empty(data):
            warnings.append('Case summary was generated, but Timeline, Evidence and Legal Issues could not be reliably extracted. Re-analyze after checking source text quality.')
            data['_incomplete_structured_analysis']=True

    data['_generation']={'provider':result.get('provider'),'model':result.get('model'),'fallback_used':bool(result.get('fallback_used') or result.get('resilience_fallback')),'fallback_reason':result.get('fallback_reason'),'repair_provider':result.get('repair_provider'),'repair_model':result.get('repair_model'),'structure_recovery_provider':result.get('structure_recovery_provider'),'structure_recovery_model':result.get('structure_recovery_model'),'warnings':warnings}
    fp=_fingerprint(user_id,case_id); now=int(time.time())
    if sb.enabled(): sb.cache_set(user_id,case_id,'case_intelligence',fp,data)
    else:
        with sqlite3.connect(DB_PATH) as db:
            db.execute('INSERT OR REPLACE INTO case_intelligence_cache(case_id,user_id,document_fingerprint,payload,updated_at) VALUES(?,?,?,?,?)',(case_id,user_id,fp,json.dumps(data,ensure_ascii=False),now)); db.commit()
    return {'status':'ready','stale':False,'partial':bool(warnings),'warnings':warnings,'updated_at':now,'intelligence':data}


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
