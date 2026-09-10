param(
    [string]$OutputPath = (Join-Path $PSScriptRoot "Entity-Gold-Review.xlsm")
)

$ErrorActionPreference = 'Stop'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

function Set-Cell {
    param($Sheet, [string]$Address, $Value, [int]$Color = 0, [bool]$Bold = $false, [int]$FontSize = 10)
    $cell = $Sheet.Range($Address)
    $cell.Value2 = $Value
    $cell.Font.Name = 'Segoe UI'
    $cell.Font.Size = $FontSize
    $cell.Font.Bold = $Bold
    if ($Color -ne 0) { $cell.Interior.Color = $Color }
    return $cell
}

function Add-Button {
    param($Sheet, [string]$Name, [string]$Caption, [string]$Macro, [double]$Left, [double]$Top, [double]$Width, [double]$Height, [int]$FillColor)
    $shape = $Sheet.Shapes.AddShape(5, $Left, $Top, $Width, $Height)
    $shape.Name = $Name
    $shape.Fill.ForeColor.RGB = $FillColor
    $shape.Line.ForeColor.RGB = 16777215
    $shape.TextFrame2.TextRange.Text = $Caption
    $shape.TextFrame2.TextRange.Font.Name = 'Segoe UI'
    $shape.TextFrame2.TextRange.Font.Size = 10
    $shape.TextFrame2.TextRange.Font.Bold = -1
    $shape.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = 16777215
    $shape.TextFrame2.VerticalAnchor = 3
    $shape.OnAction = $Macro
    return $shape
}

function Add-Validation {
    param($Range, [string]$List)
    $null = $Range.Validation.Delete()
    $null = $Range.Validation.Add(3, 1, 1, $List)
    $Range.Validation.IgnoreBlank = $true
    $Range.Validation.InCellDropdown = $true
}

try {
    if (Test-Path -LiteralPath $OutputPath) { Remove-Item -LiteralPath $OutputPath -Force }
    $workbook = $excel.Workbooks.Add()
    $desk = $workbook.Worksheets.Item(1)
    $desk.Name = 'Review Desk'
    while ($workbook.Worksheets.Count -gt 1) { $workbook.Worksheets.Item($workbook.Worksheets.Count).Delete() }

    $headers = @{
        'Entities' = @('entity_ref','claim_number','display_label','entity_type','first_note_id','first_source_text','decision')
        'Mentions' = @('mention_id','claim_number','note_id','source_text','start_character','end_character','entity_ref','mention_form','reason')
        'Fields' = @('field_id','claim_number','note_id','entity_ref','field_name','value','source_text','start_character','end_character','decision')
        'Context' = @('context_id','claim_number','note_id','entity_ref','source_characterization','start_character','end_character','optional_open_label','notes')
        'Statements' = @('statement_id','claim_number','note_id','predicate_source_text','start_character','end_character','primary_entity_ref','second_entity_ref','optional_open_label','notes')
        'Uncertain' = @('uncertain_id','claim_number','note_id','source_text','start_character','end_character','reason','candidate_entity_ref')
        'Watchlist Review' = @('pair_review_id','client_row_id','claim_number','note_id','identity_decision','source_support','reason','review_status')
        'Watchlist Candidates' = @('client_row_id','claim_number','note_id','system_entity_name','watchlist_entity_name','similarity_score')
        'Sealed Claims' = @('claim_number','sealed_at')
        'Raw Client Output' = @('Paste or import the client export with its original headers')
    }
    foreach ($name in $headers.Keys) {
        $sheet = $workbook.Worksheets.Add()
        $sheet.Name = $name
        $cols = $headers[$name].Count
        $sheet.Range($sheet.Cells(1,1), $sheet.Cells(1,$cols)).Value2 = (, $headers[$name])
        $sheet.Rows.Item(1).Font.Bold = $true
        $sheet.Rows.Item(1).Interior.Color = 3145735
        $sheet.Rows.Item(1).Font.Color = 16777215
        $sheet.Columns.AutoFit() | Out-Null
        $sheet.Visible = 2
    }

    # App canvas
    $navy = 5058560; $teal = 7500107; $yellow = 14408667; $mint = 15395562; $blue = 16764006; $purple = 14412123; $peach = 13224550; $orange = 11843839; $white = 16777215; $gray = 15132390
    $desk.Cells.Font.Name = 'Segoe UI'
    $desk.Cells.Font.Size = 10
    $desk.Columns('A').ColumnWidth = 2
    $desk.Columns('B').ColumnWidth = 19
    $desk.Columns('C').ColumnWidth = 20
    $desk.Columns('D:F').ColumnWidth = 12
    $desk.Columns('G').ColumnWidth = 3
    $desk.Columns('H').ColumnWidth = 16
    $desk.Columns('I').ColumnWidth = 3
    $desk.Columns('J').ColumnWidth = 16
    $desk.Columns('K').ColumnWidth = 24
    $desk.Columns('L').ColumnWidth = 16
    $desk.Columns('M').ColumnWidth = 10
    $desk.Columns('N').ColumnWidth = 2

    $desk.Range('B2:M2').Merge()
    $title = Set-Cell $desk 'B2' 'Gold Annotation Workbench' $navy $true 18
    $title.Font.Color = $white
    $title.HorizontalAlignment = -4108
    $desk.Rows.Item(2).RowHeight = 32
    $desk.Range('B3:M3').Merge()
    $desk.Range('B3').Value2 = 'Read the note in Notepad. Copy an exact phrase into the source box, choose one action, and Excel builds the traceable Gold records for you.'
    $desk.Range('B3').Font.Italic = $true
    $desk.Range('B3').Font.Color = 8421504
    $desk.Range('B3').WrapText = $true
    $desk.Rows.Item(3).RowHeight = 28

    $null = Set-Cell $desk 'B4' 'Claim number' 0 $true
    $null = Set-Cell $desk 'B5' 'Note ID' 0 $true
    $desk.Range('C4:F4').Merge(); $desk.Range('C5:F5').Merge()
    $desk.Range('C4:F5').Interior.Color = $yellow
    $desk.Range('C4:F5').Borders.LineStyle = 1

    $desk.Range('B7:F7').Merge()
    $selectedHeading = Set-Cell $desk 'B7' 'Paste exact source text from Notepad here' $navy $true 11
    $selectedHeading.Font.Color = $white
    $desk.Range('B8:F12').Merge()
    $desk.Range('B8').Interior.Color = $yellow
    $desk.Range('B8').WrapText = $true
    $desk.Range('B8').VerticalAlignment = -4160
    $desk.Range('B8').Borders.LineStyle = 1
    $desk.Rows('8:12').RowHeight = 24

    $desk.Range('B14:F14').Merge(); $h = Set-Cell $desk 'B14' 'Tell Excel what the selected wording means' $teal $true 11; $h.Font.Color = $white
    $null = Set-Cell $desk 'B15' 'Entity reference' 0 $true
    $null = Set-Cell $desk 'B16' 'Display name' 0 $true
    $null = Set-Cell $desk 'B17' 'Entity type' 0 $true
    $null = Set-Cell $desk 'B18' 'Reference form' 0 $true
    $null = Set-Cell $desk 'B19' 'Field kind / value' 0 $true
    $null = Set-Cell $desk 'B21' 'Second entity' 0 $true
    $null = Set-Cell $desk 'B22' 'Optional open label' 0 $true
    $null = Set-Cell $desk 'B23' 'Notes / reason' 0 $true
    foreach ($address in @('C15:F15','C16:F16','C17:F17','C18:F18','C19:F20','C21:F21','C22:F22','C23:F24')) {
        $desk.Range($address).Merge(); $desk.Range($address).Interior.Color = $yellow; $desk.Range($address).Borders.LineStyle = 1; $desk.Range($address).WrapText = $true
    }
    $desk.Rows('19:20').RowHeight = 22; $desk.Rows('23:24').RowHeight = 22
    Add-Validation $desk.Range('C17') 'person,organization,location,other,unknown'
    $desk.Range('C17').Value2 = 'person'
    Add-Validation $desk.Range('C18') 'name,alias,pronoun,description'
    Add-Validation $desk.Range('C19') 'entity_name,address,city,state,zip_code,phone,TIN,other'

    $desk.Range('H4:H4').Merge(); $cap = Set-Cell $desk 'H4' 'Choose an action' $navy $true 11; $cap.Font.Color = $white
    Add-Button $desk 'btnNewEntity' 'New entity' 'NewEntity' 485 95 120 30 $navy | Out-Null
    Add-Button $desk 'btnLinkReference' 'Link reference' 'LinkReference' 485 130 120 30 $mint | Out-Null
    Add-Button $desk 'btnField' 'Record field' 'RecordField' 485 165 120 30 $blue | Out-Null
    Add-Button $desk 'btnContext' 'Record context' 'RecordContext' 485 200 120 30 $purple | Out-Null
    Add-Button $desk 'btnStatement' 'Record statement' 'RecordStatement' 485 235 120 30 $peach | Out-Null
    Add-Button $desk 'btnUncertain' 'Mark uncertain' 'MarkUncertain' 485 270 120 30 $orange | Out-Null
    Add-Button $desk 'btnRefresh' 'Refresh entity list' 'RefreshDesk' 485 318 120 28 $teal | Out-Null
    Add-Button $desk 'btnSeal' 'Seal claim' 'SealClaim' 485 352 120 28 $navy | Out-Null

    $desk.Range('J4:M4').Merge(); $eh = Set-Cell $desk 'J4' 'Entities and evidence' $navy $true 11; $eh.Font.Color = $white
    $desk.Range('J6:M6').Interior.Color = $gray
    $desk.Range('J6:M6').Font.Bold = $true
    $desk.Range('J38:M38').Merge(); $desk.Range('J38').Interior.Color = $gray; $desk.Range('J38').Font.Bold = $true
    $desk.Range('J39:M55').Merge(); $desk.Range('J39').Interior.Color = 16448250; $desk.Range('J39').WrapText = $true; $desk.Range('J39').VerticalAlignment = -4160

    $desk.Range('B27:F27').Merge(); $wh = Set-Cell $desk 'B27' 'After Gold is sealed: review watchlist matches for this note' $navy $true 11; $wh.Font.Color = $white
    $null = Set-Cell $desk 'B28' 'Client row ID' 0 $true
    $null = Set-Cell $desk 'B29' 'Identity decision' 0 $true
    $null = Set-Cell $desk 'B30' 'Source support' 0 $true
    $null = Set-Cell $desk 'B31' 'Reason' 0 $true
    foreach ($address in @('C28:F28','C29:F29','C30:F30','C31:F33')) {
        $desk.Range($address).Merge(); $desk.Range($address).Interior.Color = $yellow; $desk.Range($address).Borders.LineStyle = 1; $desk.Range($address).WrapText = $true
    }
    Add-Validation $desk.Range('C29') 'same_entity,different_entity,insufficient_evidence'
    Add-Validation $desk.Range('C30') 'direct_note_support,partial_note_support,no_note_support,ambiguous_note_support'
    Add-Button $desk 'btnImportClient' 'Import client output' 'ImportClientOutput' 485 455 120 28 $teal | Out-Null
    Add-Button $desk 'btnLoadPairs' 'Load note matches' 'LoadWatchlistMatches' 485 489 120 28 $navy | Out-Null
    Add-Button $desk 'btnSavePair' 'Save decision' 'SaveWatchlistDecision' 485 523 120 28 $teal | Out-Null
    $desk.Range('J57:M57').Merge(); $desk.Range('J57').Value2 = 'Watchlist candidates for this note'; $desk.Range('J57').Interior.Color = $gray; $desk.Range('J57').Font.Bold = $true
    $desk.Range('J58:M58').Interior.Color = $gray; $desk.Range('J58:M58').Font.Bold = $true

    $desk.Range('B36:F36').Merge(); $desk.Range('B36').Value2 = 'Progress'; $desk.Range('B36').Interior.Color = $teal; $desk.Range('B36').Font.Color = $white; $desk.Range('B36').Font.Bold = $true
    $desk.Range('B37:C43').Value2 = @(
        @('Entities','=COUNTA(Entities!A2:A10000)'), @('References','=COUNTA(Mentions!A2:A10000)'), @('Fields','=COUNTA(Fields!A2:A10000)'), @('Context','=COUNTA(Context!A2:A10000)'), @('Statements','=COUNTA(Statements!A2:A10000)'), @('Uncertain','=COUNTA(Uncertain!A2:A10000)'), @('Watchlist decisions','=COUNTIF(''Watchlist Review''!H2:H10000,"complete")')
    )
    $desk.Range('B37:C43').Borders.LineStyle = 1
    $desk.Range('B37:B43').Font.Bold = $true

    $desk.Activate()
    $excel.ActiveWindow.DisplayGridlines = $false
    $desk.Range('C4').Select()

    $modulePath = Join-Path $PSScriptRoot 'ReviewWorkflow.bas'
    try {
        $component = $workbook.VBProject.VBComponents.Import($modulePath)
    } catch {
        throw "Excel blocked programmatic VBA insertion. Enable 'Trust access to the VBA project object model' in Excel's Trust Center, then rerun this builder. Original error: $($_.Exception.Message)"
    }
    $workbook.SaveAs($OutputPath, 52)
    $workbook.Close($true)
    Write-Output "Created $OutputPath"
} finally {
    if ($workbook) { try { $workbook.Close($false) } catch {} }
    $excel.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
