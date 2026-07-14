"""
Daily auto-refresh script for 旭星-YouTube热点库
This script runs at 10:20 AM daily.

Usage:
    python daily_refresh.py

To set up Windows Task Scheduler:
1. Open Task Scheduler
2. Create Basic Task -> Name: "旭星-YouTube热点库每日刷新"
3. Trigger: Daily, at 10:20 AM
4. Action: Start a program
   - Program: C:\Users\admin\.workbuddy\binaries\python\envs\default\Scripts\python.exe
   - Arguments: daily_refresh.py
   - Start in: C:\Users\admin\WorkBuddy\2026-07-10-14-35-13\youtube-trending-platform\backend
"""
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_refresh import run_full_refresh, discover_creators_from_videos
from youtube_api import YouTubeAPI
from config import sync_all_data_from_github

def main():
    print(f"\n{'='*60}")
    print(f"旭星-YouTube热点库 - 每日自动刷新")
    print(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Cloud deployment: pull latest data before refreshing
    sync_all_data_from_github()

    # Step 1: Full data refresh
    result = run_full_refresh()

    # Step 2: Discover new creators from trending videos
    api = YouTubeAPI()
    new_creators = discover_creators_from_videos(api)

    print(f"\nDaily refresh completed!")
    print(f"  - Videos refreshed: {result['videos']}")
    print(f"  - Reserve creators: {result['reserve_creators']}")
    print(f"  - Managed creators: {result['managed_creators']}")
    print(f"  - New creators discovered: {len(new_creators)}")

    return result

if __name__ == "__main__":
    main()
