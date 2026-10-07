#!/usr/bin/env python3
"""
샘플 JSON 파일을 영수증 PNG로 렌더링하는 스크립트

사용법:
    python scripts/render_sample.py samples/receipts-json/sample1.json -o out/sample1.png
"""

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.receipt.renderer import ReceiptRenderer


def main():
    parser = argparse.ArgumentParser(description="샘플 JSON을 영수증 PNG로 렌더링")
    parser.add_argument("input", help="입력 JSON 파일 경로")
    parser.add_argument("-o", "--output", required=True, help="출력 PNG 파일 경로")
    parser.add_argument("--width", type=int, default=576, choices=[576, 384],
                        help="용지 폭 (576=80mm, 384=58mm)")
    parser.add_argument("--font", help="사용할 폰트 파일 경로")

    args = parser.parse_args()

    # 입력 파일 확인
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"오류: 입력 파일을 찾을 수 없습니다: {args.input}")
        sys.exit(1)

    # 렌더링
    print(f"렌더링 중: {args.input}")
    renderer = ReceiptRenderer(paper_width=args.width, font_path=args.font)

    try:
        image = renderer.render_from_json(str(input_path))
        renderer.save(image, args.output)
        print(f"완료: {args.output}")
        print(f"  - 크기: {image.width} x {image.height} px")
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
