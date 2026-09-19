Attribute VB_Name = "WorkbenchTests"
Option Explicit

Private Sub Check(ByVal ok As Boolean, ByVal message As String)
    If Not ok Then Err.Raise vbObjectError + 150, , "FAIL: " & message
End Sub

Public Sub RunCoreSelfTests()
    Dim s As String, emoji As String, i As Long, p As Long, reconstructed As String, piece As String
    Dim rows As Collection, schema As ListObject
    On Error GoTo Failed
    Check OccurrenceStart("Dr Ada called. Dr Ada replied.", "Dr Ada", 1) = 1, "first word"
    Check OccurrenceStart("Dr Ada called. Dr Ada replied.", "Dr Ada", 2) = 16, "second occurrence"
    Check OccurrenceStart("aaa", "aa", 2) = 2, "overlapping matches"
    Check OccurrenceStart("abc", "z", 1) = 0, "absent quote"
    emoji = ChrW(-10179) & ChrW(-8704)
    Check Codepoints("a" & emoji & "b") = 3, "Unicode code points"
    s = String$(7999, "x") & emoji & String$(95000, "y") & vbCrLf & "last"
    p = 1
    Do While p <= Len(s)
        piece = SafeTake(s, p, 8000)
        Check Len(piece) <= 8000, "part size"
        reconstructed = reconstructed & piece: p = p + Len(piece)
    Loop
    Check reconstructed = s, "100k note round trip"
    Check OccurrenceStart(s, "x" & emoji & "y", 1) = 7999, "cross-part evidence"
    Set rows = ParseCSV("name,zip,quote" & vbCrLf & "Ada,00123,""first" & vbCrLf & "second""" & vbCrLf)
    Check rows.Count = 2, "CSV multiline record"
    Check rows(2)(2) = "00123", "CSV leading zero"
    Check rows(2)(3) = "first" & vbCrLf & "second", "CSV exact newline"
    Check T("tEntries").ListColumns(5).Name = "action", "entry/form mapping"
    Check T("tQueue").ListColumns(5).Name = "action", "queue/form mapping"
    Check T("tDrafts").ListColumns(5).Name = "action", "draft/form mapping"
    Check NewID("A-") <> NewID("A-"), "durable distinct IDs"
    MsgBox "Core tests passed: evidence boundaries, Unicode, large notes, CSV fidelity, schema mappings, IDs. This does not replace the interactive acceptance checklist.", vbInformation
    Exit Sub
Failed: MsgBox Err.Description, vbCritical
End Sub

Public Sub InjectNextSaveFailure()
    TestFailBeforeSave = Not TestFailBeforeSave
    MsgBox "Pre-save failure injection is " & IIf(TestFailBeforeSave, "ON", "OFF") & ". Use only in a disposable QA copy.", vbInformation
End Sub
