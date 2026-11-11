#!/usr/bin/env python3
"""Отправка письма через Gmail SMTP (для GitHub Actions).

Запуск:  python3 scripts/send_mail.py "Тема" файл.md      (или "-" — текст из stdin)
         python3 scripts/send_mail.py --preview "Тема" файл.md out.html   — только собрать HTML
Тело — Markdown: уходит HTML-письмом (заголовки, списки, жирный, ссылки, таблицы) и текстовой версией.
Секреты окружения: MAIL_USERNAME (адрес Gmail), MAIL_APP_PASSWORD (пароль приложения Google),
MAIL_TO (получатель; по умолчанию MAIL_USERNAME). Без секретов письмо пропускается.
"""
import html, os, re, smtplib, ssl, sys
from email.message import EmailMessage

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
INK, MUTED, LINE, ACCENT = "#1f1f1d", "#6b6a64", "#e6e5e0", "#2a78d6"
STYLE = {
    "h1": f"margin:0 0 4px;font-size:22px;line-height:1.3;font-weight:700;color:{INK}",
    "h2": f"margin:26px 0 8px;padding-top:18px;border-top:1px solid {LINE};font-size:17px;line-height:1.35;font-weight:700;color:{INK}",
    "h3": f"margin:18px 0 6px;font-size:15px;font-weight:700;color:{INK}",
    "p": "margin:0 0 10px",
    "ul": "margin:0 0 12px;padding-left:22px",
    "ol": "margin:0 0 12px;padding-left:22px",
    "li": "margin:0 0 7px",
    "a": f"color:{ACCENT};text-decoration:none",
    "strong": f"font-weight:700;color:{INK}",
    "code": "font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;background:#f1f0ec;padding:1px 5px;border-radius:4px",
    "blockquote": f"margin:0 0 12px;padding:8px 14px;border-left:3px solid {ACCENT};background:#f4f7fc;color:{INK}",
    "table": "border-collapse:collapse;width:100%;margin:0 0 12px;font-size:14px",
    "th": f"text-align:left;padding:6px 8px;border-bottom:2px solid {LINE};color:{MUTED};font-weight:600",
    "td": f"padding:6px 8px;border-bottom:1px solid {LINE};vertical-align:top",
    "hr": f"border:none;border-top:1px solid {LINE};margin:20px 0",
    "pre": "margin:0 0 12px;padding:10px 12px;background:#f6f6f3;border:1px solid #e6e5e0;border-radius:6px;font-size:12px;line-height:1.45;white-space:pre-wrap;word-break:break-word",
}


def md_to_html(md):
    try:
        import markdown
        body = markdown.markdown(md, extensions=["tables", "sane_lists", "fenced_code"])
    except ImportError:  # запасной вариант без библиотеки
        body = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in md.split("\n\n") if p.strip())
    body = re.sub(r"<(h1|h2|h3|p|ul|ol|li|a|strong|code|blockquote|table|th|td|hr|pre)(\s|>|/)",
                  lambda m: f'<{m.group(1)} style="{STYLE[m.group(1)]}"{m.group(2)}', body)
    body = re.sub(r'(<pre style="[^"]*">)<code style="[^"]*"', r"\1<code", body)
    # Первый подзаголовок без разделителя сверху
    body = body.replace(f'style="{STYLE["h2"]}"', 'style="' + STYLE["h2"].replace(f"padding-top:18px;border-top:1px solid {LINE};", "") + '"', 1) \
        if "<h1" not in body else body
    return body


def md_to_text(md):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", t)
    return t


def build(subject, md, links):
    foot = " · ".join(f'<a href="{u}" style="{STYLE["a"]}">{html.escape(n)}</a>' for n, u in links)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f4f4f1">
<div style="padding:24px 12px;background:#f4f4f1">
<div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid {LINE};border-radius:12px;padding:26px 26px 18px;font-family:{FONT};font-size:15px;line-height:1.55;color:{INK}">
<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};margin-bottom:10px">PSN бэклог · Anton_games337</div>
{md_to_html(md)}
<div style="margin-top:22px;padding-top:12px;border-top:1px solid {LINE};font-size:13px;color:{MUTED}">{foot}</div>
</div></div></body></html>"""
    text = md_to_text(md) + ("\n\n—\n" + "\n".join(f"{n}: {u}" for n, u in links) if links else "")
    return page, text


def main(argv):
    preview = argv[:1] == ["--preview"]
    if preview:
        argv = argv[1:]
    subject, src = argv[0], (argv[1] if len(argv) > 1 else "-")
    md = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    repo = os.environ.get("GITHUB_REPOSITORY", "AntonGames/psn-backlog")
    links = [("Трекер", f"https://github.com/{repo}"), ("Невыбитый онлайн", f"https://github.com/{repo}/blob/main/ONLINE.md")]
    if src != "-":
        links.append(("Этот отчёт на GitHub", f"https://github.com/{repo}/blob/main/{src}"))
    page, text = build(subject, md, links)
    if preview:
        open(argv[2], "w", encoding="utf-8").write(page)
        print("HTML сохранён:", argv[2])
        return

    user = os.environ.get("MAIL_USERNAME", "").strip()
    password = os.environ.get("MAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    if not user or not password:
        print("MAIL_USERNAME / MAIL_APP_PASSWORD не заданы — письмо не отправлено.")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"PSN бэклог <{user}>", to
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    print(f"Письмо отправлено: {subject}")


if __name__ == "__main__":
    main(sys.argv[1:])
