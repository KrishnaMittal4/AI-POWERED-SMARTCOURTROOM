@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  py -3.10 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
if not exist ".env" (
  copy /Y ".env.development.example" ".env" >nul
  echo Created .env from .env.development.example. Add your Groq/Gemini keys, then rerun.
  exit /b 1
)
set LEXAI_ENV=development
set LEXAI_STORAGE_BACKEND=local
set LEXAI_RENDER_FREE_MODE=false
set LEXAI_LOW_MEMORY_MODE=false
set GLOBAL_JUDGMENT_CORPUS_ENABLED=true
set ENABLE_DEVELOPER_TOOLS=true
".venv\Scripts\python.exe" check_local.py || exit /b 1
echo Starting LEXAI backend at http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
