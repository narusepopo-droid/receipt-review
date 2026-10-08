; ReceiptTap Installer Script
; Inno Setup 6.x

#define MyAppName "ReceiptTap"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "광고토대왕"
#define MyAppURL "https://review.placemaster.co.kr"
#define MyAppExeName "ReceiptTap.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=ReceiptTap_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main Application
Source: "..\ReceiptTap.App\bin\Release\net462\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

; SPMC Redistributable (if not already installed)
; Source: "spmc_redist.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not IsSPMCInstalled

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Start the application after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Auto-start tray app
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ReceiptTap"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\ReceiptTap\logs"
; Ask user about config and queue
Type: dirifempty; Name: "{commonappdata}\ReceiptTap"

[Messages]
korean.WelcomeLabel2=이 프로그램은 [name]을(를) 설치합니다.%n%n설치 후 활성화 코드를 입력해야 사용할 수 있습니다.%n활성화 코드는 광고토대왕 담당자에게 문의하세요.

[Code]
function IsSPMCInstalled: Boolean;
begin
  // Check if SPMC is already installed (카솔 매장 등)
  Result := FileExists(ExpandConstant('{sys}\hhdspmc.dll')) or
            FileExists(ExpandConstant('{pf32}\HHD Software\Serial Port Monitoring Control\spmc.dll'));
end;

function InitializeSetup: Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  // Check Windows version (Windows 7 SP1 or later required for .NET 4.6.2)
  if not IsWin64 then
  begin
    MsgBox('64비트 Windows가 필요합니다.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  // Check .NET Framework 4.6.2
  if not RegKeyExists(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full') then
  begin
    if MsgBox('.NET Framework 4.6.2 이상이 필요합니다. 설치하시겠습니까?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      // Open download page
      ShellExec('open', 'https://dotnet.microsoft.com/download/dotnet-framework/net462', '', '', SW_SHOW, ewNoWait, ResultCode);
    end;
    Result := False;
    Exit;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Ask about removing config and queue
    if MsgBox('설정 파일과 대기 중인 데이터를 삭제하시겠습니까?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{commonappdata}\ReceiptTap'), True, True, True);
    end;
  end;
end;
