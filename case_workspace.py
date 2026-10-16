"""Per-user case workspaces with local or Supabase persistence."""
import os, sqlite3, threading, time, uuid
from pathlib import Path
from fastapi import HTTPException, UploadFile
import supabase_repository as sb

DATA_ROOT = Path(os.getenv('LEXAI_DATA_ROOT', '.'))
DB_PATH = Path(os.getenv('CASE_DB_PATH', str(DATA_ROOT / 'cases.db')))
FILES_ROOT = Path(os.getenv('CASE_FILES_DIR', str(DATA_ROOT / 'user_case_files')))
_lock = threading.Lock()

def _remote(): return sb.enabled()

def init_case_db():
    if _remote():
        if not sb.configured(): raise RuntimeError('LEXAI_STORAGE_BACKEND=supabase but Supabase server credentials are missing.')
        return
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    with _lock, sqlite3.connect(DB_PATH) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS case_documents (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, user_id INTEGER NOT NULL, original_name TEXT NOT NULL, stored_name TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at INTEGER NOT NULL)'''); db.commit()

def _row_case(row): return {'id':row[0],'title':row[1],'description':row[2],'created_at':row[3],'updated_at':row[4]}

def _ts(v):
    if isinstance(v,(int,float)): return int(v)
    if not v:return int(time.time())
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(v).replace('Z','+00:00')).timestamp())
    except Exception:return int(time.time())

def assert_case(user_id, case_id):
    if _remote():
        uid=sb.user_uuid(user_id); rows=sb.select('cases',{'id':case_id,'user_id':uid},limit=1)
        if not rows: raise HTTPException(404,'Case not found.')
        r=rows[0]; return {'id':r['id'],'title':r['title'],'description':r.get('description') or '','created_at':_ts(r.get('created_at')),'updated_at':_ts(r.get('updated_at'))}
    with sqlite3.connect(DB_PATH) as db: row=db.execute('SELECT id,title,description,created_at,updated_at FROM cases WHERE id=? AND user_id=?',(case_id,user_id)).fetchone()
    if not row: raise HTTPException(404,'Case not found.')
    return _row_case(row)

def list_cases(user_id):
    if _remote():
        uid=sb.user_uuid(user_id); rows=sb.select('cases',{'user_id':uid},order='updated_at.desc')
        docs=sb.select('documents',{'user_id':uid},columns='id,case_id')
        counts={}
        for d in docs: counts[d['case_id']]=counts.get(d['case_id'],0)+1
        return [{'id':r['id'],'title':r['title'],'description':r.get('description') or '','created_at':_ts(r.get('created_at')),'updated_at':_ts(r.get('updated_at')),'document_count':counts.get(r['id'],0)} for r in rows]
    with sqlite3.connect(DB_PATH) as db:
        rows=db.execute('''SELECT c.id,c.title,c.description,c.created_at,c.updated_at,(SELECT COUNT(*) FROM case_documents d WHERE d.case_id=c.id AND d.user_id=c.user_id) FROM cases c WHERE c.user_id=? ORDER BY c.updated_at DESC''',(user_id,)).fetchall()
    return [{**_row_case(r[:5]),'document_count':r[5]} for r in rows]

def create_case(user_id, title, description=''):
    if _remote():
        uid=sb.user_uuid(user_id); cid=str(uuid.uuid4())
        r=sb.insert('cases',{'id':cid,'user_id':uid,'title':title.strip(),'description':description.strip()})[0]
        return {'id':r['id'],'title':r['title'],'description':r.get('description') or '','created_at':_ts(r.get('created_at')),'updated_at':_ts(r.get('updated_at')),'document_count':0}
    now,cid=int(time.time()),uuid.uuid4().hex
    with _lock,sqlite3.connect(DB_PATH) as db: db.execute('INSERT INTO cases(id,user_id,title,description,created_at,updated_at) VALUES(?,?,?,?,?,?)',(cid,user_id,title.strip(),description.strip(),now,now));db.commit()
    (FILES_ROOT/str(user_id)/cid).mkdir(parents=True,exist_ok=True); return {**assert_case(user_id,cid),'document_count':0}

def delete_case(user_id, case_id):
    assert_case(user_id,case_id)
    if _remote():
        uid=sb.user_uuid(user_id); docs=sb.select('documents',{'case_id':case_id,'user_id':uid},columns='id,storage_path')
        sb.delete_objects([d['storage_path'] for d in docs if d.get('storage_path')])
        try: sb.cache_delete_case(user_id,case_id)
        except Exception: pass
        sb.delete('cases',{'id':case_id,'user_id':uid})
    else:
        with _lock,sqlite3.connect(DB_PATH) as db:
            rows=db.execute('SELECT stored_name FROM case_documents WHERE case_id=? AND user_id=?',(case_id,user_id)).fetchall(); db.execute('DELETE FROM case_documents WHERE case_id=? AND user_id=?',(case_id,user_id));
            try:db.execute('DELETE FROM case_notes WHERE case_id=? AND user_id=?',(case_id,user_id))
            except sqlite3.OperationalError:pass
            db.execute('DELETE FROM cases WHERE id=? AND user_id=?',(case_id,user_id));db.commit()
        folder=FILES_ROOT/str(user_id)/case_id
        for (name,) in rows:
            try:(folder/name).unlink(missing_ok=True)
            except OSError:pass
        try:folder.rmdir()
        except OSError:pass
    try:
        from private_case_rag import invalidate_case_index; invalidate_case_index(user_id,case_id)
    except Exception:pass

def list_documents(user_id, case_id):
    assert_case(user_id,case_id)
    if _remote():
        uid=sb.user_uuid(user_id); rows=sb.select('documents',{'case_id':case_id,'user_id':uid},order='created_at.desc')
        return [{'id':r['id'],'name':r.get('original_filename') or r.get('filename'),'size_bytes':r.get('file_size') or 0,'created_at':_ts(r.get('created_at')),'document_type':r.get('document_type') or 'OTHER'} for r in rows]
    with sqlite3.connect(DB_PATH) as db: rows=db.execute('SELECT id,original_name,size_bytes,created_at FROM case_documents WHERE case_id=? AND user_id=? ORDER BY created_at DESC',(case_id,user_id)).fetchall()
    return [{'id':r[0],'name':r[1],'size_bytes':r[2],'created_at':r[3]} for r in rows]

async def save_documents(user_id, case_id, files, max_mb=30):
    assert_case(user_id,case_id); saved=[]
    folder=FILES_ROOT/str(user_id)/case_id
    if not _remote(): folder.mkdir(parents=True,exist_ok=True)
    for f in files:
        original=Path(f.filename or 'document.pdf').name
        if not original.lower().endswith('.pdf'):raise HTTPException(400,f'{original}: only PDF files are allowed.')
        if getattr(f,'content_type',None) and f.content_type not in {'application/pdf','application/octet-stream'}:raise HTTPException(400,f'{original}: browser reported an unsupported file type ({f.content_type}).')
        data=await f.read()
        if not data.startswith(b'%PDF'):raise HTTPException(400,f'{original}: file is not a valid PDF.')
        if len(data)>max_mb*1024*1024:raise HTTPException(413,f'{original}: exceeds {max_mb} MB.')
        now=int(time.time())
        if _remote():
            uid=sb.user_uuid(user_id); did=str(uuid.uuid4()); path=f'users/{uid}/cases/{case_id}/documents/{did}/{original}'
            sb.upload_object(path,data,'application/pdf')
            try:
                row=sb.insert('documents',{'id':did,'user_id':uid,'case_id':case_id,'filename':original,'original_filename':original,'storage_path':path,'mime_type':'application/pdf','file_size':len(data),'processing_status':'uploaded'})[0]
            except Exception:
                try:sb.delete_objects([path])
                except Exception:pass
                raise
            sb.update('cases',{'id':case_id,'user_id':uid},{'updated_at':'now()'}) if False else None
            saved.append({'id':did,'name':original,'size_bytes':len(data),'created_at':_ts(row.get('created_at'))})
        else:
            did=uuid.uuid4().hex;stored=f'{did}.pdf';(folder/stored).write_bytes(data)
            with _lock,sqlite3.connect(DB_PATH) as db:
                db.execute('INSERT INTO case_documents(id,case_id,user_id,original_name,stored_name,size_bytes,created_at) VALUES(?,?,?,?,?,?,?)',(did,case_id,user_id,original,stored,len(data),now));db.execute('UPDATE cases SET updated_at=? WHERE id=? AND user_id=?',(now,case_id,user_id));db.commit()
            saved.append({'id':did,'name':original,'size_bytes':len(data),'created_at':now})
    try:
        from private_case_rag import invalidate_case_index;invalidate_case_index(user_id,case_id)
    except Exception:pass
    return saved

def get_document_path(user_id,case_id,document_id):
    assert_case(user_id,case_id)
    if _remote():
        uid=sb.user_uuid(user_id);rows=sb.select('documents',{'id':document_id,'case_id':case_id,'user_id':uid},limit=1)
        if not rows:raise HTTPException(404,'Document not found.')
        r=rows[0]; return sb.materialize_object(r['storage_path']), r.get('original_filename') or r.get('filename')
    with sqlite3.connect(DB_PATH) as db:row=db.execute('SELECT original_name,stored_name FROM case_documents WHERE id=? AND case_id=? AND user_id=?',(document_id,case_id,user_id)).fetchone()
    if not row:raise HTTPException(404,'Document not found.')
    path=FILES_ROOT/str(user_id)/case_id/row[1]
    if not path.exists():raise HTTPException(404,'Document file is missing.')
    return path,row[0]

def delete_document(user_id,case_id,document_id):
    assert_case(user_id,case_id)
    if _remote():
        uid=sb.user_uuid(user_id);rows=sb.select('documents',{'id':document_id,'case_id':case_id,'user_id':uid},limit=1)
        if not rows:raise HTTPException(404,'Document not found.')
        if rows[0].get('storage_path'):sb.delete_objects([rows[0]['storage_path']])
        sb.delete('documents',{'id':document_id,'case_id':case_id,'user_id':uid})
    else:
        with _lock,sqlite3.connect(DB_PATH) as db:
            row=db.execute('SELECT stored_name FROM case_documents WHERE id=? AND case_id=? AND user_id=?',(document_id,case_id,user_id)).fetchone()
            if not row:raise HTTPException(404,'Document not found.')
            db.execute('DELETE FROM case_documents WHERE id=? AND case_id=? AND user_id=?',(document_id,case_id,user_id));db.commit()
        try:(FILES_ROOT/str(user_id)/case_id/row[0]).unlink(missing_ok=True)
        except OSError:pass
    try:
        from private_case_rag import invalidate_case_index;invalidate_case_index(user_id,case_id)
    except Exception:pass
