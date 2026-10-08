; 영수증리뷰 (ReceiptTap) 설치 스크립트 - Inno Setup 6
; 빌드: scripts\build_agent.ps1 이 버전을 넘겨줌 (ISCC /DMyAppVersion=1.1.1 ...)

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\ReceiptTap.App\bin\Release\net462"
#endif

#define MyAppName "영수증리뷰"
#define MyAppPublisher "광고토대왕"
#define MyAppURL "https://placemaster.co.kr/receipt-review.html"
#define MyAppExeName "ReceiptTap.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\ReceiptTap
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=Output
OutputBaseFilename=ReceiptTap_Setup_{#MyAppVersion}
SetupIconFile=..\ReceiptTap.App\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
; 32비트 윈도우(구형 포스)도 설치 가능. 64비트에서는 64비트 모드
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=6.1sp1
CloseApplications=force
SetupLogging=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Dirs]
; 자동 업데이트가 관리자 권한 없이 파일을 교체할 수 있도록 일반 사용자 쓰기 권한
Name: "{app}"; Permissions: users-modify
Name: "{commonappdata}\ReceiptTap"; Permissions: users-modify

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "*.pdb,*.xml"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Registry]
; 어떤 계정으로 로그인해도 자동 실행 (포스는 보통 자동 로그인)
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ReceiptTap"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue
; 예전 버전(zip 설치)이 남긴 사용자별 자동 실행 제거
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "ReceiptTap"; ValueType: none; Flags: deletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "영수증리뷰 실행"; Flags: nowait postinstall runasoriginaluser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillAgent"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\ReceiptTap\logs"
Type: filesandordirs; Name: "{commonappdata}\ReceiptTap\updates"

[Messages]
korean.WelcomeLabel2=[name] 프로그램을 설치합니다.%n%n설치가 끝나면 로그인 후, 포스에서 영수증을 1장 출력해 주세요.%n프린터가 자동으로 연결됩니다.

[Code]
function IsSPMCRegistered: Boolean;
begin
  // 카솔 등으로 SPMC가 이미 등록된 PC는 건드리지 않음 (기존 프로그램 보호)
  Result := RegKeyExists(HKCR, 'hhdspmc.SerialMonitor');
end;

function IsDotNet462Installed: Boolean;
var
  Release: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release)
            and (Release >= 394802);
end;

function InitializeSetup: Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not IsDotNet462Installed then
  begin
    if MsgBox('.NET Framework 4.6.2 이상이 필요합니다.' + #13#10 + '다운로드 페이지를 열까요? (설치 후 다시 실행해 주세요)',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://dotnet.microsoft.com/download/dotnet-framework/net48', '', '', SW_SHOW, ewNoWait, ResultCode);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // 실행 중인 프로그램 종료 (파일 교체를 위해)
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

procedure InstallSpmc;
var
  ResultCode: Integer;
  Inf, RegSvr: String;
begin
  if IsSPMCRegistered then
  begin
    Log('SPMC already registered - skip');
    exit;
  end;

  Inf := ExpandConstant('{app}\drivers\hhdspmc.inf');
  WizardForm.StatusLabel.Caption := 'SPMC 드라이버 설치 중...';
  // Windows 10 이상
  if not Exec(ExpandConstant('{sys}\pnputil.exe'), '/add-driver "' + Inf + '" /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
     or (ResultCode <> 0) then
    // Windows 7/8 문법
    Exec(ExpandConstant('{sys}\pnputil.exe'), '-i -a "' + Inf + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('pnputil result: ' + IntToStr(ResultCode));

  // hhdspmc.dll 은 32비트 COM → 64비트 윈도우에서는 SysWOW64 의 regsvr32 사용
  if IsWin64 then
    RegSvr := ExpandConstant('{win}\SysWOW64\regsvr32.exe')
  else
    RegSvr := ExpandConstant('{sys}\regsvr32.exe');
  WizardForm.StatusLabel.Caption := 'SPMC 등록 중...';
  Exec(RegSvr, '/s "' + ExpandConstant('{app}\hhdspmc.dll') + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('regsvr32 result: ' + IntToStr(ResultCode));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallSpmc;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('설정 파일(로그인 정보)과 전송 대기 중인 데이터도 삭제할까요?', mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{commonappdata}\ReceiptTap'), True, True, True);
  end;
end;
