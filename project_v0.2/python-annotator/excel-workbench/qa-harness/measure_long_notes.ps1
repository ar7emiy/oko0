# Times the real reviewer path on progressively longer notes, in real Excel.
# Drives the harness-built .xlsm (shipping modules + the MsgBox shadow) through
# Application.Run only, so it needs no VBA-project access setting.
# Path per size: clipboard -> Paste whole note -> open -> page turn ->
# Attest & Save of evidence placed near the END of the note (worst case for
# the per-save character walk).
param(
  [int[]]$Sizes = @(100000, 500000, 1000000),
  [string]$Source = "$env:TEMP\qa-workbench\QA-Annotation.xlsm"
)
$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP "qa-perf"
New-Item -ItemType Directory -Force $work | Out-Null
$book = Join-Path $work "perf.xlsm"
Copy-Item $Source $book -Force

Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.AutomationSecurity = 1
$sw = [Diagnostics.Stopwatch]::new()
function Time([scriptblock]$b) { $sw.Restart(); & $b | Out-Null; $sw.Stop(); [math]::Round($sw.Elapsed.TotalSeconds, 2) }

$rows = @()
try {
  $wb = $xl.Workbooks.Open($book)
  $notes = $wb.Worksheets.Item("Notes"); $desk = $wb.Worksheets.Item("Review Desk")
  foreach ($n in $Sizes) {
    $tag = "ZZEVIDENCEZZ"
    # Random words, not one repeated character: a repeated character zips to
    # almost nothing and hides the real file-size and save cost. Random words
    # compress worse than English prose, so these numbers err pessimistic.
    $rng = [Random]::new($n); $sb = [Text.StringBuilder]::new($n + 64)
    [void]$sb.Append("FIRST-")
    $target = $n - $tag.Length - 12
    while ($sb.Length -lt $target) {
      $w = $rng.Next(2, 10)
      for ($k = 0; $k -lt $w; $k++) { [void]$sb.Append([char](97 + $rng.Next(26))) }
      $r = $rng.Next(40)
      if ($r -eq 0) { [void]$sb.Append(". ") } elseif ($r -eq 1) { [void]$sb.Append(", ") } elseif ($r -eq 2) { [void]$sb.Append("`r`n") } else { [void]$sb.Append(" ") }
    }
    $sb.Length = $target
    $body = $sb.ToString() + " " + $tag + " -LAST"
    Set-Clipboard -Value $body
    $notes.Range("C4").Value2 = "PERF"; $notes.Range("C5").Value2 = "N$n"; $notes.Range("C6").Value2 = "1"

    $paste = Time { $xl.Run("PasteWholeNote") }
    $srcId = $xl.Run("State", "source")
    $open  = Time { $xl.Run("OpenSource", $srcId) }
    $page  = Time { $xl.Run("NextTextPage") }

    $desk.Range("C7").Value2 = "Perf Reviewer"
    $desk.Range("C9").Value2 = "entity";  $desk.Range("C10").Value2 = $tag
    $desk.Range("C11").Value2 = "1";      $desk.Range("C13").Value2 = $tag
    $desk.Range("C14").Value2 = "organization"
    $save  = Time { $xl.Run("AttestSave") }
    $saved = $desk.Range("C22").Value2

    $wb.Save()
    $rows += [pscustomobject]@{
      note_units = $body.Length; pages = [math]::Ceiling($body.Length / 3520); paste_s = $paste; open_s = $open; page_turn_s = $page; attest_save_s = $save
      workbook_MB = [math]::Round((Get-Item $book).Length / 1MB, 2); save_result = "$saved"
    }
  }
  $wb.Close($false)
} catch { "FAILED at size ${n}: " + $_.Exception.Message }
finally { $xl.Quit() }
$rows | Format-Table -AutoSize | Out-String -Width 220