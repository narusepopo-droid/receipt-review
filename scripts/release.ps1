# 영수증리뷰 에이전트 빌드 + 배포
#
# 사용법 (프로젝트 루트에서):
#   .\scripts\release.ps1                       # 빌드만 (dist\ 에 Setup.exe + zip 생성)
#   .\scripts\release.ps1 -Publish -Notes "변경 내용"   # 빌드 + 서버 업로드 + 최신 버전 지정
#
# 버전은 agent\ReceiptTap.App\ReceiptTap.App.csproj 의 <Version> 한 곳에서 관리.
# -Publish 하면:
#   1) 서버 다운로드 폴더에 Setup.exe(첫 설치용)와 zip(자동 업데이트용) 업로드
#   2) latest.json 갱신 → 사이트 다운로드 버튼과 설치된 프로그램 자동 업데이트에 즉시 반영
param(
    [switch]$Publish,
    [switch]$ZipOnly,   # 첫 설치도 zip 으로 (설치 파일 테스트 전)
    [string]$Notes = "버그 수정 및 안정성 개선",
    [string]$Server = "ubuntu@13.124.130.55",
    [string]$Key = "$env:USERPROFILE\.ssh\receipt-review"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

[xml]$proj = Get-Content "agent\ReceiptTap.App\ReceiptTap.App.csproj" -Encoding UTF8
$version = ($proj.Project.PropertyGroup | Where-Object { $_.Version } | Select-Object -First 1).Version
if (-not $version) { throw "csproj 에서 <Version> 을 찾을 수 없습니다" }
Write-Host "===== 영수증리뷰 에이전트 v$version =====" -ForegroundColor Cyan

# 1. 빌드
Write-Host "[1/4] 빌드" -ForegroundColor Yellow
dotnet build "agent\ReceiptTap.App\ReceiptTap.App.csproj" -c Release
if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }
$bin = "agent\ReceiptTap.App\bin\Release\net462"

# 2. 자동 업데이트용 zip (pdb 제외)
Write-Host "[2/4] zip 패키지" -ForegroundColor Yellow
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
$stage = Join-Path $env:TEMP "receipttap_stage_$version"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item "$bin\*" $stage -Recurse -Exclude "*.pdb"
$zip = Join-Path $dist "ReceiptTap_v$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Remove-Item $stage -Recurse -Force

# 3. 설치 파일 (Inno Setup)
Write-Host "[3/4] 설치 파일" -ForegroundColor Yellow
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 이 설치되어 있지 않습니다" }
& $iscc "/DMyAppVersion=$version" "/O$dist" "agent\installer\ReceiptTap.iss"
if ($LASTEXITCODE -ne 0) { throw "설치 파일 생성 실패" }
$setup = Join-Path $dist "ReceiptTap_Setup_$version.exe"

Get-ChildItem $dist -Filter "*$version*" | ForEach-Object {
    "{0}  {1:N0} bytes  sha256={2}" -f $_.Name, $_.Length, (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
}

if (-not $Publish) {
    Write-Host "`n빌드 완료 (서버 배포는 -Publish)" -ForegroundColor Green
    exit 0
}

# 4. 서버 업로드 + latest.json
Write-Host "[4/4] 서버 배포" -ForegroundColor Yellow
$remoteDir = "receipt-review/server/app/static/downloads"
if ($ZipOnly) { scp -i $Key $zip "${Server}:$remoteDir/" } else { scp -i $Key $setup $zip "${Server}:$remoteDir/" }
if ($LASTEXITCODE -ne 0) { throw "업로드 실패" }

$latest = [ordered]@{
    version = $version
    setup   = $(if ($ZipOnly) { $null } else { "ReceiptTap_Setup_$version.exe" })
    package = "ReceiptTap_v$version.zip"
    notes   = $Notes
    date    = (Get-Date -Format "yyyy-MM-dd")
} | ConvertTo-Json -Compress
$tmp = Join-Path $env:TEMP "latest.json"
[IO.File]::WriteAllText($tmp, $latest, (New-Object Text.UTF8Encoding $false))
scp -i $Key $tmp "${Server}:$remoteDir/latest.json"
if ($LASTEXITCODE -ne 0) { throw "latest.json 업로드 실패" }

$check = ssh -i $Key $Server "curl -s -A 'ReceiptTap/1.1.0' http://127.0.0.1:8000/agent/v1/latest"
Write-Host "서버 응답: $check"
Write-Host "`n배포 완료: v$version - 설치된 프로그램은 6시간 안에 자동 업데이트됩니다." -ForegroundColor Green
