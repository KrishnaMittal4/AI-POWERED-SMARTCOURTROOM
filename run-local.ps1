$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Creating Python virtual environment..."
  py -3.10 -m venv .venv 2>$null
  if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path ".env")) {
  Copy-Item ".env.development.example" ".env"
  Write-Host "Created .env from .env.development.example. Add your Groq/Gemini keys, then rerun." -ForegroundColor Yellow
  exit 1
}
$env:LEXAI_ENV="development"
$env:LEXAI_STORAGE_BACKEND="local"
$env:LEXAI_RENDER_FREE_MODE="false"
$env:LEXAI_LOW_MEMORY_MODE="false"
$env:GLOBAL_JUDGMENT_CORPUS_ENABLED="true"
$env:ENABLE_DEVELOPER_TOOLS="true"
& $py check_local.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Starting LEXAI backend at http://127.0.0.1:8000" -ForegroundColor Green
& $py -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
