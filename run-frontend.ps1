$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "frontend")
if (-not (Test-Path ".env")) { Copy-Item ".env.development.example" ".env" }
if (-not (Test-Path "node_modules")) { npm install }
Write-Host "Starting LEXAI frontend at http://localhost:5173" -ForegroundColor Green
npm run dev
