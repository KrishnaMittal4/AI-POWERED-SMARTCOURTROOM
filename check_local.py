import importlib.util, os, sys
from pathlib import Path
root=Path(__file__).resolve().parent
print('LEXAI local preflight')
print('Python:', sys.version.split()[0])
required=['fastapi','uvicorn','dotenv','numpy','faiss','sentence_transformers','groq']
missing=[m for m in required if importlib.util.find_spec(m) is None]
if missing:
    print('MISSING PYTHON PACKAGES:', ', '.join(missing))
    print('Run: python -m pip install -r requirements.txt')
    raise SystemExit(2)
print('Python dependencies: OK')
for key in ['GROQ_API_KEY','GEMINI_API_KEY']:
    print(f'{key}:', 'configured' if os.getenv(key) else 'not configured')
corpus_dirs=[root/'judgments',root/'corpus',root/'data'/'judgments']
index_dirs=list(root.glob('index_store*'))+[root/'faiss_index']
print('Local judgment corpus:', 'found' if any(p.exists() for p in corpus_dirs) else 'not bundled (restore your research corpus if you need Global RAG locally)')
print('Local research index:', 'found' if any(p.exists() for p in index_dirs) else 'not bundled (build/restore index for Global RAG)')
print('Preflight OK')
