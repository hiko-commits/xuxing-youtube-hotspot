"""
YouTube Data API v3 client wrapper
Handles all interactions with the YouTube API
"""
import requests
import datetime
import time
from config import YOUTUBE_API_KEY, YOUTUBE_API_BASE, load_json, save_json, CREATORS_DB_FILE, STATS_HISTORY_FILE


class YouTubeAPI:
    def __init__(self, api_key=None):
        self.api_key = api_key or YOUTUBE_API_KEY
        self.base_url = YOUTUBE_API_BASE
        self.session = requests.Session()

    def _get(self, endpoint, params):
        """Make a GET request to YouTube API"""
        params['key'] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                return {"error": "quota_exceeded", "message": "YouTube API daily quota exceeded"}
            if resp.status_code != 200:
                return {"error": f"http_{resp.status_code}", "message": resp.text[:500]}
            return resp.json()
        except requests.exceptions.Timeout:
            return {"error": "timeout", "message": "Request timed out"}
        except Exception as e:
            return {"error": "exception", "message": str(e)}

    def search_videos(self, query, max_results=10, order="viewCount", published_after=None):
        """Search for videos matching the query"""
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': max_results,
            'order': order,  # viewCount, relevance, date, rating
            'regionCode': 'US',
            'relevanceLanguage': 'en'
        }
        if published_after:
            params['publishedAfter'] = published_after
        return self._get('search', params)

    def get_video_details(self, video_ids):
        """Get detailed statistics for videos"""
        if not video_ids:
            return {"items": []}
        # API accepts max 50 IDs per request
        results = {"items": []}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            params = {
                'part': 'snippet,statistics,contentDetails',
                'id': ','.join(batch)
            }
            resp = self._get('videos', params)
            if 'items' in resp:
                results['items'].extend(resp['items'])
            time.sleep(0.1)  # Small delay to be polite
        return results

    def search_channels(self, query, max_results=10):
        """Search for channels matching the query"""
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'channel',
            'maxResults': max_results,
            'order': 'relevance'
        }
        return self._get('search', params)

    def get_channel_details(self, channel_ids):
        """Get detailed statistics for channels"""
        if not channel_ids:
            return {"items": []}
        results = {"items": []}
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i+50]
            params = {
                'part': 'snippet,statistics,contentDetails,brandingSettings',
                'id': ','.join(batch)
            }
            resp = self._get('channels', params)
            if 'items' in resp:
                results['items'].extend(resp['items'])
            time.sleep(0.1)
        return results

    def get_channel_videos(self, channel_id, max_results=10):
        """Get recent videos from a channel"""
        # First get the uploads playlist ID
        channel_data = self.get_channel_details([channel_id])
        if 'items' not in channel_data or not channel_data['items']:
            return {"items": []}
        uploads_playlist = channel_data['items'][0].get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
        if not uploads_playlist:
            return {"items": []}
        # Get videos from uploads playlist
        params = {
            'part': 'snippet,contentDetails',
            'playlistId': uploads_playlist,
            'maxResults': max_results
        }
        return self._get('playlistItems', params)

    def get_video_categories(self, region_code='US'):
        """Get available video categories for a region"""
        params = {
            'part': 'snippet',
            'regionCode': region_code
        }
        return self._get('videoCategories', params)


def format_video_data(raw_video):
    """Convert raw API video data to our internal format"""
    snippet = raw_video.get('snippet', {})
    stats = raw_video.get('statistics', {})
    content = raw_video.get('contentDetails', {})
    return {
        "video_id": raw_video.get('id', ''),
        "title": snippet.get('title', ''),
        "description": snippet.get('description', '')[:500],
        "channel_id": snippet.get('channelId', ''),
        "channel_title": snippet.get('channelTitle', ''),
        "published_at": snippet.get('publishedAt', ''),
        "thumbnail": snippet.get('thumbnails', {}).get('high', {}).get('url',
                    snippet.get('thumbnails', {}).get('medium', {}).get('url',
                    snippet.get('thumbnails', {}).get('default', {}).get('url', ''))),
        "tags": snippet.get('tags', []),
        "category_id": snippet.get('categoryId', ''),
        "duration": content.get('duration', ''),
        "view_count": int(stats.get('viewCount', 0)),
        "like_count": int(stats.get('likeCount', 0)),
        "comment_count": int(stats.get('commentCount', 0)),
        "fetched_at": datetime.datetime.now().isoformat()
    }


def format_channel_data(raw_channel):
    """Convert raw API channel data to our internal format"""
    snippet = raw_channel.get('snippet', {})
    stats = raw_channel.get('statistics', {})
    branding = raw_channel.get('brandingSettings', {})
    return {
        "channel_id": raw_channel.get('id', ''),
        "title": snippet.get('title', ''),
        "description": snippet.get('description', '')[:500],
        "custom_url": snippet.get('customUrl', ''),
        "country": snippet.get('country', ''),
        "published_at": snippet.get('publishedAt', ''),
        "thumbnail": snippet.get('thumbnails', {}).get('high', {}).get('url',
                    snippet.get('thumbnails', {}).get('medium', {}).get('url',
                    snippet.get('thumbnails', {}).get('default', {}).get('url', ''))),
        "banner": branding.get('image', {}).get('bannerExternalUrl', ''),
        "subscriber_count": int(stats.get('subscriberCount', 0)),
        "video_count": int(stats.get('videoCount', 0)),
        "view_count": int(stats.get('viewCount', 0)),
        "hidden_subscriber_count": stats.get('hiddenSubscriberCount', False),
        "keywords": branding.get('channel', {}).get('keywords', ''),
        "fetched_at": datetime.datetime.now().isoformat(),
        "is_tracked": True,
        "is_manual": False,
        "notes": ""
    }
