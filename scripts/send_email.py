#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Send report email through authenticated SMTP."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "email.local.json"


def load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.expanduser().open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("email config must be a JSON object")
    return data


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() not in ("0", "false", "no", "off")


def pick(config: dict[str, Any], key: str, env_name: str, default: Any = None) -> Any:
    if os.getenv(env_name) not in (None, ""):
        return os.getenv(env_name)
    if config.get(key) not in (None, ""):
        return config.get(key)
    return default


def load_settings(config_path: Path) -> dict[str, Any]:
    config = load_json_config(config_path)
    smtp_user = pick(config, "smtp_user", "SMTP_USER")
    smtp_host = pick(config, "smtp_host", "SMTP_HOST")
    if not smtp_host and smtp_user and str(smtp_user).lower().endswith("@qq.com"):
        smtp_host = "smtp.qq.com"
    settings = {
        "smtp_host": smtp_host,
        "smtp_port": int(pick(config, "smtp_port", "SMTP_PORT", 465)),
        "smtp_ssl": env_bool("SMTP_SSL", bool(config.get("smtp_ssl", True))),
        "smtp_starttls": env_bool("SMTP_STARTTLS", bool(config.get("smtp_starttls", False))),
        "smtp_user": smtp_user,
        "smtp_password": pick(config, "smtp_password", "SMTP_PASSWORD"),
        "smtp_from": pick(config, "smtp_from", "SMTP_FROM", smtp_user),
        "default_to": pick(config, "default_to", "DAILY_REVIEW_EMAIL_TO"),
    }
    return settings


def missing_settings(settings: dict[str, Any]) -> list[str]:
    required = ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from")
    return [key for key in required if settings.get(key) in (None, "")]


def build_message(sender: str, recipients: list[str], subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return message


def send_message(settings: dict[str, Any], recipients: list[str], subject: str, body: str) -> None:
    message = build_message(settings["smtp_from"], recipients, subject, body)
    if settings["smtp_ssl"]:
        with smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], context=ssl.create_default_context()) as smtp:
            smtp.login(settings["smtp_user"], settings["smtp_password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"]) as smtp:
        if settings["smtp_starttls"]:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(settings["smtp_user"], settings["smtp_password"])
        smtp.send_message(message)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Send a report email through authenticated SMTP.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--to", action="append", help="Recipient address. Can be repeated.")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.config)
        missing = missing_settings(settings)
        if missing:
            print(
                "ERROR missing SMTP settings: "
                + ", ".join(missing)
                + f". Create {args.config} from config/email.example.json or set SMTP_* env vars.",
                file=sys.stderr,
            )
            return 2
        recipients = args.to or ([settings["default_to"]] if settings.get("default_to") else [])
        recipients = [item for item in recipients if item]
        if not recipients:
            print("ERROR missing recipient: pass --to or configure default_to/DAILY_REVIEW_EMAIL_TO", file=sys.stderr)
            return 2
        body = args.body_file.expanduser().read_text(encoding="utf-8")
        send_message(settings, recipients, args.subject, body)
    except Exception as exc:
        print(f"ERROR send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"sent email to {', '.join(recipients)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
