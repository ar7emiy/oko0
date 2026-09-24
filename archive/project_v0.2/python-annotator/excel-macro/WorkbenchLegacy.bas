Attribute VB_Name = "WorkbenchLegacy"
Option Explicit

Public Sub ImportLegacyWorkbook()
    Dim picked As Variant, book As Workbook, ws As Worksheet, name As Variant, staged As Collection
    Dim header As Long, r As Long, c As Long, lastRow As Long, lastCol As Long, batch As String, row As Variant, security As Long, message As String
    On Error GoTo Failed
    picked = Application.GetOpenFilename("Previous workbook (*.xlsx;*.xlsm),*.xlsx;*.xlsm", , "Archive earlier annotations as unverified source rows")
    If VarType(picked) = vbBoolean Then Exit Sub
    If CStr(picked) = ThisWorkbook.FullName Then Err.Raise vbObjectError + 160, , "Select the previous workbook, not this working copy."
    Set staged = New Collection
    security = Application.AutomationSecurity: Application.AutomationSecurity = 3
    Set book = Workbooks.Open(CStr(picked), UpdateLinks:=0, ReadOnly:=True)
    For Each name In Array("Entities", "Mentions", "Fields", "Context", "Statements", "Uncertain", "Watchlist Review")
        Set ws = Nothing
        On Error Resume Next: Set ws = book.Worksheets(CStr(name)): On Error GoTo Failed
        If Not ws Is Nothing Then
            header = 1
            If CStr(ws.Cells(5, 1).Value2) Like "*_id" Or CStr(ws.Cells(5, 1).Value2) = "entity_ref" Then header = 5
            lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
            lastCol = ws.Cells(header, ws.Columns.Count).End(xlToLeft).Column
            For r = header + 1 To lastRow
                For c = 1 To lastCol
                    If IsError(ws.Cells(r, c).Value2) Then Err.Raise vbObjectError + 161, , "Legacy sheet contains an Excel error."
                    If CStr(ws.Cells(r, c).Value2) <> "" Then staged.Add Array(CStr(name), CStr(r), CStr(ws.Cells(header, c).Value2), CStr(ws.Cells(r, c).Value2))
                Next c
            Next r
        End If
    Next name
    book.Close False: Set book = Nothing: Application.AutomationSecurity = security
    BeginWrite: batch = NewID("L-")
    For Each row In staged
        AddRow T("tLegacy"), Array(batch, row(0), row(1), row(2), row(3), "unverified_legacy")
    Next row
    CommitWrite
    MsgBox "Archived " & staged.Count & " historical cells. They are unverified, not accepted annotations. Load the source notes and re-enter/review annotations through the main form. The original workbook is unchanged.", vbInformation
    Exit Sub
Failed:
    message = Err.Description
    On Error Resume Next
    If Not book Is Nothing Then book.Close False
    If security <> 0 Then Application.AutomationSecurity = security
    On Error GoTo 0
    AbortWrite message
End Sub
