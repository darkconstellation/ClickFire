from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from collections import Counter

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import ROOM_COLLECTIONS


UPLOAD_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "uploads"))
ROOM_UPLOAD_FOLDERS = {
    "private": "Private",
    "work": "Work",
    "testing": "Testing",
}


def _ensure_room_dirs() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for folder_name in ROOM_UPLOAD_FOLDERS.values():
        os.makedirs(os.path.join(UPLOAD_DIR, folder_name), exist_ok=True)


def _normalize_upload_relative(url: str | None) -> str | None:
    if not url:
        return None

    value = url.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/uploads/", "uploads/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return os.path.basename(value)


def _relative_to_path(relative: str) -> str:
    return os.path.normpath(os.path.join(UPLOAD_DIR, relative))


def _relative_to_url(relative: str) -> str:
    return f"/uploads/{relative.replace(os.sep, '/')}"


async def _collect_reference_counts() -> Counter[str]:
    counts: Counter[str] = Counter()
    for col in ROOM_COLLECTIONS.values():
        async for doc in col.find({}, {"media_url": 1, "thumbnail_url": 1}):
            for field in ("media_url", "thumbnail_url"):
                relative = _normalize_upload_relative(doc.get(field))
                if relative:
                    counts[relative] += 1
    return counts


async def _migrate_collection(room: str, folder_name: str, dry_run: bool, reference_counts: Counter[str]) -> dict[str, int]:
    col = ROOM_COLLECTIONS[room]
    stats = Counter()
    cleanup_paths: set[str] = set()

    async for doc in col.find({}, {"media_url": 1, "thumbnail_url": 1}):
        updates: dict[str, str | None] = {}
        for field in ("media_url", "thumbnail_url"):
            original_url = doc.get(field)
            relative = _normalize_upload_relative(original_url)
            if not relative:
                continue

            source_path = _relative_to_path(relative)
            filename = os.path.basename(relative)
            target_relative = os.path.join(folder_name, filename)
            target_path = _relative_to_path(target_relative)
            target_url = _relative_to_url(target_relative)

            if os.path.abspath(source_path) == os.path.abspath(target_path):
                continue

            cleanup_paths.add(source_path)

            source_exists = os.path.exists(source_path)
            target_exists = os.path.exists(target_path)

            if source_exists and not target_exists and not dry_run:
                if reference_counts[relative] > 1:
                    shutil.copy2(source_path, target_path)
                    stats["copied"] += 1
                else:
                    shutil.move(source_path, target_path)
                    stats["moved"] += 1

            if source_exists and target_exists and not dry_run:
                stats["reused"] += 1

            if not source_exists and not target_exists:
                stats["missing"] += 1
                continue

            updates[field] = target_url
            stats["updated"] += 1

        if updates and not dry_run:
            await col.update_one({"_id": doc["_id"]}, {"$set": updates})

    if not dry_run:
        for source_path in sorted(cleanup_paths):
            if os.path.exists(source_path):
                os.remove(source_path)

    return dict(stats)


async def main(dry_run: bool) -> None:
    _ensure_room_dirs()
    reference_counts = await _collect_reference_counts()

    summary = Counter()
    for room, folder_name in ROOM_UPLOAD_FOLDERS.items():
        stats = await _migrate_collection(room, folder_name, dry_run, reference_counts)
        summary.update(stats)

    mode = "dry-run" if dry_run else "applied"
    print(f"Migration {mode} complete")
    print(
        f"updated={summary['updated']} moved={summary['moved']} copied={summary['copied']} "
        f"reused={summary['reused']} missing={summary['missing']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Move ClickFire chat media into per-room upload folders.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files or MongoDB updates.")
    args = parser.parse_args()

    asyncio.run(main(args.dry_run))