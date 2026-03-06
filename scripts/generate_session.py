#!/usr/bin/env python3
from __future__ import annotations

import getpass
import re

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def prompt_non_empty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required.")


def prompt_api_id() -> int:
    while True:
        raw_value = prompt_non_empty("Telegram API ID: ")
        try:
            return int(raw_value)
        except ValueError:
            print("API ID must be an integer.")


def prompt_code() -> str:
    return prompt_non_empty("Please enter the code you received: ")


def prompt_password() -> str:
    while True:
        password = getpass.getpass("Two-step verification password: ").strip()
        if password:
            return password
        print("This field is required.")


def normalize_phone(phone: str) -> str:
    return re.sub(r"[\s\-()]", "", phone.strip())


def prompt_phone() -> str:
    pattern = re.compile(r"^\+[1-9]\d{1,14}$")
    while True:
        raw_phone = prompt_non_empty("Phone number (international format): ")
        phone = normalize_phone(raw_phone)
        if pattern.fullmatch(phone):
            return phone
        print(
            "Phone number must be in international format with a leading +, "
            "e.g. +8613800138000."
        )


def run_login_once() -> None:
    api_id = prompt_api_id()
    api_hash = prompt_non_empty("Telegram API hash: ")
    phone = prompt_phone()

    print("Starting Telegram login flow.")
    print(f"Using phone: {phone}")
    print(
        "Telegram usually delivers the login code inside an existing Telegram app "
        "session from the official 'Telegram' chat, not necessarily via SMS.\n"
    )

    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        client.start(
            phone=lambda: phone,
            code_callback=prompt_code,
            password=prompt_password,
        )

        if not client.is_user_authorized():
            raise RuntimeError("Login did not complete successfully.")

        print("\nStringSession:\n")
        print(client.session.save())
        print(
            "\nCopy the StringSession above into AstrBot's telethon_userbot "
            "adapter config as session_string."
        )
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def main() -> None:
    while True:
        try:
            run_login_once()
            return
        except KeyboardInterrupt:
            print("\nLogin flow cancelled.")
            raise SystemExit(1)
        except Exception as exc:
            print(f"\nLogin flow failed: {exc}")
            print("Restarting from the beginning.\n")


if __name__ == "__main__":
    main()
