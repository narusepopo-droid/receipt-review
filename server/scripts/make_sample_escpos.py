"""
샘플 ESC/POS 바이너리 생성기 (테스트용)

실제 한국 카드 영수증과 같은 구성(로고, 2배 크기 상호, 품목 열 정렬, 승인 정보, QR, 커팅)을
CP949 ESC/POS 바이트로 만든다. 포스 없이 파서·렌더러·업로드 API를 시험할 때 사용.

사용법:
    python scripts/make_sample_escpos.py -o out/sample.bin
    python scripts/make_sample_escpos.py --kind cancel -o out/cancel.bin
    python scripts/make_sample_escpos.py --kind kitchen -o out/kitchen.bin
"""
import argparse
from pathlib import Path

ESC, GS = b"\x1b", b"\x1d"
INIT = ESC + b"@"
LEFT, CENTER, RIGHT = ESC + b"a\x00", ESC + b"a\x01", ESC + b"a\x02"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
BIG, NORMAL = GS + b"!\x11", GS + b"!\x00"
CUT = GS + b"V\x42\x00"
WIDTH = 42  # 80mm 프린터에서 흔한 42칸 설정


def t(s: str) -> bytes:
    return s.encode("cp949")


def cols(s: str) -> int:
    return len(s.encode("cp949"))


def row(left: str, right: str) -> bytes:
    pad = WIDTH - cols(left) - cols(right)
    return t(left + " " * max(1, pad) + right + "\n")


def item_row(name: str, price: int, qty: int, amount: int) -> bytes:
    name_part = name + " " * max(1, 18 - cols(name))
    nums = f"{price:>8,}{qty:>4}{amount:>11,}"
    return t(name_part + nums.rjust(WIDTH - cols(name_part)) + "\n")


def logo(width_px: int = 192, height: int = 48) -> bytes:
    """GS v 0 래스터 로고 (테두리 상자 + 가운데 막대)"""
    wb = width_px // 8
    rows = []
    for y in range(height):
        line = bytearray(wb)
        for x in range(width_px):
            border = y < 3 or y >= height - 3 or x < 3 or x >= width_px - 3
            bar = height // 3 <= y < height * 2 // 3 and width_px // 4 <= x < width_px * 3 // 4
            if border or bar:
                line[x // 8] |= 0x80 >> (x % 8)
        rows.append(bytes(line))
    return GS + b"v0\x00" + bytes([wb, 0, height, 0]) + b"".join(rows)


def qr(data: str) -> bytes:
    d = data.encode("cp949")
    n = len(d) + 3
    return (GS + b"(k\x04\x00\x31\x41\x32\x00"      # 모델 2
            + GS + b"(k\x03\x00\x31\x43\x05"          # 모듈 크기 5
            + GS + b"(k\x03\x00\x31\x45\x31"          # 오류 정정 M
            + GS + b"(k" + bytes([n & 0xFF, n >> 8]) + b"\x31\x50\x30" + d
            + GS + b"(k\x03\x00\x31\x51\x30")         # 인쇄


def card_receipt(cancel: bool = False) -> bytes:
    sign = "-" if cancel else ""
    out = INIT + CENTER + logo() + b"\n"
    out += BIG + BOLD_ON + t("맛있는김치찌개\n") + NORMAL + BOLD_OFF
    out += t("서울 강남구 테헤란로 123, 1층\n")
    out += t("123-45-67890  대표 김사장\n")
    out += t("TEL 02-555-1234\n")
    out += LEFT + t("-" * WIDTH + "\n")
    if cancel:
        out += CENTER + BIG + t("[ 취 소 ]\n") + NORMAL + LEFT
    out += row("주문번호: 0042", "테이블: 7")
    out += row("판매일시:", "2026-10-09 12:34:56")
    out += t("-" * WIDTH + "\n")
    out += t("상품명                단가 수량       금액\n")
    out += t("-" * WIDTH + "\n")
    out += item_row("돼지김치찌개", 9000, 2, 18000)
    out += item_row("계란말이", 8000, 1, 8000)
    out += item_row("공기밥", 1000, 2, 2000)
    out += item_row("콜라", 2000, 1, 2000)
    out += t("-" * WIDTH + "\n")
    out += row("공급가액", f"{sign}27,273")
    out += row("부가세", f"{sign}2,727")
    total = f"{sign}30,000"
    out += BOLD_ON + BIG + t("합계" + " " * (WIDTH // 2 - cols("합계") - cols(total)) + total + "\n") + NORMAL + BOLD_OFF
    out += t("-" * WIDTH + "\n")
    out += row("카드종류", "신한카드")
    out += row("카드번호", "4518-42**-****-1234")
    out += row("할부", "일시불")
    out += row("승인번호", "30012345")
    out += row("승인일시", "2026-10-09 12:34:56")
    out += row("가맹점번호", "0123456789")
    out += t("-" * WIDTH + "\n")
    out += row("포인트 적립 회원", "010-1234-5678")
    out += t("-" * WIDTH + "\n")
    out += CENTER + qr("https://example.com/r/30012345") + b"\n"
    out += t("이용해 주셔서 감사합니다\n")
    out += ESC + b"d\x04" + CUT
    return out


def kitchen_order() -> bytes:
    out = INIT + CENTER + BIG + t("주 방 주 문 서\n") + NORMAL + LEFT
    out += row("테이블: 7", "12:30")
    out += t("-" * WIDTH + "\n")
    out += BIG + t("돼지김치찌개  x2\n계란말이      x1\n") + NORMAL
    out += ESC + b"d\x03" + CUT
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["card", "cancel", "kitchen"], default="card")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()

    data = {"card": card_receipt, "cancel": lambda: card_receipt(cancel=True), "kitchen": kitchen_order}[args.kind]()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(data)
    print(f"{args.output}: {len(data)} bytes")


if __name__ == "__main__":
    main()
