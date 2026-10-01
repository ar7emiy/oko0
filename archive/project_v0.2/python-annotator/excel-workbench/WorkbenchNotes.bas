Attribute VB_Name = "WorkbenchNotes"
Option Explicit
#If VBA7 Then
Private Declare PtrSafe Function OpenClipboard Lib "user32" (ByVal hwnd As LongPtr) As Long
Private Declare PtrSafe Function CloseClipboard Lib "user32" () As Long
Private Declare PtrSafe Function GetClipboardData Lib "user32" (ByVal fmt As Long) As LongPtr
Private Declare PtrSafe Function GlobalLock Lib "kernel32" (ByVal h As LongPtr) As LongPtr
Private Declare PtrSafe Function GlobalUnlock Lib "kernel32" (ByVal h As LongPtr) As Long
Private Declare PtrSafe Function lstrlenW Lib "kernel32" (ByVal p As LongPtr) As Long
Private Declare PtrSafe Sub CopyMemory Lib "kernel32" Alias "RtlMoveMemory" (ByVal dest As LongPtr, ByVal src As LongPtr, ByVal n As LongPtr)
#Else
Private Declare Function OpenClipboard Lib "user32" (ByVal hwnd As Long) As Long
Private Declare Function CloseClipboard Lib "user32" () As Long
Private Declare Function GetClipboardData Lib "user32" (ByVal fmt As Long) As Long
Private Declare Function GlobalLock Lib "kernel32" (ByVal h As Long) As Long
Private Declare Function GlobalUnlock Lib "kernel32" (ByVal h As Long) As Long
Private Declare Function lstrlenW Lib "kernel32" (ByVal p As Long) As Long
Private Declare Sub CopyMemory Lib "kernel32" Alias "RtlMoveMemory" (ByVal dest As Long, ByVal src As Long, ByVal n As Long)
#End If

Public Function ClipboardText() As String
#If VBA7 Then
    Dim h As LongPtr, p As LongPtr
#Else
    Dim h As Long, p As Long
#End If
    Dim n As Long, s As String, errText As String
    If OpenClipboard(0) = 0 Then Err.Raise vbObjectError + 20, , "Clipboard is busy. Copy the note again and retry."
    On Error GoTo Failed
    h = GetClipboardData(13)
    If h = 0 Then Err.Raise vbObjectError + 21, , "Clipboard has no Unicode text. Copy the note in Notepad first."
    p = GlobalLock(h)
    If p = 0 Then Err.Raise vbObjectError + 22, , "Cannot read clipboard."
    n = lstrlenW(p): s = String$(n, vbNullChar)
    If n > 0 Then CopyMemory StrPtr(s), p, CLng(n) * 2
    GlobalUnlock h: CloseClipboard
    ClipboardText = s
    Exit Function
Failed:
    errText = Err.Description
    If p <> 0 Then GlobalUnlock h
    CloseClipboard
    Err.Raise vbObjectError + 23, , errText
End Function

Public Function Codepoints(ByVal s As String) As Long
    Dim i As Long, u As Long, n As Long
    i = 1
    Do While i <= Len(s)
        u = AscW(Mid$(s, i, 1)) And &HFFFF&
        If u >= &HD800& And u <= &HDBFF& And i < Len(s) Then
            u = AscW(Mid$(s, i + 1, 1)) And &HFFFF&
            If u >= &HDC00& And u <= &HDFFF& Then i = i + 1
        End If
        n = n + 1: i = i + 1
    Loop
    Codepoints = n
End Function

Public Function SafeTake(ByVal s As String, ByVal startAt As Long, ByVal size As Long) As String
    Dim n As Long, u As Long
    n = size
    If startAt + n - 1 < Len(s) Then
        u = AscW(Mid$(s, startAt + n - 1, 1)) And &HFFFF&
        If u >= &HD800& And u <= &HDBFF& Then n = n - 1
    End If
    SafeTake = Mid$(s, startAt, n)
End Function

Public Function FullNote(ByVal sourceID As String) As String
    Dim lo As ListObject, i As Long, parts As Object, k As Long, s As String
    Set lo = T("tParts"): Set parts = CreateObject("Scripting.Dictionary")
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = sourceID Then parts.Add CLng(V(lo, i, "part")), V(lo, i, "note_text")
    Next i
    For k = 1 To parts.Count
        If Not parts.Exists(k) Then Err.Raise vbObjectError + 24, , "Note storage has a missing part."
        s = s & parts(k)
    Next k
    If Len(s) <> CLng(V(T("tNotes"), NoteRow(sourceID), "length_utf16")) Then Err.Raise vbObjectError + 25, , "Stored note length does not match its capture."
    FullNote = s
End Function

Public Function OccurrenceStart(ByVal s As String, ByVal quote As String, ByVal occurrence As Long) As Long
    Dim p As Long, n As Long
    If quote = "" Or occurrence < 1 Then Exit Function
    p = 1
    For n = 1 To occurrence
        p = InStr(p, s, quote, vbBinaryCompare)
        If p = 0 Then Exit Function
        If n < occurrence Then p = p + 1
    Next n
    OccurrenceStart = p
End Function

Public Function CaptureNote(ByVal claim As String, ByVal note As String, ByVal order As Long, ByVal contents As String) As String
    Dim lo As ListObject, i As Long, version As Long, src As String, p As Long, part As String, count As Long
    If Trim$(claim) = "" Or Trim$(note) = "" Or order < 1 Or Len(contents) = 0 Then Err.Raise vbObjectError + 26, , "Claim, note ID, positive reading order and nonempty text are required."
    Set lo = T("tNotes")
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "claim_number") = claim And V(lo, i, "note_id") = note Then
            If Val(V(lo, i, "version")) > version Then version = CLng(V(lo, i, "version"))
        End If
    Next i
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "claim_number") = claim And V(lo, i, "note_id") = note And Val(V(lo, i, "version")) = version Then
            src = V(lo, i, "source_id")
            If FullNote(src) = contents Then
                SetV lo, i, "paste_sequence", CStr(NextPasteSequence()): SetV lo, i, "note_order", CStr(order)
                CaptureNote = src: PruneAnalysis: Exit Function
            End If
            If MsgBox("This note's text changed. Keep the old version and create a new review version?", vbYesNo + vbQuestion) <> vbYes Then Err.Raise vbObjectError + 27, , "Source replacement cancelled."
            SetV lo, i, "status", "superseded"
        End If
    Next i
    src = NewID("N-")
    AddRow lo, Array(src, claim, note, CStr(order), CStr(version + 1), CStr(Len(contents)), CStr(NextPasteSequence()), "in_progress")
    p = 1
    Do While p <= Len(contents)
        part = SafeTake(contents, p, 8000): count = count + 1
        AddRow T("tParts"), Array(src, CStr(count), part): p = p + Len(part)
    Loop
    If FullNote(src) <> contents Then Err.Raise vbObjectError + 28, , "Note capture verification failed."
    PruneAnalysis
    CaptureNote = src
End Function

Private Function NextPasteSequence() As Long
    NextPasteSequence = CLng(Val(State("paste_sequence"))) + 1
    SetState "paste_sequence", CStr(NextPasteSequence)
End Function

Public Sub PruneAnalysis()
    Dim notes As ListObject, analysis As ListObject, recency As Object, retained As Object
    Dim i As Long, key As String, candidate As Variant, latestKey As String, lastTime As Double, n As Long, src As String, nr As Long
    Set notes = T("tNotes"): Set analysis = T("tAnalysis")
    Set recency = CreateObject("Scripting.Dictionary"): Set retained = CreateObject("Scripting.Dictionary")
    For i = 1 To notes.ListRows.Count
        If V(notes, i, "source_id") <> "" Then
            key = V(notes, i, "claim_number") & ChrW(30) & V(notes, i, "note_id")
            If Not recency.Exists(key) Then recency.Add key, 0#
            If Val(V(notes, i, "paste_sequence")) > recency(key) Then recency(key) = Val(V(notes, i, "paste_sequence"))
        End If
    Next i
    For n = 1 To 5
        latestKey = "": lastTime = -1
        For Each candidate In recency.Keys
            If Not retained.Exists(candidate) Then
                If recency(candidate) > lastTime Then latestKey = candidate: lastTime = recency(candidate)
            End If
        Next candidate
        If latestKey <> "" Then retained.Add latestKey, True
    Next n
    For i = analysis.ListRows.Count To 1 Step -1
        src = V(analysis, i, "source_id")
        If src <> "" Then
            nr = NoteRow(src): key = V(notes, nr, "claim_number") & ChrW(30) & V(notes, nr, "note_id")
            If Not retained.Exists(key) Then DeleteRow analysis, i
        End If
    Next i
End Sub

Public Sub PasteWholeNote()
    Dim s As String, src As String, ws As Worksheet
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    s = ClipboardText(): Set ws = ThisWorkbook.Worksheets("Notes")
    BeginWrite
    src = CaptureNote(CStr(ws.Range("C4").Value2), CStr(ws.Range("C5").Value2), CLng(Val(ws.Range("C6").Value2)), s)
    OpenSource src: CommitWrite
    MsgBox "Captured " & Len(s) & " UTF-16 units. First: " & Left$(s, 80) & vbCrLf & "Last: " & Right$(s, 80), vbInformation
    Exit Sub
Failed: AbortWrite Err.Description
End Sub

Public Sub ImportNotes()
    Dim files As Variant, path As Variant, base As String, claim As String, note As String, p As Long, stream As Object, src As String, n As Long
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    files = Application.GetOpenFilename("UTF-8 text (*.txt),*.txt", , "Select notes named CLAIM_NOTE.txt; selection order is reading order", , True)
    If VarType(files) = vbBoolean Then Exit Sub
    BeginWrite
    For Each path In files
        base = Mid$(CStr(path), InStrRev(CStr(path), "\") + 1): base = Left$(base, Len(base) - 4): p = InStrRev(base, "_")
        If p < 2 Then Err.Raise vbObjectError + 29, , "Name must be CLAIM_NOTE.txt: " & base
        claim = Left$(base, p - 1): note = Mid$(base, p + 1): n = n + 1
        Set stream = CreateObject("ADODB.Stream"): stream.Type = 2: stream.Charset = "utf-8": stream.Open: stream.LoadFromFile CStr(path)
        src = CaptureNote(claim, note, n, stream.ReadText): stream.Close
    Next path
    OpenSource src: CommitWrite
    MsgBox "Imported " & n & " notes. Check their reading order in Note Register before reviewing.", vbInformation
    Exit Sub
Failed:
    On Error Resume Next
    If Not stream Is Nothing Then stream.Close
    On Error GoTo 0
    AbortWrite "Note import did not complete. Check filenames and UTF-8 encoding."
End Sub

Public Sub SelectNote()
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    ThisWorkbook.Worksheets("Note Register").Activate
    MsgBox "Select a row in Note Register, then click Open selected note.", vbInformation
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub OpenSelectedNote()
    Dim r As Long
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    If ActiveSheet.Name <> "Note Register" Then
        ThisWorkbook.Worksheets("Note Register").Activate
        MsgBox "Select a stored note row here, then Open selected note.": Exit Sub
    End If
    r = ActiveCell.Row - T("tNotes").HeaderRowRange.Row
    If r < 1 Or r > T("tNotes").ListRows.Count Then Err.Raise vbObjectError + 31, , "Select a stored note row, not its header."
    OpenSource V(T("tNotes"), r, "source_id")
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub ShowTextPage()
    Dim s As String, p As Long, i As Long, piece As String, ws As Worksheet, startAt As Long, matchAt As Long, hiStart As Long, hiEnd As Long
    If State("source") = "" Then Exit Sub
    s = FullNote(State("source")): startAt = CLng(Val(State("text_page")))
    If startAt < 1 Then startAt = 1
    If startAt > Len(s) Then startAt = 1
    p = startAt: Set ws = ThisWorkbook.Worksheets("Review Desk")
    If IsNumeric(F(11)) Then
        If Val(F(11)) > 0 And Val(F(11)) < 2147483647# Then matchAt = OccurrenceStart(s, F(10), CLng(Val(F(11))))
    End If
    ws.Range("G5:G20").ClearContents
    ThisWorkbook.Worksheets("Notes").Range("C11:C26").ClearContents
    For i = 5 To 20
        piece = SafeTake(s, p, 220)
        ws.Cells(i, 7).NumberFormat = "@": ws.Cells(i, 7).Value2 = piece
        With ThisWorkbook.Worksheets("Notes").Cells(i + 6, 3)
            .NumberFormat = "@": .Value2 = piece: .WrapText = True: .RowHeight = 50
        End With
        ws.Cells(i, 7).Font.Bold = False: ws.Cells(i, 7).Font.Color = RGB(24, 52, 76)
        If matchAt > 0 Then
            hiStart = matchAt: If hiStart < p Then hiStart = p
            hiEnd = matchAt + Len(F(10)): If hiEnd > p + Len(piece) Then hiEnd = p + Len(piece)
            If hiEnd > hiStart Then
                ws.Cells(i, 7).Characters(hiStart - p + 1, hiEnd - hiStart).Font.Bold = True
                ws.Cells(i, 7).Characters(hiStart - p + 1, hiEnd - hiStart).Font.Color = RGB(160, 60, 0)
            End If
        End If
        ws.Cells(i, 7).WrapText = True: ws.Rows(i).RowHeight = IIf(i = 10 Or i = 20, 90, 48)
        p = p + Len(piece)
        If p > Len(s) Then Exit For
    Next i
    ws.Range("G4").Value2 = "Text " & startAt & "-" & p - 1 & " of " & Len(s) & " (UTF-16)"
    SetState "page_end", CStr(p)
End Sub

Public Sub NextTextPage()
    On Error GoTo Failed
    If Val(State("page_end")) > Len(FullNote(State("source"))) Then MsgBox "End of note.": Exit Sub
    SetState "text_page", State("page_end"): ShowTextPage: Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub PreviousTextPage()
    Dim p As Long
    On Error GoTo Failed
    p = CLng(Val(State("text_page"))) - 3520
    If p < 1 Then p = 1
    SetState "text_page", CStr(p): ShowTextPage: Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub LocateEvidence()
    Dim p As Long
    On Error GoTo Failed
    p = OccurrenceStart(FullNote(State("source")), F(10), CLng(Val(F(11))))
    If p = 0 Then Err.Raise vbObjectError + 32, , "Quote/occurrence not found. Copy the exact wording and choose the correct occurrence."
    SetState "text_page", CStr(IIf(p > 220, p - 220, 1)): ShowTextPage
    MsgBox "Located occurrence " & F(11) & ". Read the surrounding text at right.", vbInformation
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub
