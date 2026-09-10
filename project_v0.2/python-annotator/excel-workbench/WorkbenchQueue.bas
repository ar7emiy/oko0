Attribute VB_Name = "WorkbenchQueue"
Option Explicit

Public Sub SaveQueueSnapshot()
    Dim input As ListObject, queue As ListObject, ws As Worksheet, sourceID As String, runID As String
    Dim i As Long, j As Long, p As Long, s As String, keys As Object, a As Variant, row As Long, duplicate As Boolean, text As String, part As String, partN As Long
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    sourceID = State("source"): s = FullNote(sourceID)
    Set input = T("tInput"): Set queue = T("tQueue"): Set ws = ThisWorkbook.Worksheets("AI Analysis Input")
    If Trim$(CStr(ws.Range("C4").Value2)) = "" Then Err.Raise vbObjectError + 70, , "Give this AI run a label on AI Analysis Input."
    If LCase$(CStr(ws.Range("C6").Value2)) <> "yes" And LCase$(CStr(ws.Range("C6").Value2)) <> "no" Then Err.Raise vbObjectError + 71, , "Run complete? must be yes or no."
    If input.DataBodyRange Is Nothing Then Err.Raise vbObjectError + 72, , "No queue rows."
    If ContainsFormula(input.DataBodyRange) Then Err.Raise vbObjectError + 73, , "AI Queue contains formulas. Replace them with literal values."
    Set keys = CreateObject("Scripting.Dictionary")
    For i = 1 To input.ListRows.Count
        If V(input, i, "candidate_key") <> "" Then
            If keys.Exists(V(input, i, "candidate_key")) Then Err.Raise vbObjectError + 74, , "Duplicate candidate key: " & V(input, i, "candidate_key")
            keys.Add V(input, i, "candidate_key"), True
            If InStr(1, "|entity|reference|field|context|statement|uncertain|", "|" & V(input, i, "action") & "|", vbBinaryCompare) = 0 Or V(input, i, "action") = "" Then Err.Raise vbObjectError + 75, , "Unknown action at candidate " & V(input, i, "candidate_key")
            If V(input, i, "source_quote") = "" Then Err.Raise vbObjectError + 76, , "Every proposal needs an exact source quote."
        Else
            For j = 2 To input.ListColumns.Count
                If V(input, i, input.ListColumns(j).Name) <> "" Then Err.Raise vbObjectError + 77, , "A populated queue row is missing candidate_key."
            Next j
        End If
    Next i
    If MsgBox("Archive these drafts for " & F(4) & " / " & F(5) & " / version " & F(6) & "? Confirm Copilot has finished and processed parts metadata is correct.", vbYesNo + vbQuestion) <> vbYes Then Exit Sub
    BeginWrite: runID = NewID("R-")
    AddRow T("tRuns"), Array(runID, sourceID, CStr(ws.Range("C4").Value2), CStr(ws.Range("C5").Value2), LCase$(CStr(ws.Range("C6").Value2)), Stamp())
    For i = 1 To input.ListRows.Count
        If V(input, i, "candidate_key") <> "" Then
            ReDim a(0 To 18)
            a(0) = NewID("Q-"): a(1) = runID: a(2) = sourceID
            For j = 1 To 13: a(j + 2) = V(input, i, input.ListColumns(j).Name): Next j
            p = 0
            If IsNumeric(a(6)) Then
                If Val(a(6)) > 0 And Val(a(6)) < 2147483647# And Val(a(6)) = Fix(Val(a(6))) Then p = OccurrenceStart(s, CStr(a(5)), CLng(a(6)))
            End If
            If p = 0 And OccurrenceStart(s, CStr(a(5)), 1) > 0 And OccurrenceStart(s, CStr(a(5)), 2) = 0 Then
                a(6) = "1": p = OccurrenceStart(s, CStr(a(5)), 1)
            End If
            a(16) = "pending": a(17) = "": a(18) = CStr(p)
            If p = 0 Then a(16) = "needs_attention"
            ' Repeat-safe identical staging snapshot. Keys/interpretations are kept for changed proposals.
            duplicate = False
            For row = 1 To queue.ListRows.Count
                If V(queue, row, "source_id") = sourceID Then
                    duplicate = True
                    For j = 3 To 15
                        If V(queue, row, queue.ListColumns(j + 1).Name) <> CStr(a(j)) Then duplicate = False: Exit For
                    Next j
                    If duplicate Then Exit For
                End If
            Next row
            If duplicate Then
                a(16) = V(queue, row, "status"): a(17) = V(queue, row, "entry_id")
                ' Do not create a second pending candidate on a repeated snapshot.
                If a(16) = "pending" Or a(16) = "needs_attention" Then a(16) = "duplicate"
            End If
            AddRow queue, a
            text = "Candidate " & a(3) & ": " & a(4) & vbCrLf & a(5) & vbCrLf & "Reason: " & a(15)
            ArchiveAnalysis runID, sourceID, text
        End If
    Next i
    ArchiveAnalysis runID, sourceID, "Summary: " & CStr(ws.Range("C7").Value2)
    PruneAnalysis: ReopenNote sourceID: CommitWrite
    MsgBox "Queue snapshot saved. Load next AI draft on Review Desk. Missing/ambiguous quotes remain reviewable and cannot be accepted without correction.", vbInformation
    Exit Sub
Failed: AbortWrite Err.Description
End Sub

Private Sub ArchiveAnalysis(ByVal run As String, ByVal src As String, ByVal value As String)
    Dim p As Long, part As String, n As Long
    p = 1
    Do While p <= Len(value)
        part = SafeTake(value, p, 8000): n = n + 1
        AddRow T("tAnalysis"), Array(run, src, CStr(n), part, "prompt-v2", Stamp())
        p = p + Len(part)
    Loop
End Sub

Public Function ResolveKey(ByVal key As String, ByVal run As String, ByVal sourceID As String) As String
    Dim entities As ListObject, queue As ListObject, entries As Object, i As Long, r As Long, id As String, j As Long, ref As String
    If key = "" Then Exit Function
    Set entities = T("tEntities"): r = FindRow(entities, "entity_ref", key)
    If r > 0 Then
        If V(entities, r, "claim_number") = NoteClaim(sourceID) Then ResolveKey = key: Exit Function
    End If
    Set queue = T("tQueue"): Set entries = LatestEntries()
    For i = 1 To queue.ListRows.Count
        If V(queue, i, "run_id") = run And V(queue, i, "action") = "entity" And V(queue, i, "entity_key") = key Then
            id = V(queue, i, "entry_id")
            If id = "" And V(queue, i, "status") = "duplicate" Then
                For j = 1 To queue.ListRows.Count
                    If V(queue, j, "source_id") = sourceID And V(queue, j, "action") = "entity" And V(queue, j, "entity_key") = key And V(queue, j, "source_quote") = V(queue, i, "source_quote") And V(queue, j, "occurrence") = V(queue, i, "occurrence") Then
                        If V(queue, j, "status") = "accepted" Then id = V(queue, j, "entry_id"): Exit For
                    End If
                Next j
            End If
            If entries.Exists(id) Then
                r = entries(id)
                If V(T("tEntries"), r, "state") = "accepted" Then
                    If V(T("tEntries"), r, "action") = "entity" Or V(T("tEntries"), r, "action") = "reference" Then
                        ref = V(T("tEntries"), r, "entity_ref")
                        If FindRow(T("tEntities"), "entity_ref", ref) > 0 Then ResolveKey = ref: Exit Function
                    End If
                End If
            End If
        End If
    Next i
End Function

Public Sub LoadNextCandidate()
    Dim lo As ListObject, i As Long, best As Long, pos As Double, bestPos As Double, j As Long, key As String, ref As String, dependency As Long, dependencyMessage As String
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    If State("queue") <> "" Then
        i = FindRow(T("tQueue"), "queue_id", State("queue"))
        If i > 0 Then
            If V(T("tQueue"), i, "status") <> "accepted" And V(T("tQueue"), i, "status") <> "dismissed" Then
                MsgBox "The displayed candidate is still pending. Save it, delete it, or use New manual entry. Saved drafts remain available through Resume draft.", vbInformation
                Exit Sub
            End If
        End If
    End If
    Set lo = T("tQueue"): bestPos = 1E+20
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = State("source") Then
            If V(lo, i, "status") = "pending" Or V(lo, i, "status") = "needs_attention" Then
                pos = Val(V(lo, i, "start_utf16"))
                If pos = 0 Then pos = 1E+15 + i
                If pos < bestPos Then
                    best = i: bestPos = pos
                ElseIf pos = bestPos And best > 0 Then
                    If V(lo, i, "action") = "entity" And V(lo, best, "action") <> "entity" Then best = i
                End If
            End If
        End If
    Next i
    If best = 0 Then MsgBox "No pending candidates for this note. Read the full note and add anything missing before Complete note.": Exit Sub
    If V(lo, best, "action") <> "entity" Then
        dependency = RequiredEntityCandidate(best, "entity_key")
        If dependency = 0 Then dependency = RequiredEntityCandidate(best, "second_entity_key")
        If dependency > 0 Then
            dependencyMessage = "Required entity shown first; the earlier statement/reference remains pending. "
            best = dependency: bestPos = Val(V(lo, best, "start_utf16"))
        End If
    End If
    BlankEntry
    For j = 9 To 20: SetF j, V(lo, best, lo.ListColumns(j - 4).Name): Next j
    SetState "queue", V(lo, best, "queue_id")
    If F(9) <> "entity" Then
        key = F(12): ref = ResolveKey(key, V(lo, best, "run_id"), State("source")): SetF 12, ref
        If key <> "" And ref = "" Then SetF 20, F(20) & vbLf & "Choose accepted entity for draft key " & key & "."
    Else
        SetF 12, ""
    End If
    key = F(18): ref = ResolveKey(key, V(lo, best, "run_id"), State("source")): SetF 18, ref
    If key <> "" And ref = "" Then SetF 20, F(20) & vbLf & "Choose second entity for draft key " & key & "."
    RememberForm: SetF 22, dependencyMessage & "AI draft loaded. Check evidence and values before attesting."
    ThisWorkbook.Worksheets("Review Desk").Activate
    If bestPos < 1E+15 Then
        SetState "text_page", CStr(IIf(bestPos > 220, bestPos - 220, 1)): ShowTextPage
    End If
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Private Function RequiredEntityCandidate(ByVal candidate As Long, ByVal column As String) As Long
    Dim lo As ListObject, i As Long, key As String, run As String, src As String
    Set lo = T("tQueue"): key = V(lo, candidate, column): run = V(lo, candidate, "run_id"): src = V(lo, candidate, "source_id")
    If key = "" Then Exit Function
    If ResolveKey(key, run, src) <> "" Then Exit Function
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = src And V(lo, i, "run_id") = run And V(lo, i, "entity_key") = key And V(lo, i, "action") = "entity" Then
            If V(lo, i, "status") = "pending" Or V(lo, i, "status") = "needs_attention" Then RequiredEntityCandidate = i: Exit Function
        End If
    Next i
End Function
