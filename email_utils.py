"""SMTP helpers used by the rental-management web app and scheduler."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().with_name('.env'), override=False)
except Exception:
    # .env is optional; process environment variables can be used instead.
    pass


def _setting(name: str, default: str = '') -> str:
    """Read local environment first, then Streamlit Community Cloud secrets.

    Do not commit actual credentials to GitHub. For Streamlit Cloud, add these
    keys under App settings -> Secrets. Local use can continue using .env.
    """
    value = os.getenv(name)
    if value is not None and value.strip() != '':
        return value.strip()
    try:
        import streamlit as st
        value = st.secrets.get(name, default)
        if value is not None:
            return str(value).strip()
    except Exception:
        # st.secrets can be unavailable outside an initialized Streamlit app.
        pass
    return default


def get_smtp_config() -> dict[str, Any]:
    """Read SMTP settings from environment variables or Streamlit secrets."""
    host = _setting('SMTP_HOST', 'smtp.gmail.com')
    port_raw = _setting('SMTP_PORT', '587')
    try:
        port = int(port_raw)
    except ValueError:
        port = 587
    username = _setting('SMTP_USERNAME')
    password = _setting('SMTP_PASSWORD').replace(' ', '')
    from_email = _setting('SMTP_FROM_EMAIL', username)
    from_name = _setting('SMTP_FROM_NAME', 'Quản lý tiền phòng trọ')
    use_ssl = _setting('SMTP_USE_SSL', 'false').lower() in {'1', 'true', 'yes', 'on'} or port == 465
    return {
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'from_email': from_email,
        'from_name': from_name,
        'use_ssl': use_ssl,
    }


def smtp_is_configured(config: dict[str, Any] | None = None) -> bool:
    cfg = config or get_smtp_config()
    return bool(cfg.get('host') and cfg.get('username') and cfg.get('password') and cfg.get('from_email'))


def send_pdf_email(
    to_email: str,
    subject: str,
    body: str,
    pdf_bytes: bytes,
    filename: str,
    config: dict[str, Any] | None = None,
) -> None:
    """Send one message with a PDF attachment. Raises on SMTP errors."""
    cfg = config or get_smtp_config()
    if not smtp_is_configured(cfg):
        raise RuntimeError(
            'Chưa cấu hình SMTP. Hãy điền SMTP_USERNAME, SMTP_PASSWORD và SMTP_FROM_EMAIL trong file .env.'
        )
    if not to_email or '@' not in to_email:
        raise ValueError('Email người nhận không hợp lệ.')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f"{cfg['from_name']} <{cfg['from_email']}>"
    msg['To'] = to_email.strip()
    msg.set_content(body)
    msg.add_attachment(
        pdf_bytes,
        maintype='application',
        subtype='pdf',
        filename=filename,
    )

    context = ssl.create_default_context()
    if cfg.get('use_ssl'):
        with smtplib.SMTP_SSL(cfg['host'], int(cfg['port']), context=context, timeout=30) as server:
            server.login(cfg['username'], cfg['password'])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg['host'], int(cfg['port']), timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg['username'], cfg['password'])
            server.send_message(msg)
