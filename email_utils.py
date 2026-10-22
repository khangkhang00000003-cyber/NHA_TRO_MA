"""SMTP helpers: environment variables for GitHub Actions, Streamlit Secrets for the web app."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)
except Exception:
    pass


def setting(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None and value.strip():
        return value.strip()
    # Streamlit Secrets are only available inside the web process.
    try:
        import streamlit as st
        value = st.secrets.get(name, default)
        if value is not None:
            return str(value).strip()
    except Exception:
        pass
    return default


def get_smtp_config() -> dict[str, Any]:
    port_raw = setting("SMTP_PORT", "587")
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    return {
        "host": setting("SMTP_HOST", "smtp.gmail.com"),
        "port": port,
        "username": setting("SMTP_USERNAME"),
        "password": setting("SMTP_PASSWORD").replace(" ", ""),
        "from_email": setting("SMTP_FROM_EMAIL", setting("SMTP_USERNAME")),
        "from_name": setting("SMTP_FROM_NAME", "QUAN GIA - Quan ly tien tro"),
        "use_ssl": setting("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes", "on"} or port == 465,
    }


def smtp_is_configured(config: dict[str, Any] | None = None) -> bool:
    cfg = config or get_smtp_config()
    return bool(cfg.get("host") and cfg.get("username") and cfg.get("password") and cfg.get("from_email"))


def send_pdf_email(to_email: str, subject: str, body: str, pdf_bytes: bytes, filename: str,
                   config: dict[str, Any] | None = None) -> None:
    cfg = config or get_smtp_config()
    if not smtp_is_configured(cfg):
        raise RuntimeError("Chưa cấu hình SMTP trong Streamlit Secrets hoặc GitHub Actions Secrets.")
    if not to_email or "@" not in to_email:
        raise ValueError("Email người nhận không hợp lệ.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg["To"] = to_email.strip()
    msg.set_content(body)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    context = ssl.create_default_context()
    if cfg["use_ssl"]:
        with smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), context=context, timeout=30) as server:
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
