# 영수증리뷰 에이전트 릴리스 스크립트
# 사용법: .\scripts\release.ps1 1.1.0 "버그 수정 및 안정성 개선"

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [Parameter(Mandatory=$false)]
    [string]$ReleaseNotes = "버그 수정 및 안정성 개선"
)

$ErrorActionPreference = "Stop"

Write-Host "===== 영수증리뷰 에이전트 v$Version 릴리스 =====" -ForegroundColor Cyan

# 1. 버전 업데이트 (CaptureService.cs)
Write-Host "`n[1/5] 버전 업데이트 중..." -ForegroundColor Yellow
$captureServicePath = "agent\ReceiptTap.App\CaptureService.cs"
$content = Get-Content $captureServicePath -Raw
$content = $content -replace 'public const string VERSION = "[^"]+";', "public const string VERSION = `"$Version`";"
Set-Content $captureServicePath $content -Encoding UTF8
Write-Host "  CaptureService.cs 버전: $Version" -ForegroundColor Green

# 2. 에이전트 빌드
Write-Host "`n[2/5] 에이전트 빌드 중..." -ForegroundColor Yellow
Push-Location agent
dotnet build -c Release
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    throw "빌드 실패"
}
Pop-Location
Write-Host "  빌드 완료" -ForegroundColor Green

# 3. Inno Setup으로 설치파일 생성
Write-Host "`n[3/5] 설치 파일 생성 중..." -ForegroundColor Yellow
$innoPath = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $innoPath)) {
    Write-Host "  [경고] Inno Setup이 설치되지 않음 - 설치파일 생성 건너뜀" -ForegroundColor Yellow
    Write-Host "  수동으로 설치파일을 생성한 후 GitHub Release에 업로드하세요" -ForegroundColor Yellow
} else {
    & $innoPath "agent\installer\ReceiptTap.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "설치파일 생성 실패"
    }
    Write-Host "  설치 파일 생성 완료" -ForegroundColor Green
}

# 4. Git 커밋
Write-Host "`n[4/5] Git 커밋 중..." -ForegroundColor Yellow
git add -A
git commit -m "v$Version 릴리스`n`n$ReleaseNotes"
git push
Write-Host "  커밋 & 푸시 완료" -ForegroundColor Green

# 5. GitHub Release 생성
Write-Host "`n[5/5] GitHub Release 생성 중..." -ForegroundColor Yellow
$installerPath = "agent\installer\Output\ReceiptTap_Setup.exe"

if (Test-Path $installerPath) {
    gh release create "v$Version" $installerPath --title "v$Version" --notes $ReleaseNotes
    Write-Host "  릴리스 완료: v$Version" -ForegroundColor Green
} else {
    # 설치파일 없이 릴리스 (나중에 수동 업로드)
    gh release create "v$Version" --title "v$Version" --notes "$ReleaseNotes`n`n(설치 파일은 수동으로 업로드 필요)"
    Write-Host "  릴리스 생성 (설치파일 없음 - 수동 업로드 필요)" -ForegroundColor Yellow
}

Write-Host "`n===== 릴리스 완료! =====" -ForegroundColor Cyan
Write-Host "모든 매장의 에이전트가 6시간 내에 자동 업데이트됩니다." -ForegroundColor White
