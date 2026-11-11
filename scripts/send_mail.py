#!/usr/bin/env python3
"""Отправка письма через Gmail SMTP (для GitHub Actions).

Запуск:  python3 scripts/send_mail.py "Тема" файл.md      (или "-" — текст из stdin)
Секреты окружения: MAIL_USERNAME (адрес Gmail), MAIL_APP_PASSWORD (пароль приложения Google),
MAIL_TO (получатель; по умолчанию MAIL_USERNAME). Без секретов письмо пропускается.
"""
import os, smtplib, ssl, sys
from email.message import EmailMessage

user = os.environ.get("MAIL_USERNAME", "").strip()
password = os.environ.get("MAIL_APP_PASSWORD", "").replace(" ", "").strip()
to = os.environ.get("MAIL_TO", "").strip() or user
if not user or not password:
    print("MAIL_USERNAME / MAIL_APP_PASSWORD не заданы — письмо не отправлено.")
    sys.exit(0)

subject, src = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "-")
body = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
repo = os.environ.get("GITHUB_REPOSITORY")
if repo:
    body += f"\n\n—\nТрекер: https://github.com/{repo}"
    if src != "-":
        body += f"\nЭтот отчёт: https://github.com/{repo}/blob/main/{src}"

msg = EmailMessage()
msg["Subject"], msg["From"], msg["To"] = subject, user, to
msg.set_content(body)
with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
    smtp.login(user, password)
    smtp.send_message(msg)
print(f"Письмо отправлено: {subject}")
