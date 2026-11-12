# Genshin Impact Dictionary (原神)

Yomitan dictionaries of Genshin Impact names and terms, built from the game's own data files rather than a wiki: characters, places, enemies, wildlife, weapons, artifacts, items, furniture, talents and constellations, quests, glossary terms and card game cards.

Two editions with the same Chinese headwords and pinyin:

- `genshin_zh.zip` (原神): Chinese definitions, with the official English name as a note
- `genshin_en.zip` (原神 (English)): English definitions — the official English name, English facts line, and the game's English descriptions and character stories

## Yomitan

Download [`genshin_zh.zip`](https://github.com/caocaochan/genshin-yomitan/releases/latest/download/genshin_zh.zip) and/or [`genshin_en.zip`](https://github.com/caocaochan/genshin-yomitan/releases/latest/download/genshin_en.zip) and import them from Yomitan's **Dictionaries** settings. Both are updatable: Yomitan's **Check for updates** compares them against
`https://raw.githubusercontent.com/caocaochan/genshin-yomitan/main/index.json` and
`https://raw.githubusercontent.com/caocaochan/genshin-yomitan/main/index_en.json`.

## Contents

<!-- stats:start -->
- 20,953 headwords from game version 7.2.0 (`CNRELWin7.2.0_R49411577_S49291486_D49419538`, 2026-11-12), 37,488 simplified and traditional lookup entries
- Senses by category: 角色 127、地区 826、敌人 356、生物 226、武器 261、圣遗物 405、道具 5,093、摆设 3,226、衣装 29、风之翼 19、天赋 826、命之座 952、武器特效 221、术语 116、书籍 79、任务 2,802、七圣召唤 507、NPC 5,777
- Yomitan packages: dictionary format 3; `genshin_zh.zip` 4.2 MB, `genshin_en.zip` 4.5 MB
<!-- stats:end -->
- Every entry starts with traditional and simplified badges, styled like the HYDCD, chengyu and Wikipedia dictionaries
- Names that belong to several things are listed as numbered senses, in the order of the category list above (a character comes before an NPC of the same name)
- Each sense has a category label, the official English name, a facts line (title, element, weapon type, region, rarity, artifact set and slot, and so on) and the in-game description; characters also have their character stories in a collapsed section
- Traditional forms come from the game's own Traditional Chinese text, not a converter
- Readings are toned pinyin with citation tones (不 bù, 一 yī). They start from pypinyin, then:
  - for names whose English name is a romanization (重云 Chongyun, 长顺 Changshun), the English picks between a character's readings, limited to readings Chinese names use, so transliterated names such as 妮露 keep theirs; changes are listed in `dist/reading_fixes.tsv`
  - context rules fix errors that recur across many names: 勒 lè and 什 shí in transliterations, 卷 juàn in volume titles (卷一, 第二卷)
  - `overrides.tsv` holds manual readings from a full review of every headword (八重 bāchóng, 特调 tètiáo, 终曲 zhōngqǔ, 茜 xī in transliterated names, 塞 sài, and so on)
- Names longer than 16 characters (Yomitan's default scan length), test and unreleased entries, and food quality variants (奇怪的/美味的) are left out
- No frequency rankings

## Building

Requires Python 3 and Git. The fetch step makes a shallow, sparse clone of [Dimbreath/animegamedata2](https://gitlab.com/Dimbreath/animegamedata2) with only the tables and text maps used (about 270 MB).

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python build_dictionary.py all
```

`fetch` clones or updates `data/agd`; `build` writes `dist/genshin_zh.zip` and `dist/genshin_en.zip`, their indexes `index.json` and `index_en.json`, `source_attribution.txt` and the stats above. The index revision is the UTC build time, so every published rebuild sorts newer than the last one, which is what Yomitan's updater checks; the game build is in the description.

## Automatic builds

The [build workflow](.github/workflows/build.yml) publishes new versions without manual steps:

- **Daily at 06:00 UTC** it checks the game data dump and rebuilds only if it has a new commit (the last published one is in `data_commit.txt`)
- **On push to `main`** it rebuilds when `build_dictionary.py`, `overrides.tsv`, `styles.css` or `requirements.txt` change, so reading fixes publish themselves
- **By hand** from the Actions tab, with `force` to rebuild unchanged data and `dry_run` to build without publishing

Each build attaches both ZIPs to a new release tagged with the game version and build time, then commits `index.json` and `index_en.json`. The indexes are committed after the release is live, so Yomitan never sees a revision it cannot download yet.

## Files

- `build_dictionary.py` — fetch and build steps
- `overrides.tsv` — manual pinyin readings
- `styles.css` — entry styles packaged into the ZIP (same stylesheet as the HYDCD, chengyu and Wikipedia dictionaries)
- `index.json`, `index_en.json`, `source_attribution.txt` — written by the build
- `data_commit.txt` — game data commit of the latest published build
- `.github/workflows/build.yml` — daily check, build and release

## License

Game text © miHoYo / COGNOSPHERE. This is an unofficial fan-made dictionary for personal study, not affiliated with or endorsed by miHoYo.
