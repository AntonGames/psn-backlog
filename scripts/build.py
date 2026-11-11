#!/usr/bin/env python3
"""Собирает Markdown-трекер из data/.

Запуск:  python3 scripts/build.py
Входные данные:
  data/profile.json, data/titles.json, data/playtime.json, data/trophies/*.json — из fetch_psn.js
  data/estimates/<id>.json — оценки по гайдам (время, онлайн, сервера) на каждый трофей
  data/overrides.json      — ручные правки: недоступные DLC, переклассификация трофеев
Выход: README.md, ONLINE.md, UNOBTAINABLE.md, games/*.md
"""
import json, re, glob, os, datetime, unicodedata, math

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

    # Ручные правки на уровне игры (data/overrides.json → game_overrides):
    #   servers: {...}       — заменить статус серверов
    #   all_online: true     — все трофеи требуют онлайна (always-online игра)
    #   online_dead: true    — онлайн закрыт: онлайн-трофеи → «сервера закрыты»
    #   still_possible: [..] — названия онлайн-трофеев, которые всё ещё можно получить
    #   notes_ru / missed_missables: "..." — заменить план / заметку об упускаемых
    gov = overrides.get("game_overrides", {}).get(cid, {})
    est = {**est, **{k: gov[k] for k in ("servers", "notes_ru", "missed_missables") if k in gov}}
    keep = set(gov.get("still_possible", []))

    unearned = []
    for x in tr["trophies"]:
        if x["earned"]:
            continue
        e = dict(est_by_id.get(x["id"], {}))
        cat = e.get("cat") or "unknown"
        if x["group"] in ov.get("groups", []):
            cat = "unobtainable_user"
        if gov.get("all_online") and cat in ("offline", "unknown"):
            cat, e["online_kind"] = "online", e.get("online_kind") or "always-online"
        if gov.get("online_dead") and cat == "online" and x["name"] not in keep:
            cat = "unobtainable_servers"
        o = tov.get(str(x["id"]))
        if o:
            cat = o.get("cat", cat)
            if o.get("note"):
                e["note"] = o["note"]
        unearned.append({**x, "cat": cat, "hours": float(e.get("hours") or 0), "note": e.get("note") or "",
                         "online_kind": e.get("online_kind"), "server_status": e.get("server_status"),
                         "dlc_required": e.get("dlc_required"), "missable": e.get("missable", False)})
    # Платина невозможна, если недоступен хоть один трофей основной игры.
    if any(u["group"] == "default" and u["type"] != "platinum" and u["cat"] in ("unobtainable_servers", "glitched") for u in unearned):
        for u in unearned:
            if u["type"] == "platinum" and u["cat"] in OBTAINABLE:
                u["cat"], u["note"] = "unobtainable_servers", ("зависит от недоступных онлайн-трофеев. " + u["note"]).strip()

    # Остаток времени: оценка из гайда, распределённая по трофеям и пересчитанная
    # по тем, что ещё не выбиты и остаются выбиваемыми.
    rh = est.get("remaining_hours") or {}
    if est.get("offline_hours") is not None or est.get("online_hours") is not None:
        total = float(est.get("offline_hours") or 0) + float(est.get("online_hours") or 0)
    else:
        total = rh.get("best")
    orig = [e for e in est.get("trophies", []) if e.get("cat") in ("offline", "online")]
    off_now = [u for u in unearned if u["cat"] in ("offline", "unknown")]
    on_now = [u for u in unearned if u["cat"] == "online"]
    if total is None:
        off_h = on_h = None
    elif sum(float(e.get("hours") or 0) for e in orig) > 0:
        rate = total / sum(float(e.get("hours") or 0) for e in orig)
        off_h, on_h = rate * sum(u["hours"] for u in off_now), rate * sum(u["hours"] for u in on_now)
    else:
        per = total / len(orig) if orig else 0
        off_h, on_h = per * len(off_now), per * len(on_now)
    unob_h = est.get("unobtainable_hours") or 0
    rem = None if off_h is None else off_h + on_h

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
    f"Данные PSN: {fetched or '?'}",
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

# ---------- история и график сжигания ----------
HIST = f"{D}/history.csv"
HCOLS = ["date", "obtainable_trophies", "offline_h", "online_h", "total_h", "unobtainable_trophies", "platinums", "level"]
hist = {}
if os.path.exists(HIST):
    for line in open(HIST, encoding="utf-8").read().splitlines()[1:]:
        if line.strip():
            row = dict(zip(HCOLS, line.split(",")))
            hist[row["date"]] = row
obtainable_now = tot["offline"] + tot["online"] + tot["unknown"]
hist[fetched or today] = {
    "date": fetched or today, "obtainable_trophies": str(obtainable_now), "offline_h": f"{h_off:.0f}", "online_h": f"{h_on:.0f}",
    "total_h": f"{h_off + h_on:.0f}", "unobtainable_trophies": str(tot["unobtainable_user"] + tot["unobtainable_servers"] + tot["glitched"]),
    "platinums": str(et.get("platinum", 0)), "level": str(profile.get("trophyLevel", "")),
}
hrows = [hist[k] for k in sorted(hist)]
with open(HIST, "w", encoding="utf-8") as fh:
    fh.write(",".join(HCOLS) + "\n" + "\n".join(",".join(r[c] for c in HCOLS) for r in hrows) + "\n")

PACE = 20  # часов в неделю


def render_burndown(rows, path):
    """Однолинейный график остатка часов + пунктир темпа PACE ч/нед. Свой фон, светлая и тёмная тема."""
    W, H, l, r, t, b = 720, 300, 64, 92, 56, 40
    d0 = datetime.date.fromisoformat(rows[0]["date"])
    pts = [((datetime.date.fromisoformat(x["date"]) - d0).days, float(x["total_h"])) for x in rows]
    span = max(pts[-1][0], 7)
    pace = [(0, pts[0][1]), (span, pts[0][1] - PACE * span / 7)]
    vals = [v for _, v in pts] + [v for _, v in pace]
    lo, hi = min(vals), max(vals)
    pad = max(10, (hi - lo) * 0.1)
    lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    X = lambda d: l + (W - l - r) * d / span
    Y = lambda v: t + (H - t - b) * (hi - v) / (hi - lo)
    ticks = [lo + step * i for i in range(int(round((hi - lo) / step)) + 1)]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Осталось часов в бэклоге: {rows[-1]["total_h"]} ч на {rows[-1]["date"]}">',
         "<style>.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.grid{stroke:#e4e3de}.pace{stroke:#8d8b84}"
         ".ln{stroke:#2a78d6}.dot{fill:#2a78d6;stroke:#fcfcfb}"
         "@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.grid{stroke:#3a3a37}"
         ".pace{stroke:#8f8e86}.ln{stroke:#3987e5}.dot{fill:#3987e5;stroke:#1a1a19}}"
         "text{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}</style>",
         f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
         f'<text class="t1" x="{l}" y="26" font-size="16" font-weight="600">Осталось часов в бэклоге</text>',
         f'<text class="t2" x="{l}" y="44" font-size="12">пунктир — темп {PACE} ч в неделю от первой точки</text>']
    for v in ticks:
        o.append(f'<line class="grid" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke-width="1"/>')
        o.append(f'<text class="t2" x="{l - 8}" y="{Y(v) + 4:.1f}" font-size="11" text-anchor="end">{v:.0f}</text>')
    for d, anchor in ((0, "start"), (span, "end")):
        day = (d0 + datetime.timedelta(days=d)).strftime("%d.%m.%y")
        o.append(f'<text class="t2" x="{X(d):.1f}" y="{H - 14}" font-size="11" text-anchor="{anchor}">{day}</text>')
    o.append(f'<line class="pace" x1="{X(pace[0][0]):.1f}" y1="{Y(pace[0][1]):.1f}" x2="{X(pace[1][0]):.1f}" '
             f'y2="{Y(pace[1][1]):.1f}" stroke-width="1.5" stroke-dasharray="5 5"/>')
    if len(pts) > 1:
        o.append('<polyline class="ln" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="'
                 + " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in pts) + '"/>')
    o.append(f'<circle class="dot" cx="{X(pts[-1][0]):.1f}" cy="{Y(pts[-1][1]):.1f}" r="4.5" stroke-width="2"/>')
    o.append(f'<text class="t1" x="{X(pts[-1][0]) + 10:.1f}" y="{Y(pts[-1][1]) - 8:.1f}" font-size="13" font-weight="600">'
             f'{pts[-1][1]:.0f} ч</text>')
    o.append("</svg>")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("\n".join(o) + "\n")


render_burndown(hrows, f"{ROOT}/charts/burndown.svg")

# ---------- календарь дедлайнов (подписка по ссылке) ----------
def ics_escape(x):
    return str(x or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line):
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 74:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    return "\r\n".join(out + [cur])


deadlines = load(f"{D}/deadlines.json", []) or []
ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AntonGames//psn-backlog//RU", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
       "X-WR-CALNAME:PSN бэклог — дедлайны", "X-WR-TIMEZONE:Europe/Vilnius",
       "X-WR-CALDESC:Закрытие серверов · делистинг · другие сроки из трекера psn-backlog"]
for dl in sorted(deadlines, key=lambda x: x["date"]):
    day = datetime.date.fromisoformat(dl["date"])
    uid = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", dl["title"]).encode("ascii", "ignore").decode().lower()).strip("-")
    stamp = (dl.get("added") or dl["date"]).replace("-", "") + "T000000Z"
    ics += ["BEGIN:VEVENT", f"UID:{dl['date']}-{uid or 'deadline'}@psn-backlog", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + datetime.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{ics_escape(dl['title'])}", f"DESCRIPTION:{ics_escape(dl.get('details', '') + (' ' + dl['url'] if dl.get('url') else ''))}"]
    if dl.get("url"):
        ics.append(f"URL:{dl['url']}")
    for trig in ("-P30D", "-P7D", "-P1D"):
        ics += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(dl['title'])}", f"TRIGGER:{trig}", "END:VALARM"]
    ics.append("END:VEVENT")
ics.append("END:VCALENDAR")
os.makedirs(f"{ROOT}/calendar", exist_ok=True)
open(f"{ROOT}/calendar/deadlines.ics", "w", encoding="utf-8", newline="").write("\r\n".join(ics_fold(x) for x in ics) + "\r\n")
upcoming = [d for d in sorted(deadlines, key=lambda x: x["date"]) if d["date"] >= today]

weeks = (h_off + h_on) / PACE
if upcoming:
    R += ["## ⏰ Ближайшие дедлайны", ""]
    R += [f"- **{d['date']}** — {esc(d['title'])}" + (f" ([ссылка]({d['url']}))" if d.get("url") else "") for d in upcoming[:8]]
    R += ["", "Все сроки — в календаре по подписке: `calendar/deadlines.ics` (как подключить — в разделе «Автоматика»).", ""]
R += ["## 📉 Динамика", "",
      f"При {PACE} ч в неделю текущий остаток — это **~{weeks:.0f} недель** (≈ {weeks / 52.18:.1f} года).", "",
      "![Осталось часов в бэклоге](charts/burndown.svg)", "",
      "<details><summary>Таблица по датам</summary>", "",
      "| Дата | Выбиваемых трофеев | Осталось ч | Офлайн ч | Онлайн ч | Платин |", "|---|---:|---:|---:|---:|---:|"]
R += [f"| {x['date']} | {x['obtainable_trophies']} | {x['total_h']} | {x['offline_h']} | {x['online_h']} | {x['platinums']} |"
      for x in hrows[::-1][:12]]
R += ["", "Вся история — в [`data/history.csv`](data/history.csv).", "", "</details>", ""]
reports = sorted(glob.glob(f"{ROOT}/reports/*/*.md"), key=os.path.basename, reverse=True)
if reports:
    R += ["Последние отчёты: " + " · ".join(f"[{os.path.basename(os.path.dirname(p))} {os.path.basename(p)[:-3]}]"
                                             f"({os.path.relpath(p, ROOT)})" for p in reports[:3]), ""]

done = sorted([t for t in titles.values() if all(t["earned"].get(k, 0) >= v for k, v in t["defined"].items())],
              key=lambda t: t["lastUpdated"], reverse=True)[:5]
if done:
    R += ["## 🏆 Недавно закрыто на 100%", ""]
    R += [f"- {display(t['name'])} · {t['platform']} — {t['lastUpdated'][:10]}" + (" · платина" if t["defined"].get("platinum") else "")
          for t in done]
    R.append("")

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
      "",
      "## Автоматика",
      "",
      "| Что | Когда | Где |",
      "|---|---|---|",
      "| Синк трофеев из PSN | каждый день | Action **Update backlog** (секрет `PSN_NPSSO`); при сбое — письмо |",
      "| Проверка онлайна, серверов, делистинга, цены DLC Division 2, оценка новых игр, отчёт и план на неделю | понедельник ~08:40 (Вильнюс) | еженедельная сессия Claude по [`WEEKLY.md`](WEEKLY.md) → `reports/` |",
      "| Письма с отчётом и тревогами | при новом файле в `reports/` | Action **Email reports** (секреты `MAIL_USERNAME`, `MAIL_APP_PASSWORD`, `MAIL_TO`) |",
      "| Дедлайны (закрытие серверов, делистинг, продление токена) | по дате | `data/deadlines.json` → календарь `calendar/deadlines.ics` |",
      "",
      "**Подписка на календарь дедлайнов (один раз):** Google Calendar → слева «Другие календари» → «+» → «Добавить по URL» → "
      "`https://raw.githubusercontent.com/AntonGames/psn-backlog/main/calendar/deadlines.ics`. "
      "Затем в настройках этого календаря → «Уведомления о мероприятиях на весь день» → добавить «Эл. почта» за 4 недели, 1 неделю и 1 день. "
      "Google обновляет такие календари раз в несколько часов.",
      ""]
write(f"{ROOT}/README.md", "\n".join(R))

# ---------- ONLINE.md ----------
# Только то, что ещё НЕ выбито и выбиваемо: живой онлайн. Закрытые сервера — в UNOBTAINABLE.md.
alive = sorted([g for g in games if g["n"]["online"]], key=lambda g: g["on"])
O = ["# 🌐 Невыбитый онлайн", "",
     f"Только трофеи, которые **ещё не получены** (данные PSN от {fetched or '?'}) и требуют онлайна: "
     "другие игроки, онлайн-режимы, кооп, онлайн-рейтинг или таблицы рекордов. Уже выбитый онлайн сюда не попадает. "
     "Трофеи, онлайн которых закрыт, вынесены в [⛔ Недоступно](UNOBTAINABLE.md#сервера-закрыты).", "",
     f"**Итого:** {plural(tot['online'])} в {plural(len(alive), 'игре', 'играх', 'играх')}, ~{h_on:.0f} ч.", "",
     "| Игра | Платформа | Не выбито онлайн | ~ч | Сервера |", "|---|---|---|---:|---|"]
for g in alive:
    s = g["est"].get("servers") or {}
    names = [u["name"] for u in g["unearned"] if u["cat"] == "online"]
    shown = ", ".join(names[:6]) + (f" и ещё {len(names) - 6}" if len(names) > 6 else "")
    O.append(f"| {link(g)} | {g['t']['platform']} | **{len(names)}**: {esc(shown)} | {hours_fmt(g['on'])} | {SERVER.get(s.get('status'), '—')} |")
O.append("")
for g in alive:
    s = g["est"].get("servers") or {}
    items = [u for u in g["unearned"] if u["cat"] == "online"]
    O += [f"## {g['t']['name']} · {g['t']['platform']} — {plural(len(items))}", "",
          f"Сервера: {SERVER.get(s.get('status'), '—')} {esc(s.get('detail'))}" + (f" ([источник]({s['source']}))" if s.get("source") else ""), "",
          "| | Трофей | Описание | Вид | ~ч |", "|---|---|---|---|---:|"]
    for u in items:
        O.append(f"| {TYPE_ICON.get(u['type'], '')} | {esc(u['name'])} | {esc(u['detail'])} | {esc(u.get('online_kind') or '')} | "
                 f"{hours_fmt(u['hours']) if u['hours'] else ''} |")
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
