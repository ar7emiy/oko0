Attribute VB_Name = "WorkbenchWatchlist"
Option Explicit

Public Function ParseCSV(ByVal contents As String) As Collection
    Dim rows As New Collection, fields As Collection, token As String, quoted As Boolean, i As Long, c As String
    Set fields = New Collection
    i = 1
    Do While i <= Len(contents)
        c = Mid$(contents, i, 1)
        If c = """" Then
            If quoted And Mid$(contents, i + 1, 1) = """" Then
                token = token & """": i = i + 1
            Else
                quoted = Not quoted
            End If
        ElseIf c = "," And Not quoted Then
            fields.Add token: token = ""
        ElseIf (c = vbCr Or c = vbLf) And Not quoted Then
            fields.Add token: rows.Add fields: Set fields = New Collection: token = ""
            If c = vbCr And Mid$(contents, i + 1, 1) = vbLf Then i = i + 1
        Else
            token = token & c
        End If
        i = i + 1
    Loop
    If quoted Then Err.Raise vbObjectError + 110, , "CSV has an unclosed quoted field."
    If token <> "" Or fields.Count > 0 Then fields.Add token: rows.Add fields
    Set ParseCSV = rows
End Function

Public Sub ImportClientOutput()
    Dim picked As Variant, stream As Object, rows As Collection, fields As Collection, headers As Object
    Dim book As Workbook, sheet As Worksheet, r As Long, c As Long, lo As ListObject, a As Variant, batch As String, raw As Variant, security As Long
    On Error GoTo Failed
    picked = Application.GetOpenFilename("Client export (*.xlsx;*.csv),*.xlsx;*.csv", , "Import client export; all original columns required")
    If VarType(picked) = vbBoolean Then Exit Sub
    Set rows = New Collection
    If LCase$(Right$(CStr(picked), 4)) = ".csv" Then
        Set stream = CreateObject("ADODB.Stream"): stream.Type = 2: stream.Charset = "utf-8": stream.Open: stream.LoadFromFile CStr(picked)
        Set rows = ParseCSV(stream.ReadText): stream.Close
    Else
        security = Application.AutomationSecurity: Application.AutomationSecurity = 3
        Set book = Workbooks.Open(CStr(picked), UpdateLinks:=0, ReadOnly:=True): Set sheet = book.Worksheets(1)
        If ContainsFormula(sheet.UsedRange) Then Err.Raise vbObjectError + 111, , "Import must contain literal values, not formulas."
        raw = sheet.UsedRange.Value2
        If Not IsArray(raw) Then Err.Raise vbObjectError + 112, , "Export has no data table."
        For r = 1 To UBound(raw, 1)
            Set fields = New Collection
            For c = 1 To UBound(raw, 2)
                If IsError(raw(r, c)) Then Err.Raise vbObjectError + 113, , "Export contains an Excel error."
                fields.Add CStr(raw(r, c))
            Next c
            rows.Add fields
        Next r
        book.Close False: Set book = Nothing: Application.AutomationSecurity = security
    End If
    If rows.Count < 2 Then Err.Raise vbObjectError + 114, , "Client export has no data rows."
    Set headers = CreateObject("Scripting.Dictionary")
    For c = 1 To rows(1).Count
        If headers.Exists(Trim$(rows(1)(c))) Then Err.Raise vbObjectError + 115, , "Duplicate import header."
        headers.Add Trim$(rows(1)(c)), c
    Next c
    Set lo = T("tClient")
    For c = 2 To lo.ListColumns.Count
        If Not headers.Exists(lo.ListColumns(c).Name) Then Err.Raise vbObjectError + 116, , "Missing client column: " & lo.ListColumns(c).Name
    Next c
    If MsgBox("Append " & rows.Count - 1 & " client rows as a new import batch? Existing reviews remain linked to their original batch. Do not import the same export twice.", vbYesNo + vbQuestion) <> vbYes Then Exit Sub
    BeginWrite: batch = NewID("B-")
    For r = 2 To rows.Count
        If rows(r).Count <> rows(1).Count Then Err.Raise vbObjectError + 117, , "CSV row " & r & " has a different number of fields."
        ReDim a(0 To lo.ListColumns.Count - 1): a(0) = batch & ":" & r - 1
        For c = 2 To lo.ListColumns.Count: a(c - 1) = rows(r)(headers(lo.ListColumns(c).Name)): Next c
        AddRow lo, a
    Next r
    CommitWrite: MsgBox "Client data imported as literal values. Previous imports and decisions retained.", vbInformation: Exit Sub
Failed:
    Dim message As String
    message = Err.Description
    On Error Resume Next
    If Not book Is Nothing Then book.Close False
    If security <> 0 Then Application.AutomationSecurity = security
    If Not stream Is Nothing Then stream.Close
    On Error GoTo 0
    AbortWrite message
End Sub

Private Function PairEligible(ByVal r As Long) As Boolean
    Dim lo As ListObject, flag As String
    Set lo = T("tClient")
    flag = LCase$(V(lo, r, "Entity_Watchlist_flag"))
    If flag <> "1" And flag <> "true" And flag <> "yes" Then Exit Function
    If V(lo, r, "claim_number") <> F(4) Then Exit Function
    PairEligible = V(lo, r, "Exact_search_Note_ID") = F(5) Or V(lo, r, "GenAI_search_Note_ID") = F(5)
End Function

Public Sub OpenWatchlist()
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    If V(T("tNotes"), NoteRow(State("source")), "status") <> "complete" Then Err.Raise vbObjectError + 118, , "Complete the note's source annotations before reviewing watchlist matches."
    ThisWorkbook.Worksheets("Watchlist Desk").Activate
    LoadWatchlistMatches: Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub LoadWatchlistMatches()
    Dim lo As ListObject, reviews As ListObject, i As Long, j As Long, done As Boolean, ws As Worksheet, row As Long, s As String
    On Error GoTo Failed
    If V(T("tNotes"), NoteRow(State("source")), "status") <> "complete" Then Err.Raise vbObjectError + 119, , "Complete the note first."
    Set lo = T("tClient"): Set reviews = T("tWatch"): Set ws = ThisWorkbook.Worksheets("Watchlist Desk")
    If ws.Range("C5").Value2 <> "" Or ws.Range("C6").Value2 <> "" Then
        If MsgBox("Discard the unsaved watchlist decision and load the next pair?", vbYesNo + vbQuestion) <> vbYes Then Exit Sub
    End If
    ws.Range("C4:C6").ClearContents: ws.Range("G5:G45").ClearContents
    For i = 1 To lo.ListRows.Count
        If PairEligible(i) Then
            done = False
            For j = reviews.ListRows.Count To 1 Step -1
                If V(reviews, j, "client_row_id") = V(lo, i, "client_row_id") And V(reviews, j, "source_id") = State("source") Then
                    done = V(reviews, j, "review_status") = "complete": Exit For
                End If
            Next j
            If Not done Then
                ws.Range("C4").NumberFormat = "@": ws.Range("C4").Value2 = V(lo, i, "client_row_id")
                For j = 3 To lo.ListColumns.Count
                    ws.Cells(j + 2, 7).NumberFormat = "@": ws.Cells(j + 2, 7).Value2 = lo.ListColumns(j).Name & ": " & V(lo, i, lo.ListColumns(j).Name)
                    ws.Cells(j + 2, 7).WrapText = True: ws.Rows(j + 2).RowHeight = 30
                Next j
                ws.Range("C9").Value2 = "Read the full source note on Review Desk; you can switch tabs without losing this pair."
                ws.Range("C9").WrapText = True
                Exit Sub
            End If
        End If
    Next i
    MsgBox "No pending flagged pairs cite this exact note ID. Claim-level or multi-note fields need separate mapping; they are not assumed to cite this note.", vbInformation: Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub SaveWatchlistDecision()
    Dim ws As Worksheet, r As Long, decision As String
    On Error GoTo Failed
    Set ws = ThisWorkbook.Worksheets("Watchlist Desk")
    If V(T("tNotes"), NoteRow(State("source")), "status") <> "complete" Then Err.Raise vbObjectError + 120, , "Source annotation is incomplete."
    r = FindRow(T("tClient"), "client_row_id", CStr(ws.Range("C4").Value2))
    If r = 0 Then Err.Raise vbObjectError + 121, , "Load a valid client pair."
    If Not PairEligible(r) Then Err.Raise vbObjectError + 122, , "This pair does not cite the current claim/note."
    decision = CStr(ws.Range("C5").Value2)
    If InStr(1, "|same_entity|different_entity|insufficient_evidence|", "|" & decision & "|", vbBinaryCompare) = 0 Or decision = "" Then Err.Raise vbObjectError + 123, , "Choose an identity decision."
    If Trim$(CStr(ws.Range("C6").Value2)) = "" Or Trim$(F(7)) = "" Then Err.Raise vbObjectError + 124, , "Reviewer name and source-based reason are required."
    BeginWrite
    AddRow T("tWatch"), Array(NewID("WR-"), CStr(ws.Range("C4").Value2), F(4), F(5), decision, "reviewer_note_evidence", CStr(ws.Range("C6").Value2), "complete", State("source"), F(7), Stamp())
    CommitWrite
    ws.Range("C4:C6").ClearContents
    MsgBox "Watchlist decision saved. Load next pair when ready.", vbInformation: Exit Sub
Failed: AbortWrite Err.Description
End Sub
