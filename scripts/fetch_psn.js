// Выгрузка трофеев из официального API PlayStation Network.
//
// Запуск:   PSN_NPSSO=<токен> node scripts/fetch_psn.js
// Токен NPSSO: войти на playstation.com, открыть https://ca.account.sony.com/api/v1/ssocookie
// Токен нигде не сохраняется. Подойдёт токен любого аккаунта, если профиль цели публичный.
//
// Пишет:
//   data/profile.json          — уровень, количество трофеев
//   data/titles.json           — все списки трофеев аккаунта (кратко)
//   data/playtime.json         — наигранное время (только PS4/PS5)
//   data/trophies/<id>.json    — подробно по каждому незавершённому списку
const fs = require('fs');
const path = require('path');
const psn = require('psn-api');

const ROOT = path.join(__dirname, '..');
const DATA = path.join(ROOT, 'data');
const TARGET = process.env.PSN_TARGET || 'Anton_games337';
const NPSSO = process.env.PSN_NPSSO;
const LANG = { headerOverrides: { 'Accept-Language': 'en-US' } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const write = (f, obj) => fs.writeFileSync(f, JSON.stringify(obj, null, 1) + '\n');
const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return d; } };

// Повтор при временных ошибках PSN (503/429/сеть) с нарастающей паузой.
async function retry(label, fn, tries = 6) {
  for (let i = 0; ; i++) {
    try {
      return await fn();
    } catch (e) {
      const transient = /unavailable|too many|429|50[0-9]|timeout|fetch failed|ECONNRESET|socket/i.test(e.message);
      if (!transient || i >= tries - 1) throw e;
      const wait = 2000 * 2 ** i;
      console.log(`  ${label}: ${e.message} — повтор через ${wait / 1000} с`);
      await sleep(wait);
    }
  }
}

async function main() {
  if (!NPSSO) {
    console.log('PSN_NPSSO не задан — пропускаю выгрузку.');
    return;
  }
  const auth = await retry('auth', async () => psn.exchangeAccessCodeForAuthTokens(await psn.exchangeNpssoForAccessCode(NPSSO)));
  const found = await retry('profile', () => psn.getProfileFromUserName(auth, TARGET));
  const accountId = found.profile.accountId;
  const summary = await retry('summary', () => psn.getUserTrophyProfileSummary(auth, accountId));
  write(path.join(DATA, 'profile.json'), {
    onlineId: found.profile.onlineId,
    accountId,
    trophyLevel: summary.trophyLevel,
    earnedTrophies: summary.earnedTrophies,
    fetchedAt: new Date().toISOString(),
  });

  const prevTitles = new Map(readJson(path.join(DATA, 'titles.json'), []).map((t) => [t.npCommunicationId, t]));
  let titles = [];
  for (let offset = 0; ; ) {
    const r = await retry('titles', () => psn.getUserTitles(auth, accountId, { limit: 800, offset, ...LANG }));
    titles = titles.concat(r.trophyTitles);
    if (!r.nextOffset || titles.length >= r.totalItemCount) break;
    offset = r.nextOffset;
  }
  write(path.join(DATA, 'titles.json'), titles.map((t) => ({
    npCommunicationId: t.npCommunicationId,
    name: t.trophyTitleName.replace(/\s+/g, ' ').trim(),
    platform: t.trophyTitlePlatform,
    npServiceName: t.npServiceName,
    progress: t.progress,
    defined: t.definedTrophies,
    earned: t.earnedTrophies,
    lastUpdated: t.lastUpdatedDateTime,
    icon: t.trophyTitleIconUrl,
  })));
  console.log(`списков трофеев: ${titles.length}`);

  try {
    let played = [];
    for (let offset = 0; ; ) {
      const r = await retry('played', () => psn.getUserPlayedGames(auth, accountId, { limit: 200, offset }));
      played = played.concat(r.titles);
      if (!r.nextOffset || played.length >= r.totalItemCount) break;
      offset = r.nextOffset;
    }
    write(path.join(DATA, 'playtime.json'), played
      .filter((p) => /game/.test(p.category))
      .map((p) => ({ titleId: p.titleId, name: p.name, category: p.category, playDuration: p.playDuration, lastPlayed: p.lastPlayedDateTime })));
  } catch (e) {
    console.log('наигранное время недоступно:', e.message);
  }

  const dir = path.join(DATA, 'trophies');
  fs.mkdirSync(dir, { recursive: true });
  const keep = new Set();
  let fetched = 0, skipped = 0;
  const failed = [];
  for (const t of titles) {
    const id = t.npCommunicationId;
    const complete = Object.entries(t.definedTrophies).every(([k, v]) => t.earnedTrophies[k] >= v);
    if (complete) continue;
    const file = path.join(dir, id + '.json');
    keep.add(id + '.json');
    // Инкрементально: список не менялся (те же дата и состав трофеев) — берём сохранённый файл.
    const prev = prevTitles.get(id);
    if (prev && fs.existsSync(file) && prev.lastUpdated === t.lastUpdatedDateTime &&
        JSON.stringify(prev.defined) === JSON.stringify(t.definedTrophies)) {
      skipped++;
      continue;
    }
    const opt = { npServiceName: t.npServiceName, ...LANG };
    try {
      const groups = await retry(id, () => psn.getTitleTrophyGroups(auth, id, opt));
      const all = await retry(id, () => psn.getTitleTrophies(auth, id, 'all', opt));
      const mine = await retry(id, () => psn.getUserTrophiesEarnedForTitle(auth, accountId, id, 'all', opt));
      const earned = new Map(mine.trophies.map((x) => [x.trophyId, x]));
      write(file, {
        groups: groups.trophyGroups.map((g) => ({ id: g.trophyGroupId, name: g.trophyGroupName.replace(/\s+/g, ' ').trim() })),
        trophies: all.trophies.map((x) => {
          const e = earned.get(x.trophyId) || {};
          return {
            id: x.trophyId,
            type: x.trophyType,
            name: x.trophyName.replace(/\s+/g, ' ').trim(),
            detail: (x.trophyDetail || '').replace(/\s+/g, ' ').trim(),
            group: x.trophyGroupId,
            hidden: x.trophyHidden,
            earned: !!e.earned,
            earnedAt: e.earnedDateTime || null,
            rarity: e.trophyEarnedRate ? Number(e.trophyEarnedRate) : null,
          };
        }),
      });
      fetched++;
    } catch (e) {
      failed.push(`${id} ${t.trophyTitleName}: ${e.message}`);
    }
    await sleep(500);
  }
  for (const f of fs.readdirSync(dir)) if (!keep.has(f)) fs.unlinkSync(path.join(dir, f));
  console.log(`обновлено списков: ${fetched}, без изменений: ${skipped}, ошибок: ${failed.length}`);
  failed.forEach((f) => console.log('  не удалось:', f));
  console.log(`незавершённых списков: ${keep.size}`);
  if (failed.length) {
    // Чтобы в следующий раз эти списки скачались заново, оставляем им старую дату обновления.
    const ids = new Set(failed.map((f) => f.split(' ')[0]));
    const saved = readJson(path.join(DATA, 'titles.json'), []);
    for (const t of saved) if (ids.has(t.npCommunicationId)) t.lastUpdated = (prevTitles.get(t.npCommunicationId) || {}).lastUpdated || null;
    write(path.join(DATA, 'titles.json'), saved);
    if (failed.length > Math.max(3, keep.size * 0.2)) throw new Error(`слишком много ошибок PSN: ${failed.length}`);
  }
}

main().catch((e) => {
  console.error('Ошибка:', e.message);
  process.exit(1);
});
