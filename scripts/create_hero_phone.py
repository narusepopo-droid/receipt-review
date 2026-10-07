"""Hero 섹션용 3D 폰 목업 생성"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

OUTPUT = 'C:/Users/Administrator/Desktop/placemaster/hero-phone.png'

def create_receipt_screen():
    """영수증 화면 (컴팩트)"""
    width, height = 320, 580
    img = Image.new('RGB', (width, height), '#03C75A')
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 20)
        font_bold = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 12)
        font_normal = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 11)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 9)
    except:
        font_title = ImageFont.load_default()
        font_bold = font_title
        font_normal = font_title
        font_small = font_title

    cx = width // 2

    # 상단 헤더
    y = 20
    draw.text((cx, y), "모아정육식당", font=font_title, fill='white', anchor='mm')
    y += 28
    draw.text((cx, y), "리뷰 작성 시 음료 1잔 서비스!", font=font_normal, fill='#e8f8ef', anchor='mm')
    y += 32

    # 영수증 카드
    card_top = y
    card_bottom = height - 15
    draw.rounded_rectangle([15, card_top, width-15, card_bottom], radius=12, fill='white')

    y = card_top + 18

    # 영수증 제목
    draw.text((cx, y), "[ 영 수 증 ]", font=font_bold, fill='#333', anchor='mm')
    y += 22

    # 구분선
    draw.line([(28, y), (width-28, y)], fill='#333', width=1)
    y += 14

    # 매장 정보
    draw.text((cx, y), "모아정육식당", font=font_title, fill='#333', anchor='mm')
    y += 22
    draw.text((cx, y), "124-56-78901  대표: 박정훈", font=font_small, fill='#666', anchor='mm')
    y += 14
    draw.text((cx, y), "서울 강남구 역삼로 123", font=font_small, fill='#666', anchor='mm')
    y += 14
    draw.text((cx, y), "TEL: 02-555-1234", font=font_small, fill='#666', anchor='mm')
    y += 18

    # 점선
    for i in range(28, width-28, 6):
        draw.line([(i, y), (i+3, y)], fill='#999', width=1)
    y += 14

    # 품목 헤더
    draw.text((30, y), "상품", font=font_bold, fill='#333')
    draw.text((140, y), "단가", font=font_bold, fill='#333')
    draw.text((200, y), "수량", font=font_bold, fill='#333')
    draw.text((250, y), "금액", font=font_bold, fill='#333')
    y += 20

    # 점선
    for i in range(28, width-28, 6):
        draw.line([(i, y), (i+3, y)], fill='#999', width=1)
    y += 14

    # 품목
    items = [
        ("모듬6", "60,000", "1", "60,000"),
        ("모듬3", "30,000", "1", "30,000"),
        ("양념갈비", "10,000", "3", "30,000"),
        ("된장+밥", "3,000", "1", "3,000"),
    ]

    for name, price, qty, total in items:
        draw.text((30, y), name, font=font_normal, fill='#333')
        draw.text((140, y), price, font=font_normal, fill='#333')
        draw.text((205, y), qty, font=font_normal, fill='#333')
        draw.text((250, y), total, font=font_normal, fill='#333')
        y += 18

    y += 8

    # 점선
    for i in range(28, width-28, 6):
        draw.line([(i, y), (i+3, y)], fill='#999', width=1)
    y += 14

    # 합계
    draw.text((30, y), "합계", font=font_title, fill='#333')
    draw.text((200, y), "123,000원", font=font_title, fill='#333')
    y += 28

    # 구분선
    draw.line([(28, y), (width-28, y)], fill='#333', width=1)
    y += 14

    # 결제 정보
    draw.text((30, y), "NH농협", font=font_normal, fill='#333')
    draw.text((120, y), "9441-16**-****-546*", font=font_normal, fill='#333')
    y += 16
    draw.text((30, y), "승인번호:", font=font_normal, fill='#333')
    draw.text((120, y), "12345678", font=font_normal, fill='#333')
    y += 22

    # 발행일시
    draw.text((cx, y), "2026.10.07 오후 06:55", font=font_small, fill='#888', anchor='mm')

    return img

def create_3d_phone(screen_img):
    """3D 각도 폰 목업"""
    phone_width = 320
    phone_height = 640
    bezel = 8
    corner_radius = 35

    # 폰 프레임 생성
    phone = Image.new('RGBA', (phone_width, phone_height), (0, 0, 0, 0))
    phone_draw = ImageDraw.Draw(phone)

    # 폰 외부 (검정)
    phone_draw.rounded_rectangle([0, 0, phone_width, phone_height],
                                  radius=corner_radius, fill=(25, 25, 25, 255))

    # 화면 영역
    screen_x, screen_y = bezel, bezel
    screen_w = phone_width - bezel * 2
    screen_h = phone_height - bezel * 2

    # 스크린 리사이즈
    screen_resized = screen_img.resize((screen_w, screen_h), Image.Resampling.LANCZOS)

    # 라운드 마스크
    mask = Image.new('L', (screen_w, screen_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, screen_w, screen_h], radius=corner_radius - bezel, fill=255)

    # 스크린 합성
    screen_rgba = screen_resized.convert('RGBA')
    phone.paste(screen_rgba, (screen_x, screen_y), mask)

    # 카메라 구멍
    cam_x, cam_y = phone_width // 2, bezel + 15
    phone_draw.ellipse([cam_x - 6, cam_y - 6, cam_x + 6, cam_y + 6], fill=(15, 15, 15, 255))

    # 3D 변환 (비스듬하게)
    # perspective transform
    angle = 8  # 기울기 각도

    # 캔버스 크기 (여유 공간)
    canvas_w = phone_width + 150
    canvas_h = phone_height + 100
    canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))

    # 그림자 생성
    shadow = Image.new('RGBA', (phone_width + 40, phone_height + 40), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle([20, 20, phone_width + 20, phone_height + 20],
                                   radius=corner_radius, fill=(0, 0, 0, 100))
    shadow = shadow.filter(ImageFilter.GaussianBlur(25))

    # 그림자 변환 (오른쪽 아래로)
    shadow_offset_x = 60
    shadow_offset_y = 40

    # 그림자 배치
    canvas.paste(shadow, (shadow_offset_x, shadow_offset_y), shadow)

    # 폰 회전 (약간 비스듬하게)
    phone_rotated = phone.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)

    # 폰 배치
    phone_x = (canvas_w - phone_rotated.width) // 2
    phone_y = (canvas_h - phone_rotated.height) // 2 - 10
    canvas.paste(phone_rotated, (phone_x, phone_y), phone_rotated)

    # 하이라이트 (3D 효과)
    highlight = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight)
    # 왼쪽 상단 빛 반사
    h_draw.rounded_rectangle([phone_x + 10, phone_y + 10, phone_x + phone_rotated.width - 50, phone_y + 60],
                              radius=30, fill=(255, 255, 255, 20))
    canvas = Image.alpha_composite(canvas, highlight)

    return canvas

def main():
    print("1. 영수증 화면 생성...")
    screen = create_receipt_screen()

    print("2. 3D 폰 목업 생성...")
    result = create_3d_phone(screen)

    # 저장
    result.save(OUTPUT, 'PNG')
    print(f"완료: {OUTPUT}")

if __name__ == "__main__":
    main()
