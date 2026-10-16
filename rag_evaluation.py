"""Judgment-level offline retrieval evaluation and explainability for LEXAI.
No LLM/provider calls are made here. Experiment settings do not alter production RAG.
"""
from __future__ import annotations
import math, os, re, time, random
import numpy as np
from rag_pipeline import build_or_load_bm25, tokenize_for_bm25, INDEX_DIR, adaptive_retrieval_profile, analyze_legal_query, enrich_legal_query


def _norm(value: str) -> str:
    s=os.path.basename(str(value or '')).lower(); s=re.sub(r'\.pdf$','',s); s=re.sub(r'\bon\b.*$','',s)
    toks=re.findall(r'[a-z0-9]+',s); out=[]
    for t in toks:
        if not out or out[-1]!=t: out.append(t)
    return ''.join(out)

def _aliases(rec):
    return {x for x in (_norm(rec.get(k,'')) for k in ('source_file','case_name','case_no')) if x}

def _expected_match(rec, expected):
    """Resolve benchmark labels conservatively against canonical corpus identities.

    Exact normalized identity wins. A partial label (for example ``A_Sakthivel``)
    is accepted only when it is long enough to be meaningful; ambiguity is handled
    by the caller because every matching record is collected before scoring.
    """
    e=_norm(expected)
    if not e:
        return False
    aliases=_aliases(rec)
    if e in aliases:
        return True
    # Safe partial matching for human-entered short labels. Avoid tiny/generic tokens.
    if len(e) >= 8:
        return any(e in a or a in e for a in aliases if len(a) >= 8)
    return False

def _doc_key(rec): return _norm(rec.get('source_file')) or _norm(rec.get('case_name')) or str(id(rec))
def _view(rec,rank,**scores):
    return {'rank':rank,'case_name':rec.get('case_name',''),'case_no':rec.get('case_no',''),'source_file':rec.get('source_file',''),'canonical_id':_doc_key(rec),'passage':rec.get('raw_text',rec.get('text',''))[:1600],**scores}

def _unique(chunk_rows,records,limit):
    docs={}
    for idx,rank,score in chunk_rows:
        key=_doc_key(records[idx])
        if key not in docs: docs[key]=(idx,rank,score)
    return sorted(docs.values(),key=lambda x:x[1])[:limit]

def _dense(query,index,records,model,n):
    t=time.perf_counter(); qv=np.asarray(model.encode([query],normalize_embeddings=True,convert_to_numpy=True)).astype('float32')
    fetch=min(max(n*4,100),len(records)); ds,di=index.search(qv,fetch); rows=[]
    for rank,(score,idx) in enumerate(zip(ds[0],di[0]),1):
        if idx!=-1: rows.append((int(idx),rank,float(score)))
    return rows,(time.perf_counter()-t)*1000

def _sparse(query,records,n,index_dir=INDEX_DIR):
    t=time.perf_counter(); bm25=build_or_load_bm25(records,index_dir=index_dir); scores=bm25.get_scores(tokenize_for_bm25(query))
    pos=np.where(scores>0)[0]; order=pos[np.argsort(scores[pos])[::-1]] if len(pos) else []
    rows=[(int(idx),rank,float(scores[idx])) for rank,idx in enumerate(order,1)]
    return rows,(time.perf_counter()-t)*1000

def run_stages(query,index,records,model,reranker=None,settings=None):
    cfg={
        'dense_candidates':40,'bm25_candidates':40,'rrf_candidates':20,'final_k':5,'rrf_k':60,'rerank':True,
        'improved_dense_weight':1.0,'improved_bm25_weight':1.35,'improved_bm25_rescue_docs':5,'improved_rerank_stability':0.25
    }; cfg.update(settings or {})
    dc=max(5,min(int(cfg['dense_candidates']),200)); bc=max(5,min(int(cfg['bm25_candidates']),200)); rc=max(5,min(int(cfg['rrf_candidates']),100)); fk=max(1,min(int(cfg['final_k']),20)); rk=max(1,min(int(cfg['rrf_k']),200))
    dw=max(0.0,float(cfg.get('improved_dense_weight',1.0))); bw=max(0.0,float(cfg.get('improved_bm25_weight',1.35)))
    rescue=max(0,min(int(cfg.get('improved_bm25_rescue_docs',5)),20)); stability=max(0.0,min(float(cfg.get('improved_rerank_stability',0.25)),0.75))
    ap=adaptive_retrieval_profile(query)
    enriched=ap['enriched_query']
    dense,dense_ms=_dense(query,index,records,model,dc); bmrows,bm25_ms=_sparse(query,records,bc)
    abmrows,adaptive_bm25_ms=_sparse(enriched,records,bc) if enriched != query else (bmrows,0.0)
    dense_docs=_unique(dense,records,dc); bm_docs=_unique(bmrows,records,bc); adaptive_bm_docs=_unique(abmrows,records,bc)
    dr={_doc_key(records[i]):r for r,(i,_,_) in enumerate(dense_docs,1)}; br={_doc_key(records[i]):r for r,(i,_,_) in enumerate(bm_docs,1)}; abr={_doc_key(records[i]):r for r,(i,_,_) in enumerate(adaptive_bm_docs,1)}
    db={_doc_key(records[i]):(i,s) for i,_,s in dense_docs}; bb={_doc_key(records[i]):(i,s) for i,_,s in bm_docs}; abb={_doc_key(records[i]):(i,s) for i,_,s in adaptive_bm_docs}

    ft=time.perf_counter()
    legacy=[]; improved=[]; adaptive=[]
    adw=ap['dense_weight']; abw=ap['bm25_weight']; astability=ap['rerank_stability']
    keys=set(dr)|set(br); adaptive_keys=set(dr)|set(abr)
    for key in keys:
        idx=(db.get(key) or bb[key])[0]
        ls=(1/(rk+dr[key]) if key in dr else 0)+(1/(rk+br[key]) if key in br else 0)
        ws=dw*(1/(rk+dr[key]) if key in dr else 0)+bw*(1/(rk+br[key]) if key in br else 0)
        legacy.append((key,idx,ls)); improved.append((key,idx,ws))
        aws=adw*(1/(rk+dr[key]) if key in dr else 0)+abw*(1/(rk+br[key]) if key in br else 0)
    for key in adaptive_keys:
        idx=(db.get(key) or abb[key])[0]
        aws=adw*(1/(rk+dr[key]) if key in dr else 0)+abw*(1/(rk+abr[key]) if key in abr else 0)
        adaptive.append((key,idx,aws))
    legacy=sorted(legacy,key=lambda x:x[2],reverse=True)[:rc]
    improved=sorted(improved,key=lambda x:x[2],reverse=True)
    adaptive=sorted(adaptive,key=lambda x:x[2],reverse=True)
    # Sparse rescue protects the strongest unique BM25 judgments from being pruned before reranking.
    rescue_keys=[_doc_key(records[i]) for i,_,_ in bm_docs[:rescue]]
    keep={k for k,_,_ in improved[:rc]} | set(rescue_keys)
    improved=[x for x in improved if x[0] in keep]
    adaptive_rescue_keys=[_doc_key(records[i]) for i,_,_ in adaptive_bm_docs[:rescue]]
    akeep={k for k,_,_ in adaptive[:rc]} | set(adaptive_rescue_keys)
    adaptive=[x for x in adaptive if x[0] in akeep]
    fusion_ms=(time.perf_counter()-ft)*1000

    do=bool(cfg.get('rerank',True) and reranker is not None)
    def rerank(pool,stable=False):
        if not do or not pool: return list(pool),{},0.
        rt=time.perf_counter()
        try:
            vals=reranker.predict([[query,records[i].get('text','')] for _,i,_ in pool])
            rm={k:float(v) for (k,_,_),v in zip(pool,vals)}
            if not stable:
                out=sorted(pool,key=lambda x:rm.get(x[0],-1e9),reverse=True)
            else:
                rv=np.asarray([rm[k] for k,_,_ in pool],dtype=float); fv=np.asarray([v for _,_,v in pool],dtype=float)
                def norm(a):
                    lo=float(a.min()); hi=float(a.max()); return np.ones_like(a) if hi-lo<1e-9 else (a-lo)/(hi-lo)
                rn=norm(rv); fn=norm(fv); score={k:(1-stability)*float(rn[j])+stability*float(fn[j]) for j,(k,_,_) in enumerate(pool)}
                out=sorted(pool,key=lambda x:score[x[0]],reverse=True)
            return out,rm,(time.perf_counter()-rt)*1000
        except Exception:
            return list(pool),{},(time.perf_counter()-rt)*1000
    legacy_full,lrm,lms=rerank(legacy,False); improved_full,irm,ims=rerank(improved,True)
    old_stability=stability; stability=astability
    adaptive_full,arm,ams=rerank(adaptive,True)
    stability=old_stability
    # High agreement: both retrievers rank the authority in top 3; prevent destructive demotion below rank 3.
    protected=[k for k,_,_ in adaptive if dr.get(k,999)<=3 and abr.get(k,999)<=3]
    for k in protected:
        pos=next((j for j,x in enumerate(adaptive_full) if x[0]==k),None)
        if pos is not None and pos>2:
            item=adaptive_full.pop(pos); adaptive_full.insert(2,item)

    def res(key,idx,rank,fusion=None,rs=None):
        return _view(records[idx],rank,dense_score=db.get(key,(None,0))[1],bm25_score=bb.get(key,(None,0))[1],rrf_score=fusion,rerank_score=rs,dense_rank=dr.get(key),bm25_rank=br.get(key))
    fa=[res(_doc_key(records[i]),i,r) for r,(i,_,_) in enumerate(dense_docs[:fk],1)]
    bm=[res(_doc_key(records[i]),i,r) for r,(i,_,_) in enumerate(bm_docs[:fk],1)]
    lh=[res(k,i,r,s) for r,(k,i,s) in enumerate(legacy[:fk],1)]
    lf=[res(k,i,r,s,lrm.get(k)) for r,(k,i,s) in enumerate(legacy_full[:fk],1)]
    ih=[res(k,i,r,s) for r,(k,i,s) in enumerate(improved[:fk],1)]
    inf=[res(k,i,r,s,irm.get(k)) for r,(k,i,s) in enumerate(improved_full[:fk],1)]
    ah=[res(k,i,r,s) for r,(k,i,s) in enumerate(adaptive[:fk],1)]
    af=[res(k,i,r,s,arm.get(k)) for r,(k,i,s) in enumerate(adaptive_full[:fk],1)]
    pools={
      'FAISS only':[( _doc_key(records[i]),i,0) for i,_,_ in dense_docs],
      'BM25 only':[( _doc_key(records[i]),i,0) for i,_,_ in bm_docs],
      'Legacy RRF':legacy,'Legacy Full reranked':legacy_full,
      'Improved weighted fusion':improved,'Improved Full RAG':improved_full,
      'Adaptive fusion V4.1':adaptive,'Adaptive Full RAG V4.1':adaptive_full
    }
    maps={n:{k:r for r,(k,_,_) in enumerate(pool,1)} for n,pool in pools.items()}
    stages=[
      {'name':'FAISS only','strategy':'baseline_dense','latency_ms':round(dense_ms,1),'results':fa},
      {'name':'BM25 only','strategy':'baseline_sparse','latency_ms':round(bm25_ms,1),'results':bm},
      {'name':'Legacy RRF','strategy':'legacy','latency_ms':round(dense_ms+bm25_ms+fusion_ms,1),'results':lh},
      {'name':'Legacy Full reranked','strategy':'legacy','latency_ms':round(dense_ms+bm25_ms+fusion_ms+lms,1),'results':lf},
      {'name':'Improved weighted fusion','strategy':'improved','latency_ms':round(dense_ms+bm25_ms+fusion_ms,1),'results':ih},
      {'name':'Improved Full RAG','strategy':'improved','latency_ms':round(dense_ms+bm25_ms+fusion_ms+ims,1),'results':inf},
      {'name':'Adaptive fusion V4.1','strategy':'adaptive','query_type':ap['query_type'],'latency_ms':round(dense_ms+bm25_ms+fusion_ms,1),'results':ah},
      {'name':'Adaptive Full RAG V4.1','strategy':'adaptive','query_type':ap['query_type'],'latency_ms':round(dense_ms+bm25_ms+fusion_ms+ams,1),'results':af}
    ]
    return {'settings':{**cfg,'rerank':do},'stages':stages,'rank_maps':maps,'query_intelligence':ap.get('query_analysis', analyze_legal_query(query)),'enriched_query':enriched,'protected_candidates':protected,'adaptive_bm25_ranks':abr}

def inspect_query(query,index,records,model,reranker=None,top_k=5,settings=None):
    cfg=dict(settings or {}); cfg.setdefault('final_k',top_k); return {'query':query,'offline':True,**run_stages(query,index,records,model,reranker,cfg)}

def _relevance_map(records,q):
    rel={}
    graded=q.get('relevance') or []
    for item in graded:
        label=item.get('judgment') or item.get('source') or ''; grade=max(0,min(int(item.get('grade',1)),3))
        for rec in records:
            if _expected_match(rec,label): rel[_doc_key(rec)]=max(rel.get(_doc_key(rec),0),grade)
    if not rel:
        for label in (q.get('relevant_files') or q.get('relevant_cases') or []):
            for rec in records:
                if _expected_match(rec,label): rel[_doc_key(rec)]=max(rel.get(_doc_key(rec),0),3)
    return rel

def _ndcg(results,rel,k):
    gains=[rel.get(x['canonical_id'],0) for x in results[:k]]
    dcg=sum((2**g-1)/math.log2(i+2) for i,g in enumerate(gains)); ideal=sorted(rel.values(),reverse=True)[:k]; idcg=sum((2**g-1)/math.log2(i+2) for i,g in enumerate(ideal)); return dcg/idcg if idcg else 0.

def evaluate(questions,index,records,model,reranker=None,top_k=5,settings=None):
    cfg=dict(settings or {}); cfg.setdefault('final_k',top_k)
    names=['FAISS only','BM25 only','Legacy RRF','Legacy Full reranked','Improved weighted fusion','Improved Full RAG','Adaptive fusion V4.1','Adaptive Full RAG V4.1']
    agg={n:{'hits':0,'hit1':0,'rr':0.,'rec':[],'prec':[],'ndcg':[],'lat':[],'details':[]} for n in names}
    scored=0; unscored=0; behavior_tests=0; behavior_passed=0
    for q in questions:
        rel=_relevance_map(records,q)
        data=run_stages(q['query'],index,records,model,reranker,cfg)
        sb={s['name']:s for s in data['stages']}
        labels=[x.get('judgment') for x in (q.get('relevance') or []) if x.get('judgment')] or (q.get('relevant_files') or q.get('relevant_cases') or [])
        journey=[]
        for label in labels:
            keys={_doc_key(r) for r in records if _expected_match(r,label)}
            journey.append({'expected':label,'matched_corpus_ids':sorted(keys),'ranks':{n:min([data['rank_maps'][n].get(k,10**9) for k in keys],default=10**9) if keys else None for n in names}})
        expected_behavior=str(q.get('expected_behavior') or '').strip().lower()
        actual_behavior='ambiguous_query' if data.get('query_intelligence',{}).get('ambiguous') else 'complete_query'
        is_behavior=bool(expected_behavior)
        if is_behavior:
            behavior_tests+=1; behavior_passed+=int(expected_behavior==actual_behavior)
        # Retrieval metrics require at least one label that resolves to the corpus.
        is_scorable=bool(rel)
        if is_scorable: scored+=1
        else: unscored+=1
        for n in names:
            s=sb[n]; results=s['results'][:int(cfg.get('final_k',top_k))]; retrieved=[x['canonical_id'] for x in results]
            matched=[k for k in retrieved if rel.get(k,0)>0]; ranks=[i for i,k in enumerate(retrieved,1) if rel.get(k,0)>0]
            first=min(ranks) if ranks else None; hit=bool(matched); recall=len(set(matched))/len(rel) if rel else 0.; precision=len(matched)/max(len(results),1); nd=_ndcg(results,rel,int(cfg.get('final_k',top_k))) if rel else 0.
            a=agg[n]; a['lat'].append(s['latency_ms'])
            if is_scorable:
                a['hits']+=int(hit); a['hit1']+=int(first==1); a['rr']+=1/first if first else 0; a['rec'].append(recall); a['prec'].append(precision); a['ndcg'].append(nd)
            candidate_ranks=[r for j in journey for r in [j['ranks'].get('FAISS only',10**9),j['ranks'].get('BM25 only',10**9)] if isinstance(r,(int,float))]
            adaptive_sparse_ranks=[]
            for j in journey:
                for key in j.get('matched_corpus_ids',[]): adaptive_sparse_ranks.append(data.get('adaptive_bm25_ranks',{}).get(key,10**9))
            candidate_found=any(r < 10**9 for r in candidate_ranks+adaptive_sparse_ranks)
            if not is_scorable:
                failure_type='not_scored'
            elif hit: failure_type='none'
            elif data.get('query_intelligence',{}).get('ambiguous'): failure_type='ambiguous_query'
            elif not candidate_found: failure_type='candidate_retrieval_failure'
            else:
                aranks=[j['ranks'].get('Adaptive fusion V4.1',10**9) for j in journey]; franks=[j['ranks'].get('Adaptive Full RAG V4.1',10**9) for j in journey]
                if not any(r < 10**9 for r in aranks): failure_type='fusion_failure'
                elif any(r <= int(cfg.get('final_k',top_k)) for r in aranks) and not any(r <= int(cfg.get('final_k',top_k)) for r in franks): failure_type='reranking_failure'
                else: failure_type='final_top_k_failure'
            instability=[]
            for j in journey:
                b=j['ranks'].get('BM25 only'); f=j['ranks'].get('Adaptive fusion V4.1')
                if isinstance(b,int) and isinstance(f,int) and b<=3 and f<10**9 and f-b>=8:
                    instability.append({'expected':j['expected'],'bm25_rank':b,'adaptive_fusion_rank':f,'warning':'Strong lexical candidate heavily demoted during adaptive fusion.'})
            a['details'].append({'query':q['query'],'expected':labels,'expected_corpus_matches':len(rel),'scorable':is_scorable,'score_status':'scored' if is_scorable else 'not_scored','hit':hit if is_scorable else None,'first_relevant_rank':first if is_scorable else None,'recall':round(recall,3) if is_scorable else None,'precision':round(precision,3) if is_scorable else None,'ndcg':round(nd,3) if is_scorable else None,'retrieved':[x['source_file'] for x in results],'candidate_journey':journey,'candidate_found':candidate_found,'failure_type':failure_type,'query_intelligence':data.get('query_intelligence',{}),'enriched_query':data.get('enriched_query',q['query']),'protected_candidates':data.get('protected_candidates',[]),'expected_behavior':expected_behavior or None,'actual_behavior':actual_behavior if is_behavior else None,'behavior_pass':(expected_behavior==actual_behavior) if is_behavior else None,'rank_instability':instability})
    denom=max(scored,1); metrics=[]
    for name in names:
        a=agg[name]; metrics.append({'name':name,'strategy':('adaptive' if name.startswith('Adaptive') else 'improved' if name.startswith('Improved') else 'legacy' if name.startswith('Legacy') else 'baseline'),'hit_at_1':round(a['hit1']/denom,3) if scored else 0,'hit_at_k':round(a['hits']/denom,3) if scored else 0,'recall_at_k':round(sum(a['rec'])/denom,3) if scored else 0,'precision_at_k':round(sum(a['prec'])/denom,3) if scored else 0,'mrr':round(a['rr']/denom,3) if scored else 0,'ndcg_at_k':round(sum(a['ndcg'])/denom,3) if scored else 0,'avg_latency_ms':round(sum(a['lat'])/len(a['lat']),1) if a['lat'] else 0,'questions':len(questions),'scored_questions':scored,'unscored_questions':unscored,'details':a['details']})
    return {'evaluator_version':'rag-eval-v4.2.2','benchmark_dataset':'quick-sanity' if len(questions)<20 else 'reviewed-benchmark','retrieval_strategy':'adaptive-v4.1','top_k':int(cfg.get('final_k',top_k)),'questions':len(questions),'scored_questions':scored,'unscored_questions':unscored,'behavior_tests':behavior_tests,'behavior_passed':behavior_passed,'offline':True,'settings':cfg,'small_dataset_warning':len(questions)<20,'metrics':metrics}

def generate_benchmark(records,count=100,seed=42):
    """Build a reproducible corpus-derived retrieval benchmark without LLM calls.
    Each item is grounded in a real indexed judgment and marked auto_generated for human review.
    """
    bydoc={}
    for rec in records:
        key=_doc_key(rec); text=(rec.get('raw_text') or rec.get('text') or '').strip()
        if len(text)<220: continue
        if key not in bydoc or len(text)>len(bydoc[key].get('_text','')): bydoc[key]={**rec,'_text':text}
    docs=list(bydoc.values()); rnd=random.Random(seed); rnd.shuffle(docs); items=[]
    legal_terms=re.compile(r'\b(section|article|act|court|appeal|notice|cheque|accused|petitioner|respondent|evidence|conviction|liability|jurisdiction|agreement|arbitration|bail|writ|sentence|offence)\b',re.I)
    for rec in docs:
        text=re.sub(r'\s+',' ',rec['_text']); sents=re.split(r'(?<=[.!?])\s+',text)
        cand=[s.strip() for s in sents if 90<=len(s)<=360 and legal_terms.search(s) and not re.search(r'https?://|indian kanoon',s,re.I)]
        if not cand: continue
        sent=max(cand,key=lambda s:min(len(s),220)); case=rec.get('case_name') or rec.get('source_file') or 'the indexed judgment'
        # Remove obvious case-name leakage and turn the source sentence into a retrieval-style question.
        cleaned=sent
        for token in [rec.get('case_name',''),rec.get('source_file','')]:
            if token: cleaned=re.sub(re.escape(token), 'the case', cleaned, flags=re.I)
        cleaned=cleaned[:300].rstrip(' .;:')
        q=f"Which judgment in the indexed corpus discusses the following legal proposition or fact pattern: {cleaned}?"
        category='statutory' if re.search(r'\b(section|article|act)\b',sent,re.I) else ('lexical' if len(re.findall(r'\b[A-Z][A-Za-z]+\b',sent))>5 else 'semantic')
        difficulty='easy' if category=='lexical' else ('medium' if len(sent)<220 else 'hard')
        items.append({'id':f'LEX-{len(items)+1:03d}','query':q,'relevant_files':[rec.get('source_file','')],'relevant_cases':[case] if rec.get('case_name') else [],'relevance':[{'judgment':rec.get('source_file') or case,'grade':3}],'category':category,'difficulty':difficulty,'question_type':'corpus-derived proposition','auto_generated':True,'needs_human_review':True,'source_excerpt':sent[:500]})
        if len(items)>=count: break
    return {'benchmark_version':'lexical-v3','dataset_type':'lexical','questions':items,'requested':count,'generated':len(items),'seed':seed,'offline':True,'note':'Auto-generated from indexed judgment passages. Review labels/questions before using results in a formal report.'}


def generate_realistic_benchmark(records,count=100,seed=84):
    """Create a balanced, deterministic, LLM-free realistic-query benchmark.

    Ground truth always remains the exact source judgment. Query rewrites deliberately
    remove boilerplate and surface details to reduce verbatim source leakage.
    Items remain marked for human review; this is an evaluation fixture, not expert annotation.
    """
    base=generate_benchmark(records,count=min(max(count*3,150),300),seed=seed).get('questions',[])
    buckets={'lexical':[],'semantic':[],'advocate':[],'hard_paraphrase':[]}
    def compact(t):
        t=re.sub(r'\b(?:learned|hon.?ble|supreme court reports|appellant|respondent|petitioner|accused)\b',' ',t,flags=re.I)
        t=re.sub(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b',' ',t)
        t=re.sub(r'\bRs\.?\s*[\d,./-]+','the disputed amount',t,flags=re.I)
        t=re.sub(r'\s+',' ',t).strip(' .;:-')
        return t
    for i,x in enumerate(base):
        excerpt=compact(x.get('source_excerpt',''))
        if len(excerpt)<45: continue
        statutory=bool(re.search(r'\b(section|article|rule|act|code)\b',excerpt,re.I))
        # Four intentionally different user formulations from the same canonical authority.
        variants=[
          ('lexical', f"Which judgment discusses {excerpt[:250]}?", 'easy'),
          ('semantic', f"Which authority addresses the legal issue or principle concerning {excerpt[:220]}?", 'medium'),
          ('advocate', f"Which precedent can I rely on when arguing a matter involving {excerpt[:205]}?", 'medium'),
          ('hard_paraphrase', f"Find the most relevant authority for a dispute where the core issue is {excerpt[:185]}.", 'hard')
        ]
        # Statutory items get a more natural legal-research formulation.
        if statutory:
            m=re.search(r'\b(?:section|article|rule)\s+[A-Za-z0-9()/-]+(?:\s+of\s+the\s+[^,.;]{3,80})?',excerpt,re.I)
            if m: variants[0]=('lexical',f"Which judgment explains or applies {m.group(0)}?",'easy')
        for typ,q,diff in variants:
            if len(buckets[typ])>=25: continue
            y=dict(x); y.update({'id':f'REAL-{typ[:3].upper()}-{len(buckets[typ])+1:03d}','query':q,'category':typ,'query_type':typ,'difficulty':diff,'benchmark_dataset':'realistic-v4','auto_generated':True,'needs_human_review':True})
            buckets[typ].append(y)
        if all(len(v)>=25 for v in buckets.values()): break
    items=[]
    for typ in ('lexical','semantic','advocate','hard_paraphrase'): items.extend(buckets[typ][:25])
    items=items[:count]
    return {'benchmark_version':'realistic-v4','dataset_type':'realistic','questions':items,'requested':count,'generated':len(items),'seed':seed,'offline':True,'category_counts':{k:len(v[:25]) for k,v in buckets.items()},'note':'Balanced LLM-free realistic-query benchmark. Canonical source labels are preserved; review questions before formal academic reporting.'}
