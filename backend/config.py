import os
import json
import base64
from pathlib import Path

# ====== Platform Info ======
PLATFORM_NAME = "旭星-YouTube热点库"
PLATFORM_SUBTITLE = "热点内容追踪 & 创作者库"
PRIMARY_COLOR = "#00c853"        # 旭星绿 - 明亮清新
PRIMARY_DARK = "#00a844"          # 深绿色
PRIMARY_LIGHT = "#f0fdf4"         # 极浅绿色背景
BG_COLOR = "#f8fcf9"              # 整体浅绿白背景
ACCENT_COLOR = "#00e676"          # accent亮绿色
SIDEBAR_COLOR = "#fcfffb"         # 侧边栏近白色
SIDEBAR_GRAD = "linear-gradient(180deg, #fcfffb 0%, #f8fcf9 100%)"  # 侧边栏极浅渐变

# 区域标签
REGION_TAGS = ["欧区", "美区"]

# 语言选项
LANGUAGE_OPTIONS = ["英语", "日语", "中文", "韩语", "法语", "德语", "西班牙语", "葡萄牙语", "俄语", "其他"]

# ====== Configuration ======
# YouTube API Key - 优先从环境变量读取（云端部署用）
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyD7NY23Pvw3AlBydd47O5EHnvfDqvsViVg")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# GitHub 数据持久化配置（云端部署用，本地开发自动跳过）
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # 格式: owner/repo
GITHUB_BRANCH = os.environ.get("GITHUB_DATA_BRANCH", "main")
_IS_CLOUD = bool(GITHUB_TOKEN and GITHUB_REPO)

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"

# Data files
CREATORS_DB_FILE = DATA_DIR / "creators.json"
MANAGED_CREATORS_DB_FILE = DATA_DIR / "managed_creators.json"  # 在管创作者库
TRENDING_VIDEOS_FILE = DATA_DIR / "trending_videos.json"
MANUAL_VIDEOS_FILE = DATA_DIR / "manual_videos.json"
STATS_HISTORY_FILE = DATA_DIR / "stats_history.json"
REFRESH_LOG_FILE = DATA_DIR / "refresh_log.json"
ADMINS_FILE = DATA_DIR / "admins.json"

# 所有数据文件列表（用于启动时同步）
ALL_DATA_FILES = [
    "creators.json",
    "managed_creators.json",
    "trending_videos.json",
    "manual_videos.json",
    "stats_history.json",
    "refresh_log.json",
    "admins.json",
]

# Search keywords for Genshin Impact content
SEARCH_KEYWORDS = [
    "Genshin Impact",
    "Genshin Impact guide",
    "Genshin Impact gameplay",
    "原神",
    "Genshin Impact new character",
    "Genshin Impact tier list",
    "Genshin Impact trailer",
    "Genshin Impact OST",
]

# 一级标签：内容方向（来自附图）
PRIMARY_TAGS = [
    "资讯", "反应", "攻略", "玩法", "杂谈", "剪辑", "二创", "其他才艺"
]

# 二级标签：内容细分（来自附图）
SECONDARY_TAGS = [
    "内容反应", "新闻简讯", "游戏试玩", "角色攻略", "深渊攻略", "大世界收集",
    "养成挑战", "尘歌壶搭建", "特殊命题挑战", "设定解析", "美术、音乐赏析",
    "杂谈/吐槽", "排行", "AMV(现有素材)", "EXE/ネタ", "彩蛋挖掘", "摄影", "填词",
    "插画", "MMD", "AMV(原创素材)", "cosplay"
]

# Number of results per search query
SEARCH_RESULTS_PER_QUERY = 15
MAX_TRENDING_VIDEOS = 200
MAX_CREATORS = 100

# Daily refresh time (for display & scheduling reference)
DAILY_REFRESH_HOUR = 10
DAILY_REFRESH_MINUTE = 20

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ====== GitHub Data Persistence (Cloud Deployment) ======

def _github_api(method, path, payload=None):
    """Call GitHub Contents API. Returns response object or None."""
    import requests
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    params = {"ref": GITHUB_BRANCH}
    try:
        resp = requests.request(method, url, headers=headers, params=params, json=payload, timeout=30)
        return resp
    except Exception as e:
        print(f"GitHub API error ({method} {path}): {e}")
        return None


def _github_upload(filename, content_bytes):
    """Create or update a file on GitHub via Contents API."""
    # Get existing file SHA (needed for updates)
    resp = _github_api("GET", f"data/{filename}")
    sha = None
    if resp and resp.status_code == 200:
        sha = resp.json().get("sha")

    payload = {
        "message": f"auto-sync: update {filename}",
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = _github_api("PUT", f"data/{filename}", payload)
    if resp and resp.status_code in (200, 201):
        return True
    status = resp.status_code if resp else "no response"
    print(f"GitHub upload failed for {filename}: {status}")
    return False


def _github_download(filename):
    """Download file content from GitHub. Returns bytes or None."""
    resp = _github_api("GET", f"data/{filename}")
    if resp and resp.status_code == 200:
        content = resp.json().get("content", "")
        if content:
            return base64.b64decode(content)
    return None


def sync_all_data_from_github():
    """Pull all data files from GitHub to local filesystem. Called at startup."""
    if not _IS_CLOUD:
        return
    print("[Cloud] Syncing data from GitHub...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ALL_DATA_FILES:
        filepath = DATA_DIR / filename
        content = _github_download(filename)
        if content:
            with open(filepath, "wb") as f:
                f.write(content)
            print(f"  [OK] {filename}")
        else:
            print(f"  [SKIP] {filename} not found on GitHub")
    print("[Cloud] Data sync complete.")


def load_json(filepath, default=None):
    """Load JSON data from file. In cloud mode, falls back to GitHub if local file missing."""
    if default is None:
        default = []
    try:
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")

    # Local file missing or corrupt — try GitHub
    if _IS_CLOUD:
        content = _github_download(filepath.name)
        if content:
            try:
                data = json.loads(content.decode("utf-8"))
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
            except Exception as e:
                print(f"Error parsing GitHub data for {filepath.name}: {e}")

    return default


def save_json(filepath, data):
    """Save JSON data to local file. In cloud mode, also syncs to GitHub."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
        return False

    # Cloud mode: push to GitHub (best-effort, non-blocking on failure)
    if _IS_CLOUD:
        try:
            content_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            _github_upload(filepath.name, content_bytes)
        except Exception as e:
            print(f"GitHub sync error for {filepath.name}: {e}")

    return True
