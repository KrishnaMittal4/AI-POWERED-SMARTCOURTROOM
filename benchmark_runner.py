"""Background, cancellable offline RAG benchmark runner for LEXAI."""
from __future__ import annotations
import hashlib, json, threading, time, uuid
from rag_evaluation import evaluate

_jobs = {}
_cache = {}
EVALUATOR_VERSION = "rag-eval-v4.2.2.1"
_lock = threading.RLock()


def _key(question, settings, top_k):
    payload={"version":EVALUATOR_VERSION,"q":question,"settings":settings or {},"top_k":top_k}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()


def _public(job):
    now=time.time(); elapsed=max(0.0,(job.get("finished_at") or now)-job["started_at"])
    done=job["completed"]; total=job["total"]
    eta=(elapsed/done*(total-done)) if done and job["status"]=="running" else 0.0
    return {k:v for k,v in job.items() if k not in {"owner","questions","settings","cancel_event","partials"}} | {
        "elapsed_seconds":round(elapsed,1),"eta_seconds":round(eta,1),"percent":round((done/total*100) if total else 0,1)
    }


def start(owner, questions, index, records, model, reranker, top_k, settings):
    jid=uuid.uuid4().hex
    job={"job_id":jid,"owner":str(owner),"status":"queued","completed":0,"total":len(questions),"current_question":0,
         "current_stage":"Queued","started_at":time.time(),"finished_at":None,"cache_hits":0,"error":None,"result":None,
         "questions":questions,"settings":settings or {},"top_k":top_k,"cancel_event":threading.Event(),"partials":[]}
    with _lock:_jobs[jid]=job
    threading.Thread(target=_run,args=(job,index,records,model,reranker),daemon=True).start()
    return _public(job)


def _run(job,index,records,model,reranker):
    try:
        job["status"]="running"
        for i,q in enumerate(job["questions"]):
            if job["cancel_event"].is_set():
                job["status"]="cancelled"; job["current_stage"]="Cancelled"; break
            job["current_question"]=i+1; job["current_stage"]="FAISS + BM25 + RRF + Cross-Encoder" if job["settings"].get("rerank",True) else "FAISS + BM25 + RRF"
            ck=_key(q,job["settings"],job["top_k"])
            with _lock: one=_cache.get(ck)
            if one is None:
                one=evaluate([q],index,records,model,reranker,job["top_k"],job["settings"]); one["_question"]=q
                with _lock:_cache[ck]=one
            else: job["cache_hits"]+=1
            job["partials"].append(one); job["completed"]=i+1
        if job["status"]=="cancelled":
            job["finished_at"]=time.time(); return
        job["current_stage"]="Calculating metrics"
        job["result"]=_aggregate(job["partials"],job["top_k"],job["settings"])
        job["status"]="completed"; job["current_stage"]="Complete"; job["finished_at"]=time.time()
    except Exception as e:
        job["status"]="failed"; job["error"]=f"{type(e).__name__}: {e}"; job["current_stage"]="Failed"; job["finished_at"]=time.time()


def _aggregate(parts,top_k,settings):
    if not parts:
        return {"evaluator_version": EVALUATOR_VERSION, "top_k": top_k, "questions": 0, "scored_questions": 0, "unscored_questions": 0, "offline": True, "settings": settings, "metrics": []}

    names=[m["name"] for m in parts[0]["metrics"]]
    metrics=[]
    for name in names:
        rows=[next(m for m in p["metrics"] if m["name"]==name) for p in parts]
        details=[r["details"][0] for r in rows]
        scored_rows=[(r,d) for r,d in zip(rows,details) if d.get("scorable", True)]
        denom=len(scored_rows)
        def avg_metric(key):
            if not denom: return 0.0
            vals=[]
            for r,_ in scored_rows:
                v=r.get(key)
                if isinstance(v,(int,float)): vals.append(v)
            return round(sum(vals)/denom,3) if vals else 0.0
        lat=[r.get("avg_latency_ms") for r in rows if isinstance(r.get("avg_latency_ms"),(int,float))]
        metrics.append({
            "name":name,
            "hit_at_1":avg_metric("hit_at_1"),
            "hit_at_k":avg_metric("hit_at_k"),
            "recall_at_k":avg_metric("recall_at_k"),
            "precision_at_k":avg_metric("precision_at_k"),
            "mrr":avg_metric("mrr"),
            "ndcg_at_k":avg_metric("ndcg_at_k"),
            "avg_latency_ms":round(sum(lat)/len(lat),1) if lat else 0,
            "questions":len(rows),
            "scored_questions":denom,
            "unscored_questions":len(rows)-denom,
            "details":details,
        })

    qs=[p.get("_question",{}) for p in parts]
    categories={}
    for qi,q in enumerate(qs):
        cat=q.get("query_type") or q.get("category") or "uncategorized"
        categories.setdefault(cat,[]).append(qi)
    category_metrics={}
    for cat,idxs in categories.items():
        category_metrics[cat]=[]
        for m in metrics:
            ds=[m["details"][i] for i in idxs if i < len(m["details"])]
            scored_ds=[d for d in ds if d.get("scorable", True)]
            n=len(scored_ds)
            hit1=sum(1 for d in scored_ds if d.get("first_relevant_rank")==1)
            hits=sum(1 for d in scored_ds if d.get("hit") is True)
            rr=sum((1/d["first_relevant_rank"] if isinstance(d.get("first_relevant_rank"),(int,float)) and d["first_relevant_rank"]>0 else 0) for d in scored_ds)
            ndcg_vals=[d.get("ndcg") for d in scored_ds if isinstance(d.get("ndcg"),(int,float))]
            category_metrics[cat].append({
                "name":m["name"],"questions":len(ds),"scored_questions":n,"unscored_questions":len(ds)-n,
                "hit_at_1":round(hit1/n,3) if n else 0,
                "hit_at_k":round(hits/n,3) if n else 0,
                "mrr":round(rr/n,3) if n else 0,
                "ndcg_at_k":round(sum(ndcg_vals)/n,3) if n else 0,
            })

    dataset=(qs[0].get("benchmark_dataset") if qs else None) or ("realistic-v4" if any((q.get("query_type") or q.get("category")) in {"lexical","semantic","advocate","hard_paraphrase"} for q in qs) else "custom")
    adaptive=next((m for m in metrics if m["name"]=="Adaptive Full RAG V4.1"),None)
    failure_summary={}
    behavior_tests=0; behavior_passed=0
    if adaptive:
        for d in adaptive.get("details",[]):
            ft=d.get("failure_type","none"); failure_summary[ft]=failure_summary.get(ft,0)+1
            if d.get("expected_behavior"):
                behavior_tests+=1
                behavior_passed+=int(d.get("behavior_pass") is True)
    scored_questions=adaptive.get("scored_questions",0) if adaptive else 0
    return {
        "evaluator_version":EVALUATOR_VERSION,"benchmark_dataset":dataset,"retrieval_strategy":"adaptive-v4.1",
        "top_k":top_k,"questions":len(parts),"scored_questions":scored_questions,"unscored_questions":len(parts)-scored_questions,
        "behavior_tests":behavior_tests,"behavior_passed":behavior_passed,"offline":True,"settings":settings,
        "small_dataset_warning":len(parts)<20,"metrics":metrics,"category_metrics":category_metrics,"failure_summary":failure_summary
    }


def get(owner,jid):
    with _lock: job=_jobs.get(jid)
    if not job or job["owner"]!=str(owner): return None
    return _public(job)


def cancel(owner,jid):
    with _lock: job=_jobs.get(jid)
    if not job or job["owner"]!=str(owner): return None
    if job["status"] in {"queued","running"}: job["cancel_event"].set(); job["current_stage"]="Cancelling…"
    return _public(job)


def result(owner,jid):
    with _lock: job=_jobs.get(jid)
    if not job or job["owner"]!=str(owner): return None
    return job.get("result")
