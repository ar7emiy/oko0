$ErrorActionPreference = 'Stop'

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
  throw 'Python was installed. Close and reopen PowerShell, then run this script again.'
}

py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --onefile --name GoldDatasetWorkbench gold_workbench.py

Write-Host 'Built dist\GoldDatasetWorkbench.exe. It runs locally and does not start a server.'
