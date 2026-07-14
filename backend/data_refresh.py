"""
Data refresh module - fetches latest trending videos and creator stats from YouTube API
"""
import datetime
import time
import json
from youtube_api import YouTubeAPI, format_video_data, format_channel_data
from config import (
    load_json, save_json,
    SEARCH_KEYWORDS, SEARCH_RESULTS_PER_QUERY, MAX_TRENDING_VIDEOS,
    TRENDING_VIDEOS_FILE, CREATORS_DB_FILE, MANAGED_CREATORS_DB_FILE,
    STATS_HISTORY_FILE, REFRESH_LOG_FILE, MANUAL_VIDEOS_FILE,
    DAILY_REFRESH_HOUR, DAILY_REFRESH_MINUTE
)


# ====== Language Detection ======

def detect_language(creator):
    """Detect language from channel country, description, and keywords"""
    country = (creator.get('country', '') or '').upper()
    desc = (creator.get('description', '') or '').lower()
    keywords = (creator.get('keywords', '') or '').lower()
    text = desc + ' ' + keywords

    # Country-based detection
    country_lang_map = {
        'US': '英语', 'GB': '英语', 'CA': '英语', 'AU': '英语', 'IE': '英语',
        'JP': '日语', 'KR': '韩语', 'CN': '中文', 'TW': '中文', 'HK': '中文',
        'FR': '法语', 'DE': '德语', 'ES': '西班牙语', 'MX': '西班牙语', 'AR': '西班牙语',
        'BR': '葡萄牙语', 'PT': '葡萄牙语', 'RU': '俄语',
    }
    if country in country_lang_map:
        return country_lang_map[country]

    # Text-based detection
    if any(k in text for k in ['english', 'en ', 'hello', 'welcome']):
        return '英语'
    if any(k in text for k in ['日本語', 'こんにちは', 'チャンネル', '動画']):
        return '日语'
    if any(k in text for k in ['中文', '你好', '频道', '视频', '原神']):
        return '中文'
    if any(k in text for k in ['한국', '안녕', '채널']):
        return '韩语'
    if any(k in text for k in ['français', 'bonjour', 'chaîne']):
        return '法语'
    if any(k in text for k in ['deutsch', 'hallo', 'kanal']):
        return '德语'
    if any(k in text for k in ['español', 'hola', 'canal']):
        return '西班牙语'
    if any(k in text for k in ['português', 'olá', 'canal']):
        return '葡萄牙语'

    return '英语'  # Default to English for overseas content


def detect_region(creator):
    """Detect region tag from country code or description keywords"""
    country = (creator.get('country', '') or '').upper()
    eu_countries = {'GB', 'FR', 'DE', 'ES', 'IT', 'NL', 'PL', 'SE', 'NO', 'FI', 'DK', 'BE', 'AT', 'CH', 'IE', 'PT', 'GR', 'CZ', 'RO', 'HU'}
    us_countries = {'US', 'CA', 'MX', 'BR', 'AR', 'CO', 'CL', 'PE'}
    asia_countries = {'JP', 'KR', 'CN', 'TW', 'HK', 'TH', 'VN', 'ID', 'PH', 'MY', 'SG', 'IN'}

    if country in eu_countries:
        return '欧区'
    elif country in us_countries:
        return '美区'
    elif country in asia_countries:
        return '亚区'

    # Fallback: detect from description/title keywords
    text = ' '.join(filter(None, [
        creator.get('title', ''),
        creator.get('description', ''),
        creator.get('keywords', '')
    ])).lower()

    # European keywords
    eu_keywords = ['europe', 'european', 'uk ', 'british', 'england', 'german', 'french',
                   'deutsch', 'francais', 'français', 'español', 'spanish', 'italian',
                   'italia', 'netherlands', 'dutch', 'polish', 'polska', 'swedish',
                   'nordic', 'scandinavi']
    # American keywords
    us_keywords = ['american', 'america', 'usa', 'united states', 'canada', 'canadian',
                   'mexico', 'mexican', 'brazil', 'brazilian', 'brasil', 'latino',
                   'latin america', 'argentina', 'argentinian']
    # Asian keywords
    asia_keywords = ['japan', 'japanese', 'korea', 'korean', 'china', 'chinese',
                     'taiwan', 'thailand', 'thai', 'vietnam', 'vietnamese',
                     'indonesia', 'filipino', 'philippines', 'malaysia']

    if any(k in text for k in eu_keywords):
        return '欧区'
    if any(k in text for k in us_keywords):
        return '美区'
    if any(k in text for k in asia_keywords):
        return '亚区'

    return '其他'


# ====== Tag Classification ======

def classify_creator_tags(creator):
    """Auto classify creator with primary and secondary tags based on content"""
    text = ' '.join(filter(None, [
        creator.get('title', ''),
        creator.get('description', ''),
        creator.get('keywords', ''),
        ' '.join(creator.get('tags', []))
    ])).lower()

    primary_tags = []
    secondary_tags = []

    # 一级标签
    if any(k in text for k in ['news', 'new', 'latest', 'update', 'patch', '版本', '资讯', '新聞']):
        primary_tags.append('资讯')
    if any(k in text for k in ['reaction', 'react', '反应', 'reaccion', 'reazioni']):
        primary_tags.append('反应')
    if any(k in text for k in ['guide', 'build', 'tips', 'how to', 'tutorial', '攻略', '指南', 'builds']):
        primary_tags.append('攻略')
    if any(k in text for k in ['gameplay', 'play', 'game', 'live', 'stream', '玩法', 'プレイ']):
        primary_tags.append('玩法')
    if any(k in text for k in ['talk', 'discussion', 'lore', 'theory', 'story', '杂谈', '談話']):
        primary_tags.append('杂谈')
    if any(k in text for k in ['edit', 'clip', 'amv', 'mmd', '剪辑', '編集', 'meme', 'exe']):
        primary_tags.append('剪辑')
    if any(k in text for k in ['fan', 'cosplay', 'art', 'manga', 'drawing', '二创', 'fanart', 'illust', '創作']):
        primary_tags.append('二创')
    if any(k in text for k in ['talent', 'song', 'music', 'sing', 'dance', '才艺', '音楽', '歌', '踊']):
        primary_tags.append('其他才艺')

    if not primary_tags:
        primary_tags.append('杂谈')

    # 二级标签
    if any(k in text for k in ['reaction', 'react', '反应']):
        secondary_tags.append('内容反应')
    if any(k in text for k in ['news', 'new', 'latest', 'update', 'patch', '资讯', '新聞']):
        secondary_tags.append('新闻简讯')
    if any(k in text for k in ['demo', 'test', 'try', 'trial', '试玩', '体験']):
        secondary_tags.append('游戏试玩')
    if any(k in text for k in ['character', 'build', 'weapon', 'artifact', '角色', 'build guide']):
        secondary_tags.append('角色攻略')
    if any(k in text for k in ['abyss', 'spiral', 'meta', '深渊', '螺旋', '深淵']):
        secondary_tags.append('深渊攻略')
    if any(k in text for k in ['explore', 'collect', 'chest', 'world', 'map', '收集', '探索']):
        secondary_tags.append('大世界收集')
    if any(k in text for k in ['farm', 'grind', 'level up', 'ascension', 'talent', '养成', '育成']):
        secondary_tags.append('养成挑战')
    if any(k in text for k in ['serenitea', 'teapot', '尘歌壶', '壺', 'housing']):
        secondary_tags.append('尘歌壶搭建')
    if any(k in text for k in ['challenge', 'event', '命题', '挑战', 'イベント']):
        secondary_tags.append('特殊命题挑战')
    if any(k in text for k in ['lore', 'story', 'theory', 'analysis', '设定', '解析']):
        secondary_tags.append('设定解析')
    if any(k in text for k in ['music', 'ost', 'soundtrack', 'art', '美术', '音楽', '楽曲']):
        secondary_tags.append('美术、音乐赏析')
    if any(k in text for k in ['rant', 'opinion', 'talk', '吐槽', '杂谈']):
        secondary_tags.append('杂谈/吐槽')
    if any(k in text for k in ['tier list', 'ranking', 'top', '排行', 'ランキング']):
        secondary_tags.append('排行')
    if any(k in text for k in ['amv', 'gmv', 'edit']):
        if any(k in text for k in ['original', 'original song', '原创']):
            secondary_tags.append('AMV(原创素材)')
        else:
            secondary_tags.append('AMV(现有素材)')
    if any(k in text for k in ['meme', 'exe', 'ネタ', '搞笑', 'funny']):
        secondary_tags.append('EXE/ネタ')
    if any(k in text for k in ['easter egg', 'secret', '彩蛋', 'hidden']):
        secondary_tags.append('彩蛋挖掘')
    if any(k in text for k in ['photo', 'photography', 'screenshot', '摄影', '写真']):
        secondary_tags.append('摄影')
    if any(k in text for k in ['lyric', 'cover', '填词', 'song cover', '歌って']):
        secondary_tags.append('填词')
    if any(k in text for k in ['illustration', 'drawing', 'paint', '插画', 'イラスト']):
        secondary_tags.append('插画')
    if any(k in text for k in ['mmd', 'miku miku dance', '3d dance']):
        secondary_tags.append('MMD')
    if any(k in text for k in ['cosplay', 'コスプレ']):
        secondary_tags.append('cosplay')

    if not secondary_tags:
        secondary_tags.append('杂谈/吐槽')

    return primary_tags[:3], secondary_tags[:5]


# ====== Deduplication ======

def deduplicate_libraries():
    """Ensure managed creators don't appear in reserve library"""
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    managed_ids = {c.get('channel_id') for c in managed}

    original_count = len(reserve)
    reserve = [c for c in reserve if c.get('channel_id') not in managed_ids]
    removed = original_count - len(reserve)

    if removed > 0:
        save_json(CREATORS_DB_FILE, reserve)
        print(f"  Dedup: removed {removed} creators from reserve (already in managed)")

    return removed


# ====== Video Refresh ======

def refresh_trending_videos(api):
    """Fetch latest trending Genshin Impact videos from YouTube"""
    print(">>> Refreshing trending videos...")
    all_videos = {}
    published_after = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat() + "Z"

    # Save previous view counts for daily growth tracking
    existing = load_json(TRENDING_VIDEOS_FILE)
    prev_views = {}
    for v in existing:
        vid = v.get('video_id', '')
        if vid and 'view_count' in v:
            prev_views[vid] = v['view_count']

    for keyword in SEARCH_KEYWORDS:
        print(f"  Searching: {keyword}")
        result = api.search_videos(
            query=keyword,
            max_results=SEARCH_RESULTS_PER_QUERY,
            order="viewCount",
            published_after=published_after
        )

        if 'error' in result:
            print(f"  [ERROR] {result.get('message', 'Unknown error')}")
            if result.get('error') == 'quota_exceeded':
                break
            continue

        video_ids = []
        for item in result.get('items', []):
            vid = item.get('id', {}).get('videoId', '')
            if vid:
                all_videos[vid] = {'search_keyword': keyword}
                video_ids.append(vid)

        if video_ids:
            details = api.get_video_details(video_ids)
            for v in details.get('items', []):
                vid = v.get('id', '')
                if vid:
                    # Filter: must be Genshin related
                    title = (v.get('snippet', {}).get('title', '') or '')
                    desc = (v.get('snippet', {}).get('description', '') or '')
                    tags = (v.get('snippet', {}).get('tags', []) or [])
                    search_context = all_videos.get(vid, {}).get('search_keyword', '')
                    combined_text = f"{title} {desc} {' '.join(tags)} {search_context}"
                    if not is_genshin_related(combined_text):
                        print(f"  Skipping non-Genshin video: {title[:60]}...")
                        continue

                    formatted = format_video_data(v)
                    formatted['search_keyword'] = all_videos.get(vid, {}).get('search_keyword', '')
                    # Track daily view growth
                    if vid in prev_views:
                        formatted['previous_view_count'] = prev_views[vid]
                        formatted['view_growth'] = formatted['view_count'] - prev_views[vid]
                    else:
                        formatted['previous_view_count'] = 0
                        formatted['view_growth'] = 0
                    all_videos[vid] = formatted

        time.sleep(0.3)

    video_list = [v for v in all_videos.values() if 'video_id' in v]
    video_list.sort(key=lambda x: x.get('view_count', 0), reverse=True)
    video_list = video_list[:MAX_TRENDING_VIDEOS]

    # Merge with existing manual additions
    existing_ids = {v.get('video_id') for v in video_list}
    manual_videos = load_json(MANUAL_VIDEOS_FILE)
    for mv in manual_videos:
        if mv.get('video_id') not in existing_ids:
            video_list.append(mv)

    save_json(TRENDING_VIDEOS_FILE, video_list)
    print(f"  Saved {len(video_list)} trending videos")
    return video_list


# ====== Creator Refresh ======

def refresh_creator_stats(api):
    """Refresh statistics for all tracked creators (reserve + managed)"""
    print(">>> Refreshing creator stats...")

    # Deduplicate first
    deduplicate_libraries()

    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)

    all_creators = reserve + managed
    if not all_creators:
        print("  No creators to refresh")
        return reserve, managed

    channel_ids = [c.get('channel_id') for c in all_creators if c.get('channel_id')]
    if not channel_ids:
        return reserve, managed

    details = api.get_channel_details(channel_ids)
    channel_map = {c.get('id'): c for c in details.get('items', [])}

    updated_reserve = 0
    updated_managed = 0

    for creator in reserve:
        cid = creator.get('channel_id', '')
        if cid in channel_map:
            fresh = format_channel_data(channel_map[cid])
            # Preserve existing fields
            for key in ['is_managed', 'is_manual', 'notes', 'is_tracked', 'added_at',
                        'tags', 'primary_tags', 'secondary_tags', 'discovered_videos',
                        'discovered_total_views', 'region_tag', 'language', 'custom_notes']:
                if key in creator:
                    fresh[key] = creator[key]
            # Auto-detect language and region if not set
            if 'language' not in fresh or not fresh.get('language'):
                fresh['language'] = detect_language(fresh)
            if 'region_tag' not in fresh or not fresh.get('region_tag'):
                fresh['region_tag'] = detect_region(fresh)
            # Store previous stats for daily change calculation
            fresh['prev_subscriber_count'] = creator.get('subscriber_count', 0)
            fresh['prev_view_count'] = creator.get('view_count', 0)
            fresh['prev_video_count'] = creator.get('video_count', 0)
            # Calculate daily change
            fresh['daily_sub_change'] = fresh.get('subscriber_count', 0) - creator.get('subscriber_count', 0)
            fresh['daily_view_change'] = fresh.get('view_count', 0) - creator.get('view_count', 0)
            creator.update(fresh)
            updated_reserve += 1

    for creator in managed:
        cid = creator.get('channel_id', '')
        if cid in channel_map:
            fresh = format_channel_data(channel_map[cid])
            for key in ['is_managed', 'is_manual', 'notes', 'added_at', 'tags',
                        'primary_tags', 'secondary_tags', 'region_tag', 'language', 'custom_notes']:
                if key in creator:
                    fresh[key] = creator[key]
            fresh['is_managed'] = True
            if 'language' not in fresh or not fresh.get('language'):
                fresh['language'] = detect_language(fresh)
            if 'region_tag' not in fresh or not fresh.get('region_tag'):
                fresh['region_tag'] = detect_region(fresh)
            # Store previous stats for daily change calculation
            fresh['prev_subscriber_count'] = creator.get('subscriber_count', 0)
            fresh['prev_view_count'] = creator.get('view_count', 0)
            fresh['prev_video_count'] = creator.get('video_count', 0)
            # Calculate daily change
            fresh['daily_sub_change'] = fresh.get('subscriber_count', 0) - creator.get('subscriber_count', 0)
            fresh['daily_view_change'] = fresh.get('view_count', 0) - creator.get('view_count', 0)
            creator.update(fresh)
            updated_managed += 1

    save_json(CREATORS_DB_FILE, reserve)
    save_json(MANAGED_CREATORS_DB_FILE, managed)
    print(f"  Updated {updated_reserve} reserve, {updated_managed} managed creators")
    return reserve, managed


# ====== Fetch Latest Videos for Managed Creators ======

def fetch_managed_latest_videos(api):
    """Fetch latest videos for all managed creators"""
    print(">>> Fetching latest videos for managed creators...")
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    if not managed:
        return {}

    latest_videos_map = {}
    for creator in managed:
        cid = creator.get('channel_id', '')
        if not cid:
            continue
        try:
            result = api.get_channel_videos(cid, max_results=5)
            videos = []
            for item in result.get('items', []):
                vid = item.get('contentDetails', {}).get('videoId', '')
                if vid:
                    videos.append({
                        'video_id': vid,
                        'title': item.get('snippet', {}).get('title', ''),
                        'published_at': item.get('snippet', {}).get('publishedAt', ''),
                        'thumbnail': item.get('snippet', {}).get('thumbnails', {}).get('medium', {}).get('url', ''),
                    })
            latest_videos_map[cid] = videos
            time.sleep(0.2)
        except Exception as e:
            print(f"  Error fetching videos for {cid}: {e}")
            latest_videos_map[cid] = []

    print(f"  Fetched latest videos for {len(latest_videos_map)} managed creators")
    return latest_videos_map


# ====== Stats Snapshot ======

def save_stats_snapshot(creators, managed_creators, videos):
    """Save a snapshot of current stats for trend analysis"""
    history = load_json(STATS_HISTORY_FILE, [])

    all_creators = creators + managed_creators

    # Calculate tag distribution for reserve creators
    reserve_tag_dist = {}
    for c in creators:
        for t in c.get('primary_tags', []):
            reserve_tag_dist[t] = reserve_tag_dist.get(t, 0) + 1

    snapshot = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.datetime.now().isoformat(),
        "total_videos": len(videos),
        "total_creators": len(all_creators),
        "total_reserve": len(creators),
        "total_managed": len(managed_creators),
        "reserve_tag_distribution": reserve_tag_dist,
        "top_videos": [
            {
                "video_id": v.get('video_id', ''),
                "title": v.get('title', '')[:80],
                "channel_title": v.get('channel_title', ''),
                "view_count": v.get('view_count', 0),
                "like_count": v.get('like_count', 0),
            }
            for v in videos[:10]
        ],
        "top_creators": [
            {
                "channel_id": c.get('channel_id', ''),
                "title": c.get('title', ''),
                "subscriber_count": c.get('subscriber_count', 0),
                "view_count": c.get('view_count', 0),
                "video_count": c.get('video_count', 0),
            }
            for c in sorted(all_creators, key=lambda x: x.get('subscriber_count', 0), reverse=True)[:10]
        ],
        "creator_snapshots": [
            {
                "channel_id": c.get('channel_id', ''),
                "title": c.get('title', ''),
                "subscriber_count": c.get('subscriber_count', 0),
                "view_count": c.get('view_count', 0),
                "video_count": c.get('video_count', 0),
                "primary_tags": c.get('primary_tags', []),
                "language": c.get('language', ''),
                "region_tag": c.get('region_tag', ''),
            }
            for c in all_creators
        ],
        "managed_snapshots": [
            {
                "channel_id": c.get('channel_id', ''),
                "title": c.get('title', ''),
                "subscriber_count": c.get('subscriber_count', 0),
                "view_count": c.get('view_count', 0),
                "video_count": c.get('video_count', 0),
                "region_tag": c.get('region_tag', ''),
                "language": c.get('language', ''),
            }
            for c in managed_creators
        ],
        "reserve_creator_ids": [c.get('channel_id', '') for c in creators],
        "managed_creator_ids": [c.get('channel_id', '') for c in managed_creators],
    }
    history.append(snapshot)
    if len(history) > 365:
        history = history[-365:]
    save_json(STATS_HISTORY_FILE, history)
    print(f"  Stats snapshot saved for {snapshot['date']}")
    return snapshot


# ====== Refresh Log ======

def log_refresh(status, message, stats=None):
    """Log refresh activity"""
    log = load_json(REFRESH_LOG_FILE, [])
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": status,
        "message": message,
        "stats": stats or {}
    }
    log.append(entry)
    if len(log) > 100:
        log = log[-100:]
    save_json(REFRESH_LOG_FILE, log)


# ====== Full Refresh ======

def run_full_refresh():
    """Run a full data refresh cycle"""
    print(f"\n{'='*60}")
    print(f"旭星-YouTube热点库 - Data Refresh")
    print(f"Time: {datetime.datetime.now().isoformat()}")
    print(f"{'='*60}\n")

    api = YouTubeAPI()

    # 0. Deduplicate
    dedup_removed = deduplicate_libraries()

    # 1. Refresh trending videos
    videos = refresh_trending_videos(api)

    # 2. Refresh creator stats (reserve + managed)
    reserve, managed = refresh_creator_stats(api)

    # 3. Save stats snapshot
    snapshot = save_stats_snapshot(reserve, managed, videos)

    # 4. Log
    log_refresh("success", "Full refresh completed", {
        "videos_fetched": len(videos),
        "reserve_creators": len(reserve),
        "managed_creators": len(managed),
        "dedup_removed": dedup_removed
    })

    print(f"\n{'='*60}")
    print(f"Refresh completed successfully!")
    print(f"  - Videos: {len(videos)}")
    print(f"  - Reserve creators: {len(reserve)}")
    print(f"  - Managed creators: {len(managed)}")
    print(f"{'='*60}\n")

    return {
        "videos": len(videos),
        "reserve_creators": len(reserve),
        "managed_creators": len(managed),
        "dedup_removed": dedup_removed
    }


# ====== Discover New Creators ======

# ====== Genshin Impact Relevance Filter ======

GENSHIN_KEYWORDS = [
    'genshin', '原神', '원신', 'げんしん', 'mihoyo', 'hoyoverse', 'hoyolab'
]

BANNED_GAME_KEYWORDS = [
    'zenless', 'zone zero', 'zzz', 'honkai', '崩坏', '崩壊', 'star rail',
    'starrail', 'wuwa', 'wuthering', '鸣潮', '鳴潮', 'infinity nikki',
    'pokemon', 'pokémon', 'tears of the kingdom', 'botw', 'breath of the wild',
    'final fantasy', 'elden ring', 'black myth', 'call of duty', 'minecraft'
]

def is_banned_game(text):
    """Check if text is clearly about a non-Genshin game"""
    text_lower = (text or '').lower()
    return any(banned.lower() in text_lower for banned in BANNED_GAME_KEYWORDS)

def is_genshin_related(text):
    """Check if text is Genshin Impact related and not another game"""
    text_lower = (text or '').lower()
    has_genshin = any(kw.lower() in text_lower for kw in GENSHIN_KEYWORDS)
    if not has_genshin:
        return False
    if is_banned_game(text):
        return False
    return True


def is_official_channel(creator):
    """Check if a channel is an official/corporate channel (not individual creator)"""
    title = (creator.get('title', '') or '').lower()
    desc = (creator.get('description', '') or '').lower()

    # Official channel keywords
    official_keywords = [
        'genshin impact', '原神', 'hoyoverse', 'mihoyo', 'honkai',
        'official channel', 'official account', '公式', '公式チャンネル',
        'playstation', 'xbox', 'nintendo', 'ign', 'game spot', 'gamespot',
        'kotaku', 'polygon', 'eurogamer', 'rock paper shotgun',
        'twitch', 'youtube gaming', 'youtube originals',
    ]
    for kw in official_keywords:
        if kw in title:
            return True

    # Check if title contains "official" or "公式"
    if 'official' in title or '公式' in title:
        return True

    # Large media companies (high subs + media keywords in description)
    subs = creator.get('subscriber_count', 0)
    media_keywords = ['media', 'news', 'gaming news', 'entertainment', 'network', 'studio']
    if subs > 5000000 and any(kw in desc for kw in media_keywords):
        return True

    return False


def discover_creators_from_videos(api, top_n=5):
    """Discover new potential creators from trending videos and add to reserve library.

    Filtering rules:
    - Only Genshin Impact related creators
    - Only 美区 and 欧区 creators (English/European language)
    - Exclude official/corporate channels (only individual creators)
    - Good channel stats (subs > 5000 and total views > 500000) OR
      good recent video stats (latest video views > 10000)
    - Maximum 5 new creators per day
    """
    print(">>> Discovering new creators from trending videos...")
    videos = load_json(TRENDING_VIDEOS_FILE)
    existing_reserve = load_json(CREATORS_DB_FILE)
    existing_managed = load_json(MANAGED_CREATORS_DB_FILE)

    # Step 1: Clean existing reserve - remove banned-game, official channels, and non-US/EU
    cleaned_count = 0
    cleaned_reserve = []
    for c in existing_reserve:
        title = (c.get('title', '') or '')
        desc = (c.get('description', '') or '')
        keywords = ' '.join(c.get('tags', []) or [])
        combined = f"{title} {desc} {keywords}"

        if is_banned_game(combined):
            print(f"  Removing non-Genshin game creator from reserve: {c.get('title', '')}")
            cleaned_count += 1
            continue
        if is_official_channel(c):
            print(f"  Removing official channel from reserve: {c.get('title', '')}")
            cleaned_count += 1
            continue
        region = c.get('region_tag', '')
        if region and region not in ('美区', '欧区'):
            print(f"  Removing non-US/EU creator from reserve: {c.get('title', '')} ({region})")
            cleaned_count += 1
            continue
        cleaned_reserve.append(c)

    if cleaned_count > 0:
        save_json(CREATORS_DB_FILE, cleaned_reserve)
        print(f"  Cleaned {cleaned_count} entries from reserve (banned-game/official/non-US-EU)")

    existing_reserve = cleaned_reserve

    # Deduplicate: ensure managed creators don't appear in reserve
    managed_ids = {c.get('channel_id') for c in existing_managed}
    original_reserve_count = len(existing_reserve)
    existing_reserve = [c for c in existing_reserve if c.get('channel_id') not in managed_ids]
    if len(existing_reserve) < original_reserve_count:
        save_json(CREATORS_DB_FILE, existing_reserve)
        print(f"  Dedup: removed {original_reserve_count - len(existing_reserve)} from reserve")

    existing_ids = {c.get('channel_id') for c in existing_reserve + existing_managed}

    # Count videos per channel
    channel_counts = {}
    for v in videos:
        cid = v.get('channel_id', '')
        if cid and cid not in existing_ids:
            if cid not in channel_counts:
                channel_counts[cid] = {
                    'channel_id': cid,
                    'channel_title': v.get('channel_title', ''),
                    'video_count': 0,
                    'total_views': 0,
                    'video_ids': [],
                    'best_video_views': 0
                }
            channel_counts[cid]['video_count'] += 1
            channel_counts[cid]['total_views'] += v.get('view_count', 0)
            channel_counts[cid]['best_video_views'] = max(channel_counts[cid]['best_video_views'], v.get('view_count', 0))

    discovered = sorted(channel_counts.values(), key=lambda x: x['total_views'], reverse=True)
    # Get more candidates than needed, we'll filter
    top_discovered = discovered[:30]

    new_channel_ids = [d['channel_id'] for d in top_discovered]
    new_creators = []

    if new_channel_ids:
        details = api.get_channel_details(new_channel_ids)
        channel_map = {c.get('id'): c for c in details.get('items', [])}

        for d in top_discovered:
            if len(new_creators) >= top_n:
                break

            cid = d['channel_id']
            if cid not in channel_map:
                continue

            creator = format_channel_data(channel_map[cid])

            # Filter 1: Exclude banned-game channels
            title = (creator.get('title', '') or '')
            desc = (creator.get('description', '') or '')
            keywords = ' '.join(creator.get('keywords', []) or [])
            combined_text = f"{title} {desc} {keywords}"
            if is_banned_game(combined_text):
                print(f"  Skipping non-Genshin game creator: {creator.get('title', '')}")
                continue

            # Filter 2: Exclude official channels
            if is_official_channel(creator):
                print(f"  Skipping official channel: {creator.get('title', '')}")
                continue

            # Auto classify tags, language, region
            creator['primary_tags'], creator['secondary_tags'] = classify_creator_tags(creator)
            creator['language'] = detect_language(creator)
            creator['region_tag'] = detect_region(creator)

            # Filter 2: Only 美区 and 欧区
            if creator['region_tag'] not in ('美区', '欧区'):
                print(f"  Skipping non-US/EU creator: {creator.get('title', '')} ({creator['region_tag']})")
                continue

            # Filter 3: Good channel stats OR good recent video stats
            subs = creator.get('subscriber_count', 0)
            total_views = creator.get('view_count', 0)
            best_video_views = d['best_video_views']

            good_channel = subs >= 5000 and total_views >= 500000
            good_video = best_video_views >= 10000

            if not (good_channel or good_video):
                print(f"  Skipping low-stats creator: {creator.get('title', '')} (subs={subs}, views={total_views}, best_video={best_video_views})")
                continue

            # Passed all filters - add to reserve
            creator['is_manual'] = False
            creator['is_managed'] = False
            creator['added_at'] = datetime.datetime.now().isoformat()
            creator['discovered_videos'] = d['video_count']
            creator['discovered_total_views'] = d['total_views']
            creator['custom_notes'] = ''
            creator['tags'] = ['auto_discovered'] + creator['primary_tags'] + creator['secondary_tags']
            new_creators.append(creator)
            print(f"  ✓ Added to reserve: {creator.get('title', '')} (subs={subs}, region={creator['region_tag']})")

    if new_creators:
        all_creators = existing_reserve + new_creators
        save_json(CREATORS_DB_FILE, all_creators)
        print(f"  Discovered {len(new_creators)} new creators to reserve library")
        return new_creators

    print("  No new creators discovered (all filtered out)")
    return []


# ====== Dashboard Summary Report ======

def generate_dashboard_summary():
    """Generate daily summary report for dashboard"""
    videos = load_json(TRENDING_VIDEOS_FILE)
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    history = load_json(STATS_HISTORY_FILE, [])
    refresh_log = load_json(REFRESH_LOG_FILE, [])

    all_creators = reserve + managed
    total_views = sum(v.get('view_count', 0) for v in videos)
    total_likes = sum(v.get('like_count', 0) for v in videos)

    top_video = max(videos, key=lambda x: x.get('view_count', 0), default=None)
    top_managed = max(managed, key=lambda x: x.get('subscriber_count', 0), default=None)
    top_reserve = max(reserve, key=lambda x: x.get('subscriber_count', 0), default=None)
    sorted_reserve = sorted(reserve, key=lambda x: x.get('subscriber_count', 0), reverse=True)

    # Today's new additions - use added_at timestamps (more reliable than snapshot diffs)
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    today_new = {"videos": 0, "reserve": 0, "managed": 0}

    # Count creators added today
    for c in reserve:
        added = (c.get('added_at', '') or '')[:10]
        if added == today_str:
            today_new["reserve"] += 1
    for c in managed:
        added = (c.get('added_at', '') or '')[:10]
        if added == today_str:
            today_new["managed"] += 1

    # Count videos added today (from video published_at or manual add date)
    for v in videos:
        added = (v.get('added_at', '') or '')[:10]
        if added == today_str:
            today_new["videos"] += 1

    # Fallback: if added_at-based count is 0, try snapshot diff
    if today_new["reserve"] == 0 and today_new["managed"] == 0 and len(history) >= 2:
        today = history[-1]
        yesterday = history[-2]
        today_reserve_ids = set(today.get('reserve_creator_ids', []))
        yesterday_reserve_ids = set(yesterday.get('reserve_creator_ids', []))
        today_new["reserve"] = len(today_reserve_ids - yesterday_reserve_ids)
        today_managed_ids = set(today.get('managed_creator_ids', []))
        yesterday_managed_ids = set(yesterday.get('managed_creator_ids', []))
        today_new["managed"] = len(today_managed_ids - yesterday_managed_ids)

    # Weekly new additions - use added_at timestamps
    week_ago_str = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_new = {"videos": 0, "reserve": 0, "managed": 0}
    for c in reserve:
        added = (c.get('added_at', '') or '')[:10]
        if added and added >= week_ago_str:
            weekly_new["reserve"] += 1
    for c in managed:
        added = (c.get('added_at', '') or '')[:10]
        if added and added >= week_ago_str:
            weekly_new["managed"] += 1
    for v in videos:
        added = (v.get('added_at', '') or '')[:10]
        if added and added >= week_ago_str:
            weekly_new["videos"] += 1

    # Tag distribution for managed creators
    tag_dist = {}
    for c in managed:
        for t in c.get('primary_tags', []):
            tag_dist[t] = tag_dist.get(t, 0) + 1

    # Region distribution
    region_dist = {}
    for c in managed:
        r = c.get('region_tag', '其他')
        region_dist[r] = region_dist.get(r, 0) + 1

    last_refresh = refresh_log[-1] if refresh_log else None

    summary = {
        "report_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "total_videos": len(videos),
        "total_views": total_views,
        "total_likes": total_likes,
        "reserve_creators": len(reserve),
        "managed_creators": len(managed),
        "today_new": today_new,
        "weekly_new": weekly_new,
        "top_video": {
            "video_id": top_video.get('video_id', '') if top_video else '',
            "title": top_video.get('title', '')[:80] if top_video else '',
            "channel": top_video.get('channel_title', '') if top_video else '',
            "views": top_video.get('view_count', 0) if top_video else 0
        },
        "top_managed_creator": {
            "title": top_managed.get('title', '')[:80] if top_managed else '',
            "subscribers": top_managed.get('subscriber_count', 0) if top_managed else 0
        },
        "top_reserve_creator": {
            "title": top_reserve.get('title', '')[:80] if top_reserve else '',
            "subscribers": top_reserve.get('subscriber_count', 0) if top_reserve else 0
        },
        "top_reserve_creators": [{"title": c.get('title', '')[:80], "subscribers": c.get('subscriber_count', 0), "total_views": c.get('view_count', 0)} for c in sorted_reserve[:3]],
        "tag_distribution": tag_dist,
        "region_distribution": region_dist,
        "next_refresh_time": f"{DAILY_REFRESH_HOUR:02d}:{DAILY_REFRESH_MINUTE:02d}",
        "last_refresh": last_refresh
    }
    return summary


# ====== Trend Analysis: Weekly/Monthly New Reserve Creators ======

def add_months(source_date, months):
    """Add/subtract months from a date, returning the first day of the resulting month."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    return datetime.date(year, month, 1)


def _get_added_date(creator):
    """Extract the added date (date object) from a creator record, or None if unavailable."""
    added_raw = creator.get('added_at', '') or ''
    if not added_raw:
        return None
    try:
        if isinstance(added_raw, datetime.datetime):
            added_dt = added_raw
        else:
            added_dt = datetime.datetime.fromisoformat(str(added_raw).replace('Z', '+00:00'))
        return added_dt.date() if added_dt.tzinfo is None else added_dt.replace(tzinfo=None).date()
    except Exception:
        added_str = str(added_raw)[:10]
        if not added_str:
            return None
        try:
            return datetime.datetime.strptime(added_str, "%Y-%m-%d").date()
        except Exception:
            return None


def get_reserve_growth_analysis():
    """Analyze reserve creator growth: weekly and monthly new additions + channel type distribution"""
    history = load_json(STATS_HISTORY_FILE, [])
    reserve = load_json(CREATORS_DB_FILE)

    # Tag distribution from current reserve data
    tag_dist = {}
    for c in reserve:
        for t in c.get('primary_tags', []):
            tag_dist[t] = tag_dist.get(t, 0) + 1

    # Language distribution from current reserve
    lang_dist = {}
    for c in reserve:
        lang = c.get('language', '未知')
        lang_dist[lang] = lang_dist.get(lang, 0) + 1

    # Region distribution from current reserve
    region_dist = {}
    for c in reserve:
        r = c.get('region_tag', '其他')
        region_dist[r] = region_dist.get(r, 0) + 1

    # Weekly new creators - use ISO calendar weeks (Monday-start) for reliable totals
    # Show from the first week with data up to the current week
    now = datetime.datetime.now()
    today = now.date()
    current_week_start = today - datetime.timedelta(days=today.weekday())  # Monday of current week
    added_dates = [d for c in reserve if (d := _get_added_date(c))]
    if added_dates:
        earliest_date = min(added_dates)
        earliest_week_start = earliest_date - datetime.timedelta(days=earliest_date.weekday())
    else:
        earliest_week_start = current_week_start
    weekly_data = []
    week_cursor = earliest_week_start
    while week_cursor <= current_week_start:
        week_start = week_cursor
        week_end = week_start + datetime.timedelta(days=6)
        week_label = week_start.strftime("%Y-%m-%d")
        count = sum(1 for c in reserve if (d := _get_added_date(c)) and week_start <= d <= week_end)
        total_at_date = sum(1 for c in reserve if (d := _get_added_date(c)) and d <= week_end)
        weekly_data.append({
            "date": week_label,
            "new_creators": count,
            "total": total_at_date
        })
        week_cursor += datetime.timedelta(weeks=1)

    # Monthly new creators - use calendar months (1st day of month)
    # Show from the first month with data up to the current month
    current_month_first = today.replace(day=1)
    if added_dates:
        earliest_month_first = earliest_date.replace(day=1)
    else:
        earliest_month_first = current_month_first
    monthly_data = []
    month_cursor = earliest_month_first
    while month_cursor <= current_month_first:
        month_start = month_cursor
        month_end = add_months(month_start, 1) - datetime.timedelta(days=1)
        month_label = month_start.strftime("%Y-%m-%d")
        count = sum(1 for c in reserve if (d := _get_added_date(c)) and month_start <= d <= month_end)
        total_at_date = sum(1 for c in reserve if (d := _get_added_date(c)) and d <= month_end)
        monthly_data.append({
            "date": month_label,
            "new_creators": count,
            "total": total_at_date
        })
        month_cursor = add_months(month_cursor, 1)

    return {
        "weekly": weekly_data,
        "monthly": monthly_data,
        "tag_distribution": tag_dist,
        "language_distribution": lang_dist,
        "region_distribution": region_dist,
        "total_reserve": len(reserve)
    }


if __name__ == "__main__":
    run_full_refresh()
