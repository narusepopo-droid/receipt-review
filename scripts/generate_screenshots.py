"""플레이스마스터용 스크린샷 이미지 생성"""
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

def get_fonts():
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 20)
        font_bold = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 16)
        font_normal = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 14)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 12)
        font_big = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 28)
    except:
        font_title = ImageFont.load_default()
        font_bold = font_title
        font_normal = font_title
        font_small = font_title
        font_big = font_title
    return font_title, font_bold, font_normal, font_small, font_big

def create_phone_frame(width=220, height=400):
    """폰 프레임 생성"""
    img = Image.new('RGB', (width, height), '#1a1a1a')
    draw = ImageDraw.Draw(img)
    # 화면 영역 (흰색)
    screen_margin = 8
    draw.rounded_rectangle(
        [screen_margin, screen_margin, width-screen_margin, height-screen_margin],
        radius=20,
        fill='white'
    )
    return img, draw, screen_margin

def draw_header(draw, width, y, title, subtitle, color='#2563EB'):
    """상단 헤더"""
    font_title, font_bold, font_normal, font_small, _ = get_fonts()
    # 헤더 배경
    draw.rectangle([8, 8, width-8, y+60], fill=color)
    # 텍스트
    draw.text((width//2, y+15), title, font=font_title, fill='white', anchor='mm')
    draw.text((width//2, y+40), subtitle, font=font_small, fill='white', anchor='mm')
    return y + 70

def draw_button(draw, x1, y1, x2, y2, text, color='#2563EB'):
    """버튼"""
    font_title, font_bold, font_normal, font_small, _ = get_fonts()
    draw.rounded_rectangle([x1, y1, x2, y2], radius=8, fill=color)
    draw.text(((x1+x2)//2, (y1+y2)//2), text, font=font_bold, fill='white', anchor='mm')

# 1. 번호 입력 화면
def create_screen1():
    img, draw, m = create_phone_frame()
    font_title, font_bold, font_normal, font_small, font_big = get_fonts()

    y = draw_header(draw, 220, m, "모아정육식당", "리뷰 작성 시 음료 서비스")

    y += 20
    draw.text((110, y), "휴대폰 번호를 입력하세요", font=font_small, fill='#666', anchor='mm')
    y += 30

    # 입력 필드
    draw.rounded_rectangle([20, y, 200, y+45], radius=8, outline='#ddd', width=2)
    draw.text((110, y+22), "010-1234-5678", font=font_bold, fill='#333', anchor='mm')
    y += 60

    # 체크박스
    draw.rectangle([20, y, 32, y+12], outline='#2563EB', width=2)
    draw.text((38, y+6), "개인정보 수집 동의 (필수)", font=font_small, fill='#333', anchor='lm')
    y += 25
    draw.rectangle([20, y, 32, y+12], outline='#ccc', width=1)
    draw.text((38, y+6), "마케팅 수신 동의 (선택)", font=font_small, fill='#999', anchor='lm')
    y += 40

    # 버튼
    draw_button(draw, 20, y, 200, y+45, "다음")

    img.save('C:/Users/Administrator/Desktop/placemaster/screen1.png')
    print("screen1.png 생성")

# 2. 키워드 선택 화면
def create_screen2():
    img, draw, m = create_phone_frame()
    font_title, font_bold, font_normal, font_small, font_big = get_fonts()

    y = draw_header(draw, 220, m, "모아정육식당", "키워드를 선택하세요")

    y += 25

    # 키워드 칩들
    keywords = [("맛있어요", True), ("친절해요", True), ("깔끔해요", False),
                ("가성비좋아요", False), ("분위기좋아요", True)]

    x = 20
    for kw, selected in keywords:
        w = len(kw) * 12 + 24
        if x + w > 200:
            x = 20
            y += 35

        if selected:
            draw.rounded_rectangle([x, y, x+w, y+28], radius=14, fill='#2563EB')
            draw.text((x + w//2, y+14), kw, font=font_small, fill='white', anchor='mm')
        else:
            draw.rounded_rectangle([x, y, x+w, y+28], radius=14, outline='#ddd', width=1)
            draw.text((x + w//2, y+14), kw, font=font_small, fill='#666', anchor='mm')
        x += w + 10

    y += 80

    # 버튼
    draw_button(draw, 20, y, 200, y+45, "다음")

    img.save('C:/Users/Administrator/Desktop/placemaster/screen2.png')
    print("screen2.png 생성")

# 3. 영수증 확인 화면
def create_screen3():
    img, draw, m = create_phone_frame(220, 450)
    font_title, font_bold, font_normal, font_small, font_big = get_fonts()

    y = draw_header(draw, 220, m, "모아정육식당", "영수증과 문구를 확인하세요")

    y += 15

    # 영수증 미리보기 (작은 버전)
    draw.rounded_rectangle([20, y, 200, y+120], radius=8, outline='#eee', width=1, fill='#fafafa')
    draw.text((110, y+20), "[ 영 수 증 ]", font=font_bold, fill='#333', anchor='mm')
    draw.text((110, y+45), "모아정육식당", font=font_normal, fill='#333', anchor='mm')
    draw.text((110, y+70), "합계: 123,000원", font=font_bold, fill='#333', anchor='mm')
    draw.text((110, y+95), "승인번호: 12345678", font=font_small, fill='#666', anchor='mm')
    y += 135

    # 문구 미리보기
    draw.rounded_rectangle([20, y, 200, y+60], radius=8, outline='#2563EB', width=1, fill='#eff6ff')
    draw.text((110, y+15), "모듬 정말 맛있었어요!", font=font_small, fill='#333', anchor='mm')
    draw.text((110, y+35), "친절하고 또 올게요~", font=font_small, fill='#333', anchor='mm')
    y += 75

    # 버튼
    draw_button(draw, 20, y, 200, y+50, "영수증 저장 + 네이버 이동")

    img.save('C:/Users/Administrator/Desktop/placemaster/screen3.png')
    print("screen3.png 생성")

# 4. 네이버 리뷰 화면 (간략화)
def create_screen4():
    img, draw, m = create_phone_frame()
    font_title, font_bold, font_normal, font_small, font_big = get_fonts()

    # 네이버 스타일 헤더
    draw.rectangle([8, 8, 212, 55], fill='#03C75A')
    draw.text((110, 32), "네이버 리뷰 작성", font=font_title, fill='white', anchor='mm')

    y = 70

    # 영수증 업로드 완료
    draw.rounded_rectangle([20, y, 200, y+35], radius=8, fill='#e8f5e9')
    draw.text((110, y+17), "✓ 영수증 인식 완료", font=font_bold, fill='#2e7d32', anchor='mm')
    y += 50

    # 별점
    draw.text((20, y), "별점", font=font_small, fill='#666')
    y += 20
    stars = "★★★★★"
    draw.text((20, y), stars, font=font_title, fill='#FFD700')
    y += 35

    # 리뷰 입력
    draw.text((20, y), "리뷰 내용", font=font_small, fill='#666')
    y += 20
    draw.rounded_rectangle([20, y, 200, y+70], radius=8, outline='#ddd', width=1)
    draw.text((30, y+15), "모듬 정말 맛있었어요!", font=font_small, fill='#333')
    draw.text((30, y+35), "친절하고 또 올게요~", font=font_small, fill='#333')
    y += 85

    # 등록 버튼
    draw_button(draw, 20, y, 200, y+45, "등록", '#03C75A')

    img.save('C:/Users/Administrator/Desktop/placemaster/screen4.png')
    print("screen4.png 생성")

# 5. 완료 화면
def create_screen5():
    img, draw, m = create_phone_frame()
    font_title, font_bold, font_normal, font_small, font_big = get_fonts()

    y = draw_header(draw, 220, m, "모아정육식당", "리뷰 등록 완료!")

    y += 30

    # 큰 체크 아이콘
    draw.ellipse([70, y, 150, y+80], fill='#22c55e')
    draw.text((110, y+40), "✓", font=font_big, fill='white', anchor='mm')
    y += 100

    # 완료 메시지
    draw.text((110, y), "감사합니다!", font=font_title, fill='#333', anchor='mm')
    y += 30
    draw.text((110, y), "직원에게 이 화면을 보여주세요", font=font_small, fill='#666', anchor='mm')
    y += 40

    # 완료 코드
    draw.rounded_rectangle([40, y, 180, y+45], radius=8, fill='#f0f0f0')
    draw.text((110, y+22), "A3B7K2", font=font_big, fill='#333', anchor='mm')

    img.save('C:/Users/Administrator/Desktop/placemaster/screen5.png')
    print("screen5.png 생성")

if __name__ == "__main__":
    create_screen1()
    create_screen2()
    create_screen3()
    create_screen4()
    create_screen5()
    print("\n모든 스크린샷 생성 완료!")
