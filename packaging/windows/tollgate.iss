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
OutputDir=out
OutputBaseFilename=tollgate-setup-{#Version}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Tollgate

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Run Tollgate in the background when I sign in"

[Files]
Source: "..\..\dist\Tollgate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Tollgate"; Filename: "{app}\Tollgate.exe"
Name: "{autoprograms}\Tollgate"; Filename: "{app}\Tollgate.exe"
Name: "{autodesktop}\Tollgate"; Filename: "{app}\Tollgate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tollgate.exe"; Description: "Launch Tollgate"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Tollgate.exe"; Parameters: "service uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveLoginService"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  ExePath: String;
begin
  Result := '';
  ExePath := ExpandConstant('{app}\Tollgate.exe');
  { Old releases have no service command. Stop supported services before files
    are replaced so Windows does not keep the running executable locked. }
  if FileExists(ExePath) then
    if Exec(ExePath, 'service --help', ExpandConstant('{app}'), SW_HIDE,
      ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
      if not Exec(ExePath, 'service stop', ExpandConstant('{app}'), SW_HIDE,
        ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
        Result := 'Could not stop the Tollgate background service. Stop it and retry.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Arguments: String;
begin
  if CurStep = ssPostInstall then begin
    if WizardIsTaskSelected('autostart') then
      Arguments := 'service install --working-directory "' + ExpandConstant('{app}') + '"'
    else
      Arguments := 'service uninstall';
    if not Exec(ExpandConstant('{app}\Tollgate.exe'), Arguments,
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode)
      or (ResultCode <> 0) then
      MsgBox('Tollgate was installed, but its sign-in service could not be configured. ' +
        'Run Tollgate.exe service install from the installation directory and check ' +
        'Task Scheduler for details.', mbError, MB_OK);
  end;
end;
