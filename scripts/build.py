#!/usr/bin/env python3
"""Собирает Markdown-трекер из data/.

Запуск:  python3 scripts/build.py
Входные данные:
  data/profile.json, data/titles.json, data/playtime.json, data/trophies/*.json — из fetch_psn.js
  data/estimates/<id>.json — оценки по гайдам (время, онлайн, сервера) на каждый трофей
  data/overrides.json      — ручные правки: недоступные DLC, переклассификация трофеев
Выход: README.md, ONLINE.md, UNOBTAINABLE.md, games/*.md
"""
import json, re, glob, os, datetime, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
load = lambda p, default=None: json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

profile = load(f"{D}/profile.json", {})
titles = {t["npCommunicationId"]: t for t in load(f"{D}/titles.json", [])}
playtime = load(f"{D}/playtime.json", [])
overrides = load(f"{D}/overrides.json", {})

TYPE_ICON = {"platinum": "🏆", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}
CAT = {
    "offline": "офлайн",
    "online": "🌐 онлайн",
    "unobtainable_user": "⛔ недоступно (DLC)",
    "unobtainable_servers": "💀 сервера закрыты",
    "glitched": "🐞 глюк",
    "unknown": "❔ нет оценки",
}
SERVER = {"up": "🟢 работают", "shut_down": "🔴 закрыты", "partial": "🟡 частично", "unknown": "⚪ неизвестно", "n/a": "—", None: "—"}
OBTAINABLE = ("offline", "online", "unknown")


def esc(s):
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def display(name):
    name = re.sub(r"[™®]", "", name)
    return re.sub(r"\s+Trophies$", "", name).strip()


def slugify(name, platform):
    name = re.sub(r"[™®’']", "", name)
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return f"{s or 'game'}-{platform.lower().replace(',', '-')}"


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(trophies|remastered|definitive edition|ultimate edition|perfect edition|the game)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def hours_fmt(h):
    if h is None:
        return "?"
    if h == 0:
        return "0"
    if h < 1:
        return f"{h:.1f}".rstrip("0").rstrip(".")
    return f"{h:.0f}" if h >= 10 else f"{h:.1f}".rstrip("0").rstrip(".")


def iso_hours(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", d or "")
    return (int(m.group(1) or 0) + int(m.group(2) or 0) / 60) if m else None


def find_playtime(name, platform):
    fam = "ps5" if "PS5" in platform else "ps4" if "PS4" in platform else None
    if not fam:
        return None
    n = norm(name)
    best = None
    for p in playtime:
        if not p["category"].startswith(fam):
            continue
        pn = norm(p["name"])
        close = len(n) > 5 and (n in pn or pn in n) and min(len(n), len(pn)) / max(len(n), len(pn)) >= 0.7
        if pn and (pn == n or close):
            h = iso_hours(p["playDuration"])
            if h is not None and (best is None or h > best):
                best = h
    return best


def plural(n, one="трофей", few="трофея", many="трофеев"):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def is_paid(dlc):
    s = str(dlc or "").lower()
    if not s or any(k in s for k in ("free", "included in", "already owned", "owned -", "paid game")):
        return False
    return any(k in s for k in ("paid", "season pass", "expansion pass", "legacy pack", "delisted"))


def bar(pct, width=10):
    full = round(pct / 100 * width)
    return "█" * full + "░" * (width - full)


# ---------- сбор данных по играм ----------
games = []
used_slugs = set()
for f in sorted(glob.glob(f"{D}/trophies/*.json")):
    cid = os.path.basename(f)[:-5]
    t = titles.get(cid)
    if not t:
        continue
    t = {**t, "name": display(t["name"])}
    tr = load(f)
    est = load(f"{D}/estimates/{cid}.json", {}) or {}
    ov = overrides.get("unobtainable_groups", {}).get(cid, {})
    tov = overrides.get("trophy_overrides", {}).get(cid, {})
    est_by_id = {int(e["id"]): e for e in est.get("trophies", []) if "id" in e}
    groups = {g["id"]: g["name"] for g in tr["groups"]}

    unearned = []
    for x in tr["trophies"]:
        if x["earned"]:
            continue
        e = dict(est_by_id.get(x["id"], {}))
        cat = e.get("cat") or "unknown"
        if x["group"] in ov.get("groups", []):
            cat = "unobtainable_user"
        o = tov.get(str(x["id"]))
        if o:
            cat = o.get("cat", cat)
            if o.get("note"):
                e["note"] = o["note"]
        unearned.append({**x, "cat": cat, "hours": float(e.get("hours") or 0), "note": e.get("note") or "",
                         "online_kind": e.get("online_kind"), "server_status": e.get("server_status"),
                         "dlc_required": e.get("dlc_required"), "missable": e.get("missable", False)})

    # Остаток времени: оценка из гайда, пересчитанная по тем трофеям, что ещё не выбиты.
    rh = est.get("remaining_hours") or {}
    def scaled(cats, total_key):
        total = est.get(total_key)
        if total is None:
            return None
        orig = [e for e in est.get("trophies", []) if e.get("cat") in cats]
        now = [u for u in unearned if u["cat"] in cats]
        s_orig = sum(float(e.get("hours") or 0) for e in orig)
        s_now = sum(u["hours"] for u in now)
        if s_orig > 0:
            return total * s_now / s_orig
        return total * (len(now) / len(orig)) if orig else (total if now else 0)
    off_h = scaled(("offline",), "offline_hours")
    on_h = scaled(("online",), "online_hours")
    if off_h is None and on_h is None and rh.get("best") is not None:
        off_h, on_h = float(rh["best"]), 0.0
    unob_h = est.get("unobtainable_hours") or 0
    rem = None if off_h is None and on_h is None else (off_h or 0) + (on_h or 0)

    slug = slugify(t["name"], t["platform"])
    if slug in used_slugs:
        slug = f"{slug}-{cid.lower()}"
    used_slugs.add(slug)
    has_plat = any(x["type"] == "platinum" for x in tr["trophies"])
    games.append({
        "cid": cid, "t": t, "tr": tr, "est": est, "groups": groups, "unearned": unearned, "slug": slug,
        "earned": sum(1 for x in tr["trophies"] if x["earned"]), "total": len(tr["trophies"]),
        "plat": "✅" if any(x["type"] == "platinum" and x["earned"] for x in tr["trophies"]) else ("❌" if has_plat else "—"),
        "rem": rem, "off": off_h or 0, "on": on_h or 0, "unob": unob_h,
        "rem_min": rh.get("min"), "rem_max": rh.get("max"),
        "transfer": bool(rh.get("best") and rh.get("max") and rh["max"] >= 3 * rh["best"]
                         and re.search(r"автопоп|перенос|sync|подтянут", est.get("notes_ru", ""), re.I)),
        "played": find_playtime(t["name"], t["platform"]),
        "n": {c: sum(1 for u in unearned if u["cat"] == c) for c in CAT},
    })

games.sort(key=lambda g: (not g["rem"] and any(u["cat"] not in OBTAINABLE for u in g["unearned"]),
                          g["rem"] is None, g["rem"] if g["rem"] is not None else 0, -g["t"]["progress"]))
today = datetime.date.today().isoformat()
fetched = (profile.get("fetchedAt") or "")[:10]
link = lambda g, prefix="": f"[{esc(g['t']['name'])}]({prefix}games/{g['slug']}.md)"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text.rstrip() + "\n")


# ---------- страницы игр ----------
for old in glob.glob(f"{ROOT}/games/*.md"):
    os.remove(old)
for g in games:
    t, est = g["t"], g["est"]
    L = [f"# {t['name']} · {t['platform']}", ""]
    if t.get("icon"):
        L += [f'<img src="{t["icon"]}" height="96" alt="">', ""]
    L += [
        f"**Прогресс:** {g['earned']}/{g['total']} ({t['progress']}%) `{bar(t['progress'])}` · **Платина:** {g['plat']}",
        "",
        "| Параметр | Значение |",
        "|---|---|",
        f"| Осталось (оценка) | **~{hours_fmt(g['rem'])} ч**" + (f" (разброс {g['rem_min']}–{g['rem_max']} ч)" if g['rem_min'] is not None else "") + " |",
        f"| Из них офлайн / онлайн | {hours_fmt(g['off'])} ч / {hours_fmt(g['on'])} ч |",
    ]
    if g["unob"]:
        L.append(f"| Недоступное сейчас (не входит в остаток) | ~{hours_fmt(g['unob'])} ч |")
    L += [
        f"| Время на 100% по гайду | {est.get('time_to_100_hours') or '?'} ч |",
        f"| Сложность по гайду | {est.get('difficulty') or '?'} |",
        f"| Онлайн-сервера | {SERVER.get((est.get('servers') or {}).get('status'), '—')} {esc((est.get('servers') or {}).get('detail'))} |",
        f"| Наиграно (PSN) | {hours_fmt(g['played']) + ' ч' if g['played'] is not None else '—'} |",
        f"| Нужен интернет даже для соло | {'да' if est.get('needs_connection') else 'нет'} |",
        f"| Уверенность оценки | {est.get('confidence') or '—'} |",
        "",
    ]
    if est.get("notes_ru"):
        L += [f"> **План:** {est['notes_ru']}", ""]
    if est.get("missed_missables"):
        L += [f"> **Пропущенные/упускаемые:** {est['missed_missables']}", ""]
    if est.get("guide_urls"):
        L += ["**Гайды:** " + " · ".join(f"[{re.sub(r'^https?://(www\.)?', '', u).split('/')[0]}]({u})" for u in est["guide_urls"]), ""]
    L += ["## Невыбитые трофеи", ""]
    for gid, gname in g["groups"].items():
        items = [u for u in g["unearned"] if u["group"] == gid]
        if not items:
            continue
        all_in_group = [x for x in g["tr"]["trophies"] if x["group"] == gid]
        title = "Основная игра" if gid == "default" else f"DLC: {gname}"
        L += [f"### {title} — {len(all_in_group) - len(items)}/{len(all_in_group)}", "",
              "| | Трофей | Описание | Категория | ~ч | Редкость | Заметка |", "|---|---|---|---|---|---|---|"]
        for u in items:
            note = esc(u["note"])
            if u["missable"]:
                note = ("⚠️ упускаемый. " + note).strip()
            if u["cat"] in ("online", "unobtainable_servers") and u.get("online_kind"):
                note = (f"[{u['online_kind']}] " + note).strip()
            if u.get("dlc_required") and u["cat"] != "unobtainable_user":
                note = (("💲 " if is_paid(u["dlc_required"]) else "") + f"DLC: {esc(u['dlc_required'])}. " + note).strip()
            L.append(f"| {TYPE_ICON.get(u['type'], '')} | {esc(u['name'])} | {esc(u['detail'])} | {CAT.get(u['cat'], u['cat'])} | "
                     f"{hours_fmt(u['hours']) if u['hours'] else ''} | {u['rarity'] if u['rarity'] is not None else ''}% | {note} |")
        L.append("")
    L += ["---", "[← к бэклогу](../README.md) · [🌐 онлайн](../ONLINE.md) · [⛔ недоступно](../UNOBTAINABLE.md)"]
    write(f"{ROOT}/games/{g['slug']}.md", "\n".join(L))

# ---------- сводка ----------
tot = {c: sum(g["n"][c] for g in games) for c in CAT}
h_off = sum(g["off"] for g in games)
h_on = sum(g["on"] for g in games)
h_unob = sum(g["unob"] for g in games)
n_unearned = sum(len(g["unearned"]) for g in games)
et = profile.get("earnedTrophies", {})
complete_count = sum(1 for t in titles.values() if t["progress"] == 100 or all(t["earned"].get(k, 0) >= v for k, v in t["defined"].items()))

R = [
    f"# PSN бэклог · {profile.get('onlineId', '')}",
    "",
    f"Уровень **{profile.get('trophyLevel', '?')}** · 🏆 {et.get('platinum', 0)} · 🥇 {et.get('gold', 0)} · 🥈 {et.get('silver', 0)} · 🥉 {et.get('bronze', 0)}  ",
    f"Списков трофеев: **{len(titles)}**, закрыто на 100%: **{complete_count}**, в бэклоге: **{len(games)}**  ",
    f"Данные PSN: {fetched or '?'} · страница собрана: {today}",
    "",
    "## Итого осталось",
    "",
    "| | Трофеев | Время (оценка) |",
    "|---|---:|---:|",
    f"| Можно выбить офлайн | {tot['offline']} | ~{h_off:.0f} ч |",
    f"| [🌐 Невыбитый онлайн (сервера живы)](ONLINE.md) | {tot['online']} | ~{h_on:.0f} ч |",
    f"| **Всего выбиваемо** | **{tot['offline'] + tot['online'] + tot['unknown']}** | **~{h_off + h_on:.0f} ч** |",
    f"| [⛔ Недоступно сейчас (DLC: The Division 2, Astro's Playroom)](UNOBTAINABLE.md#недоступно-сейчас) | {tot['unobtainable_user']} | ~{h_unob:.0f} ч |",
    f"| [💀 Сервера закрыты](UNOBTAINABLE.md#сервера-закрыты) | {tot['unobtainable_servers']} | — |",
    f"| [🐞 Глючные](UNOBTAINABLE.md#глючные-трофеи) | {tot['glitched']} | — |",
]
if tot["unknown"]:
    R.append(f"| ❔ Без оценки | {tot['unknown']} | — |")
R += [f"| Всего невыбитых | {n_unearned} | |", ""]

quick = [g for g in games if g["rem"] is not None and 0 < g["rem"] <= 3]
if quick:
    R += ["## ⚡ Быстрые победы (≤ 3 ч)", ""]
    R += [f"- {link(g)} · {g['t']['platform']} — ~{hours_fmt(g['rem'])} ч, осталось {plural(len([u for u in g['unearned'] if u['cat'] in OBTAINABLE]))}"
          + (f" 🔁 при переносе сейва/автопопе, иначе до {g['rem_max']} ч" if g["transfer"] else "") for g in quick]
    R.append("")

paid = []
for g in games:
    items = [u for u in g["unearned"] if u["cat"] in OBTAINABLE and is_paid(u.get("dlc_required"))]
    if items:
        names = sorted({re.sub(r"\s*\(.*$", "", str(u["dlc_required"])) for u in items})
        paid.append((g, len(items), sum(u["hours"] for u in items), names))
if paid:
    R += ["<details><summary>💲 Платные DLC в остатке: проверьте, что они куплены "
          f"({plural(len(paid), 'игра', 'игры', 'игр')}, {plural(sum(p[1] for p in paid))}, ~{sum(p[2] for p in paid):.0f} ч)</summary>", "",
          "| Игра | Платформа | Трофеев | ~ч | DLC |", "|---|---|---:|---:|---|"]
    for g, n, h, names in sorted(paid, key=lambda p: -p[2]):
        R.append(f"| {link(g)} | {g['t']['platform']} | {n} | {hours_fmt(h)} | {esc(', '.join(names))} |")
    R += ["", "Если DLC нет и купить нельзя, отметьте его группу в `data/overrides.json` → `unobtainable_groups`.", "", "</details>", ""]

# по платформам
plat = {}
for g in games:
    key = "PS Vita" if "VITA" in g["t"]["platform"] else g["t"]["platform"].split(",")[0]
    p = plat.setdefault(key, [0, 0, 0.0])
    p[0] += 1; p[1] += len([u for u in g["unearned"] if u["cat"] in OBTAINABLE]); p[2] += g["rem"] or 0
R += ["## По платформам", "", "| Платформа | Игр в бэклоге | Выбиваемых трофеев | ~ч |", "|---|---:|---:|---:|"]
R += [f"| {k} | {v[0]} | {v[1]} | {v[2]:.0f} |" for k, v in sorted(plat.items(), key=lambda kv: -kv[1][2])]
R.append("")

R += ["## Все игры бэклога", "", "Отсортировано по оценке оставшегося времени. ⚠ — в остатке есть онлайн, "
      "🔁 — оценка при переносе сейва/автопопе с другой версии, ⛔ — остались только недоступные трофеи.", "",
      "| # | Игра | Платформа | Прогресс | Платина | Осталось | Офлайн | Онлайн | Недоступно | Наиграно | Сложность |",
      "|---:|---|---|---|:---:|---:|---:|---:|---:|---:|---|"]
for i, g in enumerate(games, 1):
    blocked = g["n"]["unobtainable_user"] + g["n"]["unobtainable_servers"] + g["n"]["glitched"]
    R.append(
        f"| {i} | {link(g)}{' ⚠' if g['n']['online'] else ''} | {g['t']['platform']} | {g['earned']}/{g['total']} ({g['t']['progress']}%) | {g['plat']} | "
        f"**{'⛔' if not g['rem'] and blocked else hours_fmt(g['rem']) + ' ч'}**{' 🔁' if g['transfer'] else ''} | {hours_fmt(g['off'])} | {hours_fmt(g['on'])} | {blocked or ''} | "
        f"{hours_fmt(g['played']) + ' ч' if g['played'] is not None else ''} | {esc(g['est'].get('difficulty'))} |")
R += ["",
      "## Откуда цифры",
      "",
      "- Выбитые/невыбитые трофеи — официальный API PlayStation Network (публичный профиль).",
      "- Время, онлайн, упускаемые, статус серверов — гайды PowerPyx, Knoef, Stratege, PlatPrices/PlatPursuit и новости о закрытии серверов (ноябрь 2026). "
      "Оценка дана для опытного охотника и считается только по оставшимся трофеям. У каждой игры указана уверенность (high/medium/low); "
      "там, где гайда нет, оценка экспертная.",
      "- «Наиграно» — данные PSN, есть только для PS4/PS5 и сопоставлены по названию, поэтому приблизительны.",
      "",
      "## Как обновить",
      "",
      "1. Получить токен NPSSO: войти на playstation.com и открыть https://ca.account.sony.com/api/v1/ssocookie",
      "2. Локально: `npm install`, затем `PSN_NPSSO=<токен> npm run update`. Токен нигде не сохраняется.",
      "3. Или в GitHub: Settings → Secrets → Actions → `PSN_NPSSO`, потом Actions → **Update backlog** → Run workflow (ещё и раз в сутки сам).",
      "",
      "Оценки времени и онлайна лежат в `data/estimates/` и считаются по каждому трофею: при выбивании остаток пересчитывается автоматически.",
      "Ручные правки (например, «DLC купил», «сервер на самом деле жив») — в `data/overrides.json`.",
      ""]
write(f"{ROOT}/README.md", "\n".join(R))

# ---------- ONLINE.md ----------
O = ["# 🌐 Невыбитый онлайн", "",
     "Трофеи, для которых нужны другие игроки, онлайн-режимы, кооп или онлайн-таблицы рекордов.",
     "Сначала игры с работающими серверами (по оценке оставшегося онлайна), затем — с закрытыми.", ""]
on_games = [g for g in games if g["n"]["online"] or g["n"]["unobtainable_servers"]]
alive = sorted([g for g in on_games if g["n"]["online"]], key=lambda g: g["on"])
dead = [g for g in on_games if not g["n"]["online"]]
n_dead_games = len([g for g in on_games if g['n']['unobtainable_servers']])
O += [f"**Живой онлайн:** {plural(tot['online'])} в {plural(len(alive), 'игре', 'играх', 'играх')}, ~{h_on:.0f} ч. "
      f"**Закрытые сервера:** {plural(tot['unobtainable_servers'])} в {plural(n_dead_games, 'игре', 'играх', 'играх')}.", "",
      "| Игра | Платформа | Онлайн-трофеев | ~ч | Сервера |", "|---|---|---:|---:|---|"]
for g in alive + dead:
    s = g["est"].get("servers") or {}
    O.append(f"| {link(g)} | {g['t']['platform']} | {g['n']['online']}" + (f" (+{g['n']['unobtainable_servers']} 💀)" if g['n']['unobtainable_servers'] else "")
             + f" | {hours_fmt(g['on'])} | {SERVER.get(s.get('status'), '—')} |")
O.append("")
for g in alive + dead:
    s = g["est"].get("servers") or {}
    items = [u for u in g["unearned"] if u["cat"] in ("online", "unobtainable_servers")]
    O += [f"## {g['t']['name']} · {g['t']['platform']}", "",
          f"Сервера: {SERVER.get(s.get('status'), '—')} {esc(s.get('detail'))}", "",
          "| | Трофей | Описание | Вид | Статус | ~ч |", "|---|---|---|---|---|---:|"]
    for u in items:
        O.append(f"| {TYPE_ICON.get(u['type'], '')} | {esc(u['name'])} | {esc(u['detail'])} | {esc(u.get('online_kind') or '')} | "
                 f"{CAT[u['cat']]} | {hours_fmt(u['hours']) if u['hours'] else ''} |")
    O += ["", f"[Страница игры →](games/{g['slug']}.md)", ""]
O += ["---", "[← к бэклогу](README.md)"]
write(f"{ROOT}/ONLINE.md", "\n".join(O))

# ---------- UNOBTAINABLE.md ----------
U = ["# ⛔ Недоступно на данный момент", "", "## Недоступно сейчас", ""]
for cid, ov in overrides.get("unobtainable_groups", {}).items():
    g = next((x for x in games if x["cid"] == cid), None)
    if not g:
        continue
    items = [u for u in g["unearned"] if u["cat"] == "unobtainable_user"]
    if not items:
        continue
    U += [f"### {g['t']['name']} · {g['t']['platform']}", "", f"**Причина:** {ov.get('reason', '')}  "]
    if ov.get("unlock_condition"):
        U.append(f"**Когда станет доступно:** {ov['unlock_condition']}  ")
    U += [f"**Трофеев:** {len(items)} · **время:** ~{hours_fmt(g['unob'])} ч", "",
          "| | Трофей | Описание | DLC | Редкость |", "|---|---|---|---|---:|"]
    for u in items:
        U.append(f"| {TYPE_ICON.get(u['type'], '')} | {esc(u['name'])} | {esc(u['detail'])} | {esc(g['groups'].get(u['group']))} | {u['rarity']}% |")
    U += ["", f"[Страница игры →](games/{g['slug']}.md)", ""]

U += ["## Сервера закрыты", "",
      "По данным гайдов и новостей онлайн у этих трофеев отключён. Если найдёте способ (например, сервер на самом деле жив), "
      "поменяйте категорию в `data/overrides.json` → `trophy_overrides`.", ""]
dead_any = [g for g in games if g["n"]["unobtainable_servers"]]
if not dead_any:
    U += ["Нет.", ""]
for g in dead_any:
    s = g["est"].get("servers") or {}
    items = [u for u in g["unearned"] if u["cat"] == "unobtainable_servers"]
    U += [f"### {g['t']['name']} · {g['t']['platform']} — {len(items)}", "", f"{SERVER.get(s.get('status'), '—')} {esc(s.get('detail'))}", ""]
    U += [f"- {TYPE_ICON.get(u['type'], '')} **{esc(u['name'])}** — {esc(u['detail'])}" for u in items]
    U.append("")
U += ["## Глючные трофеи", ""]
gl = [g for g in games if g["n"]["glitched"]]
if not gl:
    U += ["Нет.", ""]
for g in gl:
    U += [f"### {g['t']['name']} · {g['t']['platform']}", ""]
    U += [f"- {TYPE_ICON.get(u['type'], '')} **{esc(u['name'])}** — {esc(u['detail'])} {('— ' + esc(u['note'])) if u['note'] else ''}"
          for u in g["unearned"] if u["cat"] == "glitched"]
    U.append("")
U += ["---", "[← к бэклогу](README.md)"]
write(f"{ROOT}/UNOBTAINABLE.md", "\n".join(U))
print(f"игр: {len(games)}, невыбитых: {n_unearned}, офлайн ~{h_off:.0f} ч, онлайн ~{h_on:.0f} ч, недоступно ~{h_unob:.0f} ч, без оценки: {tot['unknown']}")
