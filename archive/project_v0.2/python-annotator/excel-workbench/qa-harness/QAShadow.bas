Attribute VB_Name = "QAShadow"
Option Explicit

' Test scaffolding only. Never import this into a real annotation workbook.
' A Public Function in a standard module shadows VBA's global MsgBox for every
' unqualified call project-wide, so the shipping modules run byte-for-byte
' unmodified while their dialogs are logged and auto-answered instead of
' blocking an unattended run.

Public QALines As Collection
Public QADialogs As Collection
Public QAAnswer As Long

Public Function MsgBox(ByVal Prompt As Variant, Optional ByVal Buttons As Variant, Optional ByVal Title As Variant, Optional ByVal HelpFile As Variant, Optional ByVal Context As Variant) As Long
    QAInit
    QADialogs.Add CStr(Prompt)
    QALines.Add "      [dialog] " & Left$(Replace(Replace(CStr(Prompt), vbCrLf, " "), vbLf, " "), 160)
    MsgBox = QAAnswer
End Function

Public Sub QAInit()
    If QALines Is Nothing Then Set QALines = New Collection
    If QADialogs Is Nothing Then Set QADialogs = New Collection
    If QAAnswer = 0 Then QAAnswer = 6
End Sub

Public Sub QALog(ByVal s As String)
    QAInit
    QALines.Add s
End Sub

Public Sub QACheck(ByVal ok As Boolean, ByVal label As String)
    QAInit
    If ok Then QALines.Add "  PASS  " & label Else QALines.Add "  FAIL  " & label
End Sub

Public Sub QAClearDialogs()
    Set QADialogs = New Collection
End Sub

Public Function QASawDialog(ByVal fragment As String) As Boolean
    Dim i As Long
    QAInit
    For i = 1 To QADialogs.Count
        If InStr(1, QADialogs(i), fragment, vbTextCompare) > 0 Then QASawDialog = True: Exit Function
    Next i
End Function

Public Function QARows(ByVal tableName As String) As Long
    QARows = T(tableName).ListRows.Count
End Function

Public Sub QAFlush(ByVal path As String)
    Dim f As Integer, i As Long
    QAInit
    f = FreeFile
    Open path For Output As #f
    For i = 1 To QALines.Count
        Print #f, QALines(i)
    Next i
    Close #f
End Sub
