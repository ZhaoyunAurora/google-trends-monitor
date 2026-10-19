"""读取词根、过滤规则、白名单；给词打方向标签。"""
import os
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG = ROOT_DIR / "config"
# 结果写到哪里：GitHub Actions 里指向私有数据仓库的目录，本地默认写在代码目录
OUT_DIR = Path(os.getenv("OUT_DIR") or ROOT_DIR).resolve()


def _lines(name):
    p = CONFIG / name
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def load_roots():
    """roots.txt 里 [daily] 段每次都查，[rotate] 段轮换查。返回 (daily, rotate)。"""
    daily, rotate, cur = [], [], None
    seen = set()
    for line in _lines("roots.txt"):
        if line.startswith("["):
            cur = line.strip("[]").strip().lower()
            continue
        kw = line.lower()
        if kw in seen:
            continue
        seen.add(kw)
        (daily if cur == "daily" else rotate).append(kw)
    return daily, rotate


def load_filters():
    rules = []
    for line in _lines("filters.txt"):
        if "|" not in line:
            continue
        reason, pattern = [x.strip() for x in line.split("|", 1)]
        rules.append((reason, re.compile(pattern, re.I)))
    return rules


ALLOW = None
FILTERS = None

QUESTION = re.compile(r"^(how|what|when|where|why|who|which|is|are|does|do|can|will|should|was|were)\b", re.I)
DOMAIN = re.compile(r"(\.(com|io|ai|net|org|app|co)\b|\bwww\.|\s(io|com)$)", re.I)


def filter_reason(kw):
    """返回过滤原因；None 表示保留。"""
    global ALLOW, FILTERS
    if ALLOW is None:
        ALLOW = {x.lower() for x in _lines("allow.txt")}
        FILTERS = load_filters()
    if kw in ALLOW:
        return None
    if any(ord(c) > 0x24F for c in kw):
        return "非英文"
    if sum(1 for c in kw if ord(c) > 127) >= 2:
        return "非英文"
    if QUESTION.match(kw) or len(kw.split()) > 7:
        return "问句长句"
    if DOMAIN.search(kw):
        return "网址导航"
    if re.fullmatch(r"[\d\s+\-x*/=.]+|whats? [\dx+\-*/ ]+", kw):
        return "算式"
    for reason, pat in FILTERS:
        if pat.search(kw):
            return reason
    return None


AI_WORDS = re.compile(
    r"\b(ai|gpt\w*|chatgpt|claude|gemini|grok|openai|anthropic|llm|model|sora|veo|kling|seedance|"
    r"higgsfield|viggle|hailuo|pixverse|nano banana|qwen|flux|midjourney|runway|pika|luma|wan|minimax|"
    r"dreamina|hedra|vidu|krea|suno|udio|elevenlabs|heygen|deepseek|kimi|glm|llama|mistral|"
    r"stable diffusion|comfyui|lora|prompt|text to|image to|to video|to image|upscal\w*|"
    r"face swap|deepfake|avatar|headshot|filter|trend)\b", re.I)
TOOL_WORDS = re.compile(
    r"\b(generator|maker|creator|converter|convert|editor|checker|detector|calculator|translator|"
    r"downloader|remover|changer|enhancer|upscaler|extractor|analyzer|tracker|planner|builder|viewer|"
    r"tester|finder|counter|solver|template|online|tool|app|humanizer|summarizer|transcriber|"
    r"paraphraser|rewriter|resizer|compressor|cropper|merger|splitter|recorder|picker|randomizer|"
    r"spinner|wheel|font|emoji|sticker|wallpaper|coloring|logo|icon)\b", re.I)
GAME_WORDS = re.compile(
    r"\b(game|games|roblox|minecraft|fortnite|pokemon|genshin|steam|codes?|tycoon|obby|tier list|"
    r"wiki|mod|mods|skin|skins|simulator|wordle|puzzle|crossword|speedrun|walkthrough|dlc|"
    r"release date|early access|demo|build|builds|patch)\b", re.I)


AI_MEDIA = re.compile(
    r"\b(video|videos|image|images|photo|photos|picture|pic|pics|art|anime|cartoon|avatar|headshot|portrait|"
    r"face swap|filter|edit|editor|upscal\w*|background|dance|hug|kiss|baby|tattoo|hairstyle|sticker|"
    r"veo|kling|seedance|sora|hailuo|pixverse|viggle|higgsfield|nano banana|midjourney|flux|seedream|"
    r"dreamina|vidu|krea|hedra|runway|pika|luma|wan|qwen image|gpt image|grok imagine|imagine|text to|image to)\b",
    re.I)
# 攻略类意图（不做）：兑换码、wiki、tier list、攻略、mod、皮肤……
GAME_GUIDE = re.compile(
    r"\b(codes?|wiki|tier list|walkthrough|mods?|skins?|dlc|patch|release date|builds?|guide|map|trello|discord|"
    r"cheats?|script|values?|trading)\b", re.I)
# 游戏名 / 游戏平台：本身不代表攻略意图，从这些词根挖出来的新名字多半是新游戏
GAME_FRANCHISE = re.compile(
    r"\b(roblox|minecraft|fortnite|pokemon|pok[eé]|genshin|steam|nintendo|zelda|mario|sonic|"
    r"game|games|survivor|survivors|rpg|roguelike|roguelite)\b", re.I)
SMALL_GAME = re.compile(
    r"\b(game|games|unblocked|io|play|playable|browser|puzzle|clicker|idle|simulator|tycoon|"
    r"arcade|runner|merge|solitaire|sudoku|quiz|trivia|html5|online game|2 player)\b", re.I)

# 查询顺序：AI 视频/图片 > 其他 AI 工具 > 工具站 > 小游戏 > 从 AI 词根挖出来的其他词 > 其他 > 游戏攻略类
TAG_PRIORITY = {"AI 视频/图片": 0, "AI 工具": 1, "工具站": 2, "小游戏": 3,
                "AI 相关（词根）": 4, "其他": 5, "游戏攻略": 6}


def tag(kw, path):
    if AI_WORDS.search(kw):
        return "AI 视频/图片" if AI_MEDIA.search(kw) else "AI 工具"
    if GAME_GUIDE.search(kw):
        return "游戏攻略"
    if SMALL_GAME.search(kw) or GAME_FRANCHISE.search(kw):
        return "小游戏"
    if TOOL_WORDS.search(kw):
        return "工具站"
    path_text = " ".join(path or [])
    if AI_WORDS.search(path_text):
        return "AI 相关（词根）"
    if GAME_FRANCHISE.search(path_text) or SMALL_GAME.search(path_text):
        return "小游戏"  # 从游戏词根挖出来的新名字（例如 pokemon › pokesurvivor），多半是新游戏
    return "其他"
