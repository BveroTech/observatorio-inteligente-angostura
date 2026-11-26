; Instalador del Observatorio Inteligente de Aves (Inno Setup 6).
; No se compila a mano: lo hace scripts\windows\construir_ejecutable.py, que pasa
;   /DVersion=1.0.0  /DCarpetaApp=...\dist\Observatorio  /DSalida=...\dist
;
; Se instala POR USUARIO en %LOCALAPPDATA%\Programs\Observatorio Angostura (sin
; permisos de administrador): el programa guarda su base de datos, capturas y fotos
; junto a los .exe, y "Archivos de programa" no permite escribir ahí.
; Al actualizar o desinstalar se CONSERVAN data\, config\observatorio.ini y
; config\camara_local.json.

#ifndef Version
  #define Version "1.0.0"
#endif
#ifndef CarpetaApp
  #define CarpetaApp "..\..\dist\Observatorio"
#endif
#ifndef Salida
  #define Salida "..\..\dist"
#endif
#define Regla "Observatorio Aves - Portal admin (TCP 5000)"

[Setup]
AppId={{6C1F2B7E-3B0E-4E2B-9E5D-0A7B5C1D2E41}
AppName=Observatorio Inteligente de Aves
AppVersion={#Version}
AppVerName=Observatorio Inteligente de Aves {#Version}
AppPublisher=Observatorio Inteligente Angostura
DefaultDirName={userpf}\Observatorio Angostura
DefaultGroupName=Observatorio de Aves
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#Salida}
OutputBaseFilename=Instalar_Observatorio_{#Version}
SetupIconFile={#CarpetaApp}\observatorio.ico
UninstallDisplayIcon={app}\Observatorio.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear accesos directos en el escritorio"; GroupDescription: "Accesos directos:"
Name: "inicio"; Description: "Abrir el Observatorio al iniciar sesión en Windows (kiosco)"; GroupDescription: "Kiosco:"; Flags: unchecked
Name: "firewall"; Description: "Permitir abrir el portal desde otros computadores de la red (pide permiso de administrador)"; GroupDescription: "Portal de administración:"

[Files]
; Todo el programa, menos lo que el usuario edita (se instala aparte, solo si no existe)
Source: "{#CarpetaApp}\*"; DestDir: "{app}"; Excludes: "config\observatorio.ini,data\observatorio.db"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#CarpetaApp}\config\observatorio.ini"; DestDir: "{app}\config"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#CarpetaApp}\data\observatorio.db"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist

[Icons]
Name: "{group}\Observatorio de Aves"; Filename: "{app}\Observatorio.exe"; WorkingDir: "{app}"
Name: "{group}\Observatorio (cámara IP)"; Filename: "{app}\Observatorio.exe"; Parameters: "--fuente rtsp"; WorkingDir: "{app}"
Name: "{group}\Observatorio (captura de pantalla)"; Filename: "{app}\Observatorio.exe"; Parameters: "--fuente pantalla"; WorkingDir: "{app}"
Name: "{group}\Observatorio (captura de una aplicación)"; Filename: "{app}\Observatorio.exe"; Parameters: "--fuente ventana"; WorkingDir: "{app}"
Name: "{group}\Portal de administración"; Filename: "{app}\Admin.exe"; WorkingDir: "{app}"
Name: "{group}\Crear usuario del portal"; Filename: "{app}\Admin.exe"; Parameters: "--crear-usuario"; WorkingDir: "{app}"
Name: "{group}\Traducir fichas (inglés y alemán)"; Filename: "{app}\Admin.exe"; Parameters: "--traducir-fichas"; WorkingDir: "{app}"
Name: "{group}\Ver monitores"; Filename: "{app}\Admin.exe"; Parameters: "--detectar-pantallas"; WorkingDir: "{app}"
Name: "{group}\Configuración"; Filename: "{win}\notepad.exe"; Parameters: """{app}\config\observatorio.ini"""; IconFilename: "{app}\observatorio.ico"
Name: "{group}\Cámara IP (dirección RTSP)"; Filename: "{win}\notepad.exe"; Parameters: """{app}\config\camara_local.json"""; IconFilename: "{app}\observatorio.ico"
Name: "{group}\Carpeta de datos"; Filename: "{app}\data"
Name: "{group}\Léame"; Filename: "{app}\LEEME.txt"
Name: "{group}\Desinstalar"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Observatorio de Aves"; Filename: "{app}\Observatorio.exe"; WorkingDir: "{app}"; Tasks: escritorio
Name: "{autodesktop}\Portal de administración"; Filename: "{app}\Admin.exe"; WorkingDir: "{app}"; Tasks: escritorio
Name: "{userstartup}\Observatorio de Aves"; Filename: "{app}\Observatorio.exe"; WorkingDir: "{app}"; Tasks: inicio

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#Regla}"""; Flags: runhidden shellexec waituntilterminated; Verb: runas; Tasks: firewall; StatusMsg: "Configurando el firewall..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#Regla}"" dir=in action=allow protocol=TCP localport=5000 profile=private,domain"; Flags: runhidden shellexec waituntilterminated; Verb: runas; Tasks: firewall
Filename: "{app}\Admin.exe"; Parameters: "--crear-usuario"; WorkingDir: "{app}"; Description: "Crear ahora el usuario del portal de administración"; Flags: postinstall nowait skipifsilent
Filename: "{app}\Observatorio.exe"; WorkingDir: "{app}"; Description: "Abrir el Observatorio"; Flags: postinstall nowait skipifsilent unchecked

[Code]
// config\camara_local.json: se crea desde el ejemplo solo si no existe (nunca se pisa la dirección configurada).
procedure CurStepChanged(CurStep: TSetupStep);
var
  Destino: String;
begin
  if CurStep = ssPostInstall then
  begin
    Destino := ExpandConstant('{app}\config\camara_local.json');
    if not FileExists(Destino) then
      FileCopy(ExpandConstant('{app}\config\camara_local.ejemplo.json'), Destino, True);
  end;
end;
