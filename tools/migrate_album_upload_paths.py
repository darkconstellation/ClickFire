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

from database import album_files_col, albums_col, ROOM_COLLECTIONS


UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))


def _ensure_album_dir(album_name: str) -> str:
    album_dir = os.path.join(UPLOAD_DIR, album_name)
    os.makedirs(album_dir, exist_ok=True)
    return album_dir


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
    collections = [album_files_col, *ROOM_COLLECTIONS.values()]

    for col in collections:
        async for doc in col.find({}, {"media_url": 1, "thumbnail_url": 1}):
            for field in ("media_url", "thumbnail_url"):
                relative = _normalize_upload_relative(doc.get(field))
                if relative:
                    counts[relative] += 1

    return counts


async def _load_album_names() -> dict[str, str]:
    album_names: dict[str, str] = {}
    async for album in albums_col.find({}, {"name": 1}):
        album_names[str(album["_id"])] = album["name"]
        _ensure_album_dir(album["name"])
    return album_names


async def _migrate_album_file(doc: dict, album_name: str, reference_counts: Counter[str], dry_run: bool) -> dict[str, int]:
    stats = {
        "updated": 0,
        "moved": 0,
        "copied": 0,
        "missing_media": 0,
        "missing_thumbnail": 0,
    }
    album_dir = _ensure_album_dir(album_name)
    updates: dict[str, str | None] = {}

    for field, required in (("media_url", True), ("thumbnail_url", False)):
        original_url = doc.get(field)
        relative = _normalize_upload_relative(original_url)
        if not relative:
            if not required:
                updates[field] = None
            continue

        source_path = _relative_to_path(relative)
        filename = os.path.basename(relative)
        target_relative = os.path.join(album_name, filename)
        target_path = _relative_to_path(target_relative)
        target_url = _relative_to_url(target_relative)

        if os.path.abspath(source_path) == os.path.abspath(target_path):
            continue

        source_exists = os.path.exists(source_path)
        target_exists = os.path.exists(target_path)
        safe_to_move = reference_counts[relative] <= 1

        if target_exists and not source_exists:
            updates[field] = target_url
            stats["updated"] += 1
            continue

        if not source_exists and not target_exists:
            if required:
                stats["missing_media"] += 1
            else:
                stats["missing_thumbnail"] += 1
                updates[field] = None
            continue

        if not dry_run:
            if target_exists:
                if safe_to_move and source_exists:
                    os.remove(source_path)
                    stats["moved"] += 1
            elif safe_to_move:
                shutil.move(source_path, target_path)
                stats["moved"] += 1
            else:
                shutil.copy2(source_path, target_path)
                stats["copied"] += 1

        updates[field] = target_url
        stats["updated"] += 1

    if updates and not dry_run:
        await album_files_col.update_one({"_id": doc["_id"]}, {"$set": updates})

    return stats


async def main(dry_run: bool) -> None:
    album_names = await _load_album_names()
    reference_counts = await _collect_reference_counts()

    summary = Counter()
    async for doc in album_files_col.find({}, {"album_id": 1, "media_url": 1, "thumbnail_url": 1}):
        album_name = album_names.get(str(doc["album_id"]))
        if not album_name:
            summary["skipped_missing_album"] += 1
            continue

        file_stats = await _migrate_album_file(doc, album_name, reference_counts, dry_run)
        summary.update(file_stats)

    mode = "dry-run" if dry_run else "applied"
    print(f"Migration {mode} complete")
    print(f"updated={summary['updated']} moved={summary['moved']} copied={summary['copied']}")
    print(
        f"missing_media={summary['missing_media']} missing_thumbnail={summary['missing_thumbnail']} "
        f"skipped_missing_album={summary['skipped_missing_album']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Move ClickFire album media into per-album upload folders.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files or MongoDB updates.")
    args = parser.parse_args()

    asyncio.run(main(args.dry_run))