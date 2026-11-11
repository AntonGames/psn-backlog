#!/usr/bin/env python3
"""Письмо о сбое ежедневного синка: настоящая ошибка из fetch.log и совет по её типу."""
import os, re, subprocess, sys

log = open("fetch.log", encoding="utf-8", errors="ignore").read() if os.path.exists("fetch.log") else ""
tail = "\n".join(log.strip().splitlines()[-12:]) or "(лог выгрузки пуст — упал шаг до выгрузки, см. ссылку на запуск)"
low = log.lower()

if "psn_npsso не задан" in low:
    kind, advice = "не задан токен", "Добавьте секрет PSN_NPSSO (шаги ниже)."
elif re.search(r"npsso|invalid_grant|unauthori|401|403|access code|authorization", low):
    kind, advice = "токен NPSSO истёк или неверный", "Нужен новый токен NPSSO (шаги ниже)."
elif re.search(r"unavailable|too many|429|50[0-9]|timeout|fetch failed|econnreset", low):
    kind, advice = "временный сбой серверов PSN", ("Обычно проходит само: завтрашний запуск всё догонит. "
                                                   "Если повторяется несколько дней подряд — запустите вручную или напишите Claude.")
else:
    kind, advice = "неизвестная ошибка", "Посмотрите лог по ссылке или перешлите это письмо Claude."

body = f"""## Синк трофеев не прошёл: {kind}

{advice}

**Последние строки лога:**

```
{tail}
```

[Открыть лог запуска]({os.environ.get('RUN_URL', '')})

### Как обновить токен NPSSO (живёт ~60 дней)

1. Войти на playstation.com и открыть https://ca.account.sony.com/api/v1/ssocookie
2. Скопировать значение npsso (лучше со второго аккаунта).
3. GitHub → репозиторий → Settings → Secrets and variables → Actions → `PSN_NPSSO` → Update.
4. Actions → Update backlog → Run workflow.
"""
subprocess.run([sys.executable, "scripts/send_mail.py", f"⚠ PSN бэклог: синк не прошёл — {kind}", "-"], input=body, text=True, check=True)
