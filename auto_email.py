"""Daily scheduled sender used by GitHub Actions.

Only sends finalized bills with auto_email_enabled=True. A successful prior send
for the same room/year/month is never sent again by the scheduled job.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

from email_utils import get_smtp_config, send_pdf_email, smtp_is_configured
from invoice_pdf import calculate, create_invoice_pdf, money
from storage import get_email_logs, get_month_settings, get_bills, log_email, make_supabase, rows


def as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Gửi hóa đơn tiền trọ đã chốt theo lịch")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ hiển thị các hóa đơn đủ điều kiện, không gửi email")
    parser.add_argument("--force", action="store_true", help="Bỏ qua ngày bắt đầu gửi, nhưng vẫn yêu cầu hóa đơn đã chốt và bật tự động")
    args = parser.parse_args()
    dry_run = args.dry_run or as_bool(os.getenv("DRY_RUN"), False)

    try:
        client = make_supabase()
        bills = rows(client.table("monthly_bills").select("*")
                     .eq("is_finalized", True).eq("auto_email_enabled", True)
                     .order("year").order("month").order("room_no").limit(5000).execute())
        settings_rows = rows(client.table("monthly_settings").select("*").limit(2000).execute())
        settings_by_period = {(int(r["year"]), int(r["month"])): r for r in settings_rows}
        logs = get_email_logs(client, limit=5000)
        sent = {(int(x["year"]), int(x["month"]), int(x["room_no"])) for x in logs if x.get("status") == "Thành công"}
        today = date.today()
        only_unpaid = as_bool(os.getenv("AUTO_EMAIL_ONLY_UNPAID"), False)
        cfg = get_smtp_config()
        if not dry_run and not smtp_is_configured(cfg):
            print("ERROR: Chưa cấu hình SMTP trong GitHub Actions Secrets.", file=sys.stderr)
            return 2

        eligible: list[tuple[dict, dict]] = []
        skipped = {"not_due": 0, "already_sent": 0, "paid": 0, "no_email": 0, "future": 0}
        for bill in bills:
            year, month, room_no = int(bill["year"]), int(bill["month"]), int(bill["room_no"])
            key = (year, month, room_no)
            if key in sent:
                skipped["already_sent"] += 1
                continue
            if year > today.year or (year == today.year and month > today.month):
                skipped["future"] += 1
                continue
            if only_unpaid and bill.get("payment_status") == "Đã thanh toán":
                skipped["paid"] += 1
                continue
            recipient = (bill.get("tenant_email") or "").strip()
            if not recipient or "@" not in recipient:
                skipped["no_email"] += 1
                continue
            month_settings = settings_by_period.get((year, month)) or {
                "electric_rate": 3500, "water_rate": 15000, "other_fee": 150000, "auto_email_day": 1,
            }
            due_day = min(28, max(1, int(month_settings.get("auto_email_day", 1) or 1)))
            if not args.force and (year == today.year and month == today.month and today.day < due_day):
                skipped["not_due"] += 1
                continue
            eligible.append((bill, month_settings))

        print(f"Hôm nay: {today.isoformat()}")
        print(f"Hóa đơn đã chốt và bật tự động: {len(bills)}")
        print(f"Đủ điều kiện gửi: {len(eligible)}")
        print(f"Bỏ qua: {skipped}")
        failure_count = 0
        for bill, month_settings in eligible:
            year, month, room_no = int(bill["year"]), int(bill["month"]), int(bill["room_no"])
            total = calculate(bill, month_settings)["total"]
            recipient = (bill.get("tenant_email") or "").strip()
            print(f" - {month:02d}/{year} | Phòng {room_no:02d} | {recipient} | {money(total)}")
            if dry_run:
                continue
            try:
                pdf = create_invoice_pdf(bill, month_settings, year, month)
                subject = f"Tiền phòng tháng {month:02d}/{year} · Phòng {room_no:02d}"
                body = (
                    f"Xin chào {bill.get('tenant_name') or 'Quý khách'},\n\n"
                    f"Đính kèm là phiếu tiền phòng Phòng {room_no:02d}, tháng {month:02d}/{year}.\n"
                    f"Tổng tiền: {money(total)}.\n"
                    f"Trạng thái thanh toán: {bill.get('payment_status', 'Chưa thanh toán')}.\n\n"
                    "Vui lòng kiểm tra hóa đơn và liên hệ quản lý nếu cần điều chỉnh.\n"
                    "Trân trọng,\nQUAN GIA · Quản lý tiền trọ"
                )
                filename = f"HoaDon_Phong_{room_no:02d}_{month:02d}_{year}.pdf"
                send_pdf_email(recipient, subject, body, pdf, filename, config=cfg)
                log_email(client, year, month, room_no, recipient, "Thành công", "")
                sent.add((year, month, room_no))
                print("   OK: gửi thành công")
            except Exception as exc:
                try:
                    log_email(client, year, month, room_no, recipient, "Thất bại", str(exc))
                except Exception as log_exc:
                    print(f"   WARNING: không lưu được nhật ký lỗi: {log_exc}", file=sys.stderr)
                failure_count += 1
                print(f"   ERROR: {exc}", file=sys.stderr)
        if dry_run:
            print("DRY RUN: Không có email nào được gửi.")
            return 0
        print(f"Đã kết thúc lượt gửi. Lỗi gửi: {failure_count}.")
        # Mark the workflow failed so the owner sees the problem; failed bills will be retried next day.
        return 3 if failure_count else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
