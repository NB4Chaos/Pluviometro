' Inicia o Monitor de calibracao de pluviometros (Elus) SEM janela preta e abre o monitor no Chrome.
' Para encerrar o servidor use parar.bat.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
py = ""
If fso.FileExists(pasta & "\..\.venv\Scripts\pythonw.exe") Then py = pasta & "\..\.venv\Scripts\pythonw.exe"
If fso.FileExists(pasta & "\.venv\Scripts\pythonw.exe") Then py = pasta & "\.venv\Scripts\pythonw.exe"
If py = "" Then
  MsgBox "Nao encontrei o ambiente Python (.venv) nesta pasta nem na pasta acima.", 48, "Elus Monitor"
  WScript.Quit 1
End If
sh.CurrentDirectory = pasta
' ja esta rodando? entao so abre a janela
On Error Resume Next
Set http = CreateObject("MSXML2.XMLHTTP")
http.Open "GET", "http://127.0.0.1:5000/api/diag", False
http.Send
rodando = (Err.Number = 0 And http.Status = 200)
On Error GoTo 0
If Not rodando Then
  sh.Run """" & py & """ app.py", 0, False
  WScript.Sleep 3000
End If
' abre como site normal no Chrome (abas e barra de endereco); sem Chrome, no navegador padrao
url = "http://127.0.0.1:5000"
chrome = ""
pf = sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe"
pf86 = sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Google\Chrome\Application\chrome.exe"
la = sh.ExpandEnvironmentStrings("%LocalAppData%") & "\Google\Chrome\Application\chrome.exe"
If fso.FileExists(pf) Then chrome = pf
If chrome = "" And fso.FileExists(pf86) Then chrome = pf86
If chrome = "" And fso.FileExists(la) Then chrome = la
If chrome <> "" Then
  sh.Run """" & chrome & """ " & url, 1, False
Else
  sh.Run url, 1, False
End If
