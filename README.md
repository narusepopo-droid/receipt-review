# 영수증리뷰 (receipt-review)

손님이 QR을 찍고 휴대폰 번호를 입력하면, 미사용 영수증 이미지가 폰에 저장되고 리뷰 문구가 복사된 상태로 네이버 영수증 리뷰 작성 페이지가 열리는 서비스.

## 프로젝트 구조

```
receipt-review/
├── server/          # FastAPI 서버 (파서, 렌더러, API)
├── agent/           # 포스 캡처 에이전트 (C#/.NET)
├── tools/           # 테스트 도구
├── samples/         # 샘플 데이터
├── docs/            # 문서
└── deploy/          # 배포 설정
```

## 개발 환경

- **서버**: Python 3.11+, FastAPI, PostgreSQL
- **에이전트**: C# / .NET Framework 4.6.2

## 시작하기

자세한 내용은 `CLAUDE.md` 참조.
