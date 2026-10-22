from __future__ import annotations

import hmac
import io
import os
import zipfile
from datetime import date, datetime
from html import escape

import pandas as pd
import streamlit as st
from supabase import create_client

from email_utils import get_smtp_config, send_pdf_email, smtp_is_configured
from invoice_pdf import calculate, create_invoice_pdf, money
from storage import (
    deactivate_room,
    ensure_month_bills,
    get_bill,
    get_bills,
    get_email_logs,
    get_month_settings,
    get_room,
    get_room_list,
    log_email,
    make_supabase,
    save_bill,
    save_month_settings,
    save_room,
    sync_unfinalized_bills_for_room,
    successful_email_keys,
    update_room_from_bill,
)

st.set_page_config(
    page_title="QUAN GIA | Quản lý tiền trọ",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Palette: emerald, deep evergreen, sage and muted champagne — intentionally not white-heavy.
st.markdown(
    """
    <style>
      :root { --evergreen:#163D35; --evergreen-2:#1F584B; --emerald:#228A72;
              --sage:#DCEBE2; --sage-2:#EEF4EF; --gold:#C9A45D; --ink:#203E36; --muted:#687E75; }
      .stApp { background: radial-gradient(circle at 92% 0%, #D6E8DD 0, #EEF4EF 34%, #E8F0EA 100%); color: var(--ink); }
      [data-testid="stHeader"] { background: transparent; }
      [data-testid="stSidebar"] { background: linear-gradient(180deg, #153B34 0%, #1C4B40 65%, #245B4C 100%); }
      [data-testid="stSidebar"] * { color:#F0F6F1 !important; }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#D0E3D8 !important; }
      [data-testid="stSidebar"] hr { border-color:rgba(235,246,239,.18); }
      [data-testid="stSidebar"] [data-testid="stRadio"] label { border-radius:12px; padding:9px 10px; }
      [data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:rgba(255,255,255,.08); }
      h1,h2,h3 { color: var(--evergreen) !important; letter-spacing:-.025em; }
      h1 { font-weight:850 !important; }
      [data-testid="stMetric"] { background:linear-gradient(135deg,#F5F8F3 0%,#E2EEE6 100%); border:1px solid #D4E3D9; padding:17px 18px; border-radius:18px; box-shadow:0 7px 22px rgba(23,68,55,.055); }
      [data-testid="stMetricLabel"] { color:#617A70 !important; font-weight:650; }
      [data-testid="stMetricValue"] { color:#173E35 !important; font-weight:850; }
      [data-testid="stMetricDelta"] { color:#28745F !important; }
      .hero { background:linear-gradient(120deg,#153C34 0%,#1E594A 60%,#2B7860 100%); border-radius:24px; padding:25px 27px; color:#F5F8F3; margin:3px 0 22px; box-shadow:0 14px 35px rgba(19,62,51,.17); position:relative; overflow:hidden; }
      .hero:after { content:''; position:absolute; width:260px;height:260px;right:-65px;top:-135px;border:1px solid rgba(226,192,125,.45);border-radius:50%;box-shadow:0 0 0 28px rgba(226,192,125,.04),0 0 0 58px rgba(226,192,125,.04); }
      .hero-kicker { color:#DCC58C; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.2em; margin-bottom:9px; }
      .hero-title { color:#FBFAF3; font-size:29px; line-height:1.2; font-weight:850; margin:0; }
      .hero-sub { color:#D0E4D8; margin-top:8px; max-width:740px; font-size:14px; line-height:1.55; }
      .hero-badge { display:inline-block; background:rgba(236,246,239,.12); border:1px solid rgba(236,246,239,.2); border-radius:99px; padding:7px 12px; font-size:11px; color:#F0F7F0; margin-top:15px; }
      .section-eyebrow { font-size:11px; letter-spacing:.15em; color:#668076; font-weight:800; text-transform:uppercase; margin-bottom:2px; }
      .panel { background:rgba(248,250,246,.62); border:1px solid #D7E4DA; border-radius:18px; padding:17px 19px; }
      .panel-title { color:#173E35; font-weight:800; font-size:16px; margin-bottom:4px; }
      .panel-sub { color:#6B8178; font-size:12px; }
      .status-pill { display:inline-block; padding:5px 10px; border-radius:99px; font-weight:750; font-size:11px; background:#F8E9C7; color:#8B6525; }
      .status-paid { background:#D7EDE0; color:#1D6A50; }
      .status-final { background:#DAE7F5; color:#2E5E8C; }
      .small-note { color:#71857C; font-size:12px; }
      .divider-gold { height:3px; width:68px; border-radius:99px; background:linear-gradient(90deg,#C9A45D,#E5D3A1); margin:12px 0 17px; }
      div.stButton > button, div.stDownloadButton > button { border-radius:11px; border:1px solid #1F735E; background:linear-gradient(135deg,#258C73,#17644F); color:#fff; font-weight:750; min-height:2.65rem; box-shadow:0 5px 12px rgba(24,103,81,.12); }
      div.stButton > button:hover, div.stDownloadButton > button:hover { border-color:#C6A35F; color:#fff; background:linear-gradient(135deg,#17644F,#124C3E); }
      div[data-testid="stForm"] { background:rgba(248,250,246,.72); border:1px solid #D6E4DA; border-radius:18px; padding:19px 20px 8px; }
      div[data-testid="stDataFrame"] { border-radius:15px; overflow:hidden; border:1px solid #D5E3D9; }
      div[data-testid="stAlert"] { border-radius:13px; }
      [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stSelectbox"] div[data-baseweb="select"] { border-radius:10px; }
      .login-wrap { max-width:520px; margin:7vh auto; background:rgba(249,251,247,.8); border:1px solid #D4E3D9; border-radius:25px; padding:28px; box-shadow:0 20px 45px rgba(27,70,57,.13); }
      .footnote { color:#7B8D84; font-size:11px; text-align:center; margin-top:27px; }
      @media (max-width: 900px) { .hero { padding:21px; } .hero-title { font-size:24px; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def secret(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    if value.strip():
        return value.strip()
    try:
        raw = st.secrets.get(name, default)
        return str(raw).strip() if raw is not None else default
    except Exception:
        return default


@st.cache_resource(show_spinner=False)
def cached_client(url: str, key: str):
    return create_client(url, key)


def get_client_or_none():
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        return cached_client(url, key)
    except Exception as exc:
        st.error(f"Không khởi tạo được kết nối Supabase: {exc}")
        return None


def header(title: str, subtitle: str, period_label: str | None = None):
    period = f'<span class="hero-badge">✦ {escape(period_label)}</span>' if period_label else ''
    st.markdown(
        f"""<div class="hero"><div class="hero-kicker">QUAN GIA · RENTAL MANAGEMENT</div>
        <div class="hero-title">{escape(title)}</div>
        <div class="hero-sub">{escape(subtitle)}</div>{period}</div>""",
        unsafe_allow_html=True,
    )


def money_short(value: int | float) -> str:
    value = int(value or 0)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",") + " tr"
    return f"{value:,}".replace(",", ".") + " đ"


def csv_for_bills(bills: list[dict], settings: dict) -> bytes:
    records = []
    for b in bills:
        c = calculate(b, settings)
        records.append({
            "Tháng": f"{int(b['month']):02d}/{b['year']}", "Phòng": f"{int(b['room_no']):02d}",
            "Người thuê": b.get("tenant_name", ""), "Email": b.get("tenant_email", ""),
            "Giá phòng": c["rent_price"], "Điện cũ": b.get("electricity_old", 0),
            "Điện mới": b.get("electricity_new", 0), "Tiền điện": c["electricity_cost"],
            "Nước cũ": b.get("water_old", 0), "Nước mới": b.get("water_new", 0),
            "Tiền nước": c["water_cost"], "Phí khác": c["other_fee"], "Tổng tiền": c["total"],
            "Thanh toán": b.get("payment_status", "Chưa thanh toán"),
            "Đã chốt": "Có" if b.get("is_finalized") else "Chưa",
            "Tự động email": "Có" if b.get("auto_email_enabled") else "Không",
            "Ghi chú": b.get("note", ""),
        })
    return pd.DataFrame(records).to_csv(index=False).encode("utf-8-sig")


def zip_for_bills(bills: list[dict], settings: dict, year: int, month: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for bill in bills:
            pdf = create_invoice_pdf(bill, settings, year, month)
            archive.writestr(f"HoaDon_Phong_{int(bill['room_no']):02d}_{month:02d}_{year}.pdf", pdf)
    return buffer.getvalue()


def send_one_invoice(client, bill: dict, settings: dict, allow_resend: bool = False) -> tuple[bool, str]:
    year, month, room_no = int(bill["year"]), int(bill["month"]), int(bill["room_no"])
    recipient = (bill.get("tenant_email") or "").strip()
    try:
        if not bill.get("is_finalized"):
            raise ValueError("Hóa đơn chưa được chốt.")
        if not recipient or "@" not in recipient:
            raise ValueError("Email người thuê chưa hợp lệ.")
        already_success = any(
            int(item.get("year", 0)) == year and int(item.get("month", 0)) == month
            and int(item.get("room_no", 0)) == room_no and item.get("status") == "Thành công"
            for item in get_email_logs(client, limit=2000)
        )
        if already_success and not allow_resend:
            return False, "Hóa đơn này đã gửi thành công; bật tùy chọn gửi lại nếu cần."
        cfg = get_smtp_config()
        if not smtp_is_configured(cfg):
            raise RuntimeError("Chưa cấu hình SMTP trong Streamlit Secrets.")
        pdf = create_invoice_pdf(bill, settings, year, month)
        subject = f"Tiền phòng tháng {month:02d}/{year} · Phòng {room_no:02d}"
        body = (
            f"Xin chào {bill.get('tenant_name') or 'Quý khách'},\n\n"
            f"Đính kèm là phiếu tiền phòng {room_no:02d} tháng {month:02d}/{year}.\n"
            f"Tổng tiền: {money(calculate(bill, settings)['total'])}.\n"
            f"Trạng thái hiện tại: {bill.get('payment_status', 'Chưa thanh toán')}.\n\n"
            "Vui lòng kiểm tra thông tin trên hóa đơn và liên hệ quản lý nếu cần điều chỉnh.\n"
            "Trân trọng.\nQUAN GIA · Quản lý tiền trọ"
        )
        filename = f"HoaDon_Phong_{room_no:02d}_{month:02d}_{year}.pdf"
        send_pdf_email(recipient, subject, body, pdf, filename, config=cfg)
        log_email(client, year, month, room_no, recipient, "Thành công", "")
        return True, "Gửi email thành công."
    except Exception as exc:
        try:
            log_email(client, year, month, room_no, recipient, "Thất bại", str(exc))
        except Exception:
            pass
        return False, str(exc)


def demo_screen():
    st.sidebar.markdown("<div style='padding:15px 9px 24px'><div style='font-size:11px;letter-spacing:.22em;color:#D3B879;font-weight:800'>QUAN GIA</div><div style='font-size:23px;font-weight:850;color:#F4F7F1'>Quản lý tiền trọ</div><div style='color:#BBD5C7;font-size:12px;margin-top:5px'>Chưa kết nối dữ liệu</div></div>", unsafe_allow_html=True)
    header("Một không gian quản lý gọn gàng hơn", "Thiết kế xanh ngọc – xanh rừng – champagne. Kết nối Supabase để bật lưu trữ thật, lập hóa đơn và gửi email.", f"BẢN XEM TRƯỚC · {date.today().strftime('%m/%Y')}")
    st.warning("Đang ở chế độ xem trước vì chưa có SUPABASE_URL và SUPABASE_SERVICE_ROLE_KEY. Dữ liệu dưới đây chỉ là dữ liệu minh họa, chưa được lưu.")
    a,b,c,d = st.columns(4)
    for col, label, value, delta in [
        (a,"PHÒNG ĐANG THUÊ","10","8 có người ở"),
        (b,"TỔNG TIỀN THÁNG","27,5 tr","ước tính"),
        (c,"ĐÃ THANH TOÁN","18,2 tr","66% hóa đơn"),
        (d,"CHỜ THANH TOÁN","9,3 tr","4 phòng còn nợ"),
    ]:
        col.metric(label, value, delta)
    st.markdown("<div class='section-eyebrow'>THEO DÕI HÓA ĐƠN</div><div class='divider-gold'></div>", unsafe_allow_html=True)
    sample = pd.DataFrame([
        ["P.01","Nguyễn Minh Anh","2.750.000","Đã thanh toán","Đã chốt"],
        ["P.02","Trần Hoàng Nam","2.930.000","Chưa thanh toán","Đã chốt"],
        ["P.03","Lê Thảo Vy","2.610.000","Chưa thanh toán","Chưa chốt"],
        ["P.05","Phạm Quốc Bảo","3.080.000","Đã thanh toán","Đã chốt"],
    ], columns=["Phòng","Người thuê","Tổng tiền (VNĐ)","Thanh toán","Hóa đơn"])
    st.dataframe(sample, hide_index=True, use_container_width=True)
    st.markdown("### Để bật hệ thống thật")
    st.markdown("1. Tạo project Supabase, chạy file `supabase_schema.sql` trong SQL Editor.\n2. Thêm `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` và `ADMIN_PIN` vào Streamlit Secrets.\n3. Thêm SMTP vào Secrets nếu muốn gửi thủ công từ giao diện; thêm cùng thông tin vào GitHub Actions Secrets để gửi định kỳ.")
    with st.expander("Vì sao cần Supabase?"):
        st.write("Streamlit Community Cloud không bảo đảm file SQLite cục bộ tồn tại lâu dài. Supabase lưu hồ sơ người thuê, hóa đơn theo tháng và nhật ký email trong PostgreSQL bền vững hơn.")
    st.stop()


def login_gate(admin_password: str):
    if st.session_state.get("authenticated"):
        return True
    st.markdown("<div class='login-wrap'><div class='section-eyebrow'>KHU VỰC QUẢN TRỊ</div><h2 style='margin-top:8px'>Chào mừng trở lại</h2><p style='color:#6B8178'>Đăng nhập để quản lý phòng, thông tin người thuê và hóa đơn.</p></div>", unsafe_allow_html=True)
    with st.form("login_form"):
        password = st.text_input("Mật khẩu quản trị", type="password", placeholder="Nhập mật khẩu đã cấu hình trong Secrets")
        submit = st.form_submit_button("Mở bảng điều khiển", use_container_width=True)
    if submit:
        if hmac.compare_digest(password, admin_password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Mật khẩu chưa đúng.")
    st.caption("Mật khẩu quản trị được lưu trong Streamlit Secrets, không nằm trong GitHub.")
    return False


client = get_client_or_none()
if client is None:
    demo_screen()

admin_password = secret("ADMIN_PIN")
if not admin_password:
    header("Sẵn sàng thiết lập hệ thống", "Cơ sở dữ liệu đã được cấu hình nhưng chưa có mật khẩu quản trị.")
    st.error("Hãy thêm ADMIN_PIN vào Streamlit Cloud → App settings → Secrets trước khi sử dụng dữ liệu người thuê.")
    st.code('ADMIN_PIN = "tao-mot-mat-khau-dai-va-rieng"', language="toml")
    st.stop()

if not login_gate(admin_password):
    st.stop()

# Confirm schema and connectivity before presenting editable controls.
try:
    rooms_all = get_room_list(client, include_inactive=True)
except Exception as exc:
    header("Chưa kết nối được kho dữ liệu", "Kiểm tra URL/key Supabase và chạy file supabase_schema.sql trước khi tiếp tục.")
    st.error(f"Không đọc được bảng rooms: {exc}")
    st.code("Supabase Dashboard → SQL Editor → New query → dán nội dung supabase_schema.sql → Run")
    st.stop()

# Sidebar navigation and period selection.
st.sidebar.markdown(
    "<div style='padding:13px 8px 18px'><div style='font-size:11px;letter-spacing:.22em;color:#D8BD7D;font-weight:850'>QUAN GIA</div><div style='font-size:22px;font-weight:850;color:#F4F7F1;line-height:1.2'>Quản lý<br>tiền trọ</div><div style='font-size:11px;color:#BFD8CB;margin-top:8px'>RESIDENTS · BILLING · EMAIL</div></div>",
    unsafe_allow_html=True,
)
st.sidebar.markdown("<div style='font-size:10px;letter-spacing:.16em;color:#D7BD7C;font-weight:800'>KỲ HÓA ĐƠN</div>", unsafe_allow_html=True)
now = date.today()
year_options = list(range(now.year - 2, now.year + 3))
sel_year = st.sidebar.selectbox("Năm", year_options, index=year_options.index(now.year), key="period_year")
sel_month = st.sidebar.selectbox("Tháng", list(range(1, 13)), index=now.month - 1,
                                 format_func=lambda value: f"Tháng {value:02d}", key="period_month")
period_label = f"THÁNG {sel_month:02d}/{sel_year}"
st.sidebar.divider()
page = st.sidebar.radio("ĐIỀU HƯỚNG", ["Tổng quan", "Phòng & người thuê", "Hóa đơn & điện nước", "Gửi email", "Lịch sử & dữ liệu"], label_visibility="visible")
st.sidebar.divider()
st.sidebar.markdown("<div style='font-size:11px;color:#BED8CC'>Lưu trữ: Supabase PostgreSQL<br>Email lịch: GitHub Actions</div>", unsafe_allow_html=True)
if st.sidebar.button("Đăng xuất", use_container_width=True):
    st.session_state["authenticated"] = False
    st.rerun()

settings = get_month_settings(client, sel_year, sel_month, create=True)
try:
    bills = ensure_month_bills(client, sel_year, sel_month)
except Exception as exc:
    st.error(f"Không thể tạo/đọc hóa đơn tháng: {exc}")
    st.stop()
rooms_all = get_room_list(client, include_inactive=True)
rooms_active = [room for room in rooms_all if room.get("is_active", True)]
bills_by_room = {int(b["room_no"]): b for b in bills}

calculated = [(b, calculate(b, settings)) for b in bills]
total_billed = sum(c["total"] for _, c in calculated)
total_paid = sum(c["total"] for b, c in calculated if b.get("payment_status") == "Đã thanh toán")
total_unpaid = total_billed - total_paid
sent_keys = set()
try:
    sent_keys = successful_email_keys(client)
except Exception:
    pass
period_sent = sum(1 for b in bills if (sel_year, sel_month, int(b["room_no"])) in sent_keys)

if page == "Tổng quan":
    header("Tổng quan vận hành", "Từ hồ sơ người thuê đến hóa đơn tháng — mọi thứ tập trung trong một bảng điều khiển.", period_label)
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("PHÒNG ĐANG HOẠT ĐỘNG", f"{len(rooms_active):02d}", "hồ sơ phòng")
    m2.metric("TỔNG TIỀN HÓA ĐƠN", money_short(total_billed), "kỳ đang chọn")
    m3.metric("ĐÃ THU", money_short(total_paid), f"{(total_paid / total_billed * 100):.0f}%" if total_billed else "chưa có hóa đơn")
    m4.metric("CÒN PHẢI THU", money_short(total_unpaid), f"{sum(1 for b in bills if b.get('payment_status') != 'Đã thanh toán')} phòng")
    st.markdown("<div class='section-eyebrow'>TỔNG HỢP PHÒNG TRỌ</div><div class='divider-gold'></div>", unsafe_allow_html=True)
    if bills:
        records = []
        for bill, costs in calculated:
            records.append({
                "Phòng": f"P.{int(bill['room_no']):02d}",
                "Người thuê": bill.get("tenant_name") or "Chưa cập nhật",
                "Giá phòng": costs["rent_price"], "Tiền điện": costs["electricity_cost"],
                "Tiền nước": costs["water_cost"], "Phí khác": costs["other_fee"],
                "Tổng tiền": costs["total"], "Thanh toán": bill.get("payment_status", "Chưa thanh toán"),
                "Email": "Đã gửi" if (sel_year, sel_month, int(bill["room_no"])) in sent_keys else ("Chưa gửi" if bill.get("tenant_email") else "Thiếu email"),
                "Hóa đơn": "Đã chốt" if bill.get("is_finalized") else "Chưa chốt",
            })
        df = pd.DataFrame(records)
        st.dataframe(df, use_container_width=True, hide_index=True, column_config={
            "Giá phòng": st.column_config.NumberColumn(format="%d"),
            "Tiền điện": st.column_config.NumberColumn(format="%d"),
            "Tiền nước": st.column_config.NumberColumn(format="%d"),
            "Phí khác": st.column_config.NumberColumn(format="%d"),
            "Tổng tiền": st.column_config.NumberColumn(format="%d"),
        })
    else:
        st.info("Chưa có phòng hoạt động. Vào mục Phòng & người thuê để tạo hồ sơ đầu tiên.")

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("<div class='panel'><div class='panel-title'>Đơn giá & lịch gửi</div><div class='panel-sub'>Cấu hình áp dụng cho kỳ hóa đơn đang chọn.</div></div>", unsafe_allow_html=True)
        with st.form("settings_form"):
            c1,c2 = st.columns(2)
            electric_rate = c1.number_input("Giá điện (đ/kWh)", min_value=0, value=int(settings.get("electric_rate",3500)), step=100)
            water_rate = c2.number_input("Giá nước (đ/m³)", min_value=0, value=int(settings.get("water_rate",15000)), step=500)
            other_fee = st.number_input("Phí khác / dịch vụ (VNĐ/phòng)", min_value=0, value=int(settings.get("other_fee",150000)), step=10000)
            auto_day = st.number_input("Ngày bắt đầu gửi hóa đơn tự động", min_value=1, max_value=28, value=int(settings.get("auto_email_day",1)), help="GitHub Actions kiểm tra hằng ngày; chỉ gửi hóa đơn đã chốt và đã bật tự động.")
            save_settings = st.form_submit_button("Lưu đơn giá & lịch", use_container_width=True)
        if save_settings:
            try:
                save_month_settings(client, {"year":sel_year,"month":sel_month,"electric_rate":electric_rate,
                                             "water_rate":water_rate,"other_fee":other_fee,"auto_email_day":auto_day})
                st.success("Đã lưu cấu hình cho kỳ hóa đơn.")
                st.rerun()
            except Exception as exc:
                st.error(f"Không lưu được cấu hình: {exc}")
    with right:
        with st.container(border=True):
            st.markdown("### Trạng thái hệ thống")
            st.caption("Các điều kiện cần có trước khi gửi thư tự động.")
            smtp_ok = smtp_is_configured(get_smtp_config())
            st.write(f"**Database:** {'Đã kết nối Supabase' if client else 'Chưa cấu hình'}")
            st.write(f"**SMTP gửi thủ công:** {'Đã cấu hình' if smtp_ok else 'Chưa cấu hình'}")
            st.write(f"**Hóa đơn đã gửi kỳ này:** {period_sent}/{len(bills)}")
            st.write(f"**Hóa đơn đã chốt:** {sum(1 for b in bills if b.get('is_finalized'))}/{len(bills)}")
        st.info("Email theo lịch do GitHub Actions chạy mỗi ngày. Chỉ hóa đơn đã chốt, bật tự động và có email hợp lệ mới đủ điều kiện.")

elif page == "Phòng & người thuê":
    header("Phòng & người thuê", "Hồ sơ phòng là dữ liệu gốc; thông tin người ở được sao lưu vào từng hóa đơn để giữ lịch sử.")
    if not rooms_all:
        st.info("Chưa có hồ sơ phòng. Tạo phòng đầu tiên bằng biểu mẫu bên dưới.")
    mode = st.radio("Thao tác", ["Thêm phòng", "Cập nhật hồ sơ"], horizontal=True)
    room_choices = sorted([int(r["room_no"]) for r in rooms_all])
    if mode == "Cập nhật hồ sơ" and not room_choices:
        st.warning("Chưa có phòng để cập nhật; hãy chọn Thêm phòng.")
    else:
        with st.form("room_master_form"):
            if mode == "Thêm phòng":
                room_no = st.number_input("Số phòng", min_value=1, max_value=9999, value=(max(room_choices)+1 if room_choices else 1), step=1)
                existing_room = None
            else:
                selected_room = st.selectbox("Chọn phòng", room_choices, format_func=lambda x: f"Phòng {x:02d}")
                existing_room = get_room(client, int(selected_room)) or {}
                room_no = int(selected_room)
            c1,c2 = st.columns(2)
            tenant_name = c1.text_input("Họ tên người thuê", value=(existing_room or {}).get("tenant_name", ""))
            tenant_phone = c2.text_input("Số điện thoại", value=(existing_room or {}).get("tenant_phone", ""))
            tenant_email = st.text_input("Email nhận hóa đơn", value=(existing_room or {}).get("tenant_email", ""), placeholder="ten@example.com")
            rent_price = st.number_input("Giá phòng (VNĐ/tháng)", min_value=0, value=int((existing_room or {}).get("rent_price",2500000) or 0), step=50000)
            c3,c4 = st.columns(2)
            is_active = c3.checkbox("Phòng đang hoạt động", value=bool((existing_room or {}).get("is_active", True)))
            auto_email_enabled = c4.checkbox("Cho phép gửi email tự động", value=bool((existing_room or {}).get("auto_email_enabled", False)))
            submit_room = st.form_submit_button("Lưu hồ sơ phòng", use_container_width=True)
        if submit_room:
            if tenant_email and "@" not in tenant_email:
                st.error("Email chưa đúng định dạng. Hãy sửa lại hoặc để trống.")
            else:
                try:
                    if mode == "Thêm phòng" and get_room(client, int(room_no)):
                        st.error("Số phòng này đã tồn tại. Hãy chọn số khác.")
                    else:
                        saved_room = save_room(client, {
                            "room_no":int(room_no),"tenant_name":tenant_name.strip(),"tenant_phone":tenant_phone.strip(),
                            "tenant_email":tenant_email.strip(),"rent_price":int(rent_price),"is_active":bool(is_active),
                            "auto_email_enabled":bool(auto_email_enabled),"updated_at":datetime.utcnow().isoformat(),
                        })
                        sync_unfinalized_bills_for_room(client, saved_room)
                        st.success(f"Đã lưu hồ sơ Phòng {int(room_no):02d}.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Không lưu được hồ sơ: {exc}")
    st.markdown("<div class='section-eyebrow'>DANH SÁCH HỒ SƠ</div><div class='divider-gold'></div>", unsafe_allow_html=True)
    if rooms_all:
        df_rooms = pd.DataFrame([{
            "Phòng": f"P.{int(r['room_no']):02d}", "Người thuê": r.get("tenant_name", ""),
            "Điện thoại": r.get("tenant_phone", ""), "Email": r.get("tenant_email", ""),
            "Giá phòng": int(r.get("rent_price", 0) or 0), "Trạng thái": "Đang thuê" if r.get("is_active") else "Ngưng hoạt động",
            "Tự động email": "Bật" if r.get("auto_email_enabled") else "Tắt",
        } for r in rooms_all])
        st.dataframe(df_rooms, use_container_width=True, hide_index=True, column_config={"Giá phòng":st.column_config.NumberColumn(format="%d")})
        active_room_numbers = [int(r["room_no"]) for r in rooms_all if r.get("is_active")]
        if active_room_numbers:
            with st.expander("Ngưng hoạt động một phòng"):
                room_to_disable = st.selectbox("Chọn phòng", active_room_numbers, format_func=lambda x:f"Phòng {x:02d}", key="disable_room_select")
                st.caption("Hồ sơ và hóa đơn cũ vẫn được giữ. Phòng ngưng hoạt động sẽ không tự tạo hóa đơn mới.")
                if st.button("Ngưng hoạt động phòng đã chọn"):
                    deactivate_room(client, int(room_to_disable))
                    st.success(f"Đã ngưng hoạt động Phòng {int(room_to_disable):02d}.")
                    st.rerun()

elif page == "Hóa đơn & điện nước":
    header("Lập hóa đơn tháng", "Cập nhật công tơ, kiểm tra tiền phải thu, chốt hóa đơn rồi mới bật gửi tự động.", period_label)
    if not bills:
        st.info("Chưa có phòng hoạt động. Hãy tạo hồ sơ ở mục Phòng & người thuê.")
    else:
        room_nos = [int(b["room_no"]) for b in bills]
        selected_bill_room = st.selectbox("Chọn phòng cần cập nhật", room_nos,
                                          format_func=lambda x:f"Phòng {x:02d} · {(bills_by_room.get(x,{}).get('tenant_name') or 'Chưa có tên')}")
        b = dict(bills_by_room[selected_bill_room])
        c = calculate(b, settings)
        top1,top2,top3 = st.columns(3)
        top1.metric("TỔNG TIỀN HIỆN TẠI", money_short(c["total"]))
        top2.metric("TIÊU THỤ ĐIỆN", f"{c['used_electricity']} kWh")
        top3.metric("TIÊU THỤ NƯỚC", f"{c['used_water']} m³")
        with st.form(f"bill_form_{sel_year}_{sel_month}_{selected_bill_room}"):
            st.markdown("**Thông tin người ở & giá phòng**")
            c1,c2 = st.columns(2)
            tenant_name = c1.text_input("Họ tên người thuê", value=b.get("tenant_name", ""))
            tenant_phone = c2.text_input("Số điện thoại", value=b.get("tenant_phone", ""))
            tenant_email = st.text_input("Email nhận hóa đơn", value=b.get("tenant_email", ""))
            rent_price = st.number_input("Giá phòng (VNĐ)", min_value=0, value=int(b.get("rent_price", 0) or 0), step=50000)
            st.markdown("**Chỉ số công tơ**")
            e1,e2,e3,e4 = st.columns(4)
            electricity_old = e1.number_input("Điện cũ (kWh)", min_value=0, value=int(b.get("electricity_old",0) or 0), step=1)
            electricity_new = e2.number_input("Điện mới (kWh)", min_value=0, value=int(b.get("electricity_new",0) or 0), step=1)
            water_old = e3.number_input("Nước cũ (m³)", min_value=0, value=int(b.get("water_old",0) or 0), step=1)
            water_new = e4.number_input("Nước mới (m³)", min_value=0, value=int(b.get("water_new",0) or 0), step=1)
            payment_status = st.selectbox("Trạng thái thanh toán", ["Chưa thanh toán", "Đã thanh toán"],
                                          index=0 if b.get("payment_status") != "Đã thanh toán" else 1)
            note = st.text_area("Ghi chú", value=b.get("note", ""), placeholder="Ví dụ: đã hẹn chuyển khoản ngày 05...")
            f1,f2 = st.columns(2)
            is_finalized = f1.checkbox("Chốt hóa đơn (xác nhận số liệu đã kiểm tra)", value=bool(b.get("is_finalized",False)))
            auto_email_enabled = f2.checkbox("Cho phép email tự động cho hóa đơn này", value=bool(b.get("auto_email_enabled",False)))
            submit_bill = st.form_submit_button("Lưu hóa đơn", use_container_width=True)
        if electricity_new < electricity_old or water_new < water_old:
            st.warning("Chỉ số mới thấp hơn chỉ số cũ: hệ thống sẽ tính tiêu thụ bằng 0. Hãy kiểm tra công tơ trước khi chốt.")
        if submit_bill:
            if tenant_email.strip() and "@" not in tenant_email:
                st.error("Email không hợp lệ.")
            elif is_finalized and auto_email_enabled and (not tenant_email.strip() or "@" not in tenant_email):
                st.error("Hóa đơn bật tự động gửi cần có email người thuê hợp lệ.")
            else:
                payload = {
                    **b, "tenant_name":tenant_name.strip(),"tenant_phone":tenant_phone.strip(),"tenant_email":tenant_email.strip(),
                    "rent_price":int(rent_price),"electricity_old":int(electricity_old),"electricity_new":int(electricity_new),
                    "water_old":int(water_old),"water_new":int(water_new),"payment_status":payment_status,"note":note.strip(),
                    "is_finalized":bool(is_finalized),"auto_email_enabled":bool(auto_email_enabled),
                    "year":sel_year,"month":sel_month,"room_no":selected_bill_room,
                }
                try:
                    save_bill(client,payload)
                    update_room_from_bill(client,payload)
                    st.success("Đã lưu hóa đơn và đồng bộ thông tin người thuê vào hồ sơ phòng.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không lưu được hóa đơn: {exc}")
        current_bill = get_bill(client, sel_year, sel_month, selected_bill_room)
        if current_bill:
            st.download_button("Tải PDF hóa đơn phòng này", create_invoice_pdf(current_bill, settings, sel_year, sel_month),
                               file_name=f"HoaDon_Phong_{selected_bill_room:02d}_{sel_month:02d}_{sel_year}.pdf",
                               mime="application/pdf", use_container_width=True)

elif page == "Gửi email":
    header("Email hóa đơn", "Mỗi người thuê nhận email riêng, kèm PDF đúng phòng và đúng kỳ. Email thành công sẽ được ghi nhận để chống gửi trùng.", period_label)
    smtp_ok = smtp_is_configured(get_smtp_config())
    if smtp_ok:
        st.success("SMTP đã cấu hình. Nên gửi thử đến địa chỉ của bạn trước khi gửi cho người thuê.")
    else:
        st.warning("Chưa cấu hình SMTP. Thêm SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL và SMTP_FROM_NAME vào Streamlit Secrets.")
    logs = get_email_logs(client, limit=2000)
    sent_keys_now = {(int(l["year"]),int(l["month"]),int(l["room_no"])) for l in logs if l.get("status")=="Thành công"}
    email_room_nos = [int(b["room_no"]) for b in bills]
    selected_email_room = st.selectbox("Gửi hóa đơn của phòng", email_room_nos,
                                       format_func=lambda x:f"Phòng {x:02d} · {(bills_by_room.get(x,{}).get('tenant_email') or 'Chưa có email')}", key="send_email_room") if email_room_nos else None
    resend = st.checkbox("Cho phép gửi lại nếu hóa đơn này đã gửi thành công", value=False)
    if selected_email_room is not None:
        mail_bill = bills_by_room[selected_email_room]
        cc = calculate(mail_bill, settings)
        st.markdown(f"<div class='panel'><div class='panel-title'>Phòng {selected_email_room:02d} · {escape(mail_bill.get('tenant_name') or 'Chưa cập nhật')}</div><div class='panel-sub'>{escape(mail_bill.get('tenant_email') or 'Chưa có email')} · Tổng hóa đơn: <b>{money(cc['total'])}</b></div><br><span class='status-pill {'status-paid' if mail_bill.get('payment_status')=='Đã thanh toán' else ''}'>{escape(mail_bill.get('payment_status','Chưa thanh toán'))}</span> &nbsp; <span class='status-pill {'status-final' if mail_bill.get('is_finalized') else ''}'>{'Đã chốt' if mail_bill.get('is_finalized') else 'Chưa chốt'}</span></div>", unsafe_allow_html=True)
        if st.button("Gửi email PDF cho phòng đang chọn", use_container_width=True, disabled=not smtp_ok):
            ok, message = send_one_invoice(client, mail_bill, settings, allow_resend=resend)
            (st.success if ok else st.error)(message)
            st.rerun()
    st.markdown("### Gửi các hóa đơn đủ điều kiện")
    eligible = [b for b in bills if b.get("is_finalized") and b.get("tenant_email") and "@" in b.get("tenant_email", "")]
    pending = [b for b in eligible if (sel_year,sel_month,int(b["room_no"])) not in sent_keys_now]
    st.write(f"Đã chốt và có email hợp lệ: **{len(eligible)}** · Chưa gửi thành công: **{len(pending)}**")
    confirm_all = st.checkbox("Tôi đã kiểm tra tháng, người nhận và tổng tiền trước khi gửi hàng loạt.")
    if st.button("Gửi các hóa đơn đã chốt chưa gửi", disabled=(not smtp_ok or not confirm_all or not pending), use_container_width=True):
        progress = st.progress(0)
        successes, failures = 0, 0
        for idx, pending_bill in enumerate(pending, start=1):
            ok, msg = send_one_invoice(client, pending_bill, settings, allow_resend=False)
            successes += int(ok)
            failures += int(not ok)
            progress.progress(idx / len(pending))
        st.success(f"Hoàn tất lượt gửi: {successes} thành công, {failures} thất bại.")
        st.rerun()
    st.info("Gửi theo lịch được thực hiện bằng GitHub Actions (workflow hằng ngày). Giao diện Streamlit không cần mở liên tục; hãy xem README để thêm các GitHub Actions Secrets.")
    if logs:
        st.markdown("<div class='section-eyebrow'>NHẬT KÝ GẦN ĐÂY</div><div class='divider-gold'></div>", unsafe_allow_html=True)
        logs_df = pd.DataFrame([{
            "Thời gian": l.get("created_at", ""), "Kỳ": f"{int(l.get('month',0)):02d}/{l.get('year','')}",
            "Phòng": f"P.{int(l.get('room_no',0)):02d}", "Người nhận": l.get("recipient", ""),
            "Kết quả": l.get("status", ""), "Lỗi": l.get("error_message", ""),
        } for l in logs[:100]])
        st.dataframe(logs_df, use_container_width=True, hide_index=True)

elif page == "Lịch sử & dữ liệu":
    header("Lịch sử & dữ liệu", "Xuất dữ liệu báo cáo và tra cứu nhật ký email; hồ sơ gốc và hóa đơn được lưu trong Supabase.")
    st.markdown("### Xuất báo cáo kỳ đang chọn")
    if bills:
        col1,col2,col3 = st.columns(3)
        with col1:
            st.download_button("Tải báo cáo CSV", csv_for_bills(bills, settings),
                               file_name=f"BaoCaoTienTro_{sel_month:02d}_{sel_year}.csv", mime="text/csv", use_container_width=True)
        with col2:
            st.download_button("Tải toàn bộ PDF (ZIP)", zip_for_bills(bills, settings, sel_year, sel_month),
                               file_name=f"HoaDon_TatCaPhong_{sel_month:02d}_{sel_year}.zip", mime="application/zip", use_container_width=True)
        with col3:
            rooms_export = pd.DataFrame([{
                "room_no":r.get("room_no"),"tenant_name":r.get("tenant_name"),"tenant_phone":r.get("tenant_phone"),
                "tenant_email":r.get("tenant_email"),"rent_price":r.get("rent_price"),"is_active":r.get("is_active"),
            } for r in rooms_all])
            st.download_button("Tải danh sách người thuê", rooms_export.to_csv(index=False).encode("utf-8-sig"),
                               file_name="DanhSachPhong_NguoiThue.csv", mime="text/csv", use_container_width=True)
    else:
        st.info("Chưa có hóa đơn để xuất.")
    st.markdown("### Nhật ký gửi email")
    all_logs = get_email_logs(client, limit=1000)
    if all_logs:
        df_logs = pd.DataFrame([{
            "Thời gian":l.get("created_at", ""), "Năm":l.get("year"), "Tháng":l.get("month"),
            "Phòng":f"P.{int(l.get('room_no',0)):02d}", "Email":l.get("recipient", ""),
            "Trạng thái":l.get("status", ""), "Thông tin":l.get("error_message", ""),
        } for l in all_logs])
        st.dataframe(df_logs, hide_index=True, use_container_width=True)
        st.download_button("Tải nhật ký email CSV", df_logs.to_csv(index=False).encode("utf-8-sig"),
                           file_name="NhatKyEmail.csv", mime="text/csv")
    else:
        st.info("Chưa có lượt gửi email nào.")
    with st.expander("Sơ đồ lưu trữ dữ liệu"):
        st.markdown("- **rooms:** hồ sơ gốc của phòng/người thuê.\n- **monthly_settings:** giá điện, nước, phí dịch vụ và ngày gửi theo từng tháng.\n- **monthly_bills:** snapshot người thuê, chỉ số, tổng tiền, trạng thái thanh toán, chốt hóa đơn.\n- **email_logs:** mọi lần gửi thành công/thất bại, người nhận và nội dung lỗi.")

st.markdown("<div class='footnote'>QUAN GIA · QUẢN LÝ TIỀN TRỌ · Bảo vệ thông tin người thuê · Lưu trữ qua Supabase</div>", unsafe_allow_html=True)
