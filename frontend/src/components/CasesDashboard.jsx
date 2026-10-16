import {useMemo,useState} from 'react'

function fmt(ts){if(!ts)return 'Recently';const d=Math.max(0,Date.now()/1000-ts);if(d<3600)return `${Math.max(1,Math.floor(d/60))}m ago`;if(d<86400)return `${Math.floor(d/3600)}h ago`;return `${Math.floor(d/86400)}d ago`}

export default function CasesDashboard({cases,onOpen,onCreate,onDelete}){
  const [query,setQuery]=useState(''),[menu,setMenu]=useState(null),[danger,setDanger]=useState(null),[confirm,setConfirm]=useState('')
  const shown=useMemo(()=>cases.filter(c=>!query.trim()||`${c.title} ${c.description}`.toLowerCase().includes(query.toLowerCase())),[cases,query])
  const doDelete=async()=>{if(!danger||confirm!=='DELETE')return;await onDelete?.(danger.id);setDanger(null);setConfirm('');setMenu(null)}
  return <section className="cases-dashboard page-enter">
    <div className="cases-dashboard-head"><div><span className="eyebrow">PRIVATE MATTERS</span><h1>My Cases</h1><p>Secure workspaces for evidence, research and case intelligence.</p></div><button className="btn-primary" onClick={onCreate}>＋ New Case</button></div>
    <div className="cases-toolbar"><div className="case-search"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search cases…"/></div><span className="muted">{cases.length} matter{cases.length===1?'':'s'}</span></div>
    <div className="case-card-grid">{shown.length?shown.map(c=><article className="case-card-v3" key={c.id}>
      <div className="case-card-top"><span className="case-card-icon">⚖</span><div className="case-kebab-wrap"><button className="icon-btn case-kebab" aria-label={`Actions for ${c.title}`} onClick={()=>setMenu(menu===c.id?null:c.id)}>⋮</button>{menu===c.id&&<div className="case-menu"><button onClick={()=>onOpen(c.id)}>Open workspace</button><button className="danger-text" onClick={()=>{setDanger(c);setConfirm('')}}>Delete case</button></div>}</div></div>
      <button className="case-card-main" onClick={()=>onOpen(c.id)}><h3>{c.title}</h3><p>{c.description||'Private legal workspace'}</p></button>
      <div className="case-card-meta"><span>📄 {c.document_count||0} documents</span><span>Updated {fmt(c.updated_at)}</span></div>
      <div className="case-card-foot"><span className="status-pill private">Private</span><button className="case-open" onClick={()=>onOpen(c.id)}>Open workspace <span>→</span></button></div>
    </article>):<div className="empty-cases"><div className="empty-icon">⚖</div><h3>{cases.length?'No matching cases':'No private cases yet'}</h3><p>{cases.length?'Try another search.':'Create your first matter, add private PDFs, then analyze it once to build reusable case intelligence.'}</p>{!cases.length&&<button className="btn-primary" onClick={onCreate}>Create first case</button>}</div>}</div>
    {danger&&<div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)setDanger(null)}}><div className="danger-modal page-enter" role="dialog" aria-modal="true" aria-labelledby="delete-case-title"><div className="danger-symbol">!</div><h2 id="delete-case-title">Delete {danger.title}?</h2><p>This permanently deletes the workspace, private PDFs, private FAISS/BM25 index, saved Case Intelligence and research notes. This cannot be undone.</p><label>Type <b>DELETE</b> to confirm<input autoFocus value={confirm} onChange={e=>setConfirm(e.target.value)} placeholder="DELETE"/></label><div className="modal-actions"><button className="btn-quiet" onClick={()=>setDanger(null)}>Cancel</button><button className="btn-danger" disabled={confirm!=='DELETE'} onClick={doDelete}>Delete permanently</button></div></div></div>}
  </section>
}
