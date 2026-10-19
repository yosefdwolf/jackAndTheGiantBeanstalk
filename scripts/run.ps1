# Windows (PowerShell):  .\scripts\run.ps1          (real OpenAI calls, key from .env)
#                        .\scripts\run.ps1 -Mock    (free, placeholder images)
# If scripts are blocked: Set-ExecutionPolicy -Scope Process Bypass
param([switch]$Mock)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path .venv)) { py -3.12 -m venv .venv; if ($LASTEXITCODE) { python -m venv .venv } }
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if ($Mock) { $env:MOCK = "1" }
# --host 0.0.0.0 so a phone on the same Wi-Fi can open http://<this-computer's-IP>:8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
