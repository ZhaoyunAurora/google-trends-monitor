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


def tag(kw, roots):
    text = kw + " " + " ".join(roots)
    if AI_WORDS.search(kw):
        return "AI 工具/模型/玩法"
    if GAME_WORDS.search(kw):
        return "游戏"
    if TOOL_WORDS.search(kw):
        return "工具站需求"
    if AI_WORDS.search(text):
        return "AI 相关（词根）"
    return "其他"
