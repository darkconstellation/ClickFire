from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter, defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import album_files_col, ROOM_COLLECTIONS


UPLOAD_PREFIX = "/uploads/"


def _normalize_upload_relative(url: str | None) -> str | None:
    if not url:
        return None

    value = url.split("?", 1)[0].split("#", 1)[0]
    if value.startswith(UPLOAD_PREFIX):
        return value[len(UPLOAD_PREFIX) :]
    if value.startswith("uploads/"):
        return value[len("uploads/") :]
    return None


def _is_thumbnail_path(url: str | None) -> bool:
    relative = _normalize_upload_relative(url)
    if not relative:
        return False
    parts = relative.split("/")
    return len(parts) >= 2 and parts[-2] == "thumbnail"


async def _inspect_collection(name: str, col) -> dict:
    total = 0
    videos = 0
    images = 0
    thumb_set = 0
    thumb_in_folder = 0
    missing_thumb = 0
    sample_missing = []
    sample_thumb_paths = []
    path_prefixes = Counter()

    async for doc in col.find({}, {"media_url": 1, "thumbnail_url": 1, "is_video": 1, "media_type": 1, "content": 1}):
        media_url = doc.get("media_url")
        thumb_url = doc.get("thumbnail_url")
        if not media_url:
            continue

        total += 1
        is_video = bool(doc.get("is_video")) or str(doc.get("media_type", "")).startswith("video/") or str(
            doc.get("content", "")
        ).startswith("video/")
        if is_video:
            videos += 1
        else:
            images += 1

        relative = _normalize_upload_relative(media_url)
        if relative:
            path_prefixes[relative.split("/")[0]] += 1

        if thumb_url:
            thumb_set += 1
            if _is_thumbnail_path(thumb_url):
                thumb_in_folder += 1
            if len(sample_thumb_paths) < 5:
                sample_thumb_paths.append(thumb_url)
        else:
            missing_thumb += 1
            if len(sample_missing) < 5:
                sample_missing.append(media_url)

    return {
        "collection": name,
        "total_media": total,
        "videos": videos,
        "images": images,
        "thumbnail_url_set": thumb_set,
        "thumbnail_url_in_thumbnail_folder": thumb_in_folder,
        "missing_thumbnail_url": missing_thumb,
        "sample_missing_media_urls": sample_missing,
        "sample_thumbnail_urls": sample_thumb_paths,
        "top_media_path_prefixes": path_prefixes.most_common(),
    }


async def main() -> None:
    report = []
    report.append(await _inspect_collection("album_files", album_files_col))
    for room, col in ROOM_COLLECTIONS.items():
        report.append(await _inspect_collection(f"messages_{room}", col))

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())