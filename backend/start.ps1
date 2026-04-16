$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

if (-not (Test-Path '.venv')) {
    py -3 -m venv .venv
}

$activate = Join-Path $PSScriptRoot '.venv\Scripts\Activate.ps1'
. $activate

python -m pip install --upgrade pip
pip install -r requirements.txt
exec python -m uvicorn app:app --host 0.0.0.0 --port 8000
