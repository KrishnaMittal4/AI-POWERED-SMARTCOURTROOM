"""Private per-user/per-case hybrid RAG and legal-intelligence helpers.
Reuses the project's MiniLM + FAISS + BM25/RRF + CrossEncoder stack while
keeping every case index physically isolated from the global judgment index.
"""
import json, os, re, shutil, threading
from pathlib import Path
import numpy as np
from fastapi import HTTPException
from rag_pipeline import clean_text, chunk_text, build_faiss_index, save_index, load_index, search, load_embedding_model
from ocr_extraction import extract_pdf_pages
from generate_answer import generate_answer, _source_out
from citation_verification import verify_answer
from private_evidence_verification import verify_private_answer
from case_workspace import assert_case, FILES_ROOT, DB_PATH, list_documents, get_document_path
from private_document_intelligence import classify_private_passage, preferred_private_roles
import sqlite3
import supabase_repository as sb

INDEX_ROOT = Path(os.getenv('CASE_INDEX_DIR', str(Path(os.getenv('LEXAI_DATA_ROOT', '.')) / 'user_case_indexes')))
_lock = threading.RLock()
_cache = {}

_embed_lock = threading.RLock()
_lazy_embed_model = None

def _ensure_embed_model(embed_model=None):
    """Lazy-load MiniLM only when private semantic retrieval is actually used."""
    global _lazy_embed_model
    if embed_model is not None:
        return embed_model
    with _embed_lock:
        if _lazy_embed_model is None:
            model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            print(f"Lazy-loading private RAG embedding model: {model_name}")
            _lazy_embed_model = load_embedding_model(model_name)
        return _lazy_embed_model



def _paths(user_id:int, case_id:str):
    base = INDEX_ROOT / str(user_id) / case_id
    return base, FILES_ROOT / str(user_id) / case_id


def invalidate_case_index(user_id:int, case_id:str):
    base,_ = _paths(user_id, case_id)
    with _lock: _cache.pop((user_id,case_id), None)
    shutil.rmtree(base, ignore_errors=True)


def _documents(user_id:int, case_id:str):
    """Return owned document descriptors independent of persistence backend."""
    assert_case(user_id, case_id)
    return list_documents(user_id, case_id)


def _page_records(user_id:int, case_id:str):
    records=[]
    for doc in _documents(user_id, case_id):
        original = doc.get('name') or 'document.pdf'
        stored = doc.get('id') or original
        path, _ = get_document_path(user_id, case_id, doc['id'])
        try:
            pages, summary = extract_pdf_pages(str(path))
            for page_info in pages:
                page_no=page_info['page']; txt=clean_text(page_info.get('text') or '')
                if not txt: continue
                for i,ch in enumerate(chunk_text(txt)):
                    header=f'[Private Case Document: {original} | Page: {page_no}]'
                    records.append({'chunk_id':f'{stored}:p{page_no}:c{i}','text':f'{header} {ch}','raw_text':ch,
                        'case_name':original,'court':'Private case file','case_no':None,'source_file':original,
                        'page':page_no,'document_id':doc.get('id'),'source_scope':'private','extraction_method':page_info.get('extraction_method','native'),
                        'extraction_quality_ok':page_info.get('quality_ok',True), **classify_private_passage(ch, original)})
            if summary.get('failed_pages'):
                print(f"Private case extraction warning ({original}): unreadable/low-quality pages {summary['failed_pages']}")
        except Exception as e:
            print(f'Private case PDF skipped ({original}): {e}')
    return records


def build_case_index(user_id:int, case_id:str, embed_model):
    embed_model = _ensure_embed_model(embed_model)
    assert_case(user_id, case_id); records=_page_records(user_id,case_id)
    if not records: raise HTTPException(400,'This case has no extractable PDF text yet.')
    texts=[r['text'] for r in records]
    vec=np.asarray(embed_model.encode(texts,batch_size=64,show_progress_bar=False,convert_to_numpy=True,normalize_embeddings=True)).astype('float32')
    idx=build_faiss_index(vec); base,_=_paths(user_id,case_id); base.mkdir(parents=True,exist_ok=True)
    save_index(idx,records,'all-MiniLM-L6-v2',str(base))
    if sb.enabled():
        try: sb.replace_case_chunks(user_id,case_id,records)
        except Exception as e: print(f'Supabase chunk persistence warning: {e}')
    with _lock: _cache[(user_id,case_id)]=(idx,records)
    return idx,records


def get_case_index(user_id:int, case_id:str, embed_model):
    embed_model = _ensure_embed_model(embed_model)
    assert_case(user_id,case_id); key=(user_id,case_id)
    with _lock:
        if key in _cache:return _cache[key]
    base,_=_paths(user_id,case_id)
    try:
        idx,records,_=load_index(str(base))
        with _lock:_cache[key]=(idx,records)
        return idx,records
    except Exception:return build_case_index(user_id,case_id,embed_model)


def _source(p):
    x=_source_out(p); x['page']=p.get('page'); x['scope']=p.get('source_scope','private'); return x


def ask_case(user_id,case_id,question,mode,top_k,verify,embed_model,reranker,client,global_index=None,global_records=None):
    embed_model = _ensure_embed_model(embed_model)
    if os.getenv("LEXAI_LOW_MEMORY_MODE", "false").lower() in {"1","true","yes","on"}: reranker = None
    if mode not in {'case','global','both'}: raise HTTPException(400,'mode must be case, global, or both')
    passages=[]; records_for_verify=[]
    if mode in {'case','both'}:
        idx,recs=get_case_index(user_id,case_id,embed_model)
        base,_=_paths(user_id,case_id)
        p=search(question,idx,recs,embed_model,top_k=max(top_k, 5),rerank=reranker is not None,reranker_model=reranker,bm25_index_dir=str(base))
        preferred=preferred_private_roles(question)
        for x in p:
            rec=next((r for r in recs if r['source_file']==x.get('source_file') and r.get('raw_text')==x.get('raw_text')), {})
            x['source_scope']='private'; x['page']=rec.get('page'); x['case_role']=rec.get('case_role','OTHER'); x['case_role_confidence']=rec.get('case_role_confidence',0.0)
            # Conservative role boost: relevance still dominates.
            x['_private_rank_score']=float(x.get('rerank_score',x.get('score',0)) or 0)+(0.12 if preferred and x['case_role'] in preferred else 0.0)
        p=sorted(p,key=lambda x:x.get('_private_rank_score',0),reverse=True)[:top_k]
        passages.extend(p); records_for_verify.extend(recs)
    if mode in {'global','both'}:
        if global_index is None: raise HTTPException(503,'Global judgment index is unavailable.')
        p=search(question,global_index,global_records,embed_model,top_k=top_k,rerank=reranker is not None,reranker_model=reranker)
        for x in p: x['source_scope']='global'
        passages.extend(p); records_for_verify.extend(global_records)
    if not passages:return {'answer':'No relevant passages found.','sources':[],'verification':None,'not_found':True}
    # In BOTH mode retain strong candidates from both stores; generation sees explicit source headers.
    passages=sorted(passages,key=lambda x:x.get('rerank_score',x.get('score',0)),reverse=True)[:max(top_k, min(len(passages), top_k*2 if mode=='both' else top_k))]
    answer=generate_answer(question,passages,client)
    verification=None
    if verify:
        private_passages=[p for p in passages if p.get("source_scope")=="private"]
        global_passages=[p for p in passages if p.get("source_scope")=="global"]
        if mode=="case":
            verification=verify_private_answer(answer, private_passages)
        elif mode=="global":
            verification={"verification_type":"judgment","judgment":verify_answer(answer, global_passages, global_records or records_for_verify, client)}
        else:
            verification={"verification_type":"mixed","private_evidence":verify_private_answer(answer, private_passages) if private_passages else None,"judgment":verify_answer(answer, global_passages, global_records or [], client) if global_passages else None}
    return {'answer':answer,'sources':[_source(p) for p in passages],'verification':verification,'not_found':False,'mode':mode}


def _case_text(user_id,case_id,max_chars=70000):
    recs=_page_records(user_id,case_id)
    seen=set(); parts=[]; total=0
    for r in recs:
        key=(r['source_file'],r['page'])
        if key in seen: continue
        seen.add(key); text=f"SOURCE: {r['source_file']} | PAGE: {r['page']}\n{r['raw_text']}"
        parts.append(text); total+=len(text)
        if total>=max_chars:break
    return '\n\n'.join(parts)



def _json_call(client, prompt, model=None, max_tokens=1800):
    """Small structured call used by batched case analysis."""
    resp=client.chat.completions.create(
        model=model or os.getenv('GROQ_ANALYSIS_MODEL','openai/gpt-oss-20b'),
        messages=[{'role':'user','content':prompt}], temperature=0.1,
        max_tokens=max_tokens, response_format={'type':'json_object'})
    raw=resp.choices[0].message.content or '{"items":[]}'
    try:return json.loads(raw)
    except Exception:
        m=re.search(r'\{.*\}',raw,re.S)
        return json.loads(m.group(0)) if m else {'items':[]}


def _analysis_pages(user_id, case_id, max_page_chars=6500):
    """Return each source page once; never ship the whole case in one prompt."""
    recs=_page_records(user_id,case_id); pages=[]; seen=set()
    for r in recs:
        key=(r['source_file'],r['page'])
        if key in seen: continue
        seen.add(key)
        # Reconstruct page from all its chunks so long pages are not silently lost.
        chunks=[x.get('raw_text','') for x in recs if (x['source_file'],x['page'])==key]
        text=' '.join(chunks)
        pages.append({'source_file':r['source_file'],'page':r['page'],'text':text[:max_page_chars]})
    return pages


def analyze_case(user_id,case_id,kind,client):
    if kind not in {'timeline','evidence','contradictions'}: raise HTTPException(400,'Unknown analysis type.')
    pages=_analysis_pages(user_id,case_id)
    if not pages: raise HTTPException(400,'No extractable text in this case.')
    extract={
      'timeline':'Extract material dated or sequential events. Return {"items":[{"date":"","time":null,"event":"","source_file":"","page":1}]}. Never invent dates.',
      'evidence':'Extract material evidence. Return {"items":[{"label":"","type":"testimonial|digital|documentary|forensic|physical|other","summary":"","supports":"prosecution|defence|neutral|unknown","source_file":"","page":1,"caveat":""}]}. No probability scores.',
      'contradictions':'Extract concrete factual CLAIMS that could be compared with other sources. Do not decide contradictions yet. Return {"items":[{"topic":"","claim":"","source_file":"","page":1}]}. Only source-grounded claims.'}[kind]
    # Map: one page per request keeps every call comfortably below provider TPM/context limits.
    mapped=[]
    for pg in pages:
        prompt=f'''You are an Indian legal document analyst. Analyze ONLY this page. {extract}\nStrict JSON only. Preserve the supplied filename/page in every item.\nSOURCE: {pg['source_file']} | PAGE: {pg['page']}\nTEXT:\n{pg['text']}'''
        data=_json_call(client,prompt,max_tokens=1100)
        for item in data.get('items',[]):
            item.setdefault('source_file',pg['source_file']); item.setdefault('page',pg['page'])
            mapped.append(item)
    if not mapped:return {'items':[]}
    # Reduce in compact batches. Contradictions compare extracted claims, not raw PDFs.
    if kind=='contradictions':
        final=[]
        for start in range(0,len(mapped),35):
            batch=mapped[start:start+35]
            prompt='''Compare these source-grounded claims. Return ONLY genuine material conflicts as {"items":[{"issue":"","statement_a":"","source_a":"","page_a":1,"statement_b":"","source_b":"","page_b":1,"severity":"low|medium|high","explanation":""}]}. Differences in wording are not contradictions. Strict JSON only.\nCLAIMS:\n'''+json.dumps(batch,ensure_ascii=False)
            final.extend(_json_call(client,prompt,max_tokens=1500).get('items',[]))
        # A final compact dedupe if needed.
        mapped=final
    # deterministic de-duplication; timeline sorting is best-effort without inventing dates.
    unique=[]; seen=set()
    for x in mapped:
        key=json.dumps(x,sort_keys=True,ensure_ascii=False)
        if key not in seen: seen.add(key); unique.append(x)
    if kind=='timeline':
        unique.sort(key=lambda x:(str(x.get('date') or '9999'),str(x.get('time') or '')))
    return {'items':unique}
