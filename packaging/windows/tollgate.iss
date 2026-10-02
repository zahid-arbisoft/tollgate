; Inno Setup script — per-user install, NO admin rights required.
; Build:  iscc /DVersion=x.y.z packaging\windows\tollgate.iss
; Requires the PyInstaller output in packaging\..\dist\Tollgate\

#define Version GetEnv("TOLLGATE_VERSION")
#if Version == ""
  #define Version "0.1.0"
#endif

[Setup]
AppId={{7C4B2A91-52D8-4E1F-9B6C-TOLLGATE01}
AppName=Tollgate
AppVersion={#Version}
AppPublisher=Tollgate
DefaultDirName={localappdata}\Programs\Tollgate
DefaultGroupName=Tollgate
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=packaging\windows\out
OutputBaseFilename=tollgate-setup-{#Version}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Tollgate

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\Tollgate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Tollgate"; Filename: "{app}\Tollgate.exe"
Name: "{autoprograms}\Tollgate"; Filename: "{app}\Tollgate.exe"
Name: "{autodesktop}\Tollgate"; Filename: "{app}\Tollgate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tollgate.exe"; Description: "Launch Tollgate"; Flags: nowait postinstall skipifsilent
