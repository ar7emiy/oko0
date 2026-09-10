Attribute VB_Name = "WorkbenchStore"
Option Explicit

Private Type GuidValue
    a As Long
    b As Integer
    c As Integer
    d(0 To 7) As Byte
End Type
#If VBA7 Then
Private Declare PtrSafe Function CoCreateGuid Lib "ole32" (ByRef v As GuidValue) As Long
Private Declare PtrSafe Function StringFromGUID2 Lib "ole32" (ByRef v As GuidValue, ByVal p As LongPtr, ByVal n As Long) As Long
#Else
Private Declare Function CoCreateGuid Lib "ole32" (ByRef v As GuidValue) As Long
Private Declare Function StringFromGUID2 Lib "ole32" (ByRef v As GuidValue, ByVal p As Long, ByVal n As Long) As Long
#End If
Public Busy As Boolean
Private Snapshots As Object
Private FormSnapshot As Variant
Private OldEvents As Boolean
Private OldScreen As Boolean
Public TestFailBeforeSave As Boolean

Public Function ContainsFormula(ByVal area As Range) As Boolean
    Dim found As Range
    If area Is Nothing Then Exit Function
    On Error Resume Next
    Set found = area.SpecialCells(xlCellTypeFormulas)
    On Error GoTo 0
    ContainsFormula = Not found Is Nothing
End Function

Public Function T(ByVal tableName As String) As ListObject
    Dim ws As Worksheet, lo As ListObject
    For Each ws In ThisWorkbook.Worksheets
        For Each lo In ws.ListObjects
            If lo.Name = tableName Then Set T = lo: Exit Function
        Next lo
    Next ws
    Err.Raise vbObjectError + 1, , "Missing table " & tableName & ". Use the new workbook template; do not import this code into the old layout."
End Function

Public Function V(ByVal lo As ListObject, ByVal r As Long, ByVal key As String) As String
    If r < 1 Or r > lo.ListRows.Count Then Exit Function
    If IsError(lo.DataBodyRange.Cells(r, lo.ListColumns(key).Index).Value2) Then Err.Raise vbObjectError + 2, , "Excel error in " & lo.Name & " / " & key
    V = CStr(lo.DataBodyRange.Cells(r, lo.ListColumns(key).Index).Value2)
End Function

Public Sub SetV(ByVal lo As ListObject, ByVal r As Long, ByVal key As String, ByVal value As Variant)
    With lo.DataBodyRange.Cells(r, lo.ListColumns(key).Index)
        .NumberFormat = "@"
        .Value2 = CStr(value)
    End With
End Sub

Public Function AddRow(ByVal lo As ListObject, ByVal values As Variant) As Long
    Dim r As Long, j As Long
    If UBound(values) - LBound(values) + 1 <> lo.ListColumns.Count Then Err.Raise vbObjectError + 3, , "Internal column count mismatch: " & lo.Name
    r = lo.ListRows.Add.Index
    For j = LBound(values) To UBound(values)
        lo.DataBodyRange.Cells(r, j - LBound(values) + 1).NumberFormat = "@"
        lo.DataBodyRange.Cells(r, j - LBound(values) + 1).Value2 = CStr(values(j))
    Next j
    AddRow = r
End Function

Public Function FindRow(ByVal lo As ListObject, ByVal key As String, ByVal value As String) As Long
    Dim i As Long
    For i = lo.ListRows.Count To 1 Step -1
        If V(lo, i, key) = value Then FindRow = i: Exit Function
    Next i
End Function

Public Function State(ByVal key As String) As String
    Dim lo As ListObject, r As Long
    Set lo = T("tState"): r = FindRow(lo, "key", key)
    If r > 0 Then State = V(lo, r, "value")
End Function

Public Sub SetState(ByVal key As String, ByVal value As String)
    Dim lo As ListObject, r As Long
    Set lo = T("tState"): r = FindRow(lo, "key", key)
    If r = 0 Then
        AddRow lo, Array(key, value)
    Else
        SetV lo, r, "value", value
    End If
End Sub

Public Function NewID(ByVal prefix As String) As String
    Dim g As GuidValue, s As String
    If CoCreateGuid(g) <> 0 Then Err.Raise vbObjectError + 4, , "Cannot allocate an entry ID."
    s = String$(39, vbNullChar)
    If StringFromGUID2(g, StrPtr(s), 39) = 0 Then Err.Raise vbObjectError + 5, , "Cannot format entry ID."
    NewID = prefix & Mid$(s, 2, 36)
End Function

Public Function Stamp() As String
    ' Explicit local time; the workbook does not pretend this is UTC.
    Stamp = Format$(Now, "yyyy-mm-dd hh:nn:ss") & " local"
End Function

Public Sub BeginWrite()
    Dim ws As Worksheet, lo As ListObject, backupPath As String
    If Busy Then Err.Raise vbObjectError + 6, , "A save is already in progress."
    If ThisWorkbook.ReadOnly Or ThisWorkbook.Path = "" Then Err.Raise vbObjectError + 7, , "Save a writable .xlsm working copy first."
    If ThisWorkbook.FileFormat <> xlOpenXMLWorkbookMacroEnabled Then Err.Raise vbObjectError + 8, , "Save this file as .xlsm before using the workbench."
    If State("schema") <> "assisted-1" Then Err.Raise vbObjectError + 12, , "Run SetupWorkbench before editing data."
    Set Snapshots = CreateObject("Scripting.Dictionary")
    For Each ws In ThisWorkbook.Worksheets
        For Each lo In ws.ListObjects
            If lo.DataBodyRange Is Nothing Then
                Snapshots.Add lo.Name, Empty
            Else
                Snapshots.Add lo.Name, lo.DataBodyRange.Value2
            End If
        Next lo
    Next ws
    FormSnapshot = ThisWorkbook.Worksheets("Review Desk").Range("C4:C22").Value2
    ' A rotating pre-write recovery file contains the same sensitive data as the workbook.
    backupPath = Environ$("TEMP") & "\" & ThisWorkbook.Name & ".recovery.xlsm"
    If Dir$(backupPath) <> "" Then Kill backupPath
    ThisWorkbook.SaveCopyAs backupPath
    OldEvents = Application.EnableEvents: OldScreen = Application.ScreenUpdating
    Busy = True: Application.EnableEvents = False: Application.ScreenUpdating = False
    SetState "recovery_path", backupPath
End Sub

Public Sub CommitWrite()
    If Not Busy Then Err.Raise vbObjectError + 9, , "No active save."
    If TestFailBeforeSave Then Err.Raise vbObjectError + 10, , "Injected pre-save failure."
    ThisWorkbook.Save
    Set Snapshots = Nothing
    Busy = False: Application.EnableEvents = OldEvents: Application.ScreenUpdating = OldScreen
End Sub

Public Sub AbortWrite(ByVal explanation As String)
    Dim key As Variant, lo As ListObject, a As Variant, r As Long, c As Long
    If Busy Then
        On Error Resume Next
        For Each key In Snapshots.Keys
            Set lo = T(CStr(key))
            If Not lo.DataBodyRange Is Nothing Then lo.DataBodyRange.Delete
            a = Snapshots(key)
            If IsArray(a) Then
                For r = 1 To UBound(a, 1)
                    lo.ListRows.Add
                Next r
                lo.DataBodyRange.NumberFormat = "@"
                lo.DataBodyRange.Value2 = a
            End If
        Next key
        ThisWorkbook.Worksheets("Review Desk").Range("C4:C22").Value2 = FormSnapshot
        Busy = False: Application.EnableEvents = OldEvents: Application.ScreenUpdating = OldScreen
        Set Snapshots = Nothing
        On Error GoTo 0
    End If
    MsgBox explanation & vbCrLf & "The action did not complete. Your form is retained. If Excel was interrupted, use the pre-write recovery copy in your TEMP folder.", vbExclamation, "Not saved"
End Sub

Public Function LatestEntries() As Object
    Dim out As Object, lo As ListObject, i As Long, id As String
    Set out = CreateObject("Scripting.Dictionary"): Set lo = T("tEntries")
    For i = 1 To lo.ListRows.Count
        id = V(lo, i, "entry_id")
        If id <> "" Then
            If Not out.Exists(id) Then
                out.Add id, i
            ElseIf Val(V(lo, i, "revision")) > Val(V(lo, CLng(out(id)), "revision")) Then
                out(id) = i
            End If
        End If
    Next i
    Set LatestEntries = out
End Function

Public Function NoteRow(ByVal sourceID As String) As Long
    If sourceID = "" Then Err.Raise vbObjectError + 11, , "Load a registered note first."
    NoteRow = FindRow(T("tNotes"), "source_id", sourceID)
    If NoteRow = 0 Then Err.Raise vbObjectError + 11, , "Load a registered note first."
End Function

Public Function NoteClaim(ByVal sourceID As String) As String
    NoteClaim = V(T("tNotes"), NoteRow(sourceID), "claim_number")
End Function

Public Sub ReopenNote(ByVal sourceID As String)
    Dim lo As ListObject, i As Long
    SetV T("tNotes"), NoteRow(sourceID), "status", "in_progress"
    Set lo = T("tWatch")
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = sourceID Then SetV lo, i, "review_status", "recheck"
    Next i
End Sub

Public Sub ClearRows(ByVal lo As ListObject)
    If Not lo.DataBodyRange Is Nothing Then lo.DataBodyRange.Delete
End Sub

Public Sub RebuildOutputs()
    Dim names As Variant, sheetName As Variant, items As Object, id As Variant, lo As ListObject
    Dim r As Long, src As String, claim As String, note As String, ent As String, quote As String, st As String, en As String
    names = Array("tEntities", "tMentions", "tFields", "tContext", "tStatements", "tUncertain")
    For Each sheetName In names: ClearRows T(CStr(sheetName)): Next sheetName
    Set items = LatestEntries(): Set lo = T("tEntries")
    For Each id In items.Keys
        r = items(id)
        If V(lo, r, "state") = "accepted" Then
            src = V(lo, r, "source_id"): claim = NoteClaim(src): note = V(T("tNotes"), NoteRow(src), "note_id")
            ent = V(lo, r, "entity_ref"): quote = V(lo, r, "source_quote"): st = V(lo, r, "start_character"): en = V(lo, r, "end_character")
            Select Case V(lo, r, "action")
            Case "entity"
                AddRow T("tEntities"), Array(ent, claim, V(lo, r, "display_name"), V(lo, r, "entity_type"), note, quote, "observed")
                AddRow T("tMentions"), Array("M-" & id, claim, note, quote, st, en, ent, "name", V(lo, r, "reason"))
            Case "reference"
                AddRow T("tMentions"), Array("M-" & id, claim, note, quote, st, en, ent, V(lo, r, "reference_form"), V(lo, r, "reason"))
            Case "field"
                AddRow T("tFields"), Array(id, claim, note, ent, V(lo, r, "field_kind"), V(lo, r, "field_value"), quote, st, en, "observed")
            Case "context"
                AddRow T("tContext"), Array(id, claim, note, ent, quote, st, en, V(lo, r, "open_label"), V(lo, r, "reason"))
            Case "statement"
                AddRow T("tStatements"), Array(id, claim, note, quote, st, en, ent, V(lo, r, "second_entity_ref"), V(lo, r, "open_label"), V(lo, r, "reason"))
            Case "uncertain"
                AddRow T("tUncertain"), Array(id, claim, note, quote, st, en, V(lo, r, "reason"), ent)
            End Select
        End If
    Next id
End Sub
