@echo off
chcp 65001 >nul
echo ================================
echo   영수증리뷰 (ReceiptTap) 설치
echo ================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [!] 마우스 오른쪽 클릭 - "관리자 권한으로 실행" 으로 다시 실행해 주세요.
    pause
    exit /b 1
)

rem 카솔 등으로 SPMC가 이미 설치된 PC는 건드리지 않음 (기존 프로그램 보호)
reg query "HKCR\hhdspmc.SerialMonitor" >nul 2>&1
if %errorLevel% equ 0 (
    echo [1/2] SPMC 이미 설치됨 - 건너뜀
    echo [2/2] SPMC 등록 이미 되어 있음 - 건너뜀
    goto done
)

echo [1/2] SPMC 드라이버 설치 중...
if exist "%~dp0drivers\hhdspmc.inf" (
    pnputil /add-driver "%~dp0drivers\hhdspmc.inf" /install
)

echo [2/2] SPMC 등록 중...
if exist "%~dp0hhdspmc.dll" (
    "%SystemRoot%\SysWOW64\regsvr32.exe" /s "%~dp0hhdspmc.dll"
)

:done
echo.
echo 완료! ReceiptTap.exe 를 실행하세요.
echo 실행 후 포스에서 영수증을 1장 출력하면 프린터가 자동으로 연결됩니다.
pause
