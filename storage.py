"""Supabase persistence helpers for the rental-management app and scheduled email job."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from supabase import Client, create_client

DEFAULT_SETTINGS = {
    "electric_rate": 3500,
    "water_rate": 15000,
    "other_fee": 150000,
    "auto_email_day": 1,
}


def make_supabase(url: str | None = None, key: str | None = None) -> Client:
    url = (url or os.getenv("SUPABASE_URL", "")).strip()
    key = (key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        raise RuntimeError("Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(url, key)


def rows(response: Any) -> list[dict]:
    return list(response.data or [])


def get_room_list(client: Client, include_inactive: bool = True) -> list[dict]:
    query = client.table("rooms").select("*").order("room_no")
    if not include_inactive:
        query = query.eq("is_active", True)
    return rows(query.execute())


def get_room(client: Client, room_no: int) -> dict | None:
    result = rows(client.table("rooms").select("*").eq("room_no", room_no).limit(1).execute())
    return result[0] if result else None


def save_room(client: Client, room: dict) -> dict:
    result = rows(client.table("rooms").upsert(room, on_conflict="room_no").execute())
    return result[0] if result else room


def deactivate_room(client: Client, room_no: int) -> None:
    client.table("rooms").update({"is_active": False}).eq("room_no", int(room_no)).execute()


def get_previous_period(year: int, month: int) -> tuple[int, int]:
    prev = date(int(year), int(month), 1) - timedelta(days=1)
    return prev.year, prev.month


def get_month_settings(client: Client, year: int, month: int, create: bool = True) -> dict:
    found = rows(
        client.table("monthly_settings").select("*")
        .eq("year", int(year)).eq("month", int(month)).limit(1).execute()
    )
    if found:
        return found[0]

    available_settings = rows(
        client.table("monthly_settings").select("*")
        .order("year", desc=True).order("month", desc=True).limit(1000).execute()
    )
    # Prefer the closest prior month; only fall back to the latest available row if no prior exists.
    prior_settings = [r for r in available_settings if (int(r["year"]), int(r["month"])) < (int(year), int(month))]
    source_settings = prior_settings or available_settings
    defaults = dict(DEFAULT_SETTINGS)
    if source_settings:
        latest = max(source_settings, key=lambda r: (int(r["year"]), int(r["month"])))
        defaults.update({k: int(latest.get(k, v) or v) for k, v in DEFAULT_SETTINGS.items()})
    defaults.update({"year": int(year), "month": int(month)})
    if create:
        saved = rows(client.table("monthly_settings").upsert(defaults, on_conflict="year,month").execute())
        if saved:
            return saved[0]
    return defaults


def save_month_settings(client: Client, settings: dict) -> dict:
    payload = {
        "year": int(settings["year"]),
        "month": int(settings["month"]),
        "electric_rate": max(0, int(settings["electric_rate"])),
        "water_rate": max(0, int(settings["water_rate"])),
        "other_fee": max(0, int(settings["other_fee"])),
        "auto_email_day": min(28, max(1, int(settings["auto_email_day"]))),
        "updated_at": date.today().isoformat(),
    }
    result = rows(client.table("monthly_settings").upsert(payload, on_conflict="year,month").execute())
    return result[0] if result else payload


def get_bill(client: Client, year: int, month: int, room_no: int) -> dict | None:
    found = rows(
        client.table("monthly_bills").select("*")
        .eq("year", int(year)).eq("month", int(month)).eq("room_no", int(room_no)).limit(1).execute()
    )
    return found[0] if found else None


def get_bills(client: Client, year: int, month: int) -> list[dict]:
    return rows(
        client.table("monthly_bills").select("*")
        .eq("year", int(year)).eq("month", int(month)).order("room_no").limit(1000).execute()
    )


def ensure_month_bills(client: Client, year: int, month: int) -> list[dict]:
    """Create invoice snapshots for active rooms; carry prior month's meter readings forward."""
    settings = get_month_settings(client, year, month, create=True)
    rooms = get_room_list(client, include_inactive=False)
    existing = {int(b["room_no"]): b for b in get_bills(client, year, month)}
    if not rooms:
        return list(existing.values())

    py, pm = get_previous_period(year, month)
    previous = {int(b["room_no"]): b for b in get_bills(client, py, pm)}
    to_create = []
    for room in rooms:
        room_no = int(room["room_no"])
        if room_no in existing:
            continue
        prior = previous.get(room_no, {})
        old_electric = int(prior.get("electricity_new", 0) or 0)
        old_water = int(prior.get("water_new", 0) or 0)
        to_create.append({
            "year": int(year), "month": int(month), "room_no": room_no,
            "tenant_name": room.get("tenant_name", "") or "",
            "tenant_phone": room.get("tenant_phone", "") or "",
            "tenant_email": room.get("tenant_email", "") or "",
            "rent_price": int(room.get("rent_price", 2500000) or 0),
            "electricity_old": old_electric, "electricity_new": old_electric,
            "water_old": old_water, "water_new": old_water,
            "payment_status": "Chưa thanh toán", "note": "",
            "is_finalized": False,
            "auto_email_enabled": bool(room.get("auto_email_enabled", False)),
        })
    if to_create:
        client.table("monthly_bills").upsert(to_create, on_conflict="year,month,room_no").execute()
    return get_bills(client, year, month)


def save_bill(client: Client, bill: dict) -> dict:
    payload = {
        "year": int(bill["year"]), "month": int(bill["month"]), "room_no": int(bill["room_no"]),
        "tenant_name": str(bill.get("tenant_name", "")).strip(),
        "tenant_phone": str(bill.get("tenant_phone", "")).strip(),
        "tenant_email": str(bill.get("tenant_email", "")).strip(),
        "rent_price": max(0, int(bill.get("rent_price", 0))),
        "electricity_old": max(0, int(bill.get("electricity_old", 0))),
        "electricity_new": max(0, int(bill.get("electricity_new", 0))),
        "water_old": max(0, int(bill.get("water_old", 0))),
        "water_new": max(0, int(bill.get("water_new", 0))),
        "payment_status": bill.get("payment_status", "Chưa thanh toán"),
        "note": str(bill.get("note", "")),
        "is_finalized": bool(bill.get("is_finalized", False)),
        "auto_email_enabled": bool(bill.get("auto_email_enabled", False)),
    }
    result = rows(client.table("monthly_bills").upsert(payload, on_conflict="year,month,room_no").execute())
    return result[0] if result else payload


def get_email_logs(client: Client, limit: int = 1000) -> list[dict]:
    return rows(client.table("email_logs").select("*").order("created_at", desc=True).limit(limit).execute())


def log_email(client: Client, year: int, month: int, room_no: int, recipient: str, status: str, error: str = "") -> None:
    client.table("email_logs").insert({
        "year": int(year), "month": int(month), "room_no": int(room_no),
        "recipient": recipient or "", "status": status,
        "error_message": (error or "")[:1500],
    }).execute()


def successful_email_keys(client: Client) -> set[tuple[int, int, int]]:
    success = rows(client.table("email_logs").select("year,month,room_no,status")
                   .eq("status", "Thành công").limit(5000).execute())
    return {(int(r["year"]), int(r["month"]), int(r["room_no"])) for r in success}


def update_room_from_bill(client: Client, bill: dict) -> None:
    """Keep current resident contact/rent in the master room record after saving a bill."""
    client.table("rooms").update({
        "tenant_name": str(bill.get("tenant_name", "")).strip(),
        "tenant_phone": str(bill.get("tenant_phone", "")).strip(),
        "tenant_email": str(bill.get("tenant_email", "")).strip(),
        "rent_price": int(bill.get("rent_price", 0)),
        "auto_email_enabled": bool(bill.get("auto_email_enabled", False)),
        "updated_at": date.today().isoformat(),
    }).eq("room_no", int(bill["room_no"])).execute()


def sync_unfinalized_bills_for_room(client: Client, room: dict) -> None:
    """Refresh draft bill snapshots after editing a room; finalized invoices stay immutable."""
    room_no = int(room["room_no"])
    drafts = rows(client.table("monthly_bills").select("year,month,room_no")
                  .eq("room_no", room_no).eq("is_finalized", False).limit(2000).execute())
    common = {
        "tenant_name": str(room.get("tenant_name", "")).strip(),
        "tenant_phone": str(room.get("tenant_phone", "")).strip(),
        "tenant_email": str(room.get("tenant_email", "")).strip(),
        "rent_price": int(room.get("rent_price", 0) or 0),
        "auto_email_enabled": bool(room.get("auto_email_enabled", False)),
        "updated_at": date.today().isoformat(),
    }
    for bill in drafts:
        client.table("monthly_bills").update(common).eq("year", int(bill["year"])) \
            .eq("month", int(bill["month"])).eq("room_no", room_no).execute()
