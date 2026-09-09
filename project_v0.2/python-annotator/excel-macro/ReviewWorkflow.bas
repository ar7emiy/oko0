Attribute VB_Name = "ReviewWorkflow"
Option Explicit

Private Const DESK As String = "Review Desk"

Private Function D() As Worksheet
    Set D = ThisWorkbook.Worksheets(DESK)
End Function

Private Function EmptyText() As String
    EmptyText = Trim$(CStr(D.Range("B8").Value))
End Function

Private Function ReadyForEvidence() As Boolean
    ReadyForEvidence = False
    If Trim$(CStr(D.Range("C4").Value)) = "" Then
        MsgBox "Enter the claim number first.", vbExclamation, "Claim number needed"
        Exit Function
    End If
    If Trim$(CStr(D.Range("C5").Value)) = "" Then
        MsgBox "Enter the note ID first.", vbExclamation, "Note ID needed"
        Exit Function
    End If
    If EmptyText = "" Then
        MsgBox "Copy the exact words from Notepad and paste them into the Selected source text box.", vbExclamation, "Source text needed"
        Exit Function
    End If
    ReadyForEvidence = True
End Function

Private Function NextRow(ByVal sheetName As String) As Long
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(sheetName)
    NextRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1
    If NextRow < 2 Then NextRow = 2
End Function

Private Function NextId(ByVal sheetName As String, ByVal prefix As String) As String
    Dim ws As Worksheet, lastRow As Long
    Set ws = ThisWorkbook.Worksheets(sheetName)
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    If lastRow < 2 Then
        NextId = prefix & "1"
    Else
        NextId = prefix & CStr(lastRow)
    End If
End Function

Private Function EntityExists(ByVal entityRef As String) As Boolean
    Dim ws As Worksheet, found As Range
    Set ws = ThisWorkbook.Worksheets("Entities")
    Set found = ws.Columns(1).Find(What:=Trim$(entityRef), LookIn:=xlValues, LookAt:=xlWhole)
    EntityExists = Not found Is Nothing
End Function

Private Function IsSealed(ByVal claimNumber As String) As Boolean
    Dim ws As Worksheet, found As Range
    Set ws = ThisWorkbook.Worksheets("Sealed Claims")
    Set found = ws.Columns(1).Find(What:=Trim$(claimNumber), LookIn:=xlValues, LookAt:=xlWhole)
    IsSealed = Not found Is Nothing
End Function

Private Sub NeedExistingEntity(ByVal entityRef As String)
    If Trim$(entityRef) = "" Then Err.Raise vbObjectError + 100, , "Enter or choose an entity reference."
    If Not EntityExists(entityRef) Then Err.Raise vbObjectError + 101, , "That entity reference does not exist. Use Refresh entity list and copy an E-number from the left panel."
End Sub

Private Sub FinishEvidence(ByVal message As String)
    D.Range("B8").ClearContents
    D.Range("C16").ClearContents
    D.Range("C17").ClearContents
    D.Range("C18").ClearContents
    D.Range("C19").ClearContents
    D.Range("C21").ClearContents
    D.Range("C22").ClearContents
    D.Range("C23").ClearContents
    D.Range("C28").ClearContents
    D.Range("C29").ClearContents
    D.Range("C30").ClearContents
    D.Range("C31").ClearContents
    RefreshDesk
    D.Range("B8").Select
    MsgBox message, vbInformation, "Saved"
End Sub

Public Sub NewEntity()
    Dim ws As Worksheet, rowN As Long, entityRef As String, displayName As String
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    displayName = Trim$(CStr(D.Range("C16").Value))
    If displayName = "" Then displayName = EmptyText
    Set ws = ThisWorkbook.Worksheets("Entities")
    rowN = NextRow("Entities")
    entityRef = NextId("Entities", "E")
    ws.Cells(rowN, 1).Resize(1, 7).Value = Array(entityRef, D.Range("C4").Value, displayName, D.Range("C17").Value, D.Range("C5").Value, EmptyText, "observed")
    AddMention entityRef, "name", "Reviewer created named entity"
    D.Range("C15").Value = entityRef
    D.Range("C16").ClearContents
    D.Range("C17").ClearContents
    FinishEvidence "Created " & entityRef & " and recorded its first named mention."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot save entity"
End Sub

Private Sub AddMention(ByVal entityRef As String, ByVal form As String, ByVal reason As String)
    Dim ws As Worksheet, rowN As Long
    Set ws = ThisWorkbook.Worksheets("Mentions")
    rowN = NextRow("Mentions")
    ws.Cells(rowN, 1).Resize(1, 9).Value = Array(NextId("Mentions", "M"), D.Range("C4").Value, D.Range("C5").Value, EmptyText, "", "", entityRef, form, reason)
End Sub

Public Sub LinkReference()
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    NeedExistingEntity D.Range("C15").Value
    If Trim$(CStr(D.Range("C18").Value)) = "" Then Err.Raise vbObjectError + 102, , "Choose the reference form: name, alias, pronoun, or description."
    AddMention D.Range("C15").Value, D.Range("C18").Value, "Reviewer linked reference"
    FinishEvidence "Linked this reference to " & D.Range("C15").Value & "."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot link reference"
End Sub

Public Sub RecordField()
    Dim ws As Worksheet, rowN As Long, valueText As String
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    NeedExistingEntity D.Range("C15").Value
    If Trim$(CStr(D.Range("C19").Value)) = "" Then Err.Raise vbObjectError + 103, , "Choose the kind of stated value."
    Set ws = ThisWorkbook.Worksheets("Fields")
    rowN = NextRow("Fields")
    valueText = EmptyText
    ws.Cells(rowN, 1).Resize(1, 10).Value = Array(NextId("Fields", "F"), D.Range("C4").Value, D.Range("C5").Value, D.Range("C15").Value, D.Range("C19").Value, valueText, EmptyText, "", "", "observed")
    FinishEvidence "Recorded the stated field value for " & D.Range("C15").Value & "."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot record field"
End Sub

Public Sub RecordContext()
    Dim ws As Worksheet, rowN As Long
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    NeedExistingEntity D.Range("C15").Value
    Set ws = ThisWorkbook.Worksheets("Context")
    rowN = NextRow("Context")
    ws.Cells(rowN, 1).Resize(1, 9).Value = Array(NextId("Context", "C"), D.Range("C4").Value, D.Range("C5").Value, D.Range("C15").Value, EmptyText, "", "", D.Range("C22").Value, D.Range("C23").Value)
    FinishEvidence "Recorded the exact descriptive wording for " & D.Range("C15").Value & "."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot record context"
End Sub

Public Sub RecordStatement()
    Dim ws As Worksheet, rowN As Long
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    NeedExistingEntity D.Range("C15").Value
    If Trim$(CStr(D.Range("C21").Value)) <> "" Then NeedExistingEntity D.Range("C21").Value
    Set ws = ThisWorkbook.Worksheets("Statements")
    rowN = NextRow("Statements")
    ws.Cells(rowN, 1).Resize(1, 10).Value = Array(NextId("Statements", "S"), D.Range("C4").Value, D.Range("C5").Value, EmptyText, "", "", D.Range("C15").Value, D.Range("C21").Value, D.Range("C22").Value, D.Range("C23").Value)
    FinishEvidence "Recorded the exact statement wording and its linked entity or entities."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot record statement"
End Sub

Public Sub MarkUncertain()
    Dim ws As Worksheet, rowN As Long
    On Error GoTo Problem
    If Not ReadyForEvidence Then Exit Sub
    If Trim$(CStr(D.Range("C23").Value)) = "" Then Err.Raise vbObjectError + 104, , "State why the wording cannot be resolved."
    Set ws = ThisWorkbook.Worksheets("Uncertain")
    rowN = NextRow("Uncertain")
    ws.Cells(rowN, 1).Resize(1, 8).Value = Array(NextId("Uncertain", "U"), D.Range("C4").Value, D.Range("C5").Value, EmptyText, "", "", D.Range("C23").Value, D.Range("C15").Value)
    FinishEvidence "Saved this span as uncertain."
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot mark uncertainty"
End Sub

Public Sub RefreshDesk()
    Dim ws As Worksheet, rowN As Long, lastRow As Long, outRow As Long, claimNumber As String, entityRef As String, evidence As String
    Dim i As Long
    Set ws = ThisWorkbook.Worksheets("Entities")
    claimNumber = Trim$(CStr(D.Range("C4").Value))
    D.Range("J6:M35").ClearContents
    D.Range("J6:M6").Value = Array("Entity ref", "Display name", "Type", "Mentions")
    outRow = 7
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For i = 2 To lastRow
        If CStr(ws.Cells(i, 2).Value) = claimNumber Then
            D.Cells(outRow, 10).Resize(1, 4).Value = Array(ws.Cells(i, 1).Value, ws.Cells(i, 3).Value, ws.Cells(i, 4).Value, MentionCount(CStr(ws.Cells(i, 1).Value)))
            outRow = outRow + 1
        End If
    Next i
    entityRef = Trim$(CStr(D.Range("C15").Value))
    D.Range("J39:M55").UnMerge
    D.Range("J38:M55").ClearContents
    D.Range("J38").Value = "Evidence for selected entity"
    If entityRef <> "" Then
        evidence = EntityEvidence(entityRef)
        D.Range("J39").Value = evidence
    Else
        D.Range("J39").Value = "Enter an entity ref, then click Refresh entity list."
    End If
    D.Range("J39:M55").Merge
    D.Range("J39").WrapText = True
    D.Range("J39").VerticalAlignment = xlTop
    D.Range("J39").HorizontalAlignment = xlLeft
End Sub

Private Function MentionCount(ByVal entityRef As String) As Long
    Dim ws As Worksheet, lastRow As Long, i As Long
    Set ws = ThisWorkbook.Worksheets("Mentions")
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For i = 2 To lastRow
        If CStr(ws.Cells(i, 7).Value) = entityRef Then MentionCount = MentionCount + 1
    Next i
End Function

Private Function EntityEvidence(ByVal entityRef As String) As String
    Dim textOut As String
    textOut = "MENTIONS" & vbCrLf & MatchLines("Mentions", 7, entityRef, 3, 4)
    textOut = textOut & vbCrLf & "FIELDS" & vbCrLf & MatchLines("Fields", 4, entityRef, 5, 7)
    textOut = textOut & vbCrLf & "SOURCE CONTEXT" & vbCrLf & MatchLines("Context", 4, entityRef, 3, 5)
    textOut = textOut & vbCrLf & "STATEMENTS" & vbCrLf & StatementLines(entityRef)
    EntityEvidence = textOut
End Function

Private Function MatchLines(ByVal sheetName As String, ByVal matchColumn As Long, ByVal entityRef As String, ByVal noteColumn As Long, ByVal textColumn As Long) As String
    Dim ws As Worksheet, lastRow As Long, i As Long, outText As String
    Set ws = ThisWorkbook.Worksheets(sheetName)
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For i = 2 To lastRow
        If CStr(ws.Cells(i, matchColumn).Value) = entityRef Then outText = outText & ws.Cells(i, noteColumn).Value & ": “" & ws.Cells(i, textColumn).Value & "”" & vbCrLf
    Next i
    If outText = "" Then outText = "None yet." & vbCrLf
    MatchLines = outText
End Function

Private Function StatementLines(ByVal entityRef As String) As String
    Dim ws As Worksheet, lastRow As Long, i As Long, outText As String
    Set ws = ThisWorkbook.Worksheets("Statements")
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For i = 2 To lastRow
        If CStr(ws.Cells(i, 7).Value) = entityRef Or CStr(ws.Cells(i, 8).Value) = entityRef Then outText = outText & ws.Cells(i, 3).Value & ": “" & ws.Cells(i, 4).Value & "”" & vbCrLf
    Next i
    If outText = "" Then outText = "None yet." & vbCrLf
    StatementLines = outText
End Function

Public Sub SealClaim()
    Dim claimNumber As String, ws As Worksheet, rowN As Long
    claimNumber = Trim$(CStr(D.Range("C4").Value))
    If claimNumber = "" Then
        MsgBox "Enter the claim number first.", vbExclamation
        Exit Sub
    End If
    If IsSealed(claimNumber) Then
        MsgBox "This claim is already sealed.", vbInformation
        Exit Sub
    End If
    If MsgBox("Seal this claim's Gold annotation? You can still reopen it manually if correction is needed.", vbYesNo + vbQuestion, "Seal Gold annotation") <> vbYes Then Exit Sub
    Set ws = ThisWorkbook.Worksheets("Sealed Claims")
    rowN = NextRow("Sealed Claims")
    ws.Cells(rowN, 1).Resize(1, 2).Value = Array(claimNumber, Now)
    MsgBox "Gold annotation is sealed for " & claimNumber & ". You may now load and review its watchlist matches.", vbInformation
End Sub

Public Sub ImportClientOutput()
    Dim picked As Variant, sourceBook As Workbook, target As Worksheet, sourceSheet As Worksheet, lastImportedRow As Long, i As Long
    picked = Application.GetOpenFilename("Excel and CSV files (*.xlsx;*.xls;*.csv),*.xlsx;*.xls;*.csv", , "Choose the client export")
    If picked = False Then Exit Sub
    Application.ScreenUpdating = False
    Set target = ThisWorkbook.Worksheets("Raw Client Output")
    target.Cells.Clear
    Set sourceBook = Workbooks.Open(CStr(picked), ReadOnly:=True)
    Set sourceSheet = sourceBook.Worksheets(1)
    sourceSheet.UsedRange.Copy target.Range("A1")
    sourceBook.Close SaveChanges:=False
    target.Columns(1).Insert
    target.Cells(1, 1).Value = "client_row_id"
    lastImportedRow = target.Cells(target.Rows.Count, 2).End(xlUp).Row
    For i = 2 To lastImportedRow
        target.Cells(i, 1).Value = "CR" & CStr(i - 1)
    Next i
    target.Rows(1).Font.Bold = True
    Application.ScreenUpdating = True
    MsgBox "Client output loaded. It remains on the hidden source sheet until a claim is sealed.", vbInformation
End Sub

Public Sub LoadWatchlistMatches()
    On Error GoTo Problem
    Dim claimNumber As String, noteID As String, raw As Worksheet, target As Worksheet
    Dim lastRow As Long, i As Long, outRow As Long, uiRow As Long, flagCol As Long, claimCol As Long, exactCol As Long, genCol As Long
    Dim idCol As Long, entityCol As Long, watchlistCol As Long, scoreCol As Long
    claimNumber = Trim$(CStr(D.Range("C4").Value)): noteID = Trim$(CStr(D.Range("C5").Value))
    If Not IsSealed(claimNumber) Then Err.Raise vbObjectError + 200, , "Seal the claim's Gold annotation before reviewing client watchlist matches."
    Set raw = ThisWorkbook.Worksheets("Raw Client Output"): Set target = ThisWorkbook.Worksheets("Watchlist Candidates")
    target.Rows("2:" & target.Rows.Count).ClearContents
    claimCol = HeaderColumn(raw, "claim_number"): flagCol = HeaderColumn(raw, "Entity_Watchlist_flag")
    exactCol = HeaderColumn(raw, "Exact_search_Note_ID"): genCol = HeaderColumn(raw, "GenAI_search_Note_ID")
    idCol = HeaderColumn(raw, "client_row_id"): entityCol = HeaderColumn(raw, "entity_name")
    watchlistCol = HeaderColumn(raw, "Watchlist_entity_name"): scoreCol = HeaderColumn(raw, "GenAI_tok_sort_similarity")
    lastRow = raw.Cells(raw.Rows.Count, claimCol).End(xlUp).Row: outRow = 2
    For i = 2 To lastRow
        If CStr(raw.Cells(i, claimCol).Value) = claimNumber And IsTrue(raw.Cells(i, flagCol).Value) Then
            If CStr(raw.Cells(i, exactCol).Value) = noteID Or CStr(raw.Cells(i, genCol).Value) = noteID Then
                target.Cells(outRow, 1).Resize(1, 6).Value = Array(raw.Cells(i, idCol).Value, claimNumber, noteID, raw.Cells(i, entityCol).Value, raw.Cells(i, watchlistCol).Value, raw.Cells(i, scoreCol).Value)
                outRow = outRow + 1
            End If
        End If
    Next i
    D.Range("J58:M75").ClearContents
    D.Range("J58:M58").Value = Array("Client row", "System entity", "Watchlist candidate", "Similarity")
    If outRow = 2 Then
        D.Range("J59").Value = "No flagged client matches cite this note."
    Else
        uiRow = 59
        For i = 2 To outRow - 1
            D.Cells(uiRow, 10).Resize(1, 4).Value = Array(target.Cells(i, 1).Value, target.Cells(i, 4).Value, target.Cells(i, 5).Value, target.Cells(i, 6).Value)
            uiRow = uiRow + 1
        Next i
    End If
    MsgBox "Loaded the current note's watchlist candidates into the lower-right panel.", vbInformation
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot load watchlist matches"
End Sub

Private Function HeaderColumn(ByVal ws As Worksheet, ByVal headerName As String) As Long
    Dim found As Range
    Set found = ws.Rows(1).Find(What:=headerName, LookIn:=xlValues, LookAt:=xlWhole)
    If found Is Nothing Then Err.Raise vbObjectError + 201, , "Client output is missing required column: " & headerName
    HeaderColumn = found.Column
End Function

Private Function IsTrue(ByVal rawValue As Variant) As Boolean
    Dim valueText As String
    valueText = LCase$(Trim$(CStr(rawValue)))
    IsTrue = valueText = "1" Or valueText = "true" Or valueText = "yes" Or valueText = "y"
End Function

Public Sub SaveWatchlistDecision()
    Dim ws As Worksheet, rowN As Long
    On Error GoTo Problem
    If Not IsSealed(Trim$(CStr(D.Range("C4").Value))) Then Err.Raise vbObjectError + 202, , "Seal Gold annotation before saving a watchlist decision."
    If Trim$(CStr(D.Range("C28").Value)) = "" Then Err.Raise vbObjectError + 203, , "Enter the client row ID shown in the lower-right panel."
    If Trim$(CStr(D.Range("C29").Value)) = "" Then Err.Raise vbObjectError + 204, , "Choose same_entity, different_entity, or insufficient_evidence."
    Set ws = ThisWorkbook.Worksheets("Watchlist Review"): rowN = NextRow("Watchlist Review")
    ws.Cells(rowN, 1).Resize(1, 8).Value = Array(NextId("Watchlist Review", "WR"), D.Range("C28").Value, D.Range("C4").Value, D.Range("C5").Value, D.Range("C29").Value, D.Range("C30").Value, D.Range("C31").Value, "complete")
    D.Range("C28").ClearContents
    D.Range("C29").ClearContents
    D.Range("C30").ClearContents
    D.Range("C31").ClearContents
    MsgBox "Saved the watchlist decision.", vbInformation
    Exit Sub
Problem:
    MsgBox Err.Description, vbExclamation, "Cannot save watchlist decision"
End Sub
