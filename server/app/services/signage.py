"""
테이블 안내판 생성기
- 매장명 + 혜택 문구
- QR 코드
- 단계 안내
"""
import io
import os
from typing import Optional
from dataclasses import dataclass

import qrcode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A6, A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


@dataclass
class SignageConfig:
    store_name: str
    store_code: str
    benefit_text: str
    table_count: int
    base_url: str = "https://review.placemaster.co.kr"
    size: str = "A6"  # A6 or A5
    primary_color: str = "#2563EB"


def generate_qr_code(url: str, size: int = 200) -> Image.Image:
    """QR 코드 생성"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def generate_signage_png(config: SignageConfig, table_no: int) -> bytes:
    """테이블 안내판 PNG 생성"""
    # 크기 설정
    if config.size == "A5":
        width, height = 420, 595  # A5 세로
    else:
        width, height = 297, 420  # A6 세로

    # 이미지 생성
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # 폰트 로드
    try:
        font_title = ImageFont.truetype("malgunbd.ttf", 24)
        font_benefit = ImageFont.truetype("malgunbd.ttf", 18)
        font_step = ImageFont.truetype("malgun.ttf", 12)
        font_table = ImageFont.truetype("malgun.ttf", 10)
    except:
        font_title = ImageFont.load_default()
        font_benefit = font_title
        font_step = font_title
        font_table = font_title

    y = 20
    cx = width // 2

    # 매장명
    draw.text((cx, y), config.store_name, font=font_title, fill="black", anchor="mm")
    y += 35

    # 혜택 문구
    draw.text((cx, y), config.benefit_text, font=font_benefit, fill=config.primary_color, anchor="mm")
    y += 40

    # QR 코드
    qr_url = f"{config.base_url}/t/{config.store_code}/{table_no}"
    qr_img = generate_qr_code(qr_url, 120)
    qr_x = (width - 120) // 2
    img.paste(qr_img, (qr_x, y))
    y += 130

    # 단계 안내
    steps = [
        "1. 📷 음식·매장 사진 2장 먼저 찍기",
        "2. QR 찍고 휴대폰 번호 입력",
        "3. [영수증 저장] → 네이버로 이동",
        "4. 영수증 선택 → 사진 첨부 → 붙여넣기",
        "5. 직원에게 완료 화면 보여주고 혜택 받기",
    ]

    for step in steps:
        draw.text((20, y), step, font=font_step, fill="black")
        y += 18

    y += 10

    # 테이블 번호
    if table_no > 0:
        draw.text((cx, y), f"테이블 {table_no}", font=font_table, fill="gray", anchor="mm")

    # PNG로 변환
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def generate_signage_pdf(config: SignageConfig) -> bytes:
    """전체 테이블 안내판 PDF 생성"""
    buffer = io.BytesIO()

    # 페이지 크기
    if config.size == "A5":
        page_size = A5
    else:
        page_size = A6

    c = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size

    # 폰트 등록 (시스템에 맑은고딕이 있다면)
    try:
        font_path = "C:/Windows/Fonts/malgun.ttf"
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont("Malgun", font_path))
            pdfmetrics.registerFont(TTFont("MalgunBold", "C:/Windows/Fonts/malgunbd.ttf"))
            use_korean_font = True
        else:
            use_korean_font = False
    except:
        use_korean_font = False

    for table_no in range(1, config.table_count + 1):
        # 매장명
        if use_korean_font:
            c.setFont("MalgunBold", 18)
        else:
            c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 30 * mm, config.store_name)

        # 혜택 문구
        if use_korean_font:
            c.setFont("MalgunBold", 14)
        c.setFillColor(config.primary_color)
        c.drawCentredString(width / 2, height - 45 * mm, config.benefit_text)
        c.setFillColorRGB(0, 0, 0)

        # QR 코드
        qr_url = f"{config.base_url}/t/{config.store_code}/{table_no}"
        qr_img = generate_qr_code(qr_url, 200)

        # PIL 이미지를 ReportLab에서 사용
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        from reportlab.lib.utils import ImageReader
        qr_reader = ImageReader(qr_buffer)
        qr_size = 35 * mm
        c.drawImage(qr_reader, (width - qr_size) / 2, height - 95 * mm, qr_size, qr_size)

        # 단계 안내
        if use_korean_font:
            c.setFont("Malgun", 9)
        else:
            c.setFont("Helvetica", 9)

        steps = [
            "1. 음식·매장 사진 2장 먼저 찍기",
            "2. QR 찍고 휴대폰 번호 입력",
            "3. [영수증 저장] → 네이버로 이동",
            "4. 영수증 선택 → 사진 첨부 → 붙여넣기",
            "5. 직원에게 완료 화면 보여주기",
        ]

        y = height - 105 * mm
        for step in steps:
            c.drawString(15 * mm, y, step)
            y -= 5 * mm

        # 테이블 번호
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawCentredString(width / 2, 10 * mm, f"Table {table_no}")
        c.setFillColorRGB(0, 0, 0)

        # 다음 페이지
        if table_no < config.table_count:
            c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.getvalue()
