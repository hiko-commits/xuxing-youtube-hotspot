"""
Flask backend API server for 旭星-YouTube热点库
"""
import os
import sys
import json
import datetime
from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    load_json, save_json,
    PLATFORM_NAME, PLATFORM_SUBTITLE, PRIMARY_COLOR, PRIMARY_DARK, PRIMARY_LIGHT, BG_COLOR,
    SIDEBAR_COLOR, SIDEBAR_GRAD, ACCENT_COLOR,
    CREATORS_DB_FILE, MANAGED_CREATORS_DB_FILE,
    TRENDING_VIDEOS_FILE, MANUAL_VIDEOS_FILE,
    STATS_HISTORY_FILE, REFRESH_LOG_FILE, FRONTEND_DIR,
    DATA_DIR, YOUTUBE_API_KEY, PRIMARY_TAGS, SECONDARY_TAGS,
    DAILY_REFRESH_HOUR, DAILY_REFRESH_MINUTE,
    REGION_TAGS, LANGUAGE_OPTIONS,
    sync_all_data_from_github
)
from youtube_api import YouTubeAPI, format_video_data, format_channel_data
from data_refresh import (
    run_full_refresh, discover_creators_from_videos, classify_creator_tags,
    deduplicate_libraries, detect_language, detect_region,
    fetch_managed_latest_videos, generate_dashboard_summary,
    get_reserve_growth_analysis
)
from admin import init_admins, get_admins, add_admin, remove_admin, is_admin, require_admin

app = Flask(__name__, static_folder=str(FRONTEND_DIR))
CORS(app)

api_client = YouTubeAPI()
init_admins()


# ====== Helper functions ======

def get_channel_id_from_input(channel_input):
    """Extract channel ID from various input formats"""
    channel_id = channel_input.strip()
    if 'youtube.com/channel/' in channel_input:
        channel_id = channel_input.split('youtube.com/channel/')[-1].split('/')[0].split('?')[0]
    elif 'youtube.com/@' in channel_input:
        handle = channel_input.split('youtube.com/@')[-1].split('/')[0].split('?')[0]
        result = api_client.search_channels(handle, max_results=1)
        if 'items' in result and result['items']:
            channel_id = result['items'][0].get('id', {}).get('channelId', '')
        else:
            return None
    elif 'youtube.com/c/' in channel_input or 'youtube.com/user/' in channel_input:
        name = channel_input.split('/')[-1].split('?')[0]
        result = api_client.search_channels(name, max_results=1)
        if 'items' in result and result['items']:
            channel_id = result['items'][0].get('id', {}).get('channelId', '')
        else:
            return None
    return channel_id


def get_admin_email():
    """Get admin email from request header"""
    return request.headers.get('X-Admin-Email', request.headers.get('x-admin-email', '')).strip()


def classify_creator_auto(creator):
    """Auto classify creator tags based on keywords"""
    return classify_creator_tags(creator)


# ====== Page serving ======

@app.route('/')
def index_redirect():
    """Redirect root to /starroad"""
    return redirect('/starroad')


@app.route('/starroad')
@app.route('/starroad/')
def starroad_index():
    """Serve the main platform page at /starroad"""
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


@app.route('/starroad/<path:path>')
def starroad_static(path):
    """Serve static files under /starroad"""
    return send_from_directory(str(FRONTEND_DIR), path)


@app.route('/<path:path>')
def static_files(path):
    """Serve static files from root"""
    if path.startswith('api/'):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(str(FRONTEND_DIR), path)


# ====== API: Config / Platform Info ======

@app.route('/api/config')
def platform_config():
    """Return platform configuration for frontend"""
    return jsonify({
        "name": PLATFORM_NAME,
        "subtitle": PLATFORM_SUBTITLE,
        "primary_color": PRIMARY_COLOR,
        "primary_dark": PRIMARY_DARK,
        "primary_light": PRIMARY_LIGHT,
        "bg_color": BG_COLOR,
        "sidebar_color": SIDEBAR_COLOR,
        "sidebar_grad": SIDEBAR_GRAD,
        "accent_color": ACCENT_COLOR,
        "primary_tags": PRIMARY_TAGS,
        "secondary_tags": SECONDARY_TAGS,
        "region_tags": REGION_TAGS,
        "language_options": LANGUAGE_OPTIONS,
        "daily_refresh_time": f"{DAILY_REFRESH_HOUR:02d}:{DAILY_REFRESH_MINUTE:02d}",
        "admin_email": get_admin_email(),
        "is_admin": is_admin(get_admin_email())
    })


# ====== API: Admin Authentication ======

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Check if email is admin"""
    data = request.json
    email = data.get('email', '').strip().lower()
    if is_admin(email):
        return jsonify({"success": True, "email": email, "is_admin": True})
    return jsonify({"success": False, "error": "该邮箱不是管理员"}), 401


@app.route('/api/admin/list')
@require_admin
def admin_list():
    """List all admin emails"""
    return jsonify({"admins": get_admins()})


@app.route('/api/admin/add', methods=['POST'])
@require_admin
def admin_add():
    """Add a new admin email"""
    data = request.json
    email = data.get('email', '').strip()
    if not email:
        return jsonify({"error": "Email required"}), 400
    if add_admin(email):
        return jsonify({"success": True, "admins": get_admins()})
    return jsonify({"error": "Admin already exists or invalid"}), 409


@app.route('/api/admin/remove', methods=['POST'])
@require_admin
def admin_remove():
    """Remove an admin email"""
    data = request.json
    email = data.get('email', '').strip()
    if not email:
        return jsonify({"error": "Email required"}), 400
    if remove_admin(email):
        return jsonify({"success": True, "admins": get_admins()})
    return jsonify({"error": "Cannot remove the last admin or admin not found"}), 400


# ====== API: Dashboard / Overview ======

@app.route('/api/dashboard')
def dashboard():
    """Get dashboard overview data"""
    videos = load_json(TRENDING_VIDEOS_FILE)
    creators = load_json(CREATORS_DB_FILE)  # 储备库
    managed_creators = load_json(MANAGED_CREATORS_DB_FILE)  # 在管库
    history = load_json(STATS_HISTORY_FILE, [])
    refresh_log = load_json(REFRESH_LOG_FILE, [])

    # Top 5 videos by views
    top_videos = sorted(videos, key=lambda x: x.get('view_count', 0), reverse=True)[:5]

    # Top 5 creators by subscribers (managed + reserve)
    all_creators = creators + managed_creators
    top_creators = sorted(all_creators, key=lambda x: x.get('subscriber_count', 0), reverse=True)[:5]

    # Latest refresh info
    last_refresh = refresh_log[-1] if refresh_log else None

    # Recent trend (last 7 days)
    recent_history = history[-7:] if len(history) >= 7 else history

    # Generate summary report
    summary = generate_dashboard_summary()

    return jsonify({
        "total_videos": len(videos),
        "total_reserve_creators": len(creators),
        "total_managed_creators": len(managed_creators),
        "last_refresh": last_refresh,
        "top_videos": top_videos,
        "top_creators": top_creators,
        "recent_trend": recent_history,
        "summary": summary
    })


# ====== API: Trending Videos ======

@app.route('/api/videos')
def get_videos():
    """Get trending videos with optional filters"""
    videos = load_json(TRENDING_VIDEOS_FILE)

    keyword = request.args.get('keyword', '')
    channel = request.args.get('channel', '')
    min_views = request.args.get('min_views', 0, type=int)
    sort_by = request.args.get('sort', 'view_count')
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    filtered = videos

    if keyword:
        kw_lower = keyword.lower()
        filtered = [v for v in filtered if kw_lower in v.get('title', '').lower() or kw_lower in v.get('channel_title', '').lower()]

    if channel:
        ch_lower = channel.lower()
        filtered = [v for v in filtered if ch_lower in v.get('channel_title', '').lower()]

    if min_views > 0:
        filtered = [v for v in filtered if v.get('view_count', 0) >= min_views]

    reverse = sort_by != 'published_at'
    if sort_by == 'published_at':
        filtered.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    else:
        filtered.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse)

    total = len(filtered)
    paginated = filtered[offset:offset+limit]

    return jsonify({
        "total": total,
        "videos": paginated,
        "offset": offset,
        "limit": limit
    })


@app.route('/api/videos/trending')
def get_trending_videos():
    """Get trending videos:
    1. all_videos: all stored videos for frontend sorting/pagination
    2. daily_growth: videos with highest daily view count growth
    """
    videos = load_json(TRENDING_VIDEOS_FILE)
    manual = load_json(MANUAL_VIDEOS_FILE)
    all_videos = videos + [mv for mv in manual if mv.get('video_id') not in {v.get('video_id') for v in videos}]

    # Sort all videos by view_count as default (frontend will re-sort)
    all_videos.sort(key=lambda x: x.get('view_count', 0), reverse=True)
    # Return up to 50 videos for the frontend to sort and paginate
    all_videos = all_videos[:50]

    # Daily growth: videos published within the last 7 days
    # For videos with growth data (seen in previous refresh), rank by view_growth
    # For new videos (first discovery, growth=0), estimate daily growth = view_count / days_since_publication
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    def _parse_published(v):
        pub = v.get('published_at', '')
        if not pub:
            return None
        try:
            return datetime.datetime.fromisoformat(str(pub).replace('Z', '+00:00'))
        except Exception:
            return None

    daily_growth = []
    for v in videos + manual:
        pub = _parse_published(v)
        if not pub or pub < one_week_ago:
            continue
        growth = v.get('view_growth', 0) or 0
        days_since = max((now_utc - pub).total_seconds() / 86400, 0.5)  # min 0.5 day
        if growth > 0:
            # Has actual growth data from previous refresh
            growth_score = growth
            v['_growth_type'] = 'measured'
        else:
            # New video, estimate daily growth rate
            growth_score = int(v.get('view_count', 0) / days_since)
            v['_growth_type'] = 'estimated'
            v['_days_since'] = round(days_since, 1)
        v['_growth_score'] = growth_score
        daily_growth.append(v)

    daily_growth.sort(key=lambda x: x.get('_growth_score', 0), reverse=True)
    daily_growth = daily_growth[:20]

    has_growth_data = len(daily_growth) > 0

    return jsonify({
        "all_videos": all_videos,
        "daily_growth": daily_growth,
        "has_growth_data": has_growth_data,
        "total_videos": len(videos + manual)
    })


@app.route('/api/videos/<video_id>')
def get_video_detail(video_id):
    """Get detailed info for a specific video"""
    videos = load_json(TRENDING_VIDEOS_FILE)
    manual = load_json(MANUAL_VIDEOS_FILE)

    for v in videos + manual:
        if v.get('video_id') == video_id:
            return jsonify(v)

    return jsonify({"error": "Video not found"}), 404


@app.route('/api/videos/add', methods=['POST'])
@require_admin
def add_manual_video():
    """Manually add a video to tracking (admin only)"""
    data = request.json
    video_url = data.get('video_url', '').strip()
    notes = data.get('notes', '')

    if not video_url:
        return jsonify({"error": "Video URL or ID is required"}), 400

    video_id = video_url
    if 'youtube.com/watch?v=' in video_url:
        video_id = video_url.split('watch?v=')[-1].split('&')[0]
    elif 'youtu.be/' in video_url:
        video_id = video_url.split('youtu.be/')[-1].split('?')[0]

    videos = load_json(TRENDING_VIDEOS_FILE)
    manual = load_json(MANUAL_VIDEOS_FILE)
    all_ids = {v.get('video_id') for v in videos + manual}

    if video_id in all_ids:
        return jsonify({"error": "Video already tracked"}), 409

    details = api_client.get_video_details([video_id])
    if 'items' not in details or not details['items']:
        return jsonify({"error": "Video not found on YouTube"}), 404

    video = format_video_data(details['items'][0])
    video['is_manual'] = True
    video['notes'] = notes
    video['added_at'] = datetime.datetime.now().isoformat()

    manual.append(video)
    save_json(MANUAL_VIDEOS_FILE, manual)

    return jsonify({"success": True, "video": video})


# ====== API: Reserve Creators (储备库) ======

@app.route('/api/creators/reserve')
def get_reserve_creators():
    """Get reserve creators (auto-discovered)"""
    creators = load_json(CREATORS_DB_FILE)

    # Deduplicate against managed
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    managed_ids = {c.get('channel_id') for c in managed}
    creators = [c for c in creators if c.get('channel_id') not in managed_ids]

    sort_by = request.args.get('sort', 'subscriber_count')
    tag = request.args.get('tag', '')
    secondary = request.args.get('secondary', '')
    region = request.args.get('region', '')
    language = request.args.get('language', '')
    keyword = request.args.get('keyword', '').lower()

    filtered = creators
    if tag:
        filtered = [c for c in filtered if tag in c.get('primary_tags', [])]
    if secondary:
        filtered = [c for c in filtered if secondary in c.get('secondary_tags', [])]
    if region:
        filtered = [c for c in filtered if c.get('region_tag', '') == region]
    if language:
        filtered = [c for c in filtered if c.get('language', '') == language]
    if keyword:
        filtered = [c for c in filtered if keyword in (c.get('title', '') + c.get('description', '')).lower()]

    if sort_by in ['subscriber_count', 'view_count', 'video_count']:
        filtered.sort(key=lambda x: x.get(sort_by, 0), reverse=True)

    return jsonify({
        "total": len(filtered),
        "creators": filtered
    })


@app.route('/api/creators/reserve/<channel_id>')
def get_reserve_creator_detail(channel_id):
    """Get reserve creator detail"""
    creators = load_json(CREATORS_DB_FILE)
    for c in creators:
        if c.get('channel_id') == channel_id:
            videos = load_json(TRENDING_VIDEOS_FILE)
            creator_videos = [v for v in videos if v.get('channel_id') == channel_id]
            return jsonify({**c, "recent_videos": creator_videos})
    return jsonify({"error": "Creator not found"}), 404


@app.route('/api/creators/reserve/<channel_id>', methods=['PUT'])
@require_admin
def update_reserve_creator(channel_id):
    """Update reserve creator notes/region/language (admin only)"""
    data = request.json
    reserve = load_json(CREATORS_DB_FILE)

    for c in reserve:
        if c.get('channel_id') == channel_id:
            if 'custom_notes' in data:
                c['custom_notes'] = data['custom_notes']
            if 'notes' in data:
                c['notes'] = data['notes']
            if 'region_tag' in data:
                c['region_tag'] = data['region_tag']
            if 'language' in data:
                c['language'] = data['language']
            if 'primary_tags' in data:
                c['primary_tags'] = data['primary_tags']
            if 'secondary_tags' in data:
                c['secondary_tags'] = data['secondary_tags']
            save_json(CREATORS_DB_FILE, reserve)
            return jsonify({"success": True, "creator": c})

    return jsonify({"error": "Creator not found in reserve library"}), 404


@app.route('/api/creators/reserve/add', methods=['POST'])
@require_admin
def add_reserve_creator():
    """Manually add a creator to the reserve library (admin only)"""
    data = request.json
    channel_input = data.get('channel_id', '').strip()
    notes = data.get('notes', '')
    custom_notes = data.get('custom_notes', '')
    primary_tags = data.get('primary_tags', [])
    secondary_tags = data.get('secondary_tags', [])
    region_tag = data.get('region_tag', '')
    language = data.get('language', '')

    if not channel_input:
        return jsonify({"error": "频道ID或链接不能为空"}), 400

    channel_id = get_channel_id_from_input(channel_input)
    if not channel_id:
        return jsonify({"error": "无法解析频道，请检查输入"}), 404

    # Check both databases
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    reserve_ids = {c.get('channel_id') for c in reserve}
    managed_ids = {c.get('channel_id') for c in managed}

    if channel_id in reserve_ids:
        return jsonify({"error": "该创作者已在储备库中", "channel_id": channel_id}), 409
    if channel_id in managed_ids:
        return jsonify({"error": "该创作者已在管库中，无法重复添加"}), 409

    # Fetch fresh details from YouTube
    details = api_client.get_channel_details([channel_id])
    if 'items' not in details or not details['items']:
        return jsonify({"error": "YouTube上未找到该频道"}), 404
    creator = format_channel_data(details['items'][0])

    # Auto-classify tags if not provided
    if not primary_tags:
        auto_primary, _ = classify_creator_auto(creator)
        primary_tags = auto_primary
    if not secondary_tags:
        _, auto_secondary = classify_creator_auto(creator)
        secondary_tags = auto_secondary

    # Auto-detect language and region if not provided
    if not language:
        language = detect_language(creator)
    if not region_tag:
        region_tag = detect_region(creator)

    creator['is_managed'] = False
    creator['is_manual'] = True
    creator['added_at'] = datetime.datetime.now().isoformat()
    creator['notes'] = notes
    creator['custom_notes'] = custom_notes
    creator['primary_tags'] = primary_tags
    creator['secondary_tags'] = secondary_tags
    creator['region_tag'] = region_tag
    creator['language'] = language
    creator['tags'] = ['reserve', 'manual'] + primary_tags + secondary_tags

    reserve.append(creator)
    save_json(CREATORS_DB_FILE, reserve)

    return jsonify({"success": True, "creator": creator})


@app.route('/api/creators/reserve/<channel_id>', methods=['DELETE'])
@require_admin
def remove_reserve_creator(channel_id):
    """Remove a reserve creator (admin only)"""
    reserve = load_json(CREATORS_DB_FILE)
    new_list = [c for c in reserve if c.get('channel_id') != channel_id]

    if len(new_list) == len(reserve):
        return jsonify({"error": "Creator not found"}), 404

    save_json(CREATORS_DB_FILE, new_list)
    return jsonify({"success": True})


# ====== API: Managed Creators (在管库) ======

@app.route('/api/creators/managed')
def get_managed_creators():
    """Get managed creators (manually added by admin)"""
    creators = load_json(MANAGED_CREATORS_DB_FILE)

    sort_by = request.args.get('sort', 'subscriber_count')
    tag = request.args.get('tag', '')
    secondary = request.args.get('secondary', '')
    region = request.args.get('region', '')
    language = request.args.get('language', '')
    keyword = request.args.get('keyword', '').lower()

    filtered = creators
    if tag:
        filtered = [c for c in filtered if tag in c.get('primary_tags', [])]
    if secondary:
        filtered = [c for c in filtered if secondary in c.get('secondary_tags', [])]
    if region:
        filtered = [c for c in filtered if c.get('region_tag', '') == region]
    if language:
        filtered = [c for c in filtered if c.get('language', '') == language]
    if keyword:
        filtered = [c for c in filtered if keyword in (c.get('title', '') + c.get('description', '')).lower()]

    if sort_by in ['subscriber_count', 'view_count', 'video_count']:
        filtered.sort(key=lambda x: x.get(sort_by, 0), reverse=True)

    return jsonify({
        "total": len(filtered),
        "creators": filtered
    })


@app.route('/api/creators/managed/<channel_id>')
def get_managed_creator_detail(channel_id):
    """Get managed creator detail"""
    creators = load_json(MANAGED_CREATORS_DB_FILE)
    for c in creators:
        if c.get('channel_id') == channel_id:
            videos = load_json(TRENDING_VIDEOS_FILE)
            creator_videos = [v for v in videos if v.get('channel_id') == channel_id]
            return jsonify({**c, "recent_videos": creator_videos})
    return jsonify({"error": "Creator not found"}), 404


@app.route('/api/creators/managed/<channel_id>/latest-videos')
def get_managed_latest_videos(channel_id):
    """Get latest videos for a managed creator (fetched live from YouTube)"""
    try:
        max_results = request.args.get('max_results', 5, type=int)
        result = api_client.get_channel_videos(channel_id, max_results=max_results)
        videos = []
        video_ids = []
        for item in result.get('items', []):
            vid = item.get('contentDetails', {}).get('videoId', '')
            if vid:
                video_ids.append(vid)
                videos.append({
                    'video_id': vid,
                    'title': item.get('snippet', {}).get('title', ''),
                    'published_at': item.get('snippet', {}).get('publishedAt', ''),
                    'thumbnail': item.get('snippet', {}).get('thumbnails', {}).get('medium', {}).get('url', ''),
                })

        # Get video statistics
        if video_ids:
            details = api_client.get_video_details(video_ids)
            detail_map = {v.get('id'): v for v in details.get('items', [])}
            for v in videos:
                d = detail_map.get(v['video_id'], {})
                stats = d.get('statistics', {})
                v['view_count'] = int(stats.get('viewCount', 0))
                v['like_count'] = int(stats.get('likeCount', 0))
                v['comment_count'] = int(stats.get('commentCount', 0))

        return jsonify({"videos": videos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ====== API: Add / Update / Promote / Remove Creators ======

@app.route('/api/creators/add', methods=['POST'])
@require_admin
def add_managed_creator():
    """Add a creator directly to managed creators (admin only)"""
    data = request.json
    channel_input = data.get('channel_id', '').strip()
    notes = data.get('notes', '')
    custom_notes = data.get('custom_notes', '')
    primary_tags = data.get('primary_tags', [])
    secondary_tags = data.get('secondary_tags', [])
    region_tag = data.get('region_tag', '')
    language = data.get('language', '')

    if not channel_input:
        return jsonify({"error": "Channel ID or URL is required"}), 400

    channel_id = get_channel_id_from_input(channel_input)
    if not channel_id:
        return jsonify({"error": "Could not resolve channel from input"}), 404

    # Check both databases
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    reserve_ids = {c.get('channel_id') for c in reserve}
    managed_ids = {c.get('channel_id') for c in managed}

    if channel_id in managed_ids:
        return jsonify({"error": "Creator already in managed library", "channel_id": channel_id}), 409

    # If already in reserve, move it
    if channel_id in reserve_ids:
        creator = [c for c in reserve if c.get('channel_id') == channel_id][0]
        reserve = [c for c in reserve if c.get('channel_id') != channel_id]
        save_json(CREATORS_DB_FILE, reserve)
    else:
        # Fetch fresh details
        details = api_client.get_channel_details([channel_id])
        if 'items' not in details or not details['items']:
            return jsonify({"error": "Channel not found on YouTube"}), 404
        creator = format_channel_data(details['items'][0])

    # Auto-classify tags if not provided
    if not primary_tags:
        auto_primary, _ = classify_creator_auto(creator)
        primary_tags = auto_primary
    if not secondary_tags:
        _, auto_secondary = classify_creator_auto(creator)
        secondary_tags = auto_secondary

    # Auto-detect language and region if not provided
    if not language:
        language = detect_language(creator)
    if not region_tag:
        region_tag = detect_region(creator)

    creator['is_managed'] = True
    creator['is_manual'] = True
    creator['added_at'] = datetime.datetime.now().isoformat()
    creator['notes'] = notes
    creator['custom_notes'] = custom_notes
    creator['primary_tags'] = primary_tags
    creator['secondary_tags'] = secondary_tags
    creator['region_tag'] = region_tag
    creator['language'] = language
    creator['tags'] = ['managed'] + primary_tags + secondary_tags

    managed.append(creator)
    save_json(MANAGED_CREATORS_DB_FILE, managed)

    return jsonify({"success": True, "creator": creator})


@app.route('/api/creators/promote/<channel_id>', methods=['POST'])
@require_admin
def promote_creator(channel_id):
    """Promote a reserve creator to managed library (admin only)"""
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)

    # Check if already managed
    if any(c.get('channel_id') == channel_id for c in managed):
        return jsonify({"error": "Creator already in managed library"}), 409

    creator = None
    for c in reserve:
        if c.get('channel_id') == channel_id:
            creator = c
            break

    if not creator:
        return jsonify({"error": "Creator not found in reserve library"}), 404

    data = request.json or {}
    primary_tags = data.get('primary_tags', [])
    secondary_tags = data.get('secondary_tags', [])
    notes = data.get('notes', creator.get('notes', ''))
    custom_notes = data.get('custom_notes', creator.get('custom_notes', ''))
    region_tag = data.get('region_tag', creator.get('region_tag', ''))
    language = data.get('language', creator.get('language', ''))

    if not primary_tags:
        auto_primary, _ = classify_creator_auto(creator)
        primary_tags = auto_primary
    if not secondary_tags:
        _, auto_secondary = classify_creator_auto(creator)
        secondary_tags = auto_secondary
    if not language:
        language = detect_language(creator)
    if not region_tag:
        region_tag = detect_region(creator)

    creator['is_managed'] = True
    creator['is_manual'] = True
    creator['notes'] = notes
    creator['custom_notes'] = custom_notes
    creator['primary_tags'] = primary_tags
    creator['secondary_tags'] = secondary_tags
    creator['region_tag'] = region_tag
    creator['language'] = language
    creator['tags'] = ['managed'] + primary_tags + secondary_tags

    # Remove from reserve, add to managed
    reserve = [c for c in reserve if c.get('channel_id') != channel_id]
    managed.append(creator)

    save_json(CREATORS_DB_FILE, reserve)
    save_json(MANAGED_CREATORS_DB_FILE, managed)

    return jsonify({"success": True, "creator": creator})


@app.route('/api/creators/managed/<channel_id>', methods=['PUT'])
@require_admin
def update_managed_creator(channel_id):
    """Update managed creator tags/notes/region/language (admin only)"""
    data = request.json
    managed = load_json(MANAGED_CREATORS_DB_FILE)

    for c in managed:
        if c.get('channel_id') == channel_id:
            if 'notes' in data:
                c['notes'] = data['notes']
            if 'custom_notes' in data:
                c['custom_notes'] = data['custom_notes']
            if 'primary_tags' in data:
                c['primary_tags'] = data['primary_tags']
            if 'secondary_tags' in data:
                c['secondary_tags'] = data['secondary_tags']
            if 'region_tag' in data:
                c['region_tag'] = data['region_tag']
            if 'language' in data:
                c['language'] = data['language']
            # Rebuild tags
            c['tags'] = ['managed'] + c.get('primary_tags', []) + c.get('secondary_tags', [])
            save_json(MANAGED_CREATORS_DB_FILE, managed)
            return jsonify({"success": True, "creator": c})

    return jsonify({"error": "Creator not found in managed library"}), 404


@app.route('/api/creators/managed/<channel_id>', methods=['DELETE'])
@require_admin
def remove_managed_creator(channel_id):
    """Remove a managed creator (admin only)"""
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    new_list = [c for c in managed if c.get('channel_id') != channel_id]

    if len(new_list) == len(managed):
        return jsonify({"error": "Creator not found"}), 404

    save_json(MANAGED_CREATORS_DB_FILE, new_list)
    return jsonify({"success": True})


# ====== API: Trend Analysis ======

@app.route('/api/trends')
def get_trends():
    """Get trend data for charts"""
    history = load_json(STATS_HISTORY_FILE, [])

    subscriber_trends = []
    view_trends = []
    video_trends = []

    for snapshot in history:
        date = snapshot.get('date', '')
        subscriber_trends.append({
            "date": date,
            "total_subscribers": sum(s.get('subscriber_count', 0) for s in snapshot.get('creator_snapshots', [])),
        })
        view_trends.append({
            "date": date,
            "total_views": sum(s.get('view_count', 0) for s in snapshot.get('creator_snapshots', [])),
        })
        video_trends.append({
            "date": date,
            "total_videos": snapshot.get('total_videos', 0),
        })

    creator_growth = []
    for snapshot in history:
        creator_growth.append({
            "date": snapshot.get('date', ''),
            "creator_count": len(snapshot.get('creator_snapshots', []))
        })

    managed_growth = []
    for snapshot in history:
        managed_growth.append({
            "date": snapshot.get('date', ''),
            "managed_count": len(snapshot.get('managed_snapshots', []))
        })

    return jsonify({
        "subscriber_trends": subscriber_trends,
        "view_trends": view_trends,
        "video_trends": video_trends,
        "creator_growth": creator_growth,
        "managed_growth": managed_growth,
        "history_count": len(history)
    })


@app.route('/api/trends/reserve-growth')
def get_reserve_growth():
    """Get reserve creator growth analysis: weekly/monthly new + tag/language distribution"""
    data = get_reserve_growth_analysis()
    return jsonify(data)


@app.route('/api/trends/creator/<channel_id>')
def get_creator_trend(channel_id):
    """Get trend data for a specific creator"""
    history = load_json(STATS_HISTORY_FILE, [])
    data_points = []
    for snapshot in history:
        for c in snapshot.get('creator_snapshots', []):
            if c.get('channel_id') == channel_id:
                data_points.append({
                    "date": snapshot.get('date', ''),
                    "subscriber_count": c.get('subscriber_count', 0),
                    "view_count": c.get('view_count', 0),
                    "video_count": c.get('video_count', 0),
                })
                break
    return jsonify({"channel_id": channel_id, "data_points": data_points})


# ====== API: Search / Discover ======

@app.route('/api/search/videos')
def search_videos():
    """Search YouTube videos via API"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    max_results = request.args.get('max', 10, type=int)
    result = api_client.search_videos(query, max_results=max_results, order='viewCount')

    if 'error' in result:
        return jsonify(result), 500

    video_ids = [item.get('id', {}).get('videoId', '') for item in result.get('items', [])]
    video_ids = [vid for vid in video_ids if vid]

    if video_ids:
        details = api_client.get_video_details(video_ids)
        videos = [format_video_data(v) for v in details.get('items', [])]
        return jsonify({"videos": videos, "total": len(videos)})

    return jsonify({"videos": [], "total": 0})


@app.route('/api/search/channels')
def search_channels():
    """Search YouTube channels via API"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    max_results = request.args.get('max', 10, type=int)
    result = api_client.search_channels(query, max_results=max_results)

    if 'error' in result:
        return jsonify(result), 500

    channel_ids = [item.get('id', {}).get('channelId', '') for item in result.get('items', [])]
    channel_ids = [cid for cid in channel_ids if cid]

    if channel_ids:
        details = api_client.get_channel_details(channel_ids)
        channels = [format_channel_data(c) for c in details.get('items', [])]
        # Auto classify tags for search results
        for c in channels:
            c['primary_tags'], c['secondary_tags'] = classify_creator_auto(c)
            c['language'] = detect_language(c)
            c['region_tag'] = detect_region(c)
        return jsonify({"channels": channels, "total": len(channels)})

    return jsonify({"channels": [], "total": 0})


# ====== API: Refresh ======

@app.route('/api/refresh', methods=['POST'])
@require_admin
def trigger_refresh():
    """Trigger a manual data refresh (admin only)"""
    try:
        result = run_full_refresh()
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/refresh/discover', methods=['POST'])
@require_admin
def trigger_discover():
    """Trigger creator discovery from trending videos (admin only)"""
    try:
        new_creators = discover_creators_from_videos(api_client)
        return jsonify({"success": True, "new_creators": len(new_creators), "creators": new_creators})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/refresh/status')
def refresh_status():
    """Get refresh history and status"""
    log = load_json(REFRESH_LOG_FILE, [])
    return jsonify({
        "history": log[-20:],
        "total_runs": len(log),
        "last_run": log[-1] if log else None
    })


# ====== API: Deduplicate ======

@app.route('/api/creators/dedup', methods=['POST'])
@require_admin
def dedup_libraries():
    """Manually trigger deduplication between reserve and managed"""
    removed = deduplicate_libraries()
    return jsonify({"success": True, "removed": removed})


@app.route('/api/creators/redetect', methods=['POST'])
@require_admin
def redetect_tags():
    """Re-detect tags, language, and region for all creators missing them"""
    from data_refresh import classify_creator_tags, detect_language, detect_region
    reserve = load_json(CREATORS_DB_FILE)
    managed = load_json(MANAGED_CREATORS_DB_FILE)
    updated = 0

    for c in reserve + managed:
        changed = False
        if not c.get('primary_tags') or not c.get('secondary_tags'):
            p, s = classify_creator_tags(c)
            if not c.get('primary_tags'):
                c['primary_tags'] = p
                changed = True
            if not c.get('secondary_tags'):
                c['secondary_tags'] = s
                changed = True
        if not c.get('language'):
            c['language'] = detect_language(c)
            changed = True
        if not c.get('region_tag') or c.get('region_tag') == '':
            c['region_tag'] = detect_region(c)
            changed = True
        if changed:
            updated += 1

    save_json(CREATORS_DB_FILE, reserve)
    save_json(MANAGED_CREATORS_DB_FILE, managed)
    return jsonify({"success": True, "updated": updated})


if __name__ == '__main__':
    # Cloud deployment: sync data from GitHub before starting
    sync_all_data_from_github()

    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '127.0.0.1')
    debug = os.environ.get('FLASK_DEBUG', '1') == '1'

    print(f"Starting {PLATFORM_NAME} server...")
    print(f"Data directory: {DATA_DIR}")
    print(f"Frontend directory: {FRONTEND_DIR}")
    print(f"Access URL: http://{host}:{port}/starroad")
    app.run(host=host, port=port, debug=debug)
