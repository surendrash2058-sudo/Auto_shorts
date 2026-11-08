
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_FILE = "credentials/token.json"
OUTPUT_DIR = Path("output")
DAYS = 7

QUERIES = [
    "what if",
    "what would happen if",
    "what if earth",
    "what if space",
    "what if humans"
]


def connect_youtube():
    credentials = Credentials.from_authorized_user_file(
        TOKEN_FILE,
        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly"
        ]
    )

    return build("youtube", "v3", credentials=credentials)


def find_trending_topics():
    youtube = connect_youtube()

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=DAYS)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    videos_found = {}

    for query in QUERIES:
        print(f"Searching: {query}")

        response = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            order="viewCount",
            publishedAfter=published_after,
            maxResults=25
        ).execute()

        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            videos_found[video_id] = item["snippet"]

    if not videos_found:
        print("No recent videos found.")
        return

    video_ids = list(videos_found.keys())
    results = []

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]

        response = youtube.videos().list(
            part="statistics,contentDetails",
            id=",".join(batch)
        ).execute()

        for video in response.get("items", []):
            video_id = video["id"]
            snippet = videos_found[video_id]
            stats = video.get("statistics", {})

            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))

            results.append({
                "title": snippet["title"],
                "channel": snippet["channelTitle"],
                "published": snippet["publishedAt"],
                "video_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_rate": round(
                    ((likes + comments) / views) * 100, 2
                ) if views else 0
            })

    results.sort(key=lambda x: x["views"], reverse=True)

    OUTPUT_DIR.mkdir(exist_ok=True)

    output_file = OUTPUT_DIR / "trending_topics.json"

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=4, ensure_ascii=False)

    print("\nTOP WHAT IF VIDEOS - LAST 7 DAYS")
    print("=" * 55)

    for index, video in enumerate(results[:15], 1):
        print(f"\n{index}. {video['title']}")
        print(f"   Views: {video['views']:,}")
        print(f"   Likes: {video['likes']:,}")
        print(f"   Channel: {video['channel']}")
        print(f"   URL: {video['url']}")

    print(f"\nSaved {len(results)} videos to {output_file}")


if __name__ == "__main__":
    find_trending_topics()
