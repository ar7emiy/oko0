Attribute VB_Name = "QADriver"
Option Explicit

' End-to-end exercise of the shipping modules in real Excel.
' Each test traps its own errors so one failure cannot hide the rest, and the
' log is flushed after every test so a hard crash still leaves partial results.

Private gNote As String
Private gSrc As String
Private gEntity As String
Private gLogPath As String

Private Function TutorialNote() As String
    TutorialNote = "Dr. Ada Monroe called regarding the claim. Dr. Ada Monroe is an orthopedic surgeon with Northstar Orthopedics, the medical provider." & vbLf & vbLf & _
      "She confirmed the clinic address as 14 Cedar Lane, Springfield, IL 62704. Its TIN is 001234567. The clinic did not schedule surgery." & vbLf & vbLf & _
      "The caller said they would send a report tomorrow. The note does not establish who they refers to."
End Function

Public Sub QARunAll()
    gLogPath = ThisWorkbook.Path & "\qa-results.txt"
    QAInit
    QAAnswer = 6
    QALog "=== END-TO-END RUN " & Format$(Now, "yyyy-mm-dd hh:nn:ss") & " ==="
    QALog "Excel " & Application.Version & " build " & Application.Build & " " & Application.OperatingSystem

    T01_Setup
    T02_SelfTests
    T03_NoteRoundTrip
    T04_LongNote
    T05_BoundaryNote
    T06_ManualEntity
    T07_RepeatedMention
    T08_LeadingZeroTIN
    T09_RejectHallucinatedQuote
    T10_RejectUncertainNoReason
    T11_QueueSnapshot
    T12_LoadCandidateAndEdit
    T13_SnapshotTwice
    T14_DeleteEntityWithDependents
    T15_CompleteBlockedByDraft
    T16_InjectedSaveFailure
    T17_ReopenMarksWatchlistRecheck

    QALog ""
    QALog "=== END ==="
    QAFlush gLogPath
End Sub

Private Sub Banner(ByVal caption As String)
    QALog ""
    QALog caption
    QAClearDialogs
End Sub

Private Sub T01_Setup()
    Dim n1 As Long, n2 As Long
    Banner "T01 SetupWorkbench, run twice"
    On Error GoTo Failed
    SetupWorkbench
    n1 = ThisWorkbook.Worksheets("Review Desk").Shapes.Count
    QACheck State("schema") = "assisted-1", "schema state set to assisted-1"
    QACheck n1 >= 15, "Review Desk buttons created (" & n1 & ")"
    SetupWorkbench
    n2 = ThisWorkbook.Worksheets("Review Desk").Shapes.Count
    QACheck n1 = n2, "second SetupWorkbench does not duplicate buttons (" & n1 & " -> " & n2 & ")"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T01 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T02_SelfTests()
    Banner "T02 RunCoreSelfTests"
    On Error GoTo Failed
    RunCoreSelfTests
    QACheck QASawDialog("Core tests passed"), "core self-tests report passing"
    QACheck Not QASawDialog("FAIL:"), "no self-test reported FAIL"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T02 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T03_NoteRoundTrip()
    Banner "T03 Capture note, reconstruct exactly"
    On Error GoTo Failed
    gNote = TutorialNote()
    gSrc = CaptureNote("QA01", "N01", 1, gNote)
    QACheck gSrc <> "", "CaptureNote returned a source id (" & gSrc & ")"
    QACheck FullNote(gSrc) = gNote, "FullNote reconstructs the note exactly"
    QACheck V(T("tNotes"), NoteRow(gSrc), "length_utf16") = CStr(Len(gNote)), "length_utf16 recorded as " & Len(gNote)
    QACheck OccurrenceStart(gNote, "Dr. Ada Monroe", 1) = 1, "first occurrence at unit 1"
    QACheck OccurrenceStart(gNote, "Dr. Ada Monroe", 2) > 1, "second occurrence found further in"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T03 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T04_LongNote()
    Dim big As String, src As String
    Banner "T04 100,000-unit note"
    On Error GoTo Failed
    big = "FIRST-100000-" & String$(100000 - 25, "x") & "-LAST-100000"
    QACheck Len(big) = 100000, "built a note of exactly 100000 UTF-16 units (" & Len(big) & ")"
    src = CaptureNote("QA02", "N01", 1, big)
    QACheck FullNote(src) = big, "100000-unit note reconstructs exactly"
    QACheck Left$(FullNote(src), 13) = "FIRST-100000-", "first text intact"
    QACheck Right$(FullNote(src), 12) = "-LAST-100000", "last text intact, no truncation"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T04 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T05_BoundaryNote()
    Dim s As String, src As String, emoji As String
    Banner "T05 emoji, combining accent, CRLF, quote across the 8000-unit part cut"
    On Error GoTo Failed
    emoji = ChrW(&HD83D) & ChrW(&HDE00)
    s = String$(7990, "x") & "STRADDLEBOUNDARY" & emoji & "e" & ChrW(&H301) & vbCrLf & "TAIL-MARKER-END"
    src = CaptureNote("QA03", "N01", 1, s)
    QACheck FullNote(src) = s, "boundary note reconstructs exactly"
    QACheck OccurrenceStart(FullNote(src), "STRADDLEBOUNDARY", 1) = 7991, "quote spanning the part cut still locates at 7991"
    QACheck InStr(FullNote(src), emoji) > 0, "surrogate-pair emoji survived chunking"
    QACheck InStr(FullNote(src), "e" & ChrW(&H301)) > 0, "combining accent survived as two code points"
    QACheck InStr(FullNote(src), vbCrLf) > 0, "CRLF preserved"
    QACheck Right$(FullNote(src), 15) = "TAIL-MARKER-END", "tail intact"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T05 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T06_ManualEntity()
    Dim before As Long
    Banner "T06 SME creates an entity by hand, no Copilot"
    On Error GoTo Failed
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    SetF 9, "entity": SetF 10, "Dr. Ada Monroe": SetF 11, "1"
    SetF 13, "Dr. Ada Monroe": SetF 14, "person"
    before = QARows("tEntries")
    AttestSave
    QACheck QARows("tEntries") = before + 1, "one accepted entry written"
    gEntity = F(12)
    QACheck gEntity <> "", "entity reference assigned (" & gEntity & ")"
    QACheck FindRow(T("tEntities"), "entity_ref", gEntity) > 0, "entity appears in the Entities output"
    QACheck V(T("tEntries"), QARows("tEntries"), "start_character") = "0", "first word starts at code point 0"
    QACheck V(T("tEntries"), QARows("tEntries"), "state") = "accepted", "state is accepted"
    QACheck QASawDialog("read enough of the source note"), "attestation was actually required"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T06 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T07_RepeatedMention()
    Dim entitiesBefore As Long, firstStart As String, secondStart As String
    Banner "T07 same quote, occurrence 2, links to the same entity"
    On Error GoTo Failed
    firstStart = V(T("tEntries"), QARows("tEntries"), "start_character")
    NewEntry
    SetF 9, "reference": SetF 10, "Dr. Ada Monroe": SetF 11, "2"
    SetF 12, gEntity: SetF 15, "name"
    entitiesBefore = QARows("tEntities")
    AttestSave
    secondStart = V(T("tEntries"), QARows("tEntries"), "start_character")
    QACheck V(T("tEntries"), QARows("tEntries"), "action") = "reference", "saved as a reference"
    QACheck secondStart <> firstStart, "different source span (" & firstStart & " vs " & secondStart & ")"
    QACheck V(T("tEntries"), QARows("tEntries"), "entity_ref") = gEntity, "points at the first Ada entity"
    QACheck QARows("tEntities") = entitiesBefore, "no duplicate entity created"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T07 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T08_LeadingZeroTIN()
    Banner "T08 TIN with leading zeros preserved"
    On Error GoTo Failed
    NewEntry
    SetF 9, "field": SetF 10, "001234567": SetF 11, "1"
    SetF 12, gEntity: SetF 16, "TIN": SetF 17, "001234567"
    AttestSave
    QACheck V(T("tEntries"), QARows("tEntries"), "field_value") = "001234567", "stored as 001234567, leading zeros intact"
    QACheck FindRow(T("tFields"), "value", "001234567") > 0, "Fields output carries the literal value"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T08 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T09_RejectHallucinatedQuote()
    Dim before As Long
    Banner "T09 quote that is not in the note is refused"
    On Error GoTo Failed
    NewEntry
    SetF 9, "entity": SetF 10, "Dr. Ada Munro": SetF 11, "1": SetF 13, "Dr. Ada Munro": SetF 14, "person"
    before = QARows("tEntries")
    AttestSave
    QACheck QARows("tEntries") = before, "nothing was written"
    QACheck QASawDialog("was not found"), "reviewer told the evidence was not found"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T09 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T10_RejectUncertainNoReason()
    Dim before As Long
    Banner "T10 uncertain with no explanation is refused"
    On Error GoTo Failed
    NewEntry
    SetF 9, "uncertain": SetF 10, "they": SetF 11, "1": SetF 20, ""
    before = QARows("tEntries")
    AttestSave
    QACheck QARows("tEntries") = before, "nothing was written"
    QACheck QASawDialog("Explain why"), "reviewer asked for a reason"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T10 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T11_QueueSnapshot()
    Dim ws As Worksheet, before As Long
    Banner "T11 stage AI queue rows and snapshot them"
    On Error GoTo Failed
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    Set ws = ThisWorkbook.Worksheets("AI Analysis Input")
    ws.Range("C4").Value2 = "qa-run-1"
    ws.Range("C5").Value2 = "1"
    ws.Range("C6").Value2 = "yes"
    ws.Range("C7").Value2 = "QA harness staging."
    ClearRows T("tInput")
    AddRow T("tInput"), Array("R1", "entity", "Northstar Orthopedics", "1", "O1", "Northstar Orthopedics", "organization", "", "", "", "", "", "")
    AddRow T("tInput"), Array("R2", "statement", "with Northstar Orthopedics", "1", "O1", "", "", "", "", "", "", "", "Proposed affiliation.")
    before = QARows("tQueue")
    SaveQueueSnapshot
    QACheck QARows("tQueue") = before + 2, "two candidates staged into Queue Store"
    QACheck V(T("tQueue"), QARows("tQueue") - 1, "status") = "pending", "first candidate pending"
    QACheck V(T("tQueue"), QARows("tQueue"), "status") = "pending", "second candidate pending"
    QACheck QARows("tAnalysis") > 0, "analysis archived to Recent AI Analysis"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T11 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T12_LoadCandidateAndEdit()
    Dim before As Long
    Banner "T12 load next candidate, correct it, accept the correction"
    On Error GoTo Failed
    LoadNextCandidate
    QACheck F(9) = "entity", "entity offered before the statement that depends on it (got " & F(9) & ")"
    QACheck F(10) = "Northstar Orthopedics", "form filled from the queue"
    SetF 13, "Northstar Orthopedics EDITED"
    before = QARows("tEntries")
    AttestSave
    QACheck QARows("tEntries") = before + 1, "candidate accepted"
    QACheck V(T("tEntries"), QARows("tEntries"), "display_name") = "Northstar Orthopedics EDITED", "SME edit persisted, not the AI wording"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T12 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T13_SnapshotTwice()
    Dim pendingBefore As Long, pendingAfter As Long, i As Long
    Banner "T13 snapshotting the identical queue again creates no new pending work"
    On Error GoTo Failed
    pendingBefore = 0
    For i = 1 To QARows("tQueue")
        If V(T("tQueue"), i, "status") = "pending" Then pendingBefore = pendingBefore + 1
    Next i
    SaveQueueSnapshot
    pendingAfter = 0
    For i = 1 To QARows("tQueue")
        If V(T("tQueue"), i, "status") = "pending" Then pendingAfter = pendingAfter + 1
    Next i
    QACheck pendingAfter <= pendingBefore, "no extra pending candidate created (" & pendingBefore & " -> " & pendingAfter & ")"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T13 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Function FindEntryFor(ByVal entityRef As String) As String
    Dim items As Object, key As Variant, lo As ListObject
    Set items = LatestEntries(): Set lo = T("tEntries")
    For Each key In items.Keys
        If V(lo, items(key), "entity_ref") = entityRef And V(lo, items(key), "action") = "entity" Then
            FindEntryFor = CStr(key): Exit Function
        End If
    Next key
End Function

Private Sub T14_DeleteEntityWithDependents()
    Dim before As Long
    Banner "T14 deleting an entity that has accepted dependents is blocked"
    On Error GoTo Failed
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    LoadEntry FindEntryFor(gEntity)
    before = QARows("tEntries")
    DeleteEntry
    QACheck QARows("tEntries") = before, "no retirement row written"
    QACheck QASawDialog("dependents"), "reviewer told about dependents"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T14 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub ResolveQueue()
    Dim i As Long, guard As Long, pending As Long
    Do
        pending = 0
        For i = 1 To QARows("tQueue")
            If V(T("tQueue"), i, "source_id") = gSrc Then
                If V(T("tQueue"), i, "status") = "pending" Or V(T("tQueue"), i, "status") = "needs_attention" Then pending = pending + 1
            End If
        Next i
        If pending = 0 Then Exit Do
        LoadNextCandidate
        DeleteEntry
        guard = guard + 1
    Loop While guard < 20
End Sub

Private Sub T15_CompleteBlockedByDraft()
    Banner "T15 completion gates: pending candidates, then unresolved drafts"
    On Error GoTo Failed
    OpenSource gSrc
    SetF 7, "QA Reviewer"

    ' Gate 1: a still-pending AI candidate blocks completion.
    CompleteNote
    QACheck QASawDialog("remaining AI candidates"), "completion refused while a candidate is pending"

    ResolveQueue
    QAClearDialogs

    ' Gate 2: with the queue clear, an unresolved draft still blocks completion.
    NewEntry
    SetF 9, "context": SetF 10, "orthopedic surgeon": SetF 11, "1": SetF 12, gEntity
    QACheck StoreDraft(), "draft saved"
    QAClearDialogs
    CompleteNote
    QACheck QASawDialog("drafts"), "completion refused while a draft is outstanding"
    QACheck V(T("tNotes"), NoteRow(gSrc), "status") <> "complete", "note not marked complete"

    ' Resolve every draft, then completion must actually succeed. More than one
    ' accumulates because this harness answers "Yes = save draft" to every
    ' dirty-form prompt; a real reviewer chooses per prompt.
    Dim guard As Long, r As Long
    Do
        r = FindRow(T("tDrafts"), "source_id", gSrc)
        If r = 0 Then Exit Do
        DeleteRow T("tDrafts"), r
        guard = guard + 1
    Loop While guard < 50
    QALog "      (cleared " & guard & " outstanding draft(s))"
    SetState "draft", ""
    NewEntry
    QAClearDialogs
    CompleteNote
    QACheck V(T("tNotes"), NoteRow(gSrc), "status") = "complete", "note completes once nothing is outstanding"
    QACheck FindRow(T("tDecisions"), "source_id", gSrc) > 0, "completion recorded in Decisions"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T15 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T17_ReopenMarksWatchlistRecheck()
    Dim before As String
    Dim guard As Long, r As Long
    Banner "T17 editing a completed note reopens it and flags watchlist rows for recheck"
    On Error GoTo Failed
    ' Re-complete first: T16's save legitimately reopened the note, so this test
    ' establishes its own starting state rather than depending on run order.
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    ResolveQueue
    Do
        r = FindRow(T("tDrafts"), "source_id", gSrc)
        If r = 0 Then Exit Do
        DeleteRow T("tDrafts"), r
        guard = guard + 1
    Loop While guard < 50
    SetState "draft", ""
    NewEntry
    QAClearDialogs
    CompleteNote
    AddRow T("tWatch"), Array("WR-QA", "batch:1", "QA01", "N01", "same_entity", "reviewer_note_evidence", "QA reason", "complete", gSrc, "QA Reviewer", Stamp())
    QACheck V(T("tNotes"), NoteRow(gSrc), "status") = "complete", "note starts complete"
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    NewEntry
    ' Evidence not used by any earlier test, so the duplicate guard cannot fire.
    SetF 9, "field": SetF 10, "14 Cedar Lane, Springfield, IL 62704": SetF 11, "1"
    SetF 12, gEntity: SetF 16, "address": SetF 17, "14 Cedar Lane, Springfield, IL 62704"
    QAClearDialogs
    AttestSave
    QACheck Not QASawDialog("already exists"), "the edit actually saved"
    QACheck V(T("tNotes"), NoteRow(gSrc), "status") = "in_progress", "note reopened to in_progress"
    QACheck V(T("tWatch"), FindRow(T("tWatch"), "pair_review_id", "WR-QA"), "review_status") = "recheck", "completed watchlist decision flagged recheck"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T17 raised: " & Err.Description
    QAFlush gLogPath
End Sub

Private Sub T16_InjectedSaveFailure()
    Dim before As Long, contextBefore As Long
    Banner "T16 injected pre-save failure rolls everything back"
    On Error GoTo Failed
    OpenSource gSrc
    SetF 7, "QA Reviewer"
    NewEntry
    SetF 9, "context": SetF 10, "medical provider": SetF 11, "1": SetF 12, gEntity
    before = QARows("tEntries"): contextBefore = QARows("tContext")
    InjectNextSaveFailure
    QAClearDialogs
    AttestSave
    QACheck QASawDialog("Injected pre-save failure"), "failure surfaced to the reviewer"
    QACheck QARows("tEntries") = before, "no accepted row survived the rollback"
    QACheck QARows("tContext") = contextBefore, "no output row survived the rollback"
    InjectNextSaveFailure
    QAClearDialogs
    AttestSave
    QACheck QARows("tEntries") = before + 1, "the same save succeeds once injection is off"
    QAFlush gLogPath
    Exit Sub
Failed: QACheck False, "T16 raised: " & Err.Description
    QAFlush gLogPath
End Sub
