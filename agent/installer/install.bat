@echo off
rem NOTE: this file is saved as CP949 (Korean ANSI). UTF-8 + chcp 65001 breaks cmd parsing.
echo ================================
echo   영수증리뷰 (ReceiptTap) 설치
echo ================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 goto need_admin

rem 압축을 어디에 풀었든(다운로드 폴더 등) 프로그램은 항상 C:\ReceiptTap 에 설치
set "APP=C:\ReceiptTap"
set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"

echo [1/4] 프로그램 복사 (%APP%)
taskkill /im ReceiptTap.exe /f >nul 2>&1
if /i "%SRC%"=="%APP%" goto copied
robocopy "%SRC%" "%APP%" /e /r:2 /w:2 /njh /njs /nfl /ndl /np >nul
if errorlevel 8 goto copy_fail
:copied
rem 자동 업데이트가 관리자 권한 없이 교체할 수 있게
icacls "%APP%" /grant *S-1-5-32-545:(OI)(CI)M /q >nul

rem SPMC: 카솔 등으로 이미 정상 설치된 PC는 건드리지 않음 (기존 프로그램 보호)
rem       예전에 다른 폴더에서 등록했는데 그 파일이 지워졌으면 새 위치로 다시 등록
set "SPMC_OK="
set "CLSID="
for /f "tokens=2,*" %%a in ('reg query "HKCR\hhdspmc.SerialMonitor\CLSID" /ve 2^>nul ^| findstr REG_SZ') do set "CLSID=%%b"
if not defined CLSID goto spmc_install
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\WOW6432Node\Classes\CLSID\%CLSID%\InprocServer32" /ve 2^>nul ^| findstr REG_SZ') do if exist "%%b" set "SPMC_OK=1"
for /f "tokens=2,*" %%a in ('reg query "HKLM\SOFTWARE\Classes\CLSID\%CLSID%\InprocServer32" /ve 2^>nul ^| findstr REG_SZ') do if exist "%%b" set "SPMC_OK=1"
if defined SPMC_OK goto spmc_skip

:spmc_install
echo [2/4] SPMC 드라이버 설치 중...
if exist "%APP%\drivers\hhdspmc.inf" pnputil /add-driver "%APP%\drivers\hhdspmc.inf" /install >nul
echo [3/4] SPMC 등록 중...
if exist "%APP%\hhdspmc.dll" "%SystemRoot%\SysWOW64\regsvr32.exe" /s "%APP%\hhdspmc.dll"
goto autorun

:spmc_skip
echo [2/4] SPMC 이미 설치됨 - 건너뜀
echo [3/4] SPMC 등록 이미 되어 있음 - 건너뜀

:autorun
echo [4/4] PC 켤 때 자동 실행 + 바탕화면 바로가기
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v ReceiptTap /t REG_SZ /d "\"%APP%\ReceiptTap.exe\" --autostart" /f >nul
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('CommonDesktopDirectory')+'\영수증리뷰.lnk');$s.TargetPath='%APP%\ReceiptTap.exe';$s.WorkingDirectory='%APP%';$s.Save()" >nul 2>&1

rem 관리자 권한이 아닌 일반 권한으로 실행
explorer.exe "%APP%\ReceiptTap.exe"

echo.
echo 설치 완료! 영수증리뷰가 실행됩니다. (설치 위치: %APP%)
echo 압축 푼 폴더는 지워도 됩니다.
echo 로그인 후 포스에서 영수증을 1장 출력하면 프린터가 자동으로 연결됩니다.
pause
exit /b 0

:need_admin
echo [!] 마우스 오른쪽 클릭 - "관리자 권한으로 실행" 으로 다시 실행해 주세요.
pause
exit /b 1

:copy_fail
echo [!] 복사 실패. 백신이 막았는지 확인해 주세요.
pause
exit /b 1
