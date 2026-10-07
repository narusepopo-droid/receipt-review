"""placemaster 사이트용 영수증 이미지 생성"""
import sys
sys.path.insert(0, 'C:/Users/Administrator/Desktop/review/server')

from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

def generate_receipt():
    width = 380
    height = 700

    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 22)
        font_bold = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 16)
        font_normal = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 14)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 12)
    except:
        font_title = ImageFont.load_default()
        font_bold = font_title
        font_normal = font_title
        font_small = font_title

    y = 30
    cx = width // 2

    # 제목
    draw.text((cx, y), "[ 영 수 증 ]", font=font_title, fill='black', anchor='mm')
    y += 45

    # 구분선
    draw.line([(20, y), (width-20, y)], fill='black', width=2)
    y += 25

    # 매장 정보
    draw.text((cx, y), "모아정육식당", font=font_title, fill='black', anchor='mm')
    y += 35
    draw.text((cx, y), "124-56-78901  대표: 박정훈", font=font_small, fill='#333', anchor='mm')
    y += 22
    draw.text((cx, y), "서울 강남구 역삼로 123", font=font_small, fill='#333', anchor='mm')
    y += 22
    draw.text((cx, y), "TEL: 02-555-1234", font=font_small, fill='#333', anchor='mm')
    y += 30

    # 점선
    for i in range(20, width-20, 8):
        draw.line([(i, y), (i+4, y)], fill='#999', width=1)
    y += 25

    # 품목 헤더
    draw.text((25, y), "상품", font=font_bold, fill='black')
    draw.text((170, y), "단가", font=font_bold, fill='black')
    draw.text((240, y), "수량", font=font_bold, fill='black')
    draw.text((300, y), "금액", font=font_bold, fill='black')
    y += 28

    # 점선
    for i in range(20, width-20, 8):
        draw.line([(i, y), (i+4, y)], fill='#999', width=1)
    y += 20

    # 품목
    items = [
        ("모듬6", "60,000", "1", "60,000"),
        ("모듬3", "30,000", "1", "30,000"),
        ("양념갈비(1인)", "10,000", "3", "30,000"),
        ("된장+밥", "3,000", "1", "3,000"),
    ]

    for name, price, qty, total in items:
        draw.text((25, y), name, font=font_normal, fill='black')
        draw.text((170, y), price, font=font_normal, fill='black')
        draw.text((250, y), qty, font=font_normal, fill='black')
        draw.text((300, y), total, font=font_normal, fill='black')
        y += 26

    y += 15

    # 점선
    for i in range(20, width-20, 8):
        draw.line([(i, y), (i+4, y)], fill='#999', width=1)
    y += 25

    # 합계
    draw.text((25, y), "합계", font=font_title, fill='black')
    draw.text((240, y), "123,000원", font=font_title, fill='black')
    y += 40

    # 구분선
    draw.line([(20, y), (width-20, y)], fill='black', width=2)
    y += 25

    # 결제 정보
    draw.text((25, y), "NH농협", font=font_normal, fill='black')
    draw.text((150, y), "9441-16**-****-546*", font=font_normal, fill='black')
    y += 26
    draw.text((25, y), "승인번호:", font=font_normal, fill='black')
    draw.text((150, y), "12345678", font=font_normal, fill='black')
    y += 35

    # 발행일시
    now = datetime.now()
    date_str = now.strftime("발행일시 : %Y.%m.%d 오후 %I:%M:%S")
    draw.text((cx, y), date_str, font=font_small, fill='#666', anchor='mm')

    # 높이 조정 (불필요한 여백 제거)
    bbox = img.getbbox()
    if bbox:
        img = img.crop((0, 0, width, bbox[3] + 30))

    output_path = 'C:/Users/Administrator/Desktop/placemaster/receipt-sample.png'
    img.save(output_path)
    print(f"생성 완료: {output_path}")

if __name__ == "__main__":
    generate_receipt()
