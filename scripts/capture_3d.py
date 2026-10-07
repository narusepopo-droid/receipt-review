"""3D 폰 목업 - 기울임 + 입체 그림자"""
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFilter
import os

OUTPUT_DIR = 'C:/Users/Administrator/Desktop/placemaster'

def create_3d_phone_mockup(screen_path, output_path, tilt_angle=-5):
    """3D 기울임 폰 목업"""
    screen = Image.open(screen_path).convert('RGBA')

    # 폰 크기
    phone_width = 240
    phone_height = 480
    bezel = 4
    corner_radius = 28

    # 폰 프레임 생성
    phone = Image.new('RGBA', (phone_width, phone_height), (0, 0, 0, 0))
    phone_draw = ImageDraw.Draw(phone)

    # 폰 외부
    phone_draw.rounded_rectangle([0, 0, phone_width, phone_height],
                                  radius=corner_radius, fill=(25, 25, 25, 255))

    # 화면 영역 배경
    screen_x, screen_y = bezel, bezel
    screen_w = phone_width - bezel * 2
    screen_h = phone_height - bezel * 2
    phone_draw.rounded_rectangle([screen_x, screen_y, screen_x + screen_w, screen_y + screen_h],
                                  radius=corner_radius - bezel, fill=(20, 20, 20, 255))

    # 스크린
    screen_resized = screen.resize((screen_w, screen_h), Image.Resampling.LANCZOS)

    mask = Image.new('L', (screen_w, screen_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, screen_w, screen_h], radius=corner_radius - bezel, fill=255)

    screen_with_mask = Image.new('RGBA', (screen_w, screen_h), (0, 0, 0, 0))
    screen_with_mask.paste(screen_resized, (0, 0), mask)
    phone.paste(screen_with_mask, (screen_x, screen_y), screen_with_mask)

    # 카메라
    cam_x, cam_y = phone_width // 2, bezel + 10
    phone_draw.ellipse([cam_x - 5, cam_y - 5, cam_x + 5, cam_y + 5], fill=(15, 15, 15, 255))

    # 하단 네비바
    nav_h = 24
    nav_bar = Image.new('RGBA', (screen_w, nav_h), (0, 0, 0, 0))
    nav_draw = ImageDraw.Draw(nav_bar)
    nav_draw.rectangle([0, 0, screen_w, nav_h], fill=(255, 255, 255, 160))
    nav_draw.polygon([(screen_w//4 - 5, nav_h//2), (screen_w//4 + 3, nav_h//2 - 6), (screen_w//4 + 3, nav_h//2 + 6)],
                     fill=(100, 100, 100, 200))
    nav_draw.ellipse([screen_w//2 - 8, 4, screen_w//2 + 8, 20], outline=(100, 100, 100, 200), width=2)
    nav_draw.rectangle([screen_w*3//4 - 6, 5, screen_w*3//4 + 6, 19], outline=(100, 100, 100, 200), width=2)
    phone.paste(nav_bar, (screen_x, screen_y + screen_h - nav_h), nav_bar)

    # 폰 회전
    phone_rotated = phone.rotate(tilt_angle, expand=True, resample=Image.Resampling.BICUBIC)

    # 캔버스
    canvas_w = phone_rotated.width + 50
    canvas_h = phone_rotated.height + 50
    canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))

    # 그림자
    shadow = Image.new('RGBA', (phone_width + 30, phone_height + 30), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle([15, 15, phone_width + 15, phone_height + 15],
                                   radius=corner_radius, fill=(0, 0, 0, 60))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    shadow_rotated = shadow.rotate(tilt_angle, expand=True, resample=Image.Resampling.BICUBIC)

    # 그림자 배치
    shadow_x = (canvas_w - shadow_rotated.width) // 2 + 8
    shadow_y = (canvas_h - shadow_rotated.height) // 2 + 8
    canvas.paste(shadow_rotated, (shadow_x, shadow_y), shadow_rotated)

    # 폰 배치
    phone_x = (canvas_w - phone_rotated.width) // 2
    phone_y = (canvas_h - phone_rotated.height) // 2
    canvas.paste(phone_rotated, (phone_x, phone_y), phone_rotated)

    canvas.save(output_path, 'PNG')
    print(f'3D 목업: {output_path}')

def capture_screens():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 780})

        url = 'https://narusepopo-droid.github.io/receipt-review/tools/preview/'
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(1000)

        screens = [
            ('번호입력', 'raw1.png', -4),
            ('키워드', 'raw2.png', -3),
            ('결과', 'raw3.png', -2),
            ('완료', 'raw5.png', -4),
        ]

        for btn_text, filename, angle in screens:
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

    draw.rectangle([0, 0, width, 56], fill='#03C75A')
    draw.text((width//2, 28), "리뷰 작성", font=font_title, fill='white', anchor='mm')

    y = 80
    draw.rounded_rectangle([20, y, width-20, y+50], radius=12, fill='#e8f5e9')
    draw.text((width//2, y+25), "✓ 영수증 인증 완료", font=font_normal, fill='#2e7d32', anchor='mm')
    y += 75

    draw.text((25, y), "별점", font=font_small, fill='#666')
    y += 28
    draw.text((25, y), "★★★★★", font=font_title, fill='#FFD700')
    y += 45

    draw.text((25, y), "키워드", font=font_small, fill='#666')
    y += 28
    keywords = ["맛있어요", "친절해요", "깔끔해요"]
    x = 25
    for kw in keywords:
        w = len(kw) * 14 + 28
        draw.rounded_rectangle([x, y, x+w, y+34], radius=17, fill='#03C75A')
        draw.text((x + w//2, y+17), kw, font=font_small, fill='white', anchor='mm')
        x += w + 10
    y += 60

    draw.text((25, y), "리뷰 내용", font=font_small, fill='#666')
    y += 28
    draw.rounded_rectangle([20, y, width-20, y+120], radius=12, outline='#ddd', width=2)
    draw.text((35, y+18), "모듬 정말 맛있었어요!", font=font_normal, fill='#333')
    draw.text((35, y+45), "친절하고 분위기도 좋아서", font=font_normal, fill='#333')
    draw.text((35, y+72), "또 방문할게요~ 추천합니다!", font=font_normal, fill='#333')
    y += 145

    draw.text((25, y), "사진 (2장)", font=font_small, fill='#666')
    y += 30
    for i in range(2):
        draw.rounded_rectangle([25 + i*90, y, 100 + i*90, y+70], radius=10, fill='#f5f5f5', outline='#ddd')
        draw.text((62 + i*90, y+35), "📷", font=font_title, anchor='mm')
    y += 100

    draw.rounded_rectangle([20, y, width-20, y+52], radius=12, fill='#03C75A')
    draw.text((width//2, y+26), "등록하기", font=font_title, fill='white', anchor='mm')

    img.save(f'{OUTPUT_DIR}/raw4.png')
    print('캡처: 네이버')

def main():
    print("1. 화면 캡처...")
    capture_screens()

    print("\n2. 네이버 화면...")
    create_naver_screen()

    print("\n3. 3D 폰 목업...")
    angles = [-4, -3, -2, -3, -4]
    for i in [1, 2, 3, 4, 5]:
        raw_path = f'{OUTPUT_DIR}/raw{i}.png'
        if os.path.exists(raw_path):
            create_3d_phone_mockup(raw_path, f'{OUTPUT_DIR}/screen{i}.png', angles[i-1])
            os.remove(raw_path)

    print("\n완료!")

if __name__ == "__main__":
    main()
