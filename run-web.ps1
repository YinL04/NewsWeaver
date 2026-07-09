$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = "python"
if (Test-Path ".venv\Scripts\python.exe") {
  $python = ".venv\Scripts\python.exe"
}

$env:PYTHONPATH = Join-Path $PSScriptRoot "src"

Write-Host "Starting NewsWeaver Web Workbench..."
Write-Host "Open http://127.0.0.1:8765 if the browser does not open automatically."

& $python -m newsweaver.cli web @args
