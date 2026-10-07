"""검정 프레임 없이 화면만 캡처"""
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFilter
import os

OUTPUT_DIR = 'C:/Users/Administrator/Desktop/placemaster'

def add_subtle_shadow(img_path, output_path):
    """미세한 그림자만 추가 (프레임 없음)"""
    img = Image.open(img_path).convert('RGBA')

    # 캔버스 (그림자 공간)
    padding = 20
    canvas = Image.new('RGBA', (img.width + padding*2, img.height + padding*2), (255, 255, 255, 0))

    # 그림자
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [padding + 8, padding + 8, padding + img.width + 8, padding + img.height + 8],
        radius=24, fill=(0, 0, 0, 40)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(15))

    canvas = Image.alpha_composite(canvas, shadow)

    # 이미지 (라운드 코너)
    mask = Image.new('L', img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, img.width, img.height], radius=24, fill=255)

    img_rounded = Image.new('RGBA', img.size, (0, 0, 0, 0))
    img_rounded.paste(img, (0, 0), mask)

    canvas.paste(img_rounded, (padding, padding), img_rounded)
    canvas.save(output_path, 'PNG')
    print(f'완료: {output_path}')

def capture_screens():
    """preview 페이지 각 화면 캡처 (프레임 없이)"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # 더 큰 뷰포트
        page = browser.new_page(viewport={'width': 390, 'height': 750})

        url = 'https://narusepopo-droid.github.io/receipt-review/tools/preview/'
        page.goto(url, wait_until='networkidle')
        page.wait_for_timeout(1000)

        screens = [
            ('번호입력', 'screen1.png'),
            ('키워드', 'screen2.png'),
            ('결과', 'screen3.png'),
            ('완료', 'screen5.png'),
        ]

        for btn_text, filename in screens:
            page.click(f'button:has-text("{btn_text}")')
            page.wait_for_timeout(500)

            # 네비게이션 숨기기
            page.evaluate('document.querySelector(".preview-nav").style.display = "none"')
            page.evaluate('document.querySelector(".preview-container").style.paddingTop = "0"')

            # 임시 파일로 캡처
            temp_path = f'{OUTPUT_DIR}/temp_{filename}'
            page.screenshot(path=temp_path)

            # 그림자만 추가
            add_subtle_shadow(temp_path, f'{OUTPUT_DIR}/{filename}')
            os.remove(temp_path)

            # 복원
            page.evaluate('document.querySelector(".preview-nav").style.display = "flex"')
            page.evaluate('document.querySelector(".preview-container").style.paddingTop = "60px"')

        browser.close()

def create_naver_screen():
    """네이버 리뷰 화면 (screen4)"""
    from PIL import ImageFont

    width, height = 390, 750
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

    # 영수증 인증 완료
    draw.rounded_rectangle([20, y, width-20, y+50], radius=12, fill='#e8f5e9')
    draw.text((width//2, y+25), "✓ 영수증 인증 완료", font=font_normal, fill='#2e7d32', anchor='mm')
    y += 75

    # 별점
    draw.text((25, y), "별점을 선택해주세요", font=font_small, fill='#666')
    y += 30
    draw.text((25, y), "★★★★★", font=font_title, fill='#FFD700')
    y += 50

    # 키워드
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

    # 리뷰 입력
    draw.text((25, y), "리뷰 내용", font=font_small, fill='#666')
    y += 30
    draw.rounded_rectangle([20, y, width-20, y+130], radius=12, outline='#ddd', width=2)
    draw.text((35, y+20), "모듬 정말 맛있었어요!", font=font_normal, fill='#333')
    draw.text((35, y+50), "친절하고 분위기도 좋아서", font=font_normal, fill='#333')
    draw.text((35, y+80), "또 방문할게요~ 추천합니다!", font=font_normal, fill='#333')
    y += 160

    # 사진 첨부
    draw.text((25, y), "사진 첨부 (2장)", font=font_small, fill='#666')
    y += 35
    for i in range(2):
        draw.rounded_rectangle([25 + i*95, y, 105 + i*95, y+80], radius=10, fill='#f5f5f5', outline='#ddd')
        draw.text((65 + i*95, y+40), "📷", font=font_title, anchor='mm')
    y += 110

    # 등록 버튼
    draw.rounded_rectangle([20, y, width-20, y+56], radius=12, fill='#03C75A')
    draw.text((width//2, y+28), "등록하기", font=font_title, fill='white', anchor='mm')

    temp_path = f'{OUTPUT_DIR}/temp_naver.png'
    img.save(temp_path)
    add_subtle_shadow(temp_path, f'{OUTPUT_DIR}/screen4.png')
    os.remove(temp_path)

def main():
    print("1. 화면 캡처 중 (프레임 없이)...")
    capture_screens()

    print("\n2. 네이버 화면 생성...")
    create_naver_screen()

    print("\n완료!")

if __name__ == "__main__":
    main()
