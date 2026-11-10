"""Build Yomitan dictionaries of Genshin Impact names and terms from the game's own data files.

Source: Dimbreath/animegamedata2 (ExcelBinOutput tables + TextMap), fetched with a sparse git clone.
Every table row points at its text through a numeric hash; the same hash looks up the simplified
Chinese (CHS), traditional Chinese (CHT) and English (EN) strings.

Two editions are built from the same entries: Chinese headwords with Chinese definitions
(genshin_zh.zip) and Chinese headwords with English definitions (genshin_en.zip).

    python build_dictionary.py fetch    # clone or update data/agd (only the files listed in TABLES/TEXTMAPS)
    python build_dictionary.py build    # write dist/*.zip, index*.json, source_attribution.txt, README stats
    python build_dictionary.py all
"""

import argparse
import collections
import datetime as dt
import json
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

from pypinyin import Style, lazy_pinyin, pinyin

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "agd"
DIST_DIR = ROOT / "dist"
DATA_REPO = "https://gitlab.com/Dimbreath/animegamedata2.git"

# GitHub repo for Yomitan's update check: index*.json on main, ZIPs attached to the latest release.
REPO = "caocaochan/genshin-yomitan"

MAX_HEADWORD_LEN = 16  # Yomitan's default scan length
MAX_SENSES = 10
BANK_SIZE = 10000

TABLES = [
    "AvatarExcelConfigData", "AvatarSkillDepotExcelConfigData", "AvatarSkillExcelConfigData",
    "AvatarTalentExcelConfigData", "ProudSkillExcelConfigData", "FetterInfoExcelConfigData",
    "FetterStoryExcelConfigData", "AvatarCostumeExcelConfigData", "AvatarFlycloakExcelConfigData",
    "WeaponExcelConfigData", "EquipAffixExcelConfigData", "ReliquaryExcelConfigData",
    "ReliquarySetExcelConfigData", "MaterialExcelConfigData", "HomeWorldFurnitureExcelConfigData",
    "AnimalCodexExcelConfigData", "MonsterDescribeExcelConfigData", "MonsterTitleExcelConfigData",
    "AnimalDescribeExcelConfigData", "NpcExcelConfigData", "WorldAreaConfigData", "CityConfigData",
    "ViewCodexExcelConfigData", "BookSuitExcelConfigData", "ChapterExcelConfigData",
    "MainQuestExcelConfigData", "HyperLinkNameExcelConifgData", "GCGCardExcelConfigData",
]
TEXTMAPS = {
    "chs": ["TextMapCHS", "TextMap_MediumCHS"],
    "cht": ["TextMapCHT", "TextMap_MediumCHT"],
    "en": ["TextMapEN", "TextMap_MediumEN"],
}

# Editions: which text map the definitions come from, and the package details.
EDITIONS = {
    "zh": {"text": "chs", "zip": "genshin_zh.zip", "index": "index.json", "title": "原神",
           "target": "zh", "lang": "zh-Hans"},
    "en": {"text": "en", "zip": "genshin_en.zip", "index": "index_en.json", "title": "原神 (English)",
           "target": "en", "lang": "en"},
}

# Sense order inside an entry; the key is the Chinese label, the value the English one.
CATEGORIES = {
    "角色": "Character", "地区": "Place", "敌人": "Enemy", "生物": "Wildlife", "武器": "Weapon",
    "圣遗物": "Artifact", "道具": "Item", "摆设": "Furnishing", "衣装": "Outfit", "风之翼": "Wind Glider",
    "天赋": "Talent", "命之座": "Constellation", "武器特效": "Weapon Passive", "术语": "Term", "书籍": "Book",
    "任务": "Quest", "七圣召唤": "TCG", "NPC": "NPC",
}
PRIORITY = {c: i for i, c in enumerate(CATEGORIES)}

# Fixed labels as (Chinese, English).
WEAPON_TYPES = {
    "WEAPON_SWORD_ONE_HAND": ("单手剑", "Sword"), "WEAPON_CLAYMORE": ("双手剑", "Claymore"),
    "WEAPON_POLE": ("长柄武器", "Polearm"), "WEAPON_BOW": ("弓", "Bow"), "WEAPON_CATALYST": ("法器", "Catalyst"),
}
RARITY = {"QUALITY_ORANGE": 5, "QUALITY_ORANGE_SP": 5, "QUALITY_PURPLE": 4}
STARS = {1: ("一星", "1★"), 2: ("二星", "2★"), 3: ("三星", "3★"), 4: ("四星", "4★"), 5: ("五星", "5★")}
ARTIFACT_SLOTS = {
    "EQUIP_BRACER": ("生之花", "Flower of Life"), "EQUIP_NECKLACE": ("死之羽", "Plume of Death"),
    "EQUIP_SHOES": ("时之沙", "Sands of Eon"), "EQUIP_RING": ("空之杯", "Goblet of Eonothem"),
    "EQUIP_DRESS": ("理之冠", "Circlet of Logos"),
}
MONSTER_TYPES = {
    "CODEX_SUBTYPE_ELEMENTAL": ("元素生物", "Elemental Lifeforms"), "CODEX_SUBTYPE_HILICHURL": ("丘丘部落", "Hilichurls"),
    "CODEX_SUBTYPE_ABYSS": ("深渊", "The Abyss"), "CODEX_SUBTYPE_FATUI": ("愚人众", "Fatui"),
    "CODEX_SUBTYPE_AUTOMATRON": ("自律机关", "Automatons"), "CODEX_SUBTYPE_HUMAN": ("其他人类势力", "Other Human Factions"),
    "CODEX_SUBTYPE_BEAST": ("异种魔兽", "Mystical Beasts"), "CODEX_SUBTYPE_BOSS": ("首领", "Bosses"),
}
ANIMAL_TYPES = {
    "CODEX_SUBTYPE_ANIMAL": ("走兽", "Beasts"), "CODEX_SUBTYPE_AVIARY": ("飞禽", "Birds"),
    "CODEX_SUBTYPE_FISH": ("鱼类", "Fish"),
}
QUEST_TYPES = {"WQ": ("世界任务", "World Quest"), "LQ": ("传说任务", "Story Quest"), "EQ": ("活动任务", "Event Quest")}
GCG_TYPES = {
    "GCG_CARD_EVENT": ("事件牌", "Event Card"), "GCG_CARD_ASSIST": ("支援牌", "Support Card"),
    "GCG_CARD_MODIFY": ("装备牌", "Equipment Card"),
}
SKILL_KINDS = {
    "normal": ("普通攻击", "Normal Attack"), "skill": ("元素战技", "Elemental Skill"),
    "burst": ("元素爆发", "Elemental Burst"), "passive": ("固有天赋", "Passive Talent"),
}
PHRASES = {
    "title": ("「{}」", "{}"),
    "constellation_of": ("{}的命之座", "Constellation of {}"),
    "constellation_lv": ("第{}层", "Constellation {}"),
    "outfit_of": ("{}的衣装", "Outfit for {}"),
    "passive": ("特效「{}」", "Passive: {}"),
    "passive_of": ("{}的特效", "Passive of {}"),
    "set_piece": ("{}件套：{}", "{}-Piece: {}"),
    "nation": ("国家/地区", "Nation/Region"),
    "viewpoint": ("观景点", "Viewpoint"),
    "artifact_set": ("圣遗物套装", "Artifact Set"),
    "book_series": ("书籍系列", "Book Series"),
    "stories": ("角色故事", "Character Stories"),
    "traveler": ("旅行者", "Traveler"),
    "male_lead": ("男性主角", "Male protagonist"),
    "female_lead": ("女性主角", "Female protagonist"),
}
# Material types that are covered by another table, duplicate a name, or are not terms.
SKIP_MATERIAL_TYPES = {
    "MATERIAL_FURNITURE_FORMULA", "MATERIAL_FURNITURE_SUITE_FORMULA", "MATERIAL_GCG_CARD",
    "MATERIAL_GCG_CARD_FACE", "MATERIAL_GCG_CARD_BACK", "MATERIAL_PHOTOGRAPH_POSE", "MATERIAL_BGM",
    "MATERIAL_AVATAR", "MATERIAL_TALENT", "MATERIAL_COSTUME", "MATERIAL_FLYCLOAK",
    "MATERIAL_CHANNELLER_SLAB_BUFF", "MATERIAL_MUSIC_GAME_BOOK_THEME", "MATERIAL_ACTIVITY_ROBOT",
}
# Placeholder text per text map: {NICKNAME}, the Wanderer's name, and {..#SEXPRO[...]} words.
PLACEHOLDERS = {
    "zh": {"NICKNAME": "旅行者", "WANDERER": "流浪者", "HE": "他", "SHE": "她", "BOY": "少年", "GIRL": "少女",
           "BROTHER": "哥哥", "SISTER": "妹妹", "BIGBROTHER": "大哥哥", "BIGSISTER": "大姐姐",
           "SON": "儿子", "DAUGHTER": "女儿"},
    "en": {"NICKNAME": "Traveler", "WANDERER": "Wanderer", "HE": "he", "SHE": "she", "BOY": "boy", "GIRL": "girl",
           "BROTHER": "brother", "SISTER": "sister", "BIGBROTHER": "big brother", "BIGSISTER": "big sister",
           "SON": "son", "DAUGHTER": "daughter"},
}

# Readings the English-name match may switch to. Foreign names are transliterated, and their English
# spelling is not pinyin (妮露 Nilou is nīlù, not nīlòu), so only switch to readings that Chinese
# names use.
NAME_READINGS = {
    "重": {"chóng"}, "长": {"cháng"}, "行": {"xíng", "háng"}, "泊": {"bó"}, "勒": {"lè"}, "蹻": {"jiǎo"},
    "乐": {"yuè", "lè"}, "曾": {"zēng", "céng"}, "朝": {"cháo", "zhāo"}, "单": {"shàn", "chán"},
    "解": {"xiè", "jiě"}, "区": {"ōu"}, "仇": {"qiú"}, "查": {"zhā"}, "盖": {"gě"}, "华": {"huà", "huá"},
    "召": {"shào"}, "种": {"chóng", "zhǒng"}, "参": {"shēn", "cān"}, "藏": {"zàng", "cáng"},
    "调": {"diào", "tiáo"}, "降": {"xiáng", "jiàng"}, "觉": {"jué"}, "落": {"luò"}, "薄": {"bó"},
    "柏": {"bǎi", "bó"}, "都": {"dū"}, "弹": {"tán"}, "传": {"zhuàn", "chuán"}, "少": {"shào", "shǎo"},
    "好": {"hào", "hǎo"}, "和": {"hé", "hè"}, "相": {"xiàng", "xiāng"}, "将": {"jiàng", "jiāng"},
    "中": {"zhōng", "zhòng"}, "正": {"zhēng", "zhèng"}, "更": {"gēng"}, "难": {"nàn", "nán"},
    "应": {"yīng", "yìng"}, "为": {"wéi", "wèi"}, "数": {"shù", "shǔ"}, "沈": {"shěn"}, "宿": {"xiù", "sù"},
    "冲": {"chōng", "chòng"}, "缝": {"féng"}, "差": {"chā", "chāi"}, "折": {"zhé", "shé"}, "鲜": {"xiān", "xiǎn"},
    "露": {"lù"}, "处": {"chǔ", "chù"}, "奇": {"qí", "jī"}, "辟": {"pì", "bì"}, "阿": {"ā", "ē"},
}

CITATION = {"不": "bù", "一": "yī"}
SANDHI = {"不": ("bú",), "一": ("yí", "yì")}

HAN = "㐀-鿿"
RE_CJK = re.compile(rf"[{HAN}\U00020000-\U0002ffff]")
# Test and unreleased markers. Only ever matched against Chinese text: English has ordinary words
# such as "greatest" and "contest".
RE_JUNK = re.compile(r"test|\$UNRELEASED|\$HIDDEN|废弃|测试|unreleased|占位|\?\?\?|？？？", re.I)


# ---------------------------------------------------------------- fetch

def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def fetch():
    paths = [f"/ExcelBinOutput/{t}.json" for t in TABLES]
    paths += [f"/TextMap/{f}.json" for files in TEXTMAPS.values() for f in files]
    if not (DATA_DIR / ".git").exists():
        DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", "--filter=blob:none", "--sparse", "--no-checkout", DATA_REPO, str(DATA_DIR))
        git("sparse-checkout", "set", "--no-cone", *paths, cwd=DATA_DIR)
        git("checkout", "main", cwd=DATA_DIR)
    else:
        git("sparse-checkout", "set", "--no-cone", *paths, cwd=DATA_DIR)
        git("fetch", "--depth", "1", "origin", "main", cwd=DATA_DIR)
        git("reset", "--hard", "FETCH_HEAD", cwd=DATA_DIR)
    print("data at", data_version()["build"])


def data_version():
    """Game build from the dump's commit title, e.g. CNRELWin7.2.0_R49086080_S49291486_D49291486."""
    out = subprocess.run(["git", "log", "-1", "--format=%s%n%cs"], cwd=DATA_DIR, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    build, date = out[0].strip(), out[1].strip()
    m = re.search(r"(\d+\.\d+\.\d+)", build)
    return {"build": build, "version": m.group(1) if m else build, "date": date}


# ---------------------------------------------------------------- text

def load_table(name):
    return json.loads((DATA_DIR / "ExcelBinOutput" / f"{name}.json").read_text("utf-8"))


def load_textmaps():
    maps = {}
    for lang, files in TEXTMAPS.items():
        m = {}
        for f in files:
            m.update(json.loads((DATA_DIR / "TextMap" / f"{f}.json").read_text("utf-8")))
        maps[lang] = m
    return maps


def clean(text, gender=None, lang="zh"):
    """Strip game markup. gender='M'/'F' picks one side of {M#..}{F#..}; None joins them with '/'."""
    if not text:
        return ""
    words = PLACEHOLDERS[lang]
    t = text.replace("\\n", "\n")
    if t.startswith("#"):
        t = t[1:]
    t = re.sub(r"\{LAYOUT_MOBILE#[^}]*\}|\{LAYOUT_PS#[^}]*\}", "", t)
    t = re.sub(r"\{LAYOUT_PC#([^}]*)\}", r"\1", t)
    if gender:
        drop = "F" if gender == "M" else "M"
        t = re.sub(r"\{%s#([^}]*)\}" % gender, r"\1", t)
        t = re.sub(r"\{%s#[^}]*\}" % drop, "", t)
    else:
        pair = lambda m, a, b: m.group(a) if m.group(a) == m.group(b) else f"{m.group(a)}/{m.group(b)}"
        t = re.sub(r"\{M#([^}]*)\}\{F#([^}]*)\}", lambda m: pair(m, 1, 2), t)
        t = re.sub(r"\{F#([^}]*)\}\{M#([^}]*)\}", lambda m: pair(m, 2, 1), t)
        t = re.sub(r"\{[MF]#([^}]*)\}", r"\1", t)
    t = t.replace("{NICKNAME}", words["NICKNAME"])
    t = re.sub(r"\{REALNAME\[ID\(1\)[^\]]*\]\}", words["WANDERER"], t)
    t = re.sub(r"\{REALNAME\[[^\]]*\]\}", "…", t)

    def sexpro(m):
        options = [words.get(code.rsplit("_", 1)[-1], "") for code in m.group(1).split("|")]
        return "/".join(dict.fromkeys(o for o in options if o))

    t = re.sub(r"\{(?:PLAYERAVATAR|MATEAVATAR)#SEXPRO\[([^\]]*)\]\}", sexpro, t)
    t = re.sub(r"\{LINK#[^}]*\}|\{/LINK\}", "", t)
    t = re.sub(r"\{RUBY#\[[A-Z]\][^}]*\}", "", t)
    t = re.sub(r"\{SPRITE(?:_PRESET)?#[^}]*\}", "", t)
    t = re.sub(r"\{param\d+\}|\{\d+\}|\{[A-Za-z]+\d*\}", "…", t)
    t = re.sub(r"</?(?:color|i|b|size|c)(?:=[^>]*)?>", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def gendered(raw):
    """A name with {M#..}{F#..} becomes two names, otherwise one."""
    if raw and re.search(r"\{[MF]#", raw):
        return [clean(raw, "M"), clean(raw, "F")]
    return [clean(raw)]


def usable_name(name):
    return (
        bool(name)
        and RE_CJK.search(name) is not None
        and len(name) <= MAX_HEADWORD_LEN
        and not RE_JUNK.search(name)
        and not re.search(r"[{}$<>\n]", name)
    )


def usable_desc(desc):
    """For Chinese text. Rejects test/unreleased text and placeholders such as "……" and "——"."""
    return (bool(desc) and not RE_JUNK.search(desc) and desc not in ("…", "暂无")
            and re.search(rf"[{HAN}A-Za-z0-9]", desc) is not None)


def has_letters(text):
    return bool(text) and re.search(rf"[{HAN}A-Za-z0-9]", text) is not None


# ---------------------------------------------------------------- readings

def _toneless(syllable):
    s = unicodedata.normalize("NFD", syllable)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("ü", "u").replace("v", "u")


def _contextual(word, ch, syl):
    """Readings pypinyin gets wrong across many game names (found by the manual review):
    勒 is lè in transliterated names (lēi only means "tighten"), 什 is shí outside 什么,
    and 卷 numbering a volume (卷一, 第二卷) is juàn."""
    if ch == "勒" and syl == "lēi" and not re.search("勒[紧住死]", word):
        return "lè"
    if ch == "什" and syl == "shén" and not re.search("什[么麽]", word):
        return "shí"
    if ch == "卷" and syl == "juǎn" and re.search("卷[一二三四五六七八九十上中下]|第[一二三四五六七八九十]+卷", word):
        return "juàn"
    return syl


def _en_letters(en):
    if not en or not re.fullmatch(r"[A-Za-z' \-]+", en):
        return None
    return re.sub(r"[^a-z]", "", en.lower())


class Readings:
    """Toned pinyin with no spaces, as in the Wikipedia and chengyu dictionaries.

    pypinyin's phrase dictionary picks the default. For all-Han names whose English name is a
    romanization (重云 Chongyun, 长顺 Changshun), the English is used to choose between a character's
    readings in NAME_READINGS when the default doesn't match it. overrides.tsv wins over both.
    """

    def __init__(self, overrides_path):
        self.overrides = {}
        if overrides_path.exists():
            for line in overrides_path.read_text("utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    term, _, reading = line.partition("\t")
                    self.overrides[term.strip()] = reading.strip()
        self.cache = {}
        self.fixed_by_en = []

    def __call__(self, word, en=None):
        if word in self.overrides:
            return self.overrides[word]
        if word not in self.cache:
            self.cache[word] = self._reading(word, en)
        return self.cache[word]

    def _reading(self, word, en):
        out = []
        for run in re.findall(rf"[{HAN}]+|[^{HAN}]+", word):
            if RE_CJK.match(run):
                syl = lazy_pinyin(run, style=Style.TONE)
                if len(syl) == len(run):
                    # pypinyin's phrase data sometimes carries tone sandhi (不会 búhuì, 一样 yíyàng);
                    # readings use citation tones
                    syl = [CITATION.get(ch, s) if s in SANDHI.get(ch, ()) else s for ch, s in zip(run, syl)]
                    syl = [_contextual(word, ch, s) for ch, s in zip(run, syl)]
                    if en and len(run) == len(word):
                        syl = self._match_en(run, syl, en)
                out.extend(syl)
            else:
                out.append(re.sub(r"[^A-Za-z0-9]", "", run).lower())
        return "".join(out)

    def _match_en(self, word, default, en):
        target = _en_letters(en)
        if not target or "".join(_toneless(s) for s in default) == target:
            return default
        cands = []
        for ch, d in zip(word, default):
            allowed = NAME_READINGS.get(ch, set())
            cands.append([d] + [p for p in pinyin(ch, style=Style.TONE, heteronym=True)[0] if p != d and p in allowed])
        # every way to spell `target` as one toneless candidate per character
        solutions = []

        def walk(i, pos, chosen):
            if len(solutions) > 1:
                return
            if i == len(word):
                if pos == len(target):
                    solutions.append(list(chosen))
                return
            seen = set()
            for opt in cands[i]:
                tl = _toneless(opt)
                if tl in seen or not target.startswith(tl, pos):
                    continue
                seen.add(tl)
                chosen.append(opt)
                walk(i + 1, pos + len(tl), chosen)
                chosen.pop()

        walk(0, 0, [])
        if len(solutions) == 1:
            self.fixed_by_en.append((word, "".join(default), "".join(solutions[0]), en))
            return solutions[0]
        return default


# ---------------------------------------------------------------- collecting senses

class Collector:
    """Headwords always come from the CHS/CHT names; definitions from the edition's text map."""

    def __init__(self, tm, edition):
        self.tm = tm
        self.ed = edition
        self.en_defs = EDITIONS[edition]["text"] == "en"
        self.groups = {}  # simplified headword -> {"forms": set, "senses": {(cat, key): sense}, "trad": str}

    def text(self, lang, h):
        return self.tm[lang].get(str(h), "") if h else ""

    def name(self, h):
        """Chinese name, for filtering and grouping."""
        return clean(self.text("chs", h))

    def disp(self, h):
        """Definition-language text for a hash, or "" when the Chinese text is test/unreleased/empty."""
        if not usable_desc(self.name(h)):
            return ""
        if not self.en_defs:
            return self.name(h)
        return clean(self.text("en", h), lang="en")

    def label(self, pair):
        """Pick one side of a (Chinese, English) label."""
        return (pair[1] if self.en_defs else pair[0]) if pair else ""

    def phrase(self, key, *args):
        return self.label(PHRASES[key]).format(*args)

    def add(self, name_hash, cat, facts=(), desc="", desc_hash=None, extra=None, key=None, raw_names=None, en=None):
        """Add one sense under the name behind name_hash (CHS + CHT forms, EN name)."""
        chs_raw = raw_names[0] if raw_names else self.text("chs", name_hash)
        cht_raw = raw_names[1] if raw_names else self.text("cht", name_hash)
        if en is None:
            en = clean(self.text("en", name_hash), lang="en") if name_hash else ""
        if desc_hash is not None:
            desc = self.disp(desc_hash)
        desc = desc if has_letters(desc) else ""
        chs_names, cht_names = gendered(chs_raw), gendered(cht_raw)
        if len(cht_names) != len(chs_names):
            cht_names = chs_names
        added = False
        for chs, cht in zip(chs_names, cht_names):
            if not usable_name(chs):
                continue
            keys = [chs]
            bare = re.fullmatch(r"「([^「」]+)」", chs)
            if bare and usable_name(bare.group(1)):
                keys.append(bare.group(1))
            for i, headword in enumerate(keys):
                g = self.groups.setdefault(headword, {"forms": set(), "senses": {}, "trad": None})
                if i == 0:
                    g["forms"] |= {chs, cht} if usable_name(cht) else {chs}
                    g["trad"] = g["trad"] or (cht if usable_name(cht) else chs)
                else:
                    g["forms"].add(headword)
                    tb = re.fullmatch(r"「([^「」]+)」", cht or "")
                    if tb and usable_name(tb.group(1)):
                        g["forms"].add(tb.group(1))
                        g["trad"] = g["trad"] or tb.group(1)
                    else:
                        g["trad"] = g["trad"] or headword
                sense = {"cat": cat, "en": en, "facts": [f for f in facts if f], "desc": desc,
                         "extra": extra or [], "display": chs if i else None}
                k = (cat, key)
                old = g["senses"].get(k)
                if old is None or _richness(sense) > _richness(old):
                    g["senses"][k] = sense
                added = True
        return added


def _richness(s):
    return (len(s["facts"]), len(s["desc"]), len(s["extra"]))


def obfuscated_text_field(rows, tm):
    """The obfuscated (all-caps) text-hash field with the shortest texts, e.g. the city name next to
    the statue name and description."""
    lens = collections.defaultdict(list)
    for r in rows:
        for k, v in r.items():
            if k.isupper() and isinstance(v, int) and str(v) in tm:
                lens[k].append(len(tm[str(v)]))
    means = {k: sum(v) / len(v) for k, v in lens.items() if len(v) >= len(rows) // 2}
    return min(means, key=means.get) if means else None


def collect(tm, edition):
    c = Collector(tm, edition)
    N, D, lab, ph = c.name, c.disp, c.label, c.phrase

    def stars(n):
        return lab(STARS.get(n))

    # --- characters, their skills, passives and constellations
    avatars = {a["id"]: a for a in load_table("AvatarExcelConfigData")}
    fetter = {f["avatarId"]: f for f in load_table("FetterInfoExcelConfigData")}
    stories = collections.defaultdict(list)
    for s in sorted(load_table("FetterStoryExcelConfigData"), key=lambda s: s.get("fetterId", 0)):
        title, body = D(s.get("storyTitleTextMapHash")), D(s.get("storyContextTextMapHash"))
        if title and body:
            stories[s["avatarId"]].append((title, body))
    depots = {d["id"]: d for d in load_table("AvatarSkillDepotExcelConfigData")}
    skills = {s["id"]: s for s in load_table("AvatarSkillExcelConfigData")}
    talents = {t["talentId"]: t for t in load_table("AvatarTalentExcelConfigData")}
    proud = {}
    for p in load_table("ProudSkillExcelConfigData"):
        g = p.get("proudSkillGroupId")
        if g and (g not in proud or p.get("level", 0) < proud[g].get("level", 0)):
            proud[g] = p
    playable = {"空", "荧"}  # Chinese names, to keep these out of the NPC senses
    avatar_disp = {}
    for aid, a in avatars.items():
        f = fetter.get(aid)
        if not f or a.get("useType") not in ("AVATAR_FORMAL", None):
            continue
        playable.add(N(a["nameTextMapHash"]))
        name = D(a["nameTextMapHash"])
        avatar_disp[aid] = name

        def after_or_before(field):
            # the "After" text (shown once unlocked) when it resolves, else the "Befor" text
            for h in (f.get(f"{field}AfterTextMapHash"), f.get(f"{field}BeforTextMapHash")):
                if D(h):
                    return h
            return None

        title, vision, native = (D(f.get("avatarTitleTextMapHash")), D(after_or_before("avatarVision")),
                                 D(f.get("avatarNativeTextMapHash")))
        facts = [ph("title", title) if title else "", vision, lab(WEAPON_TYPES.get(a.get("weaponType"))),
                 native, stars(RARITY.get(a.get("qualityType")))]
        desc = D(a.get("descTextMapHash")) or D(f.get("avatarDetailTextMapHash"))
        extra = [(ph("stories"), stories[aid])] if stories.get(aid) else []
        c.add(a["nameTextMapHash"], "角色", facts, desc, extra=extra)
        constellation = after_or_before("avatarConstellation")
        if constellation:
            c.add(constellation, "命之座", [ph("constellation_of", name)], key=N(constellation))

        for did in a.get("candSkillDepotIds") or [a.get("skillDepotId")]:
            d = depots.get(did)
            if not d:
                continue
            slots = list(zip(d.get("skills", [])[:2], ("normal", "skill"))) + [(d.get("energySkill"), "burst")]
            for sid, kind in slots:
                s = skills.get(sid)
                if s:
                    c.add(s["nameTextMapHash"], "天赋", [name, lab(SKILL_KINDS[kind])],
                          desc_hash=s.get("descTextMapHash"), key=sid)
            for open_ in d.get("inherentProudSkillOpens", []):
                p = proud.get(open_.get("proudSkillGroupId"))
                if p:
                    c.add(p["nameTextMapHash"], "天赋", [name, lab(SKILL_KINDS["passive"])],
                          desc_hash=p.get("descTextMapHash"), key=open_["proudSkillGroupId"])
            for n, tid in enumerate(d.get("talents", []), start=1):
                t = talents.get(tid)
                if t:
                    c.add(t["nameTextMapHash"], "命之座", [name, ph("constellation_lv", n)],
                          desc_hash=t.get("descTextMapHash"), key=tid)

    # Both Travelers are named 旅行者 in the avatar table; the twins' own names only appear in text.
    for chs, cht, en, who in (("空", "空", "Aether", "male_lead"), ("荧", "熒", "Lumine", "female_lead")):
        c.add(None, "角色", [ph("traveler"), ph(who)], raw_names=(chs, cht), en=en)

    for co in load_table("AvatarCostumeExcelConfigData"):
        if co.get("isDefault"):
            continue
        owner = avatar_disp.get(co.get("characterId"), "")
        c.add(co["nameTextMapHash"], "衣装", [ph("outfit_of", owner) if owner else ""], desc_hash=co.get("descTextMapHash"))
    for fl in load_table("AvatarFlycloakExcelConfigData"):
        c.add(fl["nameTextMapHash"], "风之翼", [], desc_hash=fl.get("descTextMapHash"))

    # --- places
    cities = load_table("CityConfigData")
    city_field = obfuscated_text_field(cities, tm["chs"])
    city_hash = {ct.get("cityId"): ct.get("cityNameTextMapHash") or ct.get(city_field) for ct in cities}
    city_of_area = {}
    for ct in cities:
        h = city_hash[ct.get("cityId")]
        if not usable_name(N(h)):
            continue
        for aid in ct.get("areaIdVec", []):
            city_of_area.setdefault(aid, D(h))
        c.add(h, "地区", [ph("nation")], key="city")
    areas = load_table("WorldAreaConfigData")
    level1 = {}
    for r in areas:
        if r.get("areaType") == "LEVEL_1":
            level1.setdefault(r.get("areaID1"), D(r.get("areaNameTextMapHash")))
    for r in areas:
        chain = [city_of_area.get(r.get("areaID1"), "")]
        if r.get("areaType") != "LEVEL_1":
            chain.append(level1.get(r.get("areaID1"), ""))
        chain = [x for x in chain if x]
        c.add(r.get("areaNameTextMapHash"), "地区", [" › ".join(chain)] if chain else [], key="area")
    for v in load_table("ViewCodexExcelConfigData"):
        if not v.get("isDisuse"):
            c.add(v["nameTextMapHash"], "地区", [ph("viewpoint"), D(city_hash.get(v.get("cityId")))],
                  desc_hash=v.get("descTextMapHash"), key="view")

    # --- enemies and wildlife
    mdesc = {m["id"]: m for m in load_table("MonsterDescribeExcelConfigData")}
    mtitle = {m["titleID"]: m for m in load_table("MonsterTitleExcelConfigData") if "titleID" in m}
    adesc = {a["id"]: a for a in load_table("AnimalDescribeExcelConfigData")}
    for r in load_table("AnimalCodexExcelConfigData"):
        if r.get("isDisuse"):
            continue
        if r.get("type") == "CODEX_MONSTER":
            m = mdesc.get(r.get("describeId"))
            if not m:
                continue
            t = mtitle.get(m.get("titleID"))
            title = D(t["titleNameTextMapHash"]) if t else ""
            facts = [lab(MONSTER_TYPES.get(r.get("subType"))), ph("title", title) if title else ""]
            c.add(m["nameTextMapHash"], "敌人", facts, desc_hash=r.get("descTextMapHash"))
        else:
            a = adesc.get(r.get("describeId"))
            if a:
                c.add(a["nameTextMapHash"], "生物", [lab(ANIMAL_TYPES.get(r.get("subType")))],
                      desc_hash=r.get("descTextMapHash"))

    # --- weapons and artifacts
    affix = collections.defaultdict(list)
    for e in load_table("EquipAffixExcelConfigData"):
        affix[e["id"]].append(e)
    for rows in affix.values():
        rows.sort(key=lambda e: e.get("level", 0))
    for w in load_table("WeaponExcelConfigData"):
        if w.get("weaponType") not in WEAPON_TYPES:
            continue
        aff = affix.get((w.get("skillAffix") or [0])[0], [])
        aff_name = D(aff[0]["nameTextMapHash"]) if aff and usable_name(N(aff[0]["nameTextMapHash"])) else ""
        facts = [lab(WEAPON_TYPES[w["weaponType"]]), stars(w.get("rankLevel")), ph("passive", aff_name) if aff_name else ""]
        if c.add(w["nameTextMapHash"], "武器", facts, desc_hash=w.get("descTextMapHash")) and aff:
            c.add(aff[0]["nameTextMapHash"], "武器特效", [ph("passive_of", D(w["nameTextMapHash"]))],
                  desc_hash=aff[0].get("descTextMapHash"))
    set_names = {}
    for s in load_table("ReliquarySetExcelConfigData"):
        rows = affix.get(s.get("equipAffixId"), [])
        if not rows:
            continue
        set_names[s["setId"]] = D(rows[0]["nameTextMapHash"])
        pieces = [ph("set_piece", n, D(e.get("descTextMapHash"))) for n, e in zip(s.get("setNeedNum", []), rows)]
        c.add(rows[0]["nameTextMapHash"], "圣遗物", [ph("artifact_set")], "\n".join(pieces), key="set")
    for r in sorted(load_table("ReliquaryExcelConfigData"), key=lambda r: -r.get("rankLevel", 0)):
        c.add(r["nameTextMapHash"], "圣遗物", [set_names.get(r.get("setId"), ""), lab(ARTIFACT_SLOTS.get(r.get("equipType")))],
              desc_hash=r.get("descTextMapHash"), key="piece")

    # --- items and furniture
    for m in sorted(load_table("MaterialExcelConfigData"), key=lambda m: m["id"]):
        if (m.get("materialType") in SKIP_MATERIAL_TYPES
                or m.get("foodQuality") in ("FOOD_QUALITY_STRANGE", "FOOD_QUALITY_DELICIOUS")
                or RE_JUNK.search(N(m.get("typeDescTextMapHash")))):
            continue
        c.add(m["nameTextMapHash"], "道具", [D(m.get("typeDescTextMapHash")), stars(m.get("rankLevel"))],
              desc_hash=m.get("descTextMapHash"))
    for f in load_table("HomeWorldFurnitureExcelConfigData"):
        # characters invited to the teapot are furniture rows too ("家园入住角色")
        if N(f["nameTextMapHash"]) in playable or N(f.get("descTextMapHash")) == "家园入住角色":
            continue
        c.add(f["nameTextMapHash"], "摆设", [], desc_hash=f.get("descTextMapHash"))

    # --- books, quests, glossary terms, card game
    for b in load_table("BookSuitExcelConfigData"):
        c.add(b["suitNameTextMapHash"], "书籍", [ph("book_series")])
    for ch in load_table("ChapterExcelConfigData"):
        c.add(ch.get("chapterTitleTextMapHash"), "任务", [D(ch.get("chapterNumTextMapHash"))], key="chapter")
    for q in load_table("MainQuestExcelConfigData"):
        c.add(q.get("titleTextMapHash"), "任务", [lab(QUEST_TYPES.get(q.get("type")))],
              desc_hash=q.get("descTextMapHash"), key="quest")
    for h in load_table("HyperLinkNameExcelConifgData"):
        c.add(h["nameTextMapHash"], "术语", [], desc_hash=h.get("descTextMapHash"))
    for card in load_table("GCGCardExcelConfigData"):
        if not card.get("isCanObtain") or card.get("cardType") not in GCG_TYPES:
            continue
        desc = D(card.get("descTextMapHash"))
        c.add(card["nameTextMapHash"], "七圣召唤", [lab(GCG_TYPES[card["cardType"]])], "" if "$[" in desc else desc)

    # --- named NPCs, unless the name is already a character, enemy or animal (they exist as NPCs too)
    beings = {"角色", "敌人", "生物"}
    for n in load_table("NpcExcelConfigData"):
        name = N(n.get("nameTextMapHash"))
        if name in c.groups and any(cat in beings for cat, _ in c.groups[name]["senses"]):
            continue
        if (not name or name in playable or "的" in name or len(name) < 2 or len(name) > 8
                or re.search(r"[0-9A-Za-z（）()]", name)):
            continue
        c.add(n["nameTextMapHash"], "NPC", [])
    return c


# ---------------------------------------------------------------- output

def node(tag, content, kind=None, **extra):
    """Structured-content element; `kind` becomes data-sc-content for styles.css."""
    n = {"tag": tag, "content": content}
    if kind:
        n["data"] = {"content": kind}
    n.update(extra)
    return n


def lines(text):
    out = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append({"tag": "br"})
        if line:
            out.append(line)
    return out


def form_row(simplified, traditional):
    """Traditional / simplified badges, the same header as the HYDCD, chengyu and Wikipedia dictionaries."""
    badges = [node("span", traditional, "traditional-term")]
    if simplified != traditional:
        badges.append(node("span", simplified, "simplified-term"))
    return node("span", [node("span", badges, "terms-parent")], "first-row-parent", lang="zh-Hans")


def sense_item(s, en_defs):
    head = [node("span", CATEGORIES[s["cat"]] if en_defs else s["cat"], "source-label")]
    if s["display"]:
        head += [" ", node("span", s["display"], lang="zh-Hans")]
    if s["en"] and s["en"] != s["display"]:
        # English edition: the English name is the gloss; Chinese edition: a secondary note
        head += [" ", node("span", s["en"], None if en_defs else "alternate", lang="en")]
    content = [node("div", head)]
    if s["facts"]:
        content.append(node("div", " · ".join(s["facts"]), "phonology"))
    if s["desc"]:
        content.append(node("div", lines(s["desc"]), "sense"))
    for title, parts in s["extra"]:
        body = [node("summary", title)]
        for sub, text in parts:
            body.append(node("div", [node("span", sub, style={"fontWeight": "bold"}), {"tag": "br"}, *lines(text)],
                             "example"))
        content.append(node("details", body, "examples"))
    return node("li", content)


ATTRIBUTION = (
    "Text from Genshin Impact (原神), © miHoYo / COGNOSPHERE. Extracted from the game data dump at "
    "https://gitlab.com/Dimbreath/animegamedata2 ({build}, {date}). Unofficial fan-made dictionary for "
    "personal study; not affiliated with or endorsed by miHoYo.\n"
)


def make_index(edition, version, n_headwords):
    e = EDITIONS[edition]
    defs = "English names and descriptions" if edition == "en" else "Chinese descriptions, official English names"
    index = {
        "title": e["title"],
        # Yomitan offers an update when installed revision < published revision (plain string compare
        # for non-numeric revisions), so use a sortable build time rather than the game build string.
        "revision": version["built"],
        "format": 3,
        "sequenced": True,
        "sourceLanguage": "zh",
        "targetLanguage": e["target"],
        "author": "miHoYo (game text); dictionary built from Dimbreath/animegamedata2",
        "description": (
            f"{n_headwords:,} Genshin Impact names and terms (characters, places, enemies, wildlife, weapons, "
            f"artifacts, items, furniture, talents, quests, glossary terms, card game cards) with their in-game "
            f"{defs} and simplified/traditional lookup forms. Game version {version['version']} "
            f"({version['build']})."
        ),
        "attribution": ATTRIBUTION.format(**version),
    }
    if REPO:
        index.update({
            "isUpdatable": True,
            "indexUrl": f"https://raw.githubusercontent.com/{REPO}/main/{e['index']}",
            "downloadUrl": f"https://github.com/{REPO}/releases/latest/download/{e['zip']}",
            "url": f"https://github.com/{REPO}",
        })
    return index


def write_edition(edition, c, readings, version):
    e = EDITIONS[edition]
    index = make_index(edition, version, len(c.groups))
    zip_path = DIST_DIR / e["zip"]
    n_entries = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("index.json", json.dumps(index, ensure_ascii=False, indent=2))
        z.writestr("source_attribution.txt", ATTRIBUTION.format(**version))
        z.write(ROOT / "styles.css", "styles.css")
        bank, bank_no = [], 0

        def flush():
            nonlocal bank, bank_no
            bank_no += 1
            z.writestr(f"term_bank_{bank_no}.json", json.dumps(bank, ensure_ascii=False, separators=(",", ":")))
            bank = []

        for seq, key in enumerate(sorted(c.groups), start=1):
            g = c.groups[key]
            senses = sorted(g["senses"].values(), key=lambda s: PRIORITY[s["cat"]])[:MAX_SENSES]
            en = next((s["en"] for s in senses if s["en"]), None)
            glossary = [{
                "type": "structured-content",
                "content": node("span", [form_row(key, g["trad"] or key),
                                         node("ol", [sense_item(s, c.en_defs) for s in senses], lang=e["lang"])],
                                "genshin-entry"),
            }]
            reading = readings(key, en)
            for form in sorted(g["forms"] | {key}, key=lambda f: (f != key, f)):
                bank.append([form, reading, "", "", 0, glossary, seq, ""])
                n_entries += 1
                if len(bank) >= BANK_SIZE:
                    flush()
        if bank:
            flush()
    (ROOT / e["index"]).write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = collections.Counter(s["cat"] for g in c.groups.values() for s in g["senses"].values())
    size = zip_path.stat().st_size
    print(f"wrote {zip_path}: {len(c.groups):,} headwords, {n_entries:,} entries, {size / 1e6:.1f} MB")
    return {"headwords": len(c.groups), "entries": n_entries, "counts": counts, "size": size}


def build():
    version = data_version()
    version["built"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("game data:", version["build"])
    tm = load_textmaps()
    readings = Readings(ROOT / "overrides.tsv")
    DIST_DIR.mkdir(exist_ok=True)
    stats = {ed: write_edition(ed, collect(tm, ed), readings, version) for ed in EDITIONS}
    print("senses by category:", dict(stats["zh"]["counts"]))
    print(f"readings corrected from English names: {len(readings.fixed_by_en)} (dist/reading_fixes.tsv)")
    (DIST_DIR / "reading_fixes.tsv").write_text(
        "".join(f"{w}\t{a}\t{b}\t{e}\n" for w, a, b, e in readings.fixed_by_en), encoding="utf-8")
    (ROOT / "source_attribution.txt").write_text(ATTRIBUTION.format(**version), encoding="utf-8")
    write_readme_stats(version, stats)


def write_readme_stats(version, stats):
    zh, en = stats["zh"], stats["en"]
    cats = "、".join(f"{cat} {zh['counts'][cat]:,}" for cat in CATEGORIES if zh["counts"][cat])
    text = (
        f"- {zh['headwords']:,} headwords from game version {version['version']} (`{version['build']}`, "
        f"{version['date']}), {zh['entries']:,} simplified and traditional lookup entries\n"
        f"- Senses by category: {cats}\n"
        f"- Yomitan packages: dictionary format 3; `{EDITIONS['zh']['zip']}` {zh['size'] / 1e6:.1f} MB, "
        f"`{EDITIONS['en']['zip']}` {en['size'] / 1e6:.1f} MB"
    )
    readme = ROOT / "README.md"
    if readme.exists():
        body = readme.read_text("utf-8")
        body = re.sub(r"(<!-- stats:start -->\n).*?(<!-- stats:end -->)", lambda m: m.group(1) + text + "\n" + m.group(2),
                      body, flags=re.S)
        readme.write_text(body, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["fetch", "build", "all"])
    args = ap.parse_args()
    if args.step in ("fetch", "all"):
        fetch()
    if args.step in ("build", "all"):
        if not DATA_DIR.exists():
            sys.exit("no game data; run the fetch step first")
        build()


if __name__ == "__main__":
    main()
