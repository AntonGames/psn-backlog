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

async function main() {
  if (!NPSSO) {
    console.log('PSN_NPSSO не задан — пропускаю выгрузку.');
    return;
  }
  const auth = await psn.exchangeAccessCodeForAuthTokens(await psn.exchangeNpssoForAccessCode(NPSSO));
  const found = await psn.getProfileFromUserName(auth, TARGET);
  const accountId = found.profile.accountId;
  const summary = await psn.getUserTrophyProfileSummary(auth, accountId);
  write(path.join(DATA, 'profile.json'), {
    onlineId: found.profile.onlineId,
    accountId,
    trophyLevel: summary.trophyLevel,
    earnedTrophies: summary.earnedTrophies,
    fetchedAt: new Date().toISOString(),
  });

  let titles = [];
  for (let offset = 0; ; ) {
    const r = await psn.getUserTitles(auth, accountId, { limit: 800, offset, ...LANG });
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
      const r = await psn.getUserPlayedGames(auth, accountId, { limit: 200, offset });
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
  for (const t of titles) {
    const id = t.npCommunicationId;
    const complete = Object.entries(t.definedTrophies).every(([k, v]) => t.earnedTrophies[k] >= v);
    if (complete) continue;
    keep.add(id + '.json');
    const opt = { npServiceName: t.npServiceName, ...LANG };
    const groups = await psn.getTitleTrophyGroups(auth, id, opt);
    const all = await psn.getTitleTrophies(auth, id, 'all', opt);
    const mine = await psn.getUserTrophiesEarnedForTitle(auth, accountId, id, 'all', opt);
    const earned = new Map(mine.trophies.map((x) => [x.trophyId, x]));
    write(path.join(dir, id + '.json'), {
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
    await sleep(250);
  }
  for (const f of fs.readdirSync(dir)) if (!keep.has(f)) fs.unlinkSync(path.join(dir, f));
  console.log(`незавершённых списков: ${keep.size}`);
}

main().catch((e) => {
  console.error('Ошибка:', e.message);
  process.exit(1);
});
