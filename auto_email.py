"""Send monthly rental invoices automatically.

Run this file once per day using Windows Task Scheduler or your server's scheduler.
Only successful sends are considered complete, so failed emails are retried on the next run.
"""
from __future__ import annotations

import argparse
import io
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from email_utils import get_smtp_config, send_pdf_email, smtp_is_configured

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("RENTAL_DB_PATH", str(BASE_DIR / "quan_ly_tien_tro.sqlite3")))


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS monthly_settings (
            year INTEGER NOT NULL, month INTEGER NOT NULL,
            gia_dien INTEGER NOT NULL DEFAULT 3500,
            gia_nuoc INTEGER NOT NULL DEFAULT 15000,
            phi_khac INTEGER NOT NULL DEFAULT 150000,
            so_phong INTEGER NOT NULL DEFAULT 10,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (year, month))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS room_bills (
            year INTEGER NOT NULL, month INTEGER NOT NULL, room_no INTEGER NOT NULL,
            gia_phong INTEGER NOT NULL DEFAULT 2500000,
            thong_tin_nguoi_o TEXT NOT NULL DEFAULT '',
            email_nguoi_o TEXT NOT NULL DEFAULT '',
            gui_email_tu_dong INTEGER NOT NULL DEFAULT 0,
            dien_cu INTEGER NOT NULL DEFAULT 0, dien_moi INTEGER NOT NULL DEFAULT 0,
            nuoc_cu INTEGER NOT NULL DEFAULT 0, nuoc_moi INTEGER NOT NULL DEFAULT 0,
            trang_thai TEXT NOT NULL DEFAULT 'Chưa thanh toán',
            ghi_chu TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (year, month, room_no))""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(room_bills)").fetchall()}
        if "email_nguoi_o" not in columns:
            conn.execute("ALTER TABLE room_bills ADD COLUMN email_nguoi_o TEXT NOT NULL DEFAULT ''")
        if "gui_email_tu_dong" not in columns:
            conn.execute("ALTER TABLE room_bills ADD COLUMN gui_email_tu_dong INTEGER NOT NULL DEFAULT 0")
        conn.execute("""CREATE TABLE IF NOT EXISTS email_log (
            year INTEGER NOT NULL, month INTEGER NOT NULL, room_no INTEGER NOT NULL,
            email TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'Lỗi',
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (year, month, room_no))""")


def prev_period(year: int, month: int) -> tuple[int, int]:
    first = date(year, month, 1)
    prev = first - timedelta(days=1)
    return prev.year, prev.month


def load_or_create_settings(year: int, month: int) -> dict:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM monthly_settings WHERE year=? AND month=?", (year, month)
        ).fetchone()
        if row:
            return dict(row)
        prev_year, prev_month = prev_period(year, month)
        previous = conn.execute(
            "SELECT gia_dien, gia_nuoc, phi_khac, so_phong FROM monthly_settings WHERE year=? AND month=?",
            (prev_year, prev_month),
        ).fetchone()
        if not previous:
            previous = conn.execute(
                "SELECT gia_dien, gia_nuoc, phi_khac, so_phong FROM monthly_settings ORDER BY year DESC, month DESC LIMIT 1"
            ).fetchone()
        if previous:
            settings = {key: int(previous[key]) for key in ("gia_dien", "gia_nuoc", "phi_khac", "so_phong")}
        else:
            settings = {"gia_dien": 3500, "gia_nuoc": 15000, "phi_khac": 150000, "so_phong": int(os.getenv("DEFAULT_ROOMS", "10"))}
        conn.execute(
            "INSERT INTO monthly_settings(year, month, gia_dien, gia_nuoc, phi_khac, so_phong) VALUES (?, ?, ?, ?, ?, ?)",
            (year, month, settings["gia_dien"], settings["gia_nuoc"], settings["phi_khac"], settings["so_phong"]),
        )
        return settings


def prepare_rooms(year: int, month: int, room_count: int) -> None:
    py, pm = prev_period(year, month)
    with connect_db() as conn:
        for room_no in range(1, room_count + 1):
            row = conn.execute(
                "SELECT 1 FROM room_bills WHERE year=? AND month=? AND room_no=?",
                (year, month, room_no),
            ).fetchone()
            if row:
                continue
            previous = conn.execute(
                "SELECT * FROM room_bills WHERE year=? AND month=? AND room_no=?",
                (py, pm, room_no),
            ).fetchone()
            if previous:
                rent = int(previous["gia_phong"] or 2500000)
                tenant = previous["thong_tin_nguoi_o"] or ""
                email = previous["email_nguoi_o"] or ""
                old_electric = int(previous["dien_moi"] or 0)
                old_water = int(previous["nuoc_moi"] or 0)
            else:
                rent, tenant, email, old_electric, old_water = 2500000, "", "", 0, 0
            conn.execute(
                """INSERT INTO room_bills (
                    year, month, room_no, gia_phong, thong_tin_nguoi_o, email_nguoi_o,
                    dien_cu, dien_moi, nuoc_cu, nuoc_moi, trang_thai, ghi_chu
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Chưa thanh toán', '')""",
                (year, month, room_no, rent, tenant, email, old_electric, old_electric, old_water, old_water),
            )


def get_bills(year: int, month: int) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM room_bills WHERE year=? AND month=? ORDER BY room_no", (year, month)
        ).fetchall()
    return [dict(row) for row in rows]


def get_log(year: int, month: int, room_no: int) -> dict | None:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM email_log WHERE year=? AND month=? AND room_no=?", (year, month, room_no)
        ).fetchone()
    return dict(row) if row else None


def write_log(year: int, month: int, room_no: int, email: str, status: str, error: str = "") -> None:
    with connect_db() as conn:
        conn.execute(
            """INSERT INTO email_log(year, month, room_no, email, status, sent_at, error)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(year, month, room_no) DO UPDATE SET email=excluded.email,
                status=excluded.status, sent_at=CURRENT_TIMESTAMP, error=excluded.error""",
            (year, month, room_no, email, status, error[:1000]),
        )


PDF_REGULAR = "Helvetica"
PDF_BOLD = "Helvetica-Bold"


def setup_fonts() -> None:
    global PDF_REGULAR, PDF_BOLD
    if PDF_REGULAR != "Helvetica":
        return
    regular_options = [
        os.getenv("PDF_FONT_REGULAR", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
    ]
    bold_options = [
        os.getenv("PDF_FONT_BOLD", ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
    ]
    regular = next((path for path in regular_options if path and Path(path).exists()), None)
    bold = next((path for path in bold_options if path and Path(path).exists()), None)
    try:
        if regular:
            pdfmetrics.registerFont(TTFont("AutoRentalUnicode", regular))
            PDF_REGULAR = "AutoRentalUnicode"
        if bold:
            pdfmetrics.registerFont(TTFont("AutoRentalUnicodeBold", bold))
            PDF_BOLD = "AutoRentalUnicodeBold"
        elif regular:
            PDF_BOLD = "AutoRentalUnicode"
    except Exception:
        PDF_REGULAR, PDF_BOLD = "Helvetica", "Helvetica-Bold"


def calculate(bill: dict, settings: dict) -> dict:
    used_electric = max(int(bill["dien_moi"]) - int(bill["dien_cu"]), 0)
    used_water = max(int(bill["nuoc_moi"]) - int(bill["nuoc_cu"]), 0)
    electric_cost = used_electric * int(settings["gia_dien"])
    water_cost = used_water * int(settings["gia_nuoc"])
    other = int(settings["phi_khac"])
    return {
        "used_electric": used_electric, "used_water": used_water,
        "electric_cost": electric_cost, "water_cost": water_cost,
        "other": other, "total": int(bill["gia_phong"]) + electric_cost + water_cost + other,
    }


def money(value: int) -> str:
    return f"{int(value):,}".replace(",", ".") + " VNĐ"


def make_pdf(bill: dict, settings: dict, year: int, month: int) -> bytes:
    setup_fonts()
    costs = calculate(bill, settings)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("RentalAutoTitle", parent=styles["Title"], fontName=PDF_BOLD, fontSize=16, leading=22, alignment=TA_CENTER, textColor=colors.HexColor("#176B55"), spaceAfter=5)
    normal = ParagraphStyle("RentalAutoNormal", parent=styles["Normal"], fontName=PDF_REGULAR, fontSize=10, leading=14)
    small = ParagraphStyle("RentalAutoSmall", parent=normal, fontSize=9, textColor=colors.HexColor("#5E6B66"))
    story = [
        Paragraph("PHIẾU TIỀN PHÒNG TRỌ", title),
        Paragraph(f"Kỳ thanh toán: Tháng {month:02d}/{year}", ParagraphStyle("RentalAutoSub", parent=normal, alignment=TA_CENTER, spaceAfter=14)),
    ]
    tenant = escape((bill.get("thong_tin_nguoi_o") or "Chưa cập nhật").strip())
    email = escape((bill.get("email_nguoi_o") or "Chưa cập nhật").strip())
    info = [
        [Paragraph("Phòng", normal), Paragraph(f"Phòng {int(bill['room_no']):02d}", normal)],
        [Paragraph("Người ở", normal), Paragraph(tenant, normal)],
        [Paragraph("Email", normal), Paragraph(email, normal)],
        [Paragraph("Trạng thái", normal), Paragraph(escape(bill.get("trang_thai", "Chưa thanh toán")), normal)],
        [Paragraph("Ghi chú", normal), Paragraph(escape((bill.get("ghi_chu") or "Không có").strip()), normal)],
    ]
    it = Table(info, colWidths=[32 * mm, 138 * mm])
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F7F4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E4DE")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([it, Spacer(1, 9 * mm), Paragraph("CHI TIẾT CÁC KHOẢN THU", ParagraphStyle("RentalAutoSection", parent=normal, fontName=PDF_BOLD, fontSize=11, textColor=colors.HexColor("#176B55"), spaceAfter=6))])
    charges = [
        [Paragraph("Khoản thu", normal), Paragraph("Cách tính", normal), Paragraph("Thành tiền", normal)],
        [Paragraph("Tiền phòng", normal), Paragraph("Giá thuê trong tháng", normal), Paragraph(money(bill["gia_phong"]), normal)],
        [Paragraph("Tiền điện", normal), Paragraph(f"{costs['used_electric']} kWh × {money(settings['gia_dien'])}/kWh", normal), Paragraph(money(costs["electric_cost"]), normal)],
        [Paragraph("Tiền nước", normal), Paragraph(f"{costs['used_water']} m³ × {money(settings['gia_nuoc'])}/m³", normal), Paragraph(money(costs["water_cost"]), normal)],
        [Paragraph("Phí khác", normal), Paragraph("Wifi, vệ sinh và phí dịch vụ", normal), Paragraph(money(costs["other"]), normal)],
        [Paragraph("TỔNG CỘNG", ParagraphStyle("RentalAutoTotalLabel", parent=normal, fontName=PDF_BOLD)), "", Paragraph(money(costs["total"]), ParagraphStyle("RentalAutoTotal", parent=normal, fontName=PDF_BOLD, textColor=colors.HexColor("#176B55")))],
    ]
    ct = Table(charges, colWidths=[35 * mm, 86 * mm, 49 * mm], repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F3ED")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F7F4")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9DAD1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    meters = [
        [Paragraph("Chỉ số", normal), Paragraph("Số cũ", normal), Paragraph("Số mới", normal), Paragraph("Tiêu thụ", normal)],
        [Paragraph("Điện (kWh)", normal), str(bill["dien_cu"]), str(bill["dien_moi"]), str(costs["used_electric"])],
        [Paragraph("Nước (m³)", normal), str(bill["nuoc_cu"]), str(bill["nuoc_moi"]), str(costs["used_water"])],
    ]
    mt = Table(meters, colWidths=[45 * mm, 40 * mm, 40 * mm, 45 * mm])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F7F4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E4DE")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([Spacer(1, 8 * mm), ct, Spacer(1, 8 * mm), Paragraph("CHỈ SỐ ĐIỆN, NƯỚC", ParagraphStyle("RentalAutoSection2", parent=normal, fontName=PDF_BOLD, fontSize=11, textColor=colors.HexColor("#176B55"), spaceAfter=6)), mt, Spacer(1, 10 * mm), Paragraph("Vui lòng kiểm tra các khoản thu và phản hồi nếu có sai sót.", small)])
    doc.build(story)
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Gửi hóa đơn tiền trọ qua email theo lịch.")
    parser.add_argument("--force", action="store_true", help="Gửi ngay, không kiểm tra SEND_DAY.")
    parser.add_argument("--resend", action="store_true", help="Gửi lại cả những hóa đơn đã gửi thành công.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ liệt kê người nhận, không gửi email.")
    parser.add_argument("--year", type=int, help="Năm hóa đơn (mặc định: năm hiện tại).")
    parser.add_argument("--month", type=int, help="Tháng hóa đơn (mặc định: tháng hiện tại).")
    args = parser.parse_args()

    today = date.today()
    year = args.year or today.year
    month = args.month or today.month
    if not 1 <= month <= 12:
        print("Tháng phải nằm trong khoảng 1–12.", file=sys.stderr)
        return 2

    send_day = max(1, min(28, int(os.getenv("SEND_DAY", "1"))))
    if not args.force and today.day < send_day:
        print(f"Chưa đến ngày gửi. SEND_DAY={send_day}; hôm nay là ngày {today.day}. Không làm gì.")
        return 0

    init_db()
    settings = load_or_create_settings(year, month)
    prepare_rooms(year, month, int(settings["so_phong"]))
    bills = get_bills(year, month)
    only_unpaid = os.getenv("AUTO_EMAIL_ONLY_UNPAID", "false").lower() in {"1", "true", "yes", "on"}
    config = get_smtp_config()
    if not args.dry_run and not smtp_is_configured(config):
        print("Chưa cấu hình SMTP. Hãy thiết lập file .env hoặc biến môi trường SMTP_*.", file=sys.stderr)
        return 2

    sent = skipped = failed = 0
    for bill in bills:
        room_no = int(bill["room_no"])
        recipient = (bill.get("email_nguoi_o") or "").strip()
        if not recipient:
            print(f"[BỎ QUA] Phòng {room_no:02d}: chưa có email")
            skipped += 1
            continue
        if not int(bill.get("gui_email_tu_dong", 0) or 0):
            print(f"[BỎ QUA] Phòng {room_no:02d}: chưa chốt hóa đơn/không bật gửi tự động")
            skipped += 1
            continue
        if only_unpaid and bill.get("trang_thai") == "Đã thanh toán":
            print(f"[BỎ QUA] Phòng {room_no:02d}: đã thanh toán (AUTO_EMAIL_ONLY_UNPAID=true)")
            skipped += 1
            continue
        old = get_log(year, month, room_no)
        if old and old.get("status") == "Đã gửi" and not args.resend:
            print(f"[BỎ QUA] Phòng {room_no:02d}: đã gửi thành công trước đó")
            skipped += 1
            continue
        costs = calculate(bill, settings)
        print(f"[{ 'DRY-RUN' if args.dry_run else 'GỬI' }] Phòng {room_no:02d} -> {recipient} | {money(costs['total'])}")
        if args.dry_run:
            continue
        try:
            pdf = make_pdf(bill, settings, year, month)
            tenant = bill.get("thong_tin_nguoi_o") or f"Phòng {room_no:02d}"
            subject = f"Hóa đơn tiền trọ - Phòng {room_no:02d} - Tháng {month:02d}/{year}"
            body = (
                f"Xin chào {tenant},\n\n"
                f"Đính kèm là phiếu tiền phòng tháng {month:02d}/{year}.\n"
                f"Tổng tiền: {money(costs['total'])}.\n"
                f"Trạng thái thanh toán: {bill.get('trang_thai', 'Chưa thanh toán')}.\n\n"
                "Vui lòng xem file PDF đính kèm và liên hệ chủ trọ nếu có sai sót.\n"
                "Trân trọng."
            )
            filename = f"Phieu_Tien_Phong_{room_no:02d}_T{month:02d}_{year}.pdf"
            send_pdf_email(recipient, subject, body, pdf, filename, config)
            write_log(year, month, room_no, recipient, "Đã gửi", "")
            sent += 1
            print(f"[OK] Phòng {room_no:02d} gửi thành công")
        except Exception as exc:
            write_log(year, month, room_no, recipient, "Lỗi", str(exc))
            failed += 1
            print(f"[LỖI] Phòng {room_no:02d}: {exc}", file=sys.stderr)

    print(f"Hoàn tất kỳ {month:02d}/{year}: {sent} gửi thành công, {skipped} bỏ qua, {failed} lỗi.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
