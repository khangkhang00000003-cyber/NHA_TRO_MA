"""Generate Vietnamese rent invoices as PDF attachments."""
from __future__ import annotations

import io
import os
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

GREEN = colors.HexColor("#176B57")
DARK = colors.HexColor("#153D36")
MINT = colors.HexColor("#E6F1EB")
GOLD = colors.HexColor("#D0AD65")
TEXT = colors.HexColor("#253D37")
MUTED = colors.HexColor("#637A72")
REGULAR = "Helvetica"
BOLD = "Helvetica-Bold"


def _setup_font() -> None:
    global REGULAR, BOLD
    if REGULAR != "Helvetica":
        return
    candidates = [
        os.getenv("PDF_FONT_REGULAR", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
    ]
    bold_candidates = [
        os.getenv("PDF_FONT_BOLD", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
    ]
    regular_path = next((p for p in candidates if p and Path(p).exists()), None)
    bold_path = next((p for p in bold_candidates if p and Path(p).exists()), None)
    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont("RentSans", regular_path))
            REGULAR = "RentSans"
        if bold_path:
            pdfmetrics.registerFont(TTFont("RentSansBold", bold_path))
            BOLD = "RentSansBold"
        elif regular_path:
            BOLD = "RentSans"
    except Exception:
        REGULAR, BOLD = "Helvetica", "Helvetica-Bold"


def calculate(bill: dict, settings: dict) -> dict:
    used_electricity = max(0, int(bill.get("electricity_new", 0) or 0) - int(bill.get("electricity_old", 0) or 0))
    used_water = max(0, int(bill.get("water_new", 0) or 0) - int(bill.get("water_old", 0) or 0))
    electricity = used_electricity * int(settings.get("electric_rate", 3500) or 0)
    water = used_water * int(settings.get("water_rate", 15000) or 0)
    other = int(settings.get("other_fee", 150000) or 0)
    rent = int(bill.get("rent_price", 0) or 0)
    return {
        "used_electricity": used_electricity,
        "used_water": used_water,
        "electricity_cost": electricity,
        "water_cost": water,
        "other_fee": other,
        "rent_price": rent,
        "total": rent + electricity + water + other,
    }


def money(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".") + " đ"


def create_invoice_pdf(bill: dict, settings: dict, year: int, month: int) -> bytes:
    _setup_font()
    calc = calculate(bill, settings)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=f"Hoa don tien tro phong {bill.get('room_no')}")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", fontName=BOLD, fontSize=10, leading=14, textColor=GREEN))
    styles.add(ParagraphStyle(name="InvoiceTitle", fontName=BOLD, fontSize=21, leading=26, textColor=DARK, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="SmallMuted", fontName=REGULAR, fontSize=8.5, leading=12, textColor=MUTED))
    styles.add(ParagraphStyle(name="BodyVi", fontName=REGULAR, fontSize=9.5, leading=14, textColor=TEXT))
    styles.add(ParagraphStyle(name="TotalLabel", fontName=BOLD, fontSize=11, leading=15, textColor=DARK))
    styles.add(ParagraphStyle(name="TotalAmount", fontName=BOLD, fontSize=17, leading=22, textColor=GREEN, alignment=TA_RIGHT))
    elements = []
    heading = Table([
        [Paragraph("QUAN GIA<br/><font size='8'>RENTAL MANAGEMENT</font>", styles["Brand"]),
         Paragraph(f"PHIẾU TIỀN PHÒNG<br/><font size='10'>THÁNG {month:02d}/{year}</font>", styles["InvoiceTitle"])],
    ], colWidths=[62 * mm, 110 * mm])
    heading.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, -1), 2, GOLD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements += [heading, Spacer(1, 8 * mm)]

    tenant = escape(str(bill.get("tenant_name") or "Chưa cập nhật"))
    contact = escape(str(bill.get("tenant_phone") or "Chưa cập nhật"))
    email = escape(str(bill.get("tenant_email") or "Chưa cập nhật"))
    status = escape(str(bill.get("payment_status") or "Chưa thanh toán"))
    identity = Table([
        [Paragraph("THÔNG TIN NGƯỜI THUÊ", styles["Brand"]), Paragraph("TRẠNG THÁI", styles["Brand"])],
        [Paragraph(f"<b>Phòng:</b> {int(bill['room_no']):02d}<br/><b>Người thuê:</b> {tenant}<br/><b>Điện thoại:</b> {contact}<br/><b>Email:</b> {email}", styles["BodyVi"]),
         Paragraph(f"<b>{status}</b><br/><br/><font color='#637A72'>Ngày lập: {__import__('datetime').date.today().strftime('%d/%m/%Y')}</font>", styles["BodyVi"])],
    ], colWidths=[110 * mm, 62 * mm])
    identity.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), MINT),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D3E3D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("SPAN", (0, 0), (0, 0)),
    ]))
    elements += [identity, Spacer(1, 8 * mm)]

    data = [
        ["NỘI DUNG", "CHỈ SỐ CŨ", "CHỈ SỐ MỚI", "THÀNH TIỀN"],
        ["Giá phòng", "—", "—", money(calc["rent_price"])],
        [f"Điện ({calc['used_electricity']} kWh × {money(settings.get('electric_rate', 3500))})",
         str(int(bill.get("electricity_old", 0) or 0)), str(int(bill.get("electricity_new", 0) or 0)), money(calc["electricity_cost"])],
        [f"Nước ({calc['used_water']} m³ × {money(settings.get('water_rate', 15000))})",
         str(int(bill.get("water_old", 0) or 0)), str(int(bill.get("water_new", 0) or 0)), money(calc["water_cost"])],
        ["Phí khác / dịch vụ", "—", "—", money(calc["other_fee"])],
    ]
    bill_table = Table(data, colWidths=[83 * mm, 25 * mm, 25 * mm, 39 * mm], repeatRows=1)
    bill_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD),
        ("FONTNAME", (0, 1), (-1, -1), REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#D7E4DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8F5")]),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements += [bill_table, Spacer(1, 6 * mm)]

    total_table = Table([[Paragraph("TỔNG TIỀN CẦN THANH TOÁN", styles["TotalLabel"]),
                          Paragraph(money(calc["total"]), styles["TotalAmount"])]], colWidths=[95 * mm, 77 * mm])
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), MINT),
        ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    elements += [total_table, Spacer(1, 6 * mm)]

    note = escape(str(bill.get("note", "") or "Không có ghi chú."))
    elements.append(Paragraph(f"<b>Ghi chú:</b> {note}", styles["BodyVi"]))
    elements += [Spacer(1, 14 * mm),
                 Paragraph("Cảm ơn bạn đã phối hợp thanh toán đúng hạn.",
                           ParagraphStyle(name="Thanks", fontName=BOLD, fontSize=10, leading=14, textColor=GREEN, alignment=TA_CENTER)),
                 Spacer(1, 3 * mm),
                 Paragraph("Phiếu được tạo tự động từ hệ thống quản lý tiền phòng.",
                           ParagraphStyle(name="Foot", fontName=REGULAR, fontSize=8, leading=11, textColor=MUTED, alignment=TA_CENTER))]
    doc.build(elements)
    return buffer.getvalue()
