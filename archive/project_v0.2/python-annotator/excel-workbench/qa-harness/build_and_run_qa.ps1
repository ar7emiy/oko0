# Builds a disposable .xlsm from the shipping template plus the shipping .bas
# modules, adds the QA harness, and runs the end-to-end driver in real Excel.
# The shipping modules are imported byte-for-byte unmodified.
param(
  [string]$Root = "C:\Users\yalov\oko0\project_v0.2\python-annotator\excel-workbench"
)
$ErrorActionPreference = 'Stop'

$work = Join-Path $env:TEMP "qa-workbench"
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $work | Out-Null
$template = Join-Path $work "template.xlsx"
$xlsm     = Join-Path $work "QA-Annotation.xlsm"
Copy-Item (Join-Path $Root "Entity-Gold-Review-Macro-Free.xlsx") $template

Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.EnableEvents = $false
$xl.AutomationSecurity = 1

try {
  $wb = $xl.Workbooks.Open($template)

  foreach ($f in Get-ChildItem (Join-Path $Root "*.bas")) {
    $wb.VBProject.VBComponents.Import($f.FullName) | Out-Null
  }
  foreach ($f in Get-ChildItem (Join-Path $Root "qa-harness\*.bas")) {
    $wb.VBProject.VBComponents.Import($f.FullName) | Out-Null
  }
  $twCode = Get-Content (Join-Path $Root "ThisWorkbook.txt") -Raw
  $wb.VBProject.VBComponents.Item("ThisWorkbook").CodeModule.AddFromString($twCode)

  $wb.SaveAs($xlsm, 52)
  $names = ($wb.VBProject.VBComponents | ForEach-Object { $_.Name }) -join ', '
  "components: $names"

  try {
    $xl.Run("QARunAll")
    "QARunAll returned normally"
  } catch {
    "QARunAll THREW: " + $_.Exception.Message
  }

  $wb.Save()
  $xl.EnableEvents = $false
  $wb.Close($false)
} catch {
  "BUILD FAILED: " + $_.Exception.Message
} finally {
  $xl.Quit()
}

"----- qa-results.txt -----"
$log = Join-Path $work "qa-results.txt"
if (Test-Path $log) { Get-Content $log } else { "NO LOG PRODUCED" }
