Attribute VB_Name = "WorkbenchSetup"
Option Explicit

Private Sub Button(ByVal sheetName As String, ByVal cell As String, ByVal label As String, ByVal macro As String)
    Dim ws As Worksheet, shape As Shape, box As Range, name As String
    Set ws = ThisWorkbook.Worksheets(sheetName): Set box = ws.Range(cell): name = "wb_" & macro
    On Error Resume Next: ws.Shapes(name).Delete: On Error GoTo 0
    Set shape = ws.Shapes.AddShape(msoShapeRoundedRectangle, box.Left, box.Top, box.Width, 27)
    shape.Name = name: shape.TextFrame2.TextRange.Text = label
    shape.TextFrame2.TextRange.Font.Size = 10: shape.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = RGB(255, 255, 255)
    shape.Fill.ForeColor.RGB = RGB(24, 52, 76): shape.Line.Visible = msoFalse
    shape.OnAction = "'" & Replace(ThisWorkbook.Name, "'", "''") & "'!" & macro
    shape.AlternativeText = label & ". See Instructions for the workflow."
    shape.Placement = xlMove
End Sub

Public Sub SetupWorkbench()
    Dim ws As Worksheet, lo As ListObject, cell As Range
    On Error GoTo Failed
    If T("tEntries").ListColumns.Count <> 22 Or T("tInput").ListColumns.Count <> 13 Then Err.Raise vbObjectError + 90, , "Unexpected workbook schema. Use the supplied new template."
    If State("schema") <> "" And State("schema") <> "assisted-1" Then Err.Raise vbObjectError + 91, , "This workbook has a different schema version."
    For Each ws In ThisWorkbook.Worksheets
        For Each cell In ws.UsedRange.Cells
            If cell.MergeCells Then Err.Raise vbObjectError + 92, , "Merged cells found in " & ws.Name & ". Use the unmerged template."
        Next cell
    Next ws
    SetState "schema", "assisted-1"
    Button "Review Desk", "E4", "Select note", "SelectNote"
    Button "Review Desk", "E5", "New manual entry", "NewEntry"
    Button "Review Desk", "E7", "Load next AI draft", "LoadNextCandidate"
    Button "Review Desk", "E9", "Attest & Save", "AttestSave"
    Button "Review Desk", "E11", "Save draft", "SaveDraft"
    Button "Review Desk", "E12", "Previous entry", "PreviousEntry"
    Button "Review Desk", "E13", "Next reviewed entry", "NextEntry"
    Button "Review Desk", "E15", "Delete entry", "DeleteEntry"
    Button "Review Desk", "E17", "Choose entity", "ChooseEntity"
    Button "Review Desk", "E18", "Locate evidence", "LocateEvidence"
    Button "Review Desk", "E20", "Complete note", "CompleteNote"
    Button "Review Desk", "E22", "Previous text page", "PreviousTextPage"
    Button "Review Desk", "E23", "Next text page", "NextTextPage"
    Button "Review Desk", "E25", "Watchlist review", "OpenWatchlist"
    Button "Review Desk", "E27", "Resume saved draft", "ResumeDraft"
    Button "Notes", "E4", "Paste whole note", "PasteWholeNote"
    Button "Notes", "E6", "Import TXT files", "ImportNotes"
    Button "Notes", "E8", "Open selected note", "OpenSelectedNote"
    ThisWorkbook.Worksheets("Note Register").Columns("J").ColumnWidth = 27
    Button "Note Register", "J2", "Open selected note", "OpenSelectedNote"
    ThisWorkbook.Worksheets("AI Analysis Input").Columns("E").ColumnWidth = 27
    Button "AI Analysis Input", "E4", "Save queue snapshot", "SaveQueueSnapshot"
    Button "Watchlist Desk", "E4", "Load next pair", "LoadWatchlistMatches"
    Button "Watchlist Desk", "E6", "Save decision", "SaveWatchlistDecision"
    Button "Watchlist Desk", "E8", "Import client output", "ImportClientOutput"
    If F(7) = "" Then SetF 7, Application.UserName
    ' Named input cells decouple integrations from the visual row layout.
    On Error Resume Next
    ThisWorkbook.Names.Add Name:="CurrentClaim", RefersTo:="='Review Desk'!$C$4"
    ThisWorkbook.Names.Add Name:="CurrentNote", RefersTo:="='Review Desk'!$C$5"
    ThisWorkbook.Names.Add Name:="EvidenceQuote", RefersTo:="='Review Desk'!$C$10"
    On Error GoTo Failed
    If State("baseline") = "" Then RememberForm
    ProtectWorkbench
    SetF 22, "Ready. Add notes on Notes, then review manually or load AI drafts."
    ThisWorkbook.Save
    MsgBox "Buttons installed. Use Notes to begin. No Copilot is needed for manual annotation.", vbInformation
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation, "Setup did not complete"
End Sub

Public Sub WorkbenchOpen()
    On Error GoTo Failed
    If State("schema") <> "assisted-1" Then Exit Sub
    ProtectWorkbench
    RestoreForm
    If State("source") <> "" Then ShowTextPage: RefreshDesk
    Exit Sub
Failed: MsgBox "Startup check: " & Err.Description, vbExclamation
End Sub

Public Sub ProtectWorkbench()
    Dim ws As Worksheet, name As String
    For Each ws In ThisWorkbook.Worksheets
        name = ws.Name
        If name <> "Review Desk" And name <> "Notes" And name <> "AI Queue" And name <> "AI Analysis Input" And name <> "Watchlist Desk" And name <> "Instructions" And name <> "AI Instructions" Then
            ws.Unprotect
            ws.Cells.Locked = True
            If name = "Note Register" Then
                If Not T("tNotes").DataBodyRange Is Nothing Then T("tNotes").ListColumns("note_order").DataBodyRange.Locked = False
            End If
            ws.Protect UserInterfaceOnly:=True, AllowFiltering:=True
        End If
    Next ws
End Sub
