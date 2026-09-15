; VRLab Toolbox installer.
; Built by build.ps1, which invokes: ISCC.exe toolbox_installer.iss /DMyAppVersion=<version>

#define MyAppName "VRLab Toolbox"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Stellenbosch University"
#define MyAppURL "https://www.sun.ac.za"
#define MyAppExeName "vrlab_toolbox_launcher.exe"
#define MyAppId "6C6E6F26-6E75-4B6D-9C0F-2F6F6C626F78"

[Setup]
; Three "{" here, not two: the preprocessor consumes "{#MyAppId}" and substitutes it with the
; raw GUID text *before* Inno's own "{{" (literal "{") escaping is evaluated, so "{{#MyAppId}"
; collapses to one unescaped "{" with no closing "}" -- a compile error. "{{{#MyAppId}}"
; preprocesses first to "{{" + "6C6E6F26-...-2F6F6C626F78" + "}", which is what "{{<guid>}"
; needs to be to begin with.
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\VRLabToolbox
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=VRLabToolboxSetup-{#MyAppVersion}
; Relative to this script's own directory (the repo root) -- keeps every build artifact
; under one gitignored build_output/ tree instead of a top-level Output/ folder.
OutputDir=build_output\installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\vrlab_icon.ico
; Every toolbox exe/dll about to be overwritten is checked for running processes that hold it
; open (Restart Manager) -- the wizard shows a "close these applications" page and can close
; them itself before any file is touched. This is Inno 6's own default; stated explicitly here
; so it can never be silently disabled by a future edit. RestartApplications=no because these
; are user-launched tools, not background services -- nothing should relaunch itself unasked
; right after setup finishes.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "build_output\toolbox\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\vrlab_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Icons]
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vrlab_icon.ico"; Tasks: desktopicon

[Code]
const
  WM_SETTINGCHANGE = $1A;
  SMTO_ABORTIFHUNG = $0002;

function SendMessageTimeoutA(hWnd: Integer; Msg: Integer; wParam: Integer; lParam: String;
  fuFlags: Integer; uTimeout: Integer; var lpdwResult: Integer): Integer;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure EnvBroadcastChange();
var
  Res: Integer;
begin
  SendMessageTimeoutA(HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment', SMTO_ABORTIFHUNG, 5000, Res);
end;

// Current-user PATH only (matches PrivilegesRequired=lowest -- no HKLM access).
procedure EnvAddPath(Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    Paths := '';

  if Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    exit;

  if (Length(Paths) > 0) and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + Path + ';';

  RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

procedure EnvRemovePath(Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;

  Delete(Paths, P - 1, Length(Path) + 1);
  RegWriteStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths);
end;

// PrivilegesRequired=lowest -- this installer only ever writes its own uninstall entry under
// HKCU, so that's the only hive a previous install of *this same product* (same AppId) could
// be registered under. Returns '' if none is found (fresh machine, or a differently-scoped
// install this Setup shouldn't touch).
function GetUninstallString(): String;
var
  UninstallKey: String;
  UninstallString: String;
begin
  // {#MyAppId} preprocesses to the bare GUID text with no braces (see the AppId= comment
  // in [Setup]) -- but the registry key Inno actually creates has the braces. They're added
  // here as their own literal string segments so nothing collapses them the way "{{" would.
  UninstallKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#MyAppId}' + '}_is1';
  if not RegQueryStringValue(HKCU, UninstallKey, 'QuietUninstallString', UninstallString) then
    RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', UninstallString);
  Result := UninstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

// QuietUninstallString (preferred by GetUninstallString above) is a full command line --
// '"<path>" /SILENT' -- not a bare path. RemoveQuotes only strips a leading/trailing quote
// *character*, so fed a string that doesn't end on a quote (because arguments follow it) it
// only strips the leading one, leaving the trailing '" /SILENT' stuck onto the path. This pulls
// out just the quoted (or, lacking quotes, whole) path and drops any trailing arguments --
// UninstallOldVersion supplies its own switches regardless of what was baked into this value.
function ExtractExePath(const CommandLine: String): String;
var
  ClosingQuote: Integer;
begin
  if (Length(CommandLine) > 0) and (CommandLine[1] = '"') then
  begin
    ClosingQuote := Pos('"', Copy(CommandLine, 2, Length(CommandLine) - 1));
    if ClosingQuote > 0 then
    begin
      Result := Copy(CommandLine, 2, ClosingQuote - 1);
      exit;
    end;
  end;
  Result := CommandLine;
end;

// Runs the previous version's own uninstaller fully silently and waits for it to finish, so
// the new version's [Files] always lands in a clean directory -- files the old version wrote
// that the new version no longer ships (a renamed/removed tool's stale .exe, say) are removed
// by the uninstaller instead of being left behind forever by Inno's default in-place file
// overwrite. Runs at ssInstall, i.e. after Setup's own CloseApplications/Restart-Manager check
// has already prompted to close anything holding those files open -- by this point nothing
// should still be locking them.
procedure UninstallOldVersion();
var
  UninstallString: String;
  ResultCode: Integer;
begin
  UninstallString := GetUninstallString();
  if UninstallString = '' then
    exit;
  UninstallString := ExtractExePath(UninstallString);
  Exec(UninstallString, '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if IsUpgrade() then
      UninstallOldVersion();
  end
  else if CurStep = ssPostInstall then
  begin
    EnvAddPath(ExpandConstant('{app}'));
    EnvBroadcastChange();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    EnvRemovePath(ExpandConstant('{app}'));
    EnvBroadcastChange();
  end;
end;
