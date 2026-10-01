param([switch]$SelfTest)

$ErrorActionPreference = 'Stop'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  throw 'Activate a Python virtual environment, or install Python and reopen PowerShell.'
}

& $python.Source -m pip install -r requirements.txt
if ($SelfTest) {
  & $python.Source gold_workbench.py --self-test
} else {
  & $python.Source gold_workbench.py
}
