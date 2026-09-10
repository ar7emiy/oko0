Attribute VB_Name = "ReviewWorkflow"
Option Explicit

Public Function F(ByVal r As Long) As String
    If IsError(ThisWorkbook.Worksheets("Review Desk").Cells(r, 3).Value2) Then Err.Raise vbObjectError + 40, , "Correct the Excel error in form row " & r
    F = CStr(ThisWorkbook.Worksheets("Review Desk").Cells(r, 3).Value2)
End Function

Public Sub SetF(ByVal r As Long, ByVal value As String)
    With ThisWorkbook.Worksheets("Review Desk").Cells(r, 3)
        .NumberFormat = "@": .Value2 = value
    End With
End Sub

Public Function FormSignature() As String
    Dim r As Long, s As String
    For r = 4 To 20
        s = s & Len(F(r)) & ":" & F(r)
    Next r
    FormSignature = s
End Function

Public Sub RememberForm()
    Dim r As Long
    For r = 4 To 20: SetState "form_" & r, F(r): Next r
    SetState "baseline", "recorded"
End Sub

Public Function FormDirty() As Boolean
    Dim r As Long
    If State("baseline") = "" Then Exit Function
    For r = 4 To 20
        If F(r) <> State("form_" & r) Then FormDirty = True: Exit Function
    Next r
End Function

Public Function CanLeave() As Boolean
    Dim choice As VbMsgBoxResult
    CanLeave = False
    If Busy Then Exit Function
    If FormDirty() Then
        choice = MsgBox("Unsaved changes: Yes = save draft; No = discard edits; Cancel = stay here.", vbYesNoCancel + vbQuestion)
        If choice = vbCancel Then Exit Function
        If choice = vbYes Then
            If Not StoreDraft() Then Exit Function
        Else
            RestoreForm
        End If
    End If
    CanLeave = True
End Function

Public Sub RestoreForm()
    Dim r As Long
    For r = 4 To 20: SetF r, State("form_" & r): Next r
End Sub

Public Sub BlankEntry()
    ThisWorkbook.Worksheets("Review Desk").Range("C9:C20").ClearContents
    SetF 9, "entity": SetF 11, "1"
    SetState "entry", "": SetState "queue", "": SetState "draft", ""
    RememberForm
End Sub

Public Sub OpenSource(ByVal sourceID As String)
    Dim n As Long
    n = NoteRow(sourceID)
    SetState "source", sourceID: SetState "text_page", "1"
    SetF 4, V(T("tNotes"), n, "claim_number"): SetF 5, V(T("tNotes"), n, "note_id"): SetF 6, V(T("tNotes"), n, "version")
    BlankEntry
    ThisWorkbook.Worksheets("Review Desk").Activate
    ShowTextPage: RefreshDesk
End Sub

Public Sub NewEntry()
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    If State("source") = "" Then Err.Raise vbObjectError + 41, , "Select a note first."
    BlankEntry: SetF 22, "Manual draft. Nothing accepted yet."
    Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Function StoreDraft() As Boolean
    Dim lo As ListObject, id As String, r As Long
    On Error GoTo Failed
    If State("source") = "" Then Err.Raise vbObjectError + 42, , "Select a note before saving a draft."
    BeginWrite: Set lo = T("tDrafts"): id = State("draft")
    If id = "" Then id = NewID("D-")
    r = FindRow(lo, "draft_id", id)
    If r > 0 Then lo.ListRows(r).Delete
    AddRow lo, Array(id, State("source"), State("queue"), State("entry"), F(9), F(10), F(11), F(12), F(13), F(14), F(15), F(16), F(17), F(18), F(19), F(20), F(7))
    SetState "draft", id: RememberForm: SetF 22, "Draft saved; not attested."
    CommitWrite: StoreDraft = True: Exit Function
Failed: AbortWrite Err.Description
End Function

Public Sub SaveDraft()
    If StoreDraft() Then MsgBox "Draft saved. It is not an accepted annotation.", vbInformation
End Sub

Public Sub ResumeDraft()
    Dim lo As ListObject, i As Long, list As String, ids As Collection, choice As Variant, r As Long, j As Long
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    Set lo = T("tDrafts"): Set ids = New Collection
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = State("source") Then
            ids.Add i: list = list & ids.Count & ": " & V(lo, i, "action") & " - " & Left$(V(lo, i, "source_quote"), 45) & vbCrLf
        End If
    Next i
    If ids.Count = 0 Then MsgBox "No saved drafts for this note.": Exit Sub
    If Len(list) > 900 Then list = "See Drafts for details. Enter a position from 1 to " & ids.Count
    choice = Application.InputBox(list, "Resume saved draft", Type:=1)
    If VarType(choice) = vbBoolean Then Exit Sub
    If choice < 1 Or choice > ids.Count Or choice <> Fix(choice) Then Exit Sub
    r = ids(CLng(choice))
    SetState "draft", V(lo, r, "draft_id"): SetState "entry", V(lo, r, "entry_id"): SetState "queue", V(lo, r, "queue_id")
    For j = 9 To 20: SetF j, V(lo, r, lo.ListColumns(j - 4).Name): Next j
    SetF 7, V(lo, r, "reviewer"): RememberForm: SetF 22, "Resumed draft; not attested.": Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub NeedEntity(ByVal ref As String)
    Dim lo As ListObject, r As Long
    Set lo = T("tEntities"): r = FindRow(lo, "entity_ref", ref)
    If r = 0 Or ref = "" Then Err.Raise vbObjectError + 43, , "Choose an accepted entity. A local AI key is not an accepted entity reference."
    If V(lo, r, "claim_number") <> NoteClaim(State("source")) Then Err.Raise vbObjectError + 44, , "Entity belongs to another claim."
End Sub

Public Function ValidateForm() As Long
    Dim src As String, n As Long, p As Long, action As String, occ As Double, s As String, qr As Long
    src = State("source"): n = NoteRow(src)
    If F(4) <> V(T("tNotes"), n, "claim_number") Or F(5) <> V(T("tNotes"), n, "note_id") Or F(6) <> V(T("tNotes"), n, "version") Then Err.Raise vbObjectError + 45, , "Claim/note/version changed in the form. Use Select note to switch sources."
    If V(T("tNotes"), n, "status") = "superseded" Then Err.Raise vbObjectError + 46, , "This source version is superseded. Select its latest version."
    If Trim$(F(7)) = "" Then Err.Raise vbObjectError + 47, , "Enter your reviewer name before attesting."
    If ContainsFormula(ThisWorkbook.Worksheets("Review Desk").Range("C4:C20")) Then Err.Raise vbObjectError + 64, , "Use literal text in the annotation form, not formulas."
    If Not IsNumeric(F(11)) Then Err.Raise vbObjectError + 48, , "Occurrence must be a positive whole number."
    occ = CDbl(F(11))
    If occ < 1 Or occ <> Fix(occ) Or occ > 2147483646# Then Err.Raise vbObjectError + 49, , "Invalid occurrence number."
    s = FullNote(src): p = OccurrenceStart(s, F(10), CLng(occ))
    If p = 0 Then Err.Raise vbObjectError + 50, , "Exact evidence was not found at this occurrence. Use Locate evidence."
    action = F(9)
    Select Case action
    Case "entity"
        If Trim$(F(13)) = "" Then SetF 13, F(10)
        If Trim$(F(14)) = "" Then SetF 14, "unknown"
    Case "reference"
        NeedEntity F(12)
        If InStr(1, "|name|alias|pronoun|description|", "|" & F(15) & "|", vbBinaryCompare) = 0 Or F(15) = "" Then Err.Raise vbObjectError + 51, , "Choose a valid reference form."
    Case "field"
        NeedEntity F(12)
        If F(16) = "" Or F(17) = "" Then Err.Raise vbObjectError + 52, , "Field kind and field value are required."
        If InStr(1, "|entity_name|address|city|state|zip_code|phone|TIN|other|", "|" & F(16) & "|", vbBinaryCompare) = 0 Then Err.Raise vbObjectError + 53, , "Choose a valid field kind."
    Case "context", "statement"
        NeedEntity F(12)
        If action = "statement" And F(18) <> "" Then NeedEntity F(18)
        qr = FindRow(T("tQueue"), "queue_id", State("queue"))
        If action = "statement" And qr > 0 And F(18) = "" Then
            If V(T("tQueue"), qr, "second_entity_key") <> "" Then
                If MsgBox("The AI proposed a second entity but none is selected. Intentionally save this as a one-entity statement?", vbYesNo + vbQuestion) <> vbYes Then Err.Raise vbObjectError + 65, , "Choose the second entity or mark the statement uncertain."
            End If
        End If
    Case "uncertain"
        If F(20) = "" Then Err.Raise vbObjectError + 54, , "Explain why this evidence cannot be resolved."
        If F(12) <> "" Then NeedEntity F(12)
    Case Else
        Err.Raise vbObjectError + 55, , "Choose an entry kind from the list."
    End Select
    ValidateForm = p
End Function

Private Function HasDependents(ByVal entityRef As String, ByVal ownEntry As String) As Boolean
    Dim entries As Object, id As Variant, r As Long, lo As ListObject
    Set entries = LatestEntries(): Set lo = T("tEntries")
    For Each id In entries.Keys
        r = entries(id)
        If id <> ownEntry And V(lo, r, "state") = "accepted" Then
            If V(lo, r, "entity_ref") = entityRef Or V(lo, r, "second_entity_ref") = entityRef Then HasDependents = True: Exit Function
        End If
    Next id
End Function

Public Sub AttestSave()
    Dim p As Long, src As String, s As String, id As String, ent As String, rev As Long, old As Long
    Dim lo As ListObject, items As Object, key As Variant, r As Long, qr As Long, startCP As Long, endCP As Long
    On Error GoTo Failed
    If Busy Then Exit Sub
    p = ValidateForm(): src = State("source"): s = FullNote(src)
    id = State("entry"): Set lo = T("tEntries"): Set items = LatestEntries()
    If id <> "" Then
        If items.Exists(id) Then old = items(id)
    End If
    If old > 0 Then
        If Not FormDirty() And V(lo, old, "state") = "accepted" Then MsgBox "This revision is already saved.": Exit Sub
        If V(lo, old, "action") = "entity" And F(9) <> "entity" Then
            If HasDependents(V(lo, old, "entity_ref"), id) Then Err.Raise vbObjectError + 56, , "Reassign dependent entries before changing this entity into another kind."
        End If
        rev = CLng(V(lo, old, "revision"))
    End If
    startCP = Codepoints(Left$(s, p - 1)): endCP = startCP + Codepoints(F(10))
    For Each key In items.Keys
        r = items(key)
        If key <> id And V(lo, r, "state") = "accepted" And V(lo, r, "source_id") = src And V(lo, r, "action") = F(9) And V(lo, r, "start_character") = CStr(startCP) And V(lo, r, "end_character") = CStr(endCP) Then
            If V(lo, r, "entity_ref") = F(12) Or F(9) = "entity" Then
                If V(lo, r, "field_kind") = F(16) And V(lo, r, "second_entity_ref") = F(18) Then Err.Raise vbObjectError + 57, , "This annotation already exists. Use Previous/Next reviewed entry to revise it."
            End If
        End If
    Next key
    If MsgBox(ThisWorkbook.Worksheets("Review Desk").Range("C24").Value2 & vbCrLf & vbCrLf & "Attest and save this entry?", vbYesNo + vbQuestion, "Reviewer attestation") <> vbYes Then Exit Sub
    BeginWrite
    If id = "" Then id = NewID("A-")
    ent = F(12)
    If F(9) = "entity" Then
        ent = "E-" & Mid$(id, 3)
        If old > 0 Then
            If V(lo, old, "action") = "entity" Then ent = V(lo, old, "entity_ref")
        End If
        SetF 12, ent
    End If
    ' Remove irrelevant values before persistence, avoiding stale fields across action changes.
    If F(9) <> "entity" Then SetF 13, "": SetF 14, ""
    If F(9) <> "reference" Then SetF 15, ""
    If F(9) <> "field" Then SetF 16, "": SetF 17, ""
    If F(9) <> "statement" Then SetF 18, ""
    AddRow lo, Array(id, CStr(rev + 1), "accepted", src, F(9), F(10), F(11), ent, F(13), F(14), F(15), F(16), F(17), F(18), F(19), F(20), CStr(startCP), CStr(endCP), State("queue"), F(7), Stamp(), "entry-v1")
    qr = FindRow(T("tQueue"), "queue_id", State("queue"))
    If qr > 0 Then
        Put T("tQueue"), qr, "status", "accepted": Put T("tQueue"), qr, "entry_id", id
    End If
    For r = T("tDrafts").ListRows.Count To 1 Step -1
        If V(T("tDrafts"), r, "draft_id") = State("draft") Or V(T("tDrafts"), r, "entry_id") = id Then
            T("tDrafts").ListRows(r).Delete
        ElseIf State("queue") <> "" Then
            If V(T("tDrafts"), r, "queue_id") = State("queue") Then T("tDrafts").ListRows(r).Delete
        End If
    Next r
    ReopenNote src: RebuildOutputs
    SetState "entry", id: SetState "draft", "": RememberForm
    SetF 22, "Saved revision " & rev + 1 & ": " & id
    CommitWrite
    RefreshDesk
    Exit Sub
Failed: AbortWrite Err.Description
End Sub

Public Sub LoadEntry(ByVal id As String)
    Dim items As Object, lo As ListObject, r As Long, j As Long
    Set items = LatestEntries(): Set lo = T("tEntries")
    If Not items.Exists(id) Then Err.Raise vbObjectError + 58, , "Entry no longer exists."
    r = items(id): OpenSource V(lo, r, "source_id")
    For j = 9 To 20: SetF j, V(lo, r, lo.ListColumns(j - 4).Name): Next j
    SetState "entry", id: SetState "queue", V(lo, r, "queue_id")
    RememberForm: SetF 22, "Accepted revision " & V(lo, r, "revision") & ". Edits require a new attestation."
End Sub

Private Sub NavigateEntry(ByVal direction As Long)
    Dim items As Object, ids() As String, positions() As Double, key As Variant, r As Long, count As Long, i As Long, j As Long, tmp As String, pos As Double, current As Long
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    Set items = LatestEntries()
    ReDim ids(1 To items.Count + 1): ReDim positions(1 To items.Count + 1)
    For Each key In items.Keys
        r = items(key)
        If V(T("tEntries"), r, "source_id") = State("source") And V(T("tEntries"), r, "state") = "accepted" Then
            count = count + 1: ids(count) = key: positions(count) = Val(V(T("tEntries"), r, "start_character"))
        End If
    Next key
    For i = 2 To count
        j = i
        Do While j > 1
            If positions(j - 1) <= positions(j) Then Exit Do
            pos = positions(j): positions(j) = positions(j - 1): positions(j - 1) = pos
            tmp = ids(j): ids(j) = ids(j - 1): ids(j - 1) = tmp: j = j - 1
        Loop
    Next i
    For i = 1 To count
        If ids(i) = State("entry") Then current = i
    Next i
    If current = 0 Then
        If direction < 0 Then current = count + 1
    End If
    current = current + direction
    If current < 1 Or current > count Then MsgBox "No more accepted entries in this direction.": Exit Sub
    LoadEntry ids(current): Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub PreviousEntry()
    NavigateEntry -1
End Sub
Public Sub NextEntry()
    NavigateEntry 1
End Sub

Public Sub DeleteEntry()
    Dim items As Object, r As Long, lo As ListObject, a As Variant, j As Long, qr As Long
    On Error GoTo Failed
    If MsgBox("Delete/dismiss the displayed entry? Accepted history remains. Unsaved edits will be discarded.", vbYesNo + vbQuestion) <> vbYes Then Exit Sub
    Set items = LatestEntries(): Set lo = T("tEntries")
    If items.Exists(State("entry")) Then
        r = items(State("entry"))
        If V(lo, r, "action") = "entity" Then
            If HasDependents(V(lo, r, "entity_ref"), State("entry")) Then Err.Raise vbObjectError + 59, , "This entity has accepted dependents. Reassign them first."
        End If
    End If
    BeginWrite
    If r > 0 Then
        ReDim a(0 To lo.ListColumns.Count - 1)
        For j = 1 To lo.ListColumns.Count: a(j - 1) = V(lo, r, lo.ListColumns(j).Name): Next j
        a(1) = CStr(CLng(a(1)) + 1): a(2) = "retired": a(19) = F(7): a(20) = Stamp()
        AddRow lo, a
    End If
    qr = FindRow(T("tQueue"), "queue_id", State("queue"))
    If qr > 0 Then Put T("tQueue"), qr, "status", "dismissed"
    r = FindRow(T("tDrafts"), "draft_id", State("draft"))
    If r > 0 Then T("tDrafts").ListRows(r).Delete
    ReopenNote State("source"): RebuildOutputs: BlankEntry: SetF 22, "Entry deleted/dismissed; history retained."
    CommitWrite: RefreshDesk: Exit Sub
Failed: AbortWrite Err.Description
End Sub

Public Sub ChooseEntity()
    Dim lo As ListObject, ids As Collection, i As Long, list As String, choice As Variant
    On Error GoTo Failed
    Set lo = T("tEntities"): Set ids = New Collection
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "claim_number") = NoteClaim(State("source")) Then
            ids.Add V(lo, i, "entity_ref"): list = list & ids.Count & ": " & V(lo, i, "display_label") & vbCrLf
        End If
    Next i
    If ids.Count = 0 Then MsgBox "No accepted entities in this claim. Create one first.": Exit Sub
    If Len(list) > 900 Then list = "See Entities sheet for the full list. Enter a position from 1 to " & ids.Count
    choice = Application.InputBox(list, "Choose entity (primary reference)", Type:=1)
    If VarType(choice) = vbBoolean Then Exit Sub
    If choice < 1 Or choice > ids.Count Or choice <> Fix(choice) Then Exit Sub
    SetF 12, ids(CLng(choice)): Exit Sub
Failed: MsgBox Err.Description, vbExclamation
End Sub

Public Sub RefreshDesk()
    Dim lo As ListObject, i As Long, row As Long
    Set lo = T("tEntities"): row = 24
    ThisWorkbook.Worksheets("Review Desk").Range("G24:G35").ClearContents
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "claim_number") = F(4) Then
            If row > 34 Then
                ThisWorkbook.Worksheets("Review Desk").Range("G35").Value2 = "More entities: use Choose entity or Entities tab."
                Exit For
            End If
            ThisWorkbook.Worksheets("Review Desk").Cells(row, 7).Value2 = V(lo, i, "display_label") & " | " & V(lo, i, "entity_ref")
            row = row + 1
        End If
    Next i
End Sub

Public Sub CompleteNote()
    Dim lo As ListObject, i As Long, src As String
    On Error GoTo Failed
    If Not CanLeave Then Exit Sub
    src = State("source")
    If Trim$(F(7)) = "" Then Err.Raise vbObjectError + 60, , "Enter reviewer name."
    If V(T("tNotes"), NoteRow(src), "status") = "superseded" Then Err.Raise vbObjectError + 61, , "Complete the latest source version."
    Set lo = T("tQueue")
    For i = 1 To lo.ListRows.Count
        If V(lo, i, "source_id") = src Then
            If V(lo, i, "status") <> "accepted" And V(lo, i, "status") <> "dismissed" And V(lo, i, "status") <> "duplicate" Then Err.Raise vbObjectError + 62, , "Review or dismiss remaining AI candidates first."
        End If
    Next i
    If FindRow(T("tDrafts"), "source_id", src) > 0 Then Err.Raise vbObjectError + 63, , "Resume and resolve saved drafts before completing the note."
    If MsgBox("I have reviewed the entire note, resolved the proposed entries, and added any missing annotations required by the annotation guide.", vbYesNo + vbQuestion, "Note completeness attestation") <> vbYes Then Exit Sub
    BeginWrite
    Put T("tNotes"), NoteRow(src), "status", "complete"
    AddRow T("tDecisions"), Array(NewID("D-"), src, "", "note-complete-v1", F(7), Stamp())
    RememberForm: SetF 22, "Note complete. Watchlist review is now available."
    CommitWrite: Exit Sub
Failed: AbortWrite Err.Description
End Sub
