import io
import os
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st
from email_utils import get_smtp_config, smtp_is_configured, send_pdf_email
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)


# ============================================================
# CẤU HÌNH ỨNG DỤNG & DATABASE
# ============================================================
st.set_page_config(
    page_title="Quản lý tiền phòng trọ",
    page_icon="🏠",
    layout="wide",
)

DB_PATH = Path(
    os.environ.get(
        "RENTAL_DB_PATH",
        str(Path(__file__).resolve().with_name("quan_ly_tien_tro.sqlite3")),
    )
)
TRANG_THAI = ["Chưa thanh toán", "Đã thanh toán"]


@contextmanager
def db_connection():
    """Tạo kết nối SQLite và luôn đóng kết nối sau khi sử dụng."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Tạo các bảng cần thiết nếu đây là lần chạy đầu tiên."""
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_settings (
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                gia_dien INTEGER NOT NULL DEFAULT 3500,
                gia_nuoc INTEGER NOT NULL DEFAULT 15000,
                phi_khac INTEGER NOT NULL DEFAULT 150000,
                so_phong INTEGER NOT NULL DEFAULT 10,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (year, month)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS room_bills (
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                room_no INTEGER NOT NULL,
                gia_phong INTEGER NOT NULL DEFAULT 2500000,
                thong_tin_nguoi_o TEXT NOT NULL DEFAULT '',
                email_nguoi_o TEXT NOT NULL DEFAULT '',
                gui_email_tu_dong INTEGER NOT NULL DEFAULT 0,
                dien_cu INTEGER NOT NULL DEFAULT 0,
                dien_moi INTEGER NOT NULL DEFAULT 0,
                nuoc_cu INTEGER NOT NULL DEFAULT 0,
                nuoc_moi INTEGER NOT NULL DEFAULT 0,
                trang_thai TEXT NOT NULL DEFAULT 'Chưa thanh toán',
                ghi_chu TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (year, month, room_no)
            )
            """
        )
        # Hỗ trợ nâng cấp database cũ mà không làm mất dữ liệu.
        room_columns = {row["name"] for row in conn.execute("PRAGMA table_info(room_bills)").fetchall()}
        if "email_nguoi_o" not in room_columns:
            conn.execute("ALTER TABLE room_bills ADD COLUMN email_nguoi_o TEXT NOT NULL DEFAULT ''")
        if "gui_email_tu_dong" not in room_columns:
            conn.execute("ALTER TABLE room_bills ADD COLUMN gui_email_tu_dong INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_room_bills_period "
            "ON room_bills(year, month, room_no)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_log (
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                room_no INTEGER NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Lỗi',
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (year, month, room_no)
            )
            """
        )


def get_month_settings(year: int, month: int) -> dict:
    defaults = {
        "gia_dien": 3500,
        "gia_nuoc": 15000,
        "phi_khac": 150000,
        "so_phong": 10,
    }
    with db_connection() as conn:
        row = conn.execute(
            "SELECT gia_dien, gia_nuoc, phi_khac, so_phong "
            "FROM monthly_settings WHERE year=? AND month=?",
            (year, month),
        ).fetchone()
    if row is None:
        return defaults
    return {key: int(row[key]) for key in defaults}


def save_month_settings(
    year: int,
    month: int,
    gia_dien: int,
    gia_nuoc: int,
    phi_khac: int,
    so_phong: int,
):
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO monthly_settings
                (year, month, gia_dien, gia_nuoc, phi_khac, so_phong, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(year, month) DO UPDATE SET
                gia_dien=excluded.gia_dien,
                gia_nuoc=excluded.gia_nuoc,
                phi_khac=excluded.phi_khac,
                so_phong=excluded.so_phong,
                updated_at=CURRENT_TIMESTAMP
            """,
            (year, month, gia_dien, gia_nuoc, phi_khac, so_phong),
        )


def get_previous_period(year: int, month: int) -> tuple[int, int]:
    first_day = date(year, month, 1)
    last_day_previous_month = first_day - timedelta(days=1)
    return last_day_previous_month.year, last_day_previous_month.month


def ensure_month_rooms(year: int, month: int, so_phong: int):
    """Khởi tạo phòng còn thiếu; kế thừa chỉ số cuối tháng trước nếu có."""
    prev_year, prev_month = get_previous_period(year, month)
    with db_connection() as conn:
        for room_no in range(1, so_phong + 1):
            exists = conn.execute(
                "SELECT 1 FROM room_bills WHERE year=? AND month=? AND room_no=?",
                (year, month, room_no),
            ).fetchone()
            if exists:
                continue

            previous = conn.execute(
                """
                SELECT dien_moi, nuoc_moi, thong_tin_nguoi_o, email_nguoi_o, gia_phong
                FROM room_bills
                WHERE year=? AND month=? AND room_no=?
                """,
                (prev_year, prev_month, room_no),
            ).fetchone()

            if previous:
                dien_cu = int(previous["dien_moi"])
                nuoc_cu = int(previous["nuoc_moi"])
                nguoi_o = previous["thong_tin_nguoi_o"] or ""
                email_o = previous["email_nguoi_o"] or ""
                gia_phong_cu = int(previous["gia_phong"] or 2500000)
            else:
                dien_cu = 0
                nuoc_cu = 0
                nguoi_o = ""
                email_o = ""
                gia_phong_cu = 2500000

            conn.execute(
                """
                INSERT INTO room_bills (
                    year, month, room_no, gia_phong, thong_tin_nguoi_o, email_nguoi_o,
                    dien_cu, dien_moi, nuoc_cu, nuoc_moi,
                    trang_thai, ghi_chu, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Chưa thanh toán', '', CURRENT_TIMESTAMP)
                """,
                (
                    year,
                    month,
                    room_no,
                    gia_phong_cu,
                    nguoi_o,
                    email_o,
                    dien_cu,
                    dien_cu,
                    nuoc_cu,
                    nuoc_cu,
                ),
            )


def get_bill(year: int, month: int, room_no: int) -> dict | None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM room_bills WHERE year=? AND month=? AND room_no=?",
            (year, month, room_no),
        ).fetchone()
    return dict(row) if row else None


def get_bills(year: int, month: int, so_phong: int) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM room_bills
            WHERE year=? AND month=? AND room_no BETWEEN 1 AND ?
            ORDER BY room_no
            """,
            (year, month, so_phong),
        ).fetchall()
    return [dict(row) for row in rows]


def save_bill(
    year: int,
    month: int,
    room_no: int,
    gia_phong: int,
    thong_tin_nguoi_o: str,
    email_nguoi_o: str,
    gui_email_tu_dong: bool,
    dien_cu: int,
    dien_moi: int,
    nuoc_cu: int,
    nuoc_moi: int,
    trang_thai: str,
    ghi_chu: str,
):
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO room_bills (
                year, month, room_no, gia_phong, thong_tin_nguoi_o, email_nguoi_o, gui_email_tu_dong,
                dien_cu, dien_moi, nuoc_cu, nuoc_moi,
                trang_thai, ghi_chu, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(year, month, room_no) DO UPDATE SET
                gia_phong=excluded.gia_phong,
                thong_tin_nguoi_o=excluded.thong_tin_nguoi_o,
                email_nguoi_o=excluded.email_nguoi_o,
                gui_email_tu_dong=excluded.gui_email_tu_dong,
                dien_cu=excluded.dien_cu,
                dien_moi=excluded.dien_moi,
                nuoc_cu=excluded.nuoc_cu,
                nuoc_moi=excluded.nuoc_moi,
                trang_thai=excluded.trang_thai,
                ghi_chu=excluded.ghi_chu,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                year,
                month,
                room_no,
                gia_phong,
                thong_tin_nguoi_o.strip(),
                email_nguoi_o.strip(),
                1 if gui_email_tu_dong else 0,
                dien_cu,
                dien_moi,
                nuoc_cu,
                nuoc_moi,
                trang_thai,
                ghi_chu.strip(),
            ),
        )


def calculate_bill(bill: dict, settings: dict) -> dict:
    dien_tieu_thu = max(int(bill["dien_moi"]) - int(bill["dien_cu"]), 0)
    nuoc_tieu_thu = max(int(bill["nuoc_moi"]) - int(bill["nuoc_cu"]), 0)
    tien_dien = dien_tieu_thu * int(settings["gia_dien"])
    tien_nuoc = nuoc_tieu_thu * int(settings["gia_nuoc"])
    phi_khac = int(settings["phi_khac"])
    tong_tien = int(bill["gia_phong"]) + tien_dien + tien_nuoc + phi_khac
    return {
        "dien_tieu_thu": dien_tieu_thu,
        "nuoc_tieu_thu": nuoc_tieu_thu,
        "tien_dien": tien_dien,
        "tien_nuoc": tien_nuoc,
        "phi_khac": phi_khac,
        "tong_tien": tong_tien,
    }


def get_email_log(year: int, month: int, room_no: int) -> dict | None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM email_log WHERE year=? AND month=? AND room_no=?",
            (year, month, room_no),
        ).fetchone()
    return dict(row) if row else None


def record_email_log(year: int, month: int, room_no: int, email: str, status: str, error: str = ""):
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_log(year, month, room_no, email, status, sent_at, error)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(year, month, room_no) DO UPDATE SET
                email=excluded.email,
                status=excluded.status,
                sent_at=CURRENT_TIMESTAMP,
                error=excluded.error
            """,
            (year, month, room_no, email, status, error[:1000]),
        )


def get_recent_email_logs(year: int, month: int) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM email_log WHERE year=? AND month=? ORDER BY sent_at DESC, room_no",
            (year, month),
        ).fetchall()
    return [dict(row) for row in rows]


def money(value: int | float) -> str:
    return f"{int(value):,}".replace(",", ".") + " VNĐ"


# ============================================================
# XUẤT PDF (HỖ TRỢ TIẾNG VIỆT)
# ============================================================
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"
_PDF_FONT_READY = False


def setup_pdf_fonts():
    """Tìm font Unicode có sẵn trên máy để PDF hiển thị tiếng Việt."""
    global PDF_FONT_REGULAR, PDF_FONT_BOLD, _PDF_FONT_READY
    if _PDF_FONT_READY:
        return

    regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
    ]
    regular_path = next((p for p in regular_candidates if Path(p).exists()), None)
    bold_path = next((p for p in bold_candidates if Path(p).exists()), None)
    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont("RentalUnicode", regular_path))
            PDF_FONT_REGULAR = "RentalUnicode"
        if bold_path:
            pdfmetrics.registerFont(TTFont("RentalUnicode-Bold", bold_path))
            PDF_FONT_BOLD = "RentalUnicode-Bold"
        elif regular_path:
            PDF_FONT_BOLD = "RentalUnicode"
    except Exception:
        PDF_FONT_REGULAR = "Helvetica"
        PDF_FONT_BOLD = "Helvetica-Bold"
    _PDF_FONT_READY = True


def create_room_pdf(bill: dict, settings: dict, year: int, month: int) -> bytes:
    setup_pdf_fonts()
    result = calculate_bill(bill, settings)
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Tien phong - Phong {bill['room_no']} - {month:02d}/{year}",
        author="Phần mềm quản lý tiền phòng trọ",
    )

    base_styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RentalTitle",
        parent=base_styles["Title"],
        fontName=PDF_FONT_BOLD,
        fontSize=17,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#176B55"),
        spaceAfter=5,
    )
    subtitle_style = ParagraphStyle(
        "RentalSubTitle",
        parent=base_styles["Normal"],
        fontName=PDF_FONT_REGULAR,
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#52616B"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "RentalSection",
        parent=base_styles["Heading2"],
        fontName=PDF_FONT_BOLD,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#176B55"),
        spaceBefore=8,
        spaceAfter=6,
    )
    normal_style = ParagraphStyle(
        "RentalNormal",
        parent=base_styles["Normal"],
        fontName=PDF_FONT_REGULAR,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#263238"),
    )
    small_style = ParagraphStyle(
        "RentalSmall",
        parent=normal_style,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#52616B"),
    )

    story = [
        Paragraph("PHIẾU TIỀN PHÒNG TRỌ", title_style),
        Paragraph(f"Kỳ thanh toán: Tháng {month:02d}/{year}", subtitle_style),
        Paragraph(f"THÔNG TIN PHÒNG {int(bill['room_no'])}", section_style),
    ]

    tenant = escape((bill.get("thong_tin_nguoi_o") or "Chưa cập nhật").strip())
    tenant_email = escape((bill.get("email_nguoi_o") or "Chưa cập nhật").strip())
    note = escape((bill.get("ghi_chu") or "Không có").strip())
    info_rows = [
        [Paragraph("Phòng", normal_style), Paragraph(f"Phòng {int(bill['room_no'])}", normal_style)],
        [Paragraph("Người ở", normal_style), Paragraph(tenant, normal_style)],
        [Paragraph("Email", normal_style), Paragraph(tenant_email, normal_style)],
        [Paragraph("Trạng thái", normal_style), Paragraph(escape(bill["trang_thai"]), normal_style)],
        [Paragraph("Ghi chú", normal_style), Paragraph(note, normal_style)],
    ]
    info_table = Table(info_rows, colWidths=[35 * mm, 135 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F7F4")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E4DE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([info_table, Spacer(1, 5 * mm), Paragraph("CHI TIẾT CÁC KHOẢN THU", section_style)])

    table_data = [
        [
            Paragraph("Khoản thu", normal_style),
            Paragraph("Cách tính / diễn giải", normal_style),
            Paragraph("Thành tiền", normal_style),
        ],
        [Paragraph("Tiền phòng", normal_style), Paragraph("Giá thuê trong tháng", normal_style), Paragraph(money(bill["gia_phong"]), normal_style)],
        [
            Paragraph("Tiền điện", normal_style),
            Paragraph(
                f"{result['dien_tieu_thu']} kWh × {int(settings['gia_dien']):,} VNĐ/kWh".replace(",", "."),
                normal_style,
            ),
            Paragraph(money(result["tien_dien"]), normal_style),
        ],
        [
            Paragraph("Tiền nước", normal_style),
            Paragraph(
                f"{result['nuoc_tieu_thu']} m³ × {int(settings['gia_nuoc']):,} VNĐ/m³".replace(",", "."),
                normal_style,
            ),
            Paragraph(money(result["tien_nuoc"]), normal_style),
        ],
        [Paragraph("Phí khác", normal_style), Paragraph("Wifi, vệ sinh và phí dịch vụ", normal_style), Paragraph(money(result["phi_khac"]), normal_style)],
        [Paragraph("TỔNG CỘNG", ParagraphStyle("TotalLabel", parent=normal_style, fontName=PDF_FONT_BOLD)), "", Paragraph(money(result["tong_tien"]), ParagraphStyle("TotalValue", parent=normal_style, fontName=PDF_FONT_BOLD, alignment=TA_RIGHT, textColor=colors.HexColor("#176B55")))],
    ]
    charges_table = Table(table_data, colWidths=[36 * mm, 86 * mm, 48 * mm], repeatRows=1)
    charges_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F3ED")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F7F4")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9DAD1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    meter_rows = [
        [Paragraph("Chỉ số", normal_style), Paragraph("Số cũ", normal_style), Paragraph("Số mới", normal_style), Paragraph("Tiêu thụ", normal_style)],
        [Paragraph("Điện (kWh)", normal_style), str(bill["dien_cu"]), str(bill["dien_moi"]), str(result["dien_tieu_thu"])],
        [Paragraph("Nước (m³)", normal_style), str(bill["nuoc_cu"]), str(bill["nuoc_moi"]), str(result["nuoc_tieu_thu"])],
    ]
    meter_table = Table(meter_rows, colWidths=[48 * mm, 39 * mm, 39 * mm, 44 * mm])
    meter_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F7F4")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E4DE")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E4DE")),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    story.extend(
        [
            charges_table,
            Spacer(1, 5 * mm),
            Paragraph("CHỈ SỐ ĐIỆN, NƯỚC", section_style),
            meter_table,
            Spacer(1, 8 * mm),
            Paragraph(
                "Vui lòng kiểm tra lại thông tin và các khoản thu trên phiếu. "
                "Phiếu được tạo từ phần mềm quản lý tiền phòng trọ.",
                small_style,
            ),
            Spacer(1, 8 * mm),
        ]
    )

    signature_table = Table(
        [
            [Paragraph("Người thuê phòng", ParagraphStyle("Sign1", parent=normal_style, alignment=TA_CENTER)), Paragraph("Người thu tiền", ParagraphStyle("Sign2", parent=normal_style, alignment=TA_CENTER))],
            [Paragraph("(Ký và ghi rõ họ tên)", ParagraphStyle("Sign3", parent=small_style, alignment=TA_CENTER)), Paragraph("(Ký và ghi rõ họ tên)", ParagraphStyle("Sign4", parent=small_style, alignment=TA_CENTER))],
            [Paragraph("<br/><br/><br/>", normal_style), Paragraph("<br/><br/><br/>", normal_style)],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    signature_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    story.append(KeepTogether(signature_table))
    doc.build(story)
    return output.getvalue()


def create_all_pdfs_zip(bills: list[dict], settings: dict, year: int, month: int) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for bill in bills:
            pdf_bytes = create_room_pdf(bill, settings, year, month)
            filename = f"Phieu_tien_phong_{int(bill['room_no']):02d}_T{month:02d}_{year}.pdf"
            archive.writestr(filename, pdf_bytes)
    return output.getvalue()


# ============================================================
# GIAO DIỆN
# ============================================================
init_db()
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2.5rem;}
      [data-testid="stMetric"] {background: #F2F8F5; border: 1px solid #DCEAE2; padding: 14px 16px; border-radius: 12px;}
      [data-testid="stSidebar"] {background: #F7FAF8;}
      div.stButton > button[kind="primary"] {background: #176B55; border-color: #176B55;}
      h1, h2, h3 {color: #174D40;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏠 QUẢN LÝ THU TIỀN DÃY TRỌ")
st.caption("Theo dõi tiền phòng, điện nước, người ở và trạng thái thanh toán — dữ liệu được lưu trong SQLite.")

# Chọn kỳ làm việc
with st.sidebar:
    st.header("🗓️ Kỳ làm việc")
    now = datetime.now()
    years = list(range(now.year - 3, now.year + 6))
    year = st.selectbox(
        "Chọn năm",
        years,
        index=years.index(now.year),
        key="selected_year",
    )
    month = st.selectbox(
        "Chọn tháng",
        list(range(1, 13)),
        index=now.month - 1,
        format_func=lambda value: f"Tháng {value:02d}",
        key="selected_month",
    )
    settings_defaults = get_month_settings(year, month)
    st.divider()
    st.header("⚙️ Đơn giá & cấu hình")
    gia_dien = st.number_input(
        "⚡ Giá điện (VNĐ/kWh)", min_value=0, step=100,
        value=int(settings_defaults["gia_dien"]), key=f"gia_dien_{year}_{month}"
    )
    gia_nuoc = st.number_input(
        "💧 Giá nước (VNĐ/m³)", min_value=0, step=500,
        value=int(settings_defaults["gia_nuoc"]), key=f"gia_nuoc_{year}_{month}"
    )
    phi_khac = st.number_input(
        "📦 Phí khác / phòng (VNĐ)", min_value=0, step=10000,
        value=int(settings_defaults["phi_khac"]), key=f"phi_khac_{year}_{month}"
    )
    so_phong = st.slider(
        "Số lượng phòng", min_value=1, max_value=100,
        value=max(1, min(100, int(settings_defaults["so_phong"]))),
        step=1, key=f"so_phong_{year}_{month}"
    )
    st.caption("Cấu hình được lưu riêng theo từng tháng.")

# Lưu cấu hình tháng và bảo đảm các phòng có bản ghi trong SQLite.
settings = {
    "gia_dien": int(gia_dien),
    "gia_nuoc": int(gia_nuoc),
    "phi_khac": int(phi_khac),
    "so_phong": int(so_phong),
}
save_month_settings(year, month, gia_dien, gia_nuoc, phi_khac, so_phong)
ensure_month_rooms(year, month, so_phong)
period_label = f"Tháng {month:02d}/{year}"

st.subheader(f"📋 Cập nhật dữ liệu — {period_label}")
room_no = st.selectbox(
    "Chọn phòng cần cập nhật",
    options=list(range(1, so_phong + 1)),
    format_func=lambda room: f"Phòng {room:02d}",
    key=f"selected_room_{year}_{month}",
)
bill = get_bill(year, month, room_no)
if bill is None:  # Bảo vệ trường hợp dữ liệu bị xóa ngoài ứng dụng.
    ensure_month_rooms(year, month, so_phong)
    bill = get_bill(year, month, room_no)

with st.form(key=f"room_form_{year}_{month}_{room_no}", clear_on_submit=False):
    st.markdown(f"#### 🏠 Phòng {room_no:02d} · {period_label}")
    col_price, col_tenant, col_email = st.columns([1, 2, 2])
    with col_price:
        gia_phong_input = st.number_input(
            "💵 Giá phòng (VNĐ)", min_value=0, step=50000,
            value=int(bill["gia_phong"]), key=f"edit_gia_phong_{year}_{month}_{room_no}"
        )
    with col_tenant:
        thong_tin_nguoi_o_input = st.text_input(
            "👤 Thông tin người ở",
            value=bill.get("thong_tin_nguoi_o", ""),
            placeholder="Tên người thuê, số người, SĐT...",
            key=f"edit_nguoi_o_{year}_{month}_{room_no}",
        )
    with col_email:
        email_nguoi_o_input = st.text_input(
            "✉️ Email nhận hóa đơn",
            value=bill.get("email_nguoi_o", ""),
            placeholder="ten@example.com",
            key=f"edit_email_nguoi_o_{year}_{month}_{room_no}",
            help="Hệ thống gửi PDF tiền trọ đến địa chỉ email này.",
        )

    st.markdown("**Chỉ số điện, nước**")
    e1, e2, w1, w2 = st.columns(4)
    with e1:
        dien_cu_input = st.number_input(
            "⚡ Số điện cũ", min_value=0, step=1,
            value=int(bill["dien_cu"]), key=f"edit_dien_cu_{year}_{month}_{room_no}"
        )
    with e2:
        dien_moi_input = st.number_input(
            "⚡ Số điện mới", min_value=0, step=1,
            value=int(bill["dien_moi"]), key=f"edit_dien_moi_{year}_{month}_{room_no}"
        )
    with w1:
        nuoc_cu_input = st.number_input(
            "💧 Số nước cũ", min_value=0, step=1,
            value=int(bill["nuoc_cu"]), key=f"edit_nuoc_cu_{year}_{month}_{room_no}"
        )
    with w2:
        nuoc_moi_input = st.number_input(
            "💧 Số nước mới", min_value=0, step=1,
            value=int(bill["nuoc_moi"]), key=f"edit_nuoc_moi_{year}_{month}_{room_no}"
        )

    col_status, col_note = st.columns([1, 2])
    with col_status:
        status_input = st.selectbox(
            "🧾 Trạng thái thanh toán",
            options=TRANG_THAI,
            index=TRANG_THAI.index(bill["trang_thai"]) if bill["trang_thai"] in TRANG_THAI else 0,
            key=f"edit_status_{year}_{month}_{room_no}",
        )
    with col_note:
        ghi_chu_input = st.text_input(
            "📝 Ghi chú thêm (không bắt buộc)",
            value=bill.get("ghi_chu", ""),
            placeholder="Ví dụ: Đã hẹn chuyển khoản ngày 05...",
            key=f"edit_note_{year}_{month}_{room_no}",
        )

    auto_email_input = st.checkbox(
        "✅ Chốt hóa đơn và cho phép gửi email tự động theo lịch",
        value=bool(bill.get("gui_email_tu_dong", 0)),
        key=f"auto_email_ready_{year}_{month}_{room_no}",
        help="Chỉ bật sau khi đã kiểm tra giá phòng và chỉ số điện/nước. Tác vụ tự động sẽ bỏ qua phòng chưa chốt.",
    )

    submitted = st.form_submit_button("💾 Lưu cập nhật phòng", type="primary", use_container_width=True)

if submitted:
    save_bill(
        year=year,
        month=month,
        room_no=room_no,
        gia_phong=int(gia_phong_input),
        thong_tin_nguoi_o=thong_tin_nguoi_o_input,
        email_nguoi_o=email_nguoi_o_input,
        gui_email_tu_dong=auto_email_input,
        dien_cu=int(dien_cu_input),
        dien_moi=int(dien_moi_input),
        nuoc_cu=int(nuoc_cu_input),
        nuoc_moi=int(nuoc_moi_input),
        trang_thai=status_input,
        ghi_chu=ghi_chu_input,
    )
    st.success(f"Đã lưu dữ liệu Phòng {room_no:02d} vào SQLite.")
    bill = get_bill(year, month, room_no)

if bill["dien_moi"] < bill["dien_cu"]:
    st.warning("Chỉ số điện mới nhỏ hơn chỉ số cũ. Mức tiêu thụ điện đang được tính bằng 0; hãy kiểm tra lại số nhập.")
if bill["nuoc_moi"] < bill["nuoc_cu"]:
    st.warning("Chỉ số nước mới nhỏ hơn chỉ số cũ. Mức tiêu thụ nước đang được tính bằng 0; hãy kiểm tra lại số nhập.")

current_cost = calculate_bill(bill, settings)
preview_cols = st.columns(4)
preview_cols[0].metric("Tiền phòng", money(bill["gia_phong"]))
preview_cols[1].metric("Tiền điện", money(current_cost["tien_dien"]))
preview_cols[2].metric("Tiền nước", money(current_cost["tien_nuoc"]))
preview_cols[3].metric("Tổng tiền phòng", money(current_cost["tong_tien"]))

# ============================================================
# EMAIL HÓA ĐƠN
# ============================================================
with st.expander("✉️ Gửi hóa đơn qua email", expanded=True):
    smtp_config = get_smtp_config()
    if smtp_is_configured(smtp_config):
        st.success(
            f"SMTP đã được cấu hình: {smtp_config['host']}:{smtp_config['port']}. "
            "Mỗi người thuê sẽ nhận một email riêng kèm phiếu PDF của phòng mình."
        )
    else:
        st.warning(
            "Chưa cấu hình email gửi đi. Khi chạy trên máy, điền thông tin SMTP trong `.env`. "
            "Khi triển khai Streamlit Cloud, thêm các khóa SMTP vào App settings → Secrets."
        )

    sent_log = get_email_log(year, month, room_no)
    if sent_log:
        if sent_log.get("status") == "Đã gửi":
            st.caption(f"Email phòng {room_no:02d} đã gửi lúc {sent_log.get('sent_at', '')} đến {sent_log.get('email', '')}.")
        elif sent_log.get("error"):
            st.caption(f"Lần gửi gần nhất lỗi: {sent_log.get('error', '')}")

    resend_all = st.checkbox(
        "Gửi lại cả những phòng đã gửi trong tháng này",
        value=False,
        key=f"resend_all_{year}_{month}",
        help="Mặc định hệ thống bỏ qua hóa đơn đã gửi thành công để tránh gửi trùng.",
    )
    email_col1, email_col2 = st.columns(2)
    with email_col1:
        if st.button(
            f"📩 Gửi PDF cho Phòng {room_no:02d}",
            type="primary",
            use_container_width=True,
            key=f"send_one_{year}_{month}_{room_no}",
        ):
            recipient = (bill.get("email_nguoi_o") or "").strip()
            if not recipient:
                st.error("Phòng này chưa có email. Hãy nhập email và bấm Lưu cập nhật phòng trước.")
            elif not smtp_is_configured(smtp_config):
                st.error("Chưa cấu hình SMTP. Xem README: dùng .env ở máy local hoặc App settings → Secrets trên Streamlit Cloud.")
            else:
                try:
                    pdf_bytes = create_room_pdf(bill, settings, year, month)
                    name = bill.get("thong_tin_nguoi_o") or f"Phòng {room_no:02d}"
                    subject = f"Hóa đơn tiền trọ - Phòng {room_no:02d} - Tháng {month:02d}/{year}"
                    body = (
                        f"Xin chào {name},\n\n"
                        f"Đính kèm là phiếu tiền phòng tháng {month:02d}/{year}.\n"
                        f"Tổng tiền: {money(current_cost['tong_tien'])}.\n"
                        f"Trạng thái: {bill['trang_thai']}.\n\n"
                        "Vui lòng xem file PDF đính kèm và liên hệ chủ trọ nếu có sai sót.\n"
                        "Trân trọng."
                    )
                    filename = f"Phieu_Tien_Phong_{room_no:02d}_T{month:02d}_{year}.pdf"
                    send_pdf_email(recipient, subject, body, pdf_bytes, filename, smtp_config)
                    record_email_log(year, month, room_no, recipient, "Đã gửi", "")
                    st.success(f"Đã gửi hóa đơn Phòng {room_no:02d} đến {recipient}.")
                except Exception as exc:
                    record_email_log(year, month, room_no, recipient, "Lỗi", str(exc))
                    st.error(f"Gửi email thất bại: {exc}")

    with email_col2:
        if st.button(
            "📨 Gửi hóa đơn cho các phòng có email",
            use_container_width=True,
            key=f"send_all_{year}_{month}",
        ):
            if not smtp_is_configured(smtp_config):
                st.error("Chưa cấu hình SMTP. Xem README: dùng .env ở máy local hoặc App settings → Secrets trên Streamlit Cloud.")
            else:
                latest_bills = get_bills(year, month, so_phong)
                sent_count = 0
                skip_count = 0
                failed_count = 0
                progress = st.progress(0.0)
                total_count = max(len(latest_bills), 1)
                for index, row in enumerate(latest_bills, start=1):
                    recipient = (row.get("email_nguoi_o") or "").strip()
                    old_log = get_email_log(year, month, int(row["room_no"]))
                    if not recipient:
                        skip_count += 1
                        progress.progress(index / total_count)
                        continue
                    if old_log and old_log.get("status") == "Đã gửi" and not resend_all:
                        skip_count += 1
                        progress.progress(index / total_count)
                        continue
                    try:
                        pdf_bytes = create_room_pdf(row, settings, year, month)
                        costs = calculate_bill(row, settings)
                        tenant = row.get("thong_tin_nguoi_o") or f"Phòng {int(row['room_no']):02d}"
                        subject = f"Hóa đơn tiền trọ - Phòng {int(row['room_no']):02d} - Tháng {month:02d}/{year}"
                        body = (
                            f"Xin chào {tenant},\n\n"
                            f"Đính kèm là phiếu tiền phòng tháng {month:02d}/{year}.\n"
                            f"Tổng tiền: {money(costs['tong_tien'])}.\n"
                            f"Trạng thái: {row['trang_thai']}.\n\n"
                            "Vui lòng xem file PDF đính kèm và liên hệ chủ trọ nếu có sai sót.\n"
                            "Trân trọng."
                        )
                        filename = f"Phieu_Tien_Phong_{int(row['room_no']):02d}_T{month:02d}_{year}.pdf"
                        send_pdf_email(recipient, subject, body, pdf_bytes, filename, smtp_config)
                        record_email_log(year, month, int(row["room_no"]), recipient, "Đã gửi", "")
                        sent_count += 1
                    except Exception as exc:
                        record_email_log(year, month, int(row["room_no"]), recipient, "Lỗi", str(exc))
                        failed_count += 1
                    progress.progress(index / total_count)
                st.success(f"Hoàn tất gửi hàng loạt: {sent_count} thành công, {skip_count} bỏ qua, {failed_count} lỗi.")

    st.caption(
        "Gửi thủ công hoạt động trực tiếp từ giao diện. Gửi tự động theo lịch cần chạy `auto_email.py` "
        "trên máy chủ/tác vụ theo lịch có quyền truy cập cùng database; Streamlit Community Cloud "
        "không tự chạy script nền này."
    )

    mail_logs = get_recent_email_logs(year, month)
    if mail_logs:
        st.markdown("**Lịch sử gửi email trong tháng**")
        st.dataframe(
            pd.DataFrame(mail_logs)[["room_no", "email", "status", "sent_at", "error"]].rename(
                columns={"room_no": "Phòng", "email": "Email", "status": "Kết quả", "sent_at": "Thời gian", "error": "Lỗi (nếu có)"}
            ),
            use_container_width=True,
            hide_index=True,
        )

# ============================================================
# BẢNG TỔNG HỢP & XUẤT FILE
# ============================================================
st.divider()
st.subheader(f"📊 Bảng tổng hợp tiền trọ — {period_label}")
all_bills = get_bills(year, month, so_phong)
summary_rows = []
for row in all_bills:
    costs = calculate_bill(row, settings)
    summary_rows.append(
        {
            "Phòng": f"Phòng {int(row['room_no']):02d}",
            "Thông tin người ở": row.get("thong_tin_nguoi_o", ""),
            "Email": row.get("email_nguoi_o", ""),
            "Gửi tự động": "Bật" if row.get("gui_email_tu_dong", 0) else "Tắt",
            "Giá phòng": int(row["gia_phong"]),
            "Số điện cũ": int(row["dien_cu"]),
            "Số điện mới": int(row["dien_moi"]),
            "Tiền điện": costs["tien_dien"],
            "Số nước cũ": int(row["nuoc_cu"]),
            "Số nước mới": int(row["nuoc_moi"]),
            "Tiền nước": costs["tien_nuoc"],
            "Phí khác": costs["phi_khac"],
            "Tổng tiền": costs["tong_tien"],
            "Trạng thái thanh toán": row["trang_thai"],
            "Ghi chú": row.get("ghi_chu", ""),
        }
    )

df = pd.DataFrame(summary_rows)
if not df.empty:
    total_due = int(df["Tổng tiền"].sum())
    paid_df = df[df["Trạng thái thanh toán"] == "Đã thanh toán"]
    unpaid_df = df[df["Trạng thái thanh toán"] != "Đã thanh toán"]
    paid_total = int(paid_df["Tổng tiền"].sum())
    unpaid_total = int(unpaid_df["Tổng tiền"].sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng tiền cần thu", money(total_due))
    m2.metric("Đã thanh toán", money(paid_total))
    m3.metric("Chưa thanh toán", money(unpaid_total))
    m4.metric("Phòng đã thanh toán", f"{len(paid_df)}/{len(df)} phòng")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Giá phòng": st.column_config.NumberColumn(format="%d"),
            "Tiền điện": st.column_config.NumberColumn(format="%d"),
            "Tiền nước": st.column_config.NumberColumn(format="%d"),
            "Phí khác": st.column_config.NumberColumn(format="%d"),
            "Tổng tiền": st.column_config.NumberColumn(format="%d"),
        },
    )

    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    safe_period = f"T{month:02d}_{year}"
    export1, export2, export3 = st.columns(3)
    with export1:
        st.download_button(
            "📥 Xuất bảng tổng hợp CSV",
            data=csv_bytes,
            file_name=f"Bang_Tien_Phong_{safe_period}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with export2:
        selected_pdf = create_room_pdf(bill, settings, year, month)
        st.download_button(
            f"📄 Tải PDF Phòng {room_no:02d}",
            data=selected_pdf,
            file_name=f"Phieu_Tien_Phong_{room_no:02d}_{safe_period}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with export3:
        all_pdfs_zip = create_all_pdfs_zip(all_bills, settings, year, month)
        st.download_button(
            "🗂️ Tải PDF tất cả phòng (ZIP)",
            data=all_pdfs_zip,
            file_name=f"Phieu_Tien_Phong_Tat_Ca_{safe_period}.zip",
            mime="application/zip",
            use_container_width=True,
        )
else:
    st.info("Chưa có dữ liệu phòng trong kỳ này.")

with st.expander("💾 Sao lưu dữ liệu SQLite"):
    st.write(f"Tệp cơ sở dữ liệu hiện tại: `{DB_PATH.name}`")
    try:
        db_bytes = DB_PATH.read_bytes()
        st.download_button(
            "Tải bản sao lưu database",
            data=db_bytes,
            file_name=f"Sao_Luu_Quan_Ly_Tien_Tro_{datetime.now():%Y%m%d_%H%M%S}.sqlite3",
            mime="application/vnd.sqlite3",
        )
    except OSError:
        st.warning("Chưa tìm thấy tệp database để sao lưu.")

st.caption("Lưu ý: dữ liệu được lưu trên máy/môi trường đang chạy ứng dụng trong tệp SQLite. Hãy tải bản sao lưu định kỳ nếu sử dụng cho dữ liệu thực tế.")
