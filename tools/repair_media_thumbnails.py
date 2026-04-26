from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from collections import Counter
from importlib import import_module

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import album_files_col, ROOM_COLLECTIONS


UPLOAD_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "uploads"))
THUMBNAIL_FOLDER_NAME = "thumbnail"
SECRET = b"CLICKFIRE_P2P_SECRET_KEY_889900"


def _ensure_folder(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_upload_relative(url: str | None) -> str | None:
    if not url:
        return None

    value = url.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/uploads/", "uploads/"):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _resolve_upload_path(url: str | None) -> str | None:
    relative = _normalize_upload_relative(url)
    if not relative:
        return None
    return os.path.normpath(os.path.join(UPLOAD_DIR, relative))


def _split_upload_relative(relative: str) -> tuple[str, str]:
    parts = relative.replace("\\", "/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Unexpected upload path: {relative}")
    folder = parts[0]
    filename = "/".join(parts[1:])
    return folder, filename


def _thumbnail_dir_for(folder: str) -> str:
    return _ensure_folder(os.path.join(UPLOAD_DIR, folder, THUMBNAIL_FOLDER_NAME))


def _thumbnail_url(folder: str, filename: str) -> str:
    return f"/uploads/{folder}/{THUMBNAIL_FOLDER_NAME}/{filename}"


def _evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len: int, iv_len: int) -> tuple[bytes, bytes]:
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + passphrase + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def decrypt_cryptojs_text(encrypted_text: str) -> bytes:
    raw = base64.b64decode(encrypted_text)
    if not raw.startswith(b"Salted__"):
        raise ValueError("Unsupported encrypted payload format")

    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = _evp_bytes_to_key(SECRET, salt, 32, 16)

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def encrypt_cryptojs_text(data: bytes) -> str:
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(SECRET, salt, 32, 16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


def _load_encrypted_bytes(path: str) -> bytes:
    with open(path, "r", encoding="utf-8") as handle:
        return decrypt_cryptojs_text(handle.read())


def _image_format_from_suffix(suffix: str) -> tuple[str, str]:
    suffix = suffix.lower()
    if suffix in (".png",):
        return "PNG", ".png"
    if suffix in (".webp",):
        return "WEBP", ".webp"
    if suffix in (".jpg", ".jpeg"):
        return "JPEG", ".jpg"
    return "JPEG", ".jpg"


def _get_pil_modules():
    pil_image = import_module("PIL.Image")
    pil_image_ops = import_module("PIL.ImageOps")
    return pil_image, pil_image_ops


def _get_ffmpeg_exe():
    return import_module("imageio_ffmpeg").get_ffmpeg_exe()


def _get_imageio_module():
    return import_module("imageio")


def _generate_image_thumbnail(image_bytes: bytes, source_name: str) -> tuple[bytes, str]:
    Image, _ = _get_pil_modules()
    with Image.open(BytesIO(image_bytes)) as image:
        source_suffix = Path(source_name).suffix or ".jpg"
        output_format, output_ext = _image_format_from_suffix(source_suffix)

        if output_format == "JPEG" and image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha_image = image.convert("RGBA")
            background.paste(alpha_image, mask=alpha_image.split()[-1])
            working = background
        else:
            working = image.convert("RGB") if output_format == "JPEG" else image.copy()

        working.thumbnail((480, 480), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        save_kwargs = {"optimize": True}
        if output_format == "JPEG":
            save_kwargs["quality"] = 85
        working.save(buffer, format=output_format, **save_kwargs)
        return buffer.getvalue(), output_ext


def _extract_video_frames(video_bytes: bytes, source_name: str) -> bytes:
    Image, ImageOps = _get_pil_modules()
    temp_dir = tempfile.mkdtemp(prefix="clickfire_thumb_")
    try:
        video_source = os.path.join(temp_dir, source_name)
        with open(video_source, "wb") as handle:
            handle.write(video_bytes)

        imageio = _get_imageio_module()

        reader = imageio.get_reader(video_source)
        meta = reader.get_meta_data()
        duration = float(meta.get("duration") or 0)
        fps = float(meta.get("fps") or 0)

        if duration <= 0 and fps > 0:
            try:
                duration = reader.count_frames() / fps
            except Exception:
                duration = 0

        if duration <= 0:
            duration = 1.0

        sample_points = [0.1, 0.35, 0.6, 0.85]
        frame_paths: list[str] = []
        ffmpeg_bin = _get_ffmpeg_exe()

        for index, point in enumerate(sample_points):
            timestamp = max(0.0, min(duration * point, max(duration - 0.05, 0.0)))
            frame_path = os.path.join(temp_dir, f"frame_{index}.jpg")
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    video_source,
                    "-frames:v",
                    "1",
                    frame_path,
                ],
                check=True,
            )
            frame_paths.append(frame_path)

        tile_width = 320
        tile_height = 180
        canvas = Image.new("RGB", (tile_width * 2, tile_height * 2), (0, 0, 0))
        positions = [(0, 0), (tile_width, 0), (0, tile_height), (tile_width, tile_height)]

        for frame_path, position in zip(frame_paths, positions, strict=True):
            with Image.open(frame_path) as frame:
                fitted = ImageOps.fit(frame.convert("RGB"), (tile_width, tile_height), method=Image.Resampling.LANCZOS)
                canvas.paste(fitted, position)

        buffer = BytesIO()
        canvas.save(buffer, format="JPEG", quality=85, optimize=True)
        return buffer.getvalue()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _collect_documents() -> list[tuple[str, str, dict]]:
    collections: list[tuple[str, object]] = [("album_files", album_files_col)]
    for room, col in ROOM_COLLECTIONS.items():
        collections.append((f"messages_{room}", col))

    documents: list[tuple[str, str, dict]] = []
    async def _load() -> None:
        for collection_name, col in collections:
            async for doc in col.find({}, {"media_url": 1, "thumbnail_url": 1, "is_video": 1, "media_type": 1, "content": 1}):
                documents.append((collection_name, str(doc["_id"]), doc))

    return documents, _load


async def _process_collection(collection_name: str, collection, dry_run: bool) -> dict[str, int]:
    stats = Counter()
    async for doc in collection.find({}, {"media_url": 1, "thumbnail_url": 1, "is_video": 1, "media_type": 1, "content": 1}):
        media_url = doc.get("media_url")
        if not media_url:
            continue

        media_path = _resolve_upload_path(media_url)
        if not media_path or not os.path.exists(media_path):
            stats["missing_media"] += 1
            continue

        media_relative = _normalize_upload_relative(media_url)
        assert media_relative is not None
        folder, media_filename = _split_upload_relative(media_relative)
        thumb_dir = _thumbnail_dir_for(folder)

        existing_thumb_url = doc.get("thumbnail_url")
        target_thumb_url = None

        if existing_thumb_url:
          existing_thumb_path = _resolve_upload_path(existing_thumb_url)
          if existing_thumb_path and os.path.exists(existing_thumb_path):
              existing_relative = _normalize_upload_relative(existing_thumb_url)
              if existing_relative and "/thumbnail/" not in existing_relative:
                  thumb_filename = os.path.basename(existing_thumb_path)
                  target_thumb_path = os.path.join(thumb_dir, thumb_filename)
                  target_thumb_url = _thumbnail_url(folder, thumb_filename)
                  if not dry_run:
                      if os.path.abspath(existing_thumb_path) != os.path.abspath(target_thumb_path):
                          shutil.move(existing_thumb_path, target_thumb_path)
                  stats["moved"] += 1
              else:
                  stats["already_correct"] += 1
                  continue
          else:
              existing_thumb_url = None

        if target_thumb_url is None:
            base_name = Path(media_filename)
            source_stem = base_name.name[:-4] if base_name.name.endswith(".enc") else base_name.name
            if doc.get("is_video") or str(doc.get("media_type", "")).startswith("video/") or str(doc.get("content", "")).startswith("video/"):
                output_bytes = _extract_video_frames(_load_encrypted_bytes(media_path), source_stem)
                thumb_filename = f"thumb_{doc['_id']}_{Path(source_stem).stem}.jpg.enc"
                target_thumb_url = _thumbnail_url(folder, thumb_filename)
            else:
                image_bytes, output_ext = _generate_image_thumbnail(_load_encrypted_bytes(media_path), source_stem)
                thumb_filename = f"thumb_{doc['_id']}_{Path(source_stem).stem}{output_ext}.enc"
                target_thumb_url = _thumbnail_url(folder, thumb_filename)
                output_bytes = image_bytes

            thumb_path = os.path.join(thumb_dir, thumb_filename)
            if not dry_run:
                with open(thumb_path, "w", encoding="utf-8") as handle:
                    handle.write(encrypt_cryptojs_text(output_bytes))
            stats["generated"] += 1

        if not dry_run and target_thumb_url and doc.get("thumbnail_url") != target_thumb_url:
            await collection.update_one({"_id": doc["_id"]}, {"$set": {"thumbnail_url": target_thumb_url}})
            stats["updated"] += 1
        elif dry_run and target_thumb_url and doc.get("thumbnail_url") != target_thumb_url:
            stats["would_update"] += 1

    return dict(stats)


async def main(dry_run: bool) -> None:
    _ensure_folder(UPLOAD_DIR)
    summary = Counter()

    collections: list[tuple[str, object]] = [("album_files", album_files_col)]
    for room, col in ROOM_COLLECTIONS.items():
        collections.append((f"messages_{room}", col))

    for collection_name, collection in collections:
        stats = await _process_collection(collection_name, collection, dry_run)
        summary.update(stats)

    mode = "dry-run" if dry_run else "applied"
    print(f"Thumbnail repair {mode} complete")
    print(
        f"updated={summary['updated']} generated={summary['generated']} moved={summary['moved']} "
        f"already_correct={summary['already_correct']} missing_media={summary['missing_media']} would_update={summary['would_update']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repair ClickFire media thumbnails and move them into per-folder thumbnail subdirectories.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned changes without writing files or MongoDB updates.")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))