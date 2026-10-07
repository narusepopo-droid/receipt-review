"""얇은 베젤 폰 목업"""
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFilter
import os

OUTPUT_DIR = 'C:/Users/Administrator/Desktop/placemaster'

def create_thin_bezel_mockup(screen_path, output_path):
    """얇은 베젤 폰 목업"""
    screen = Image.open(screen_path).convert('RGBA')

    # 폰 크기
    phone_width = 260
    phone_height = 520
    bezel = 3  # 매우 얇은 베젤
    corner_radius = 28

    # 캔버스
    canvas_width = phone_width + 40
    canvas_height = phone_height + 40
    canvas = Image.new('RGBA', (canvas_width, canvas_height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)

    # 그림자
    shadow = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [20 + 6, 20 + 6, 20 + phone_width + 6, 20 + phone_height + 6],
        radius=corner_radius, fill=(0, 0, 0, 50)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas)

    phone_x, phone_y = 20, 20

    # 폰 프레임 (얇은 검정)
    draw.rounded_rectangle(
        [phone_x, phone_y, phone_x + phone_width, phone_y + phone_height],
        radius=corner_radius, fill=(25, 25, 25, 255)
    )

    # 화면 영역
    screen_x = phone_x + bezel
    screen_y = phone_y + bezel
    screen_w = phone_width - (bezel * 2)
    screen_h = phone_height - (bezel * 2)

    # 화면 영역 배경 (검정)
    draw.rounded_rectangle(
        [screen_x, screen_y, screen_x + screen_w, screen_y + screen_h],
        radius=corner_radius - bezel, fill=(20, 20, 20, 255)
    )

    # 스크린 리사이즈
    screen_resized = screen.resize((screen_w, screen_h), Image.Resampling.LANCZOS).convert('RGBA')

    # 라운드 마스크
    mask = Image.new('L', (screen_w, screen_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, screen_w, screen_h], radius=corner_radius - bezel, fill=255)

    screen_with_corners = Image.new('RGBA', (screen_w, screen_h), (0, 0, 0, 0))
    screen_with_corners.paste(screen_resized, (0, 0), mask)
    canvas.paste(screen_with_corners, (screen_x, screen_y), screen_with_corners)

    # 카메라 구멍 (펀치홀) - 작게
    camera_size = 8
    camera_x = phone_x + phone_width // 2
    camera_y = phone_y + bezel + 10
    draw.ellipse([camera_x - camera_size//2, camera_y - camera_size//2,
                  camera_x + camera_size//2, camera_y + camera_size//2],
                 fill=(10, 10, 10, 255))

    # 하단 네비게이션 바 (투명)
    nav_bar = Image.new('RGBA', (screen_w, 28), (0, 0, 0, 0))
    nav_draw = ImageDraw.Draw(nav_bar)
    nav_draw.rectangle([0, 0, screen_w, 28], fill=(255, 255, 255, 180))

    # 뒤로가기 (◁)
    nav_draw.polygon([(screen_w//4 - 6, 14), (screen_w//4 + 4, 7), (screen_w//4 + 4, 21)],
                     fill=(120, 120, 120, 220))
    # 홈 (○)
    nav_draw.ellipse([screen_w//2 - 9, 5, screen_w//2 + 9, 23],
                     outline=(120, 120, 120, 220), width=2)
    # 최근 앱 (□)
    nav_draw.rectangle([screen_w*3//4 - 7, 6, screen_w*3//4 + 7, 22],
                       outline=(120, 120, 120, 220), width=2)

    canvas.paste(nav_bar, (screen_x, screen_y + screen_h - 28), nav_bar)

    canvas.save(output_path, 'PNG')
    print(f'목업: {output_path}')

def capture_screens():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 780})

        url = 'https://narusepopo-droid.github.io/receipt-review/tools/preview/'
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(1000)

        screens = [
            ('번호입력', 'raw1.png'),
            ('키워드', 'raw2.png'),
            ('결과', 'raw3.png'),
            ('완료', 'raw5.png'),
        ]

        for btn_text, filename in screens:
            page.click(f'button:has-text("{btn_text}")')
            page.wait_for_timeout(500)
            page.evaluate('document.querySelector(".preview-nav").style.display = "none"')
            page.evaluate('document.querySelector(".preview-container").style.paddingTop = "0"')
            page.screenshot(path=f'{OUTPUT_DIR}/{filename}')
            print(f'캡처: {btn_text}')
            page.evaluate('document.querySelector(".preview-nav").style.display = "flex"')
            page.evaluate('document.querySelector(".preview-container").style.paddingTop = "60px"')

        browser.close()

def create_naver_screen():
    from PIL import ImageFont

    width, height = 390, 780
    img = Image.new('RGB', (width, height), '#ffffff')
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 20)
        font_normal = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 15)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 13)
    except:
        font_title = ImageFont.load_default()
        font_normal = font_title
        font_small = font_title

    # 네이버 헤더
    draw.rectangle([0, 0, width, 56], fill='#03C75A')
    draw.text((width//2, 28), "리뷰 작성", font=font_title, fill='white', anchor='mm')

    y = 80
    draw.rounded_rectangle([20, y, width-20, y+50], radius=12, fill='#e8f5e9')
    draw.text((width//2, y+25), "✓ 영수증 인증 완료", font=font_normal, fill='#2e7d32', anchor='mm')
    y += 75

    draw.text((25, y), "별점을 선택해주세요", font=font_small, fill='#666')
    y += 30
    draw.text((25, y), "★★★★★", font=font_title, fill='#FFD700')
    y += 50

    draw.text((25, y), "이 매장의 장점은?", font=font_small, fill='#666')
    y += 30
    keywords = ["맛있어요", "친절해요", "깔끔해요"]
    x = 25
    for kw in keywords:
        w = len(kw) * 14 + 28
        draw.rounded_rectangle([x, y, x+w, y+36], radius=18, fill='#03C75A')
        draw.text((x + w//2, y+18), kw, font=font_small, fill='white', anchor='mm')
        x += w + 12
    y += 65

    draw.text((25, y), "리뷰 내용", font=font_small, fill='#666')
    y += 30
    draw.rounded_rectangle([20, y, width-20, y+130], radius=12, outline='#ddd', width=2)
    draw.text((35, y+20), "모듬 정말 맛있었어요!", font=font_normal, fill='#333')
    draw.text((35, y+50), "친절하고 분위기도 좋아서", font=font_normal, fill='#333')
    draw.text((35, y+80), "또 방문할게요~ 추천합니다!", font=font_normal, fill='#333')
    y += 160

    draw.text((25, y), "사진 첨부 (2장)", font=font_small, fill='#666')
    y += 35
    for i in range(2):
        draw.rounded_rectangle([25 + i*95, y, 105 + i*95, y+80], radius=10, fill='#f5f5f5', outline='#ddd')
        draw.text((65 + i*95, y+40), "📷", font=font_title, anchor='mm')
    y += 110

    draw.rounded_rectangle([20, y, width-20, y+56], radius=12, fill='#03C75A')
    draw.text((width//2, y+28), "등록하기", font=font_title, fill='white', anchor='mm')

    img.save(f'{OUTPUT_DIR}/raw4.png')
    print('캡처: 네이버')

def main():
    print("1. 화면 캡처...")
    capture_screens()

    print("\n2. 네이버 화면...")
    create_naver_screen()

    print("\n3. 얇은 베젤 폰 목업...")
    for i in [1, 2, 3, 4, 5]:
        raw_path = f'{OUTPUT_DIR}/raw{i}.png'
        if os.path.exists(raw_path):
            create_thin_bezel_mockup(raw_path, f'{OUTPUT_DIR}/screen{i}.png')
            os.remove(raw_path)

    print("\n완료!")

if __name__ == "__main__":
    main()
