# 카솔 PosAssist SPMC 분석 결과

> 분석일: 2026-10-07
> 분석 대상: `C:\PosAssist\` (읽기 전용)

## 1. SPMC 기본 정보

| 항목 | 내용 |
|---|---|
| 제품명 | HHD Software Serial Port Monitoring Control |
| 드라이버 버전 | 3.1.0.7347 (2016-11-11) |
| 드라이버 파일 | `hhdspmc32.sys` (32bit), `hhdspmc64.sys` (64bit) |
| 라이선스 파일 | `SPMC_License.spmclic` (암호화된 바이너리) |
| .NET 바인딩 | `Interop.hhdspmcLib.dll` (COM Interop) |

## 2. 설치 구조

```
C:\PosAssist\
├── hhdspmc.dll              # SPMC 메인 DLL
├── Interop.hhdspmcLib.dll   # .NET COM 래퍼
├── SPMC_License.spmclic     # 라이선스 파일
├── drivers/
│   ├── hhdspmc.inf          # 드라이버 설치 정보
│   ├── hhdspmc32.sys        # 32bit 커널 드라이버
│   ├── hhdspmc64.sys        # 64bit 커널 드라이버
│   ├── hhdspmc_x86.cat      # 서명 카탈로그
│   └── hhdspmc_x64.cat
└── hhdspmc/
    ├── hhdspmc.exe          # SPMC 관리 프로그램
    ├── SPMC_License.spmclic
    ├── sqlite3.dll
    └── System.Data.SQLite.dll
```

## 3. 동작 방식 (로그 분석)

### 라이선스 로딩
```
[INFO] sm_license_loaded = False
[INFO] !sm_license_loaded && sm != null = True
[INFO] Utils.FileExists(licenseFile)
```
→ 라이선스 파일 존재 확인 후 로드

### COM 포트 자동 감지
```
[INFO] HHD device: name=[표준 Bluetooth에서 직렬 링크(COM5)], port=[COM5], present=True
[INFO] HHD device: name=[표준 Bluetooth에서 직렬 링크(COM6)], port=[COM6], present=True
```
→ 시스템의 모든 COM 포트를 열거하고 감지

### 프린트 모니터링 활성화
```
[INFO] havePrint = True
```

## 4. PosAssist 환경

| 항목 | 내용 |
|---|---|
| PosAssist 버전 | 2026.09.18.1225 |
| .NET Framework | 4.0 |
| API 서버 | storesalesplus.com |
| 현재 매장 | 카페떼오 (store_id=823) |

## 5. 라이선스 관련

- 라이선스 파일 형식: `.spmclic` (암호화된 바이너리)
- 파일 위치: 루트와 hhdspmc 폴더 양쪽에 존재
- **재배포 가능 여부**: 확인 필요 (D12)

## 6. 우리 에이전트에 적용할 사항

### 확인된 것
- ✅ SPMC는 .NET에서 COM Interop으로 사용
- ✅ COM 포트 자동 감지 기능 내장
- ✅ 커널 드라이버 방식 (비간섭 모니터링)
- ✅ 32/64bit 모두 지원

### 추가 확인 필요
- ❓ 금액 파싱 로직 (소스 없이는 확인 불가)
- ❓ 영수증 1건 경계 판별 로직
- ❓ 같은 COM 포트 동시 모니터링 가능 여부 (Phase 2에서 테스트)
- ❓ SPMC 라이선스를 영수증리뷰에도 쓸 수 있는지

## 7. 요청자 확인 필요

1. **PosAssist 소스 코드 위치** — 영수증 파싱 로직을 참고하려면 소스가 필요합니다
2. **SPMC 라이선스 공유 가능 여부** — 카솔 라이선스로 영수증리뷰 배포가 가능한지 (D12)
3. **테스트 포스의 프린터 연결 방식** — COM인지 네트워크인지 (P6)
