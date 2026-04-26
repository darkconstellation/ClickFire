from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime, timezone
import base64
import binascii
from bson import ObjectId
import hashlib
import hmac
import os
import shutil
from urllib.parse import quote, unquote

from database import db, users_col, albums_col, album_files_col, get_messages_col, ROOM_COLLECTIONS
from schemas import (
    UserLogin, UserResponse, MessageCreate, MessageResponse,
    StatusUpdate, MessageStatus, ReplyTo,
    AlbumResponse, AlbumAuth, AlbumFileResponse, SaveToAlbum,
)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
VIDEO_DIR = os.path.join(UPLOAD_DIR, "videos")
THUMB_DIR = os.path.join(UPLOAD_DIR, "thumbnails")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

CHAT_ROOM_UPLOAD_FOLDERS = {
    "private": "Private",
    "work": "Work",
    "testing": "Testing",
}

ALBUM_PASSWORD_HASHES = {
    "DataScript": "pbkdf2_sha256$390000$08jDuN2nDkQqZsouo5SzOw==$fir7Eq2iNgP6+MyBTb8A69WetgAJqVo9s90RsOtpbHs=",
    "Tuning": "pbkdf2_sha256$390000$LLMVvIDSBd+uzT2z/rTmRA==$L0k4JSJtuFowts0oi67RcK5WFazv8TdkpXYXTPkWbvs=",
    "Drivetest": "pbkdf2_sha256$390000$b71et2LYYSY205+SYJ8v+Q==$pUIT5FootFRvqhycDlRIyQa1UZMf9xiTnKb9gcccFZM=",
    "Optimization": "pbkdf2_sha256$390000$GBQl7sgn6vxIfXLTSHlRtQ==$PL+/yA7HHaxiTVL5G9ucru0L9gidVessEw6ZCu8iMPk=",
}


def _album_upload_dir(album_name: str) -> str:
    return os.path.join(UPLOAD_DIR, album_name)


def _ensure_upload_subdir(folder_name: str) -> str:
    folder_dir = os.path.join(UPLOAD_DIR, folder_name)
    os.makedirs(folder_dir, exist_ok=True)
    return folder_dir


def _ensure_album_upload_dir(album_name: str) -> str:
    return _ensure_upload_subdir(album_name)


def _safe_upload_folder_path(folder: str) -> str:
    normalized = folder.strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""

    safe_parts: list[str] = []
    for part in normalized.split("/"):
        if not part:
            continue
        safe_part = os.path.basename(part)
        if not safe_part or safe_part in (".", "..") or safe_part != part:
            raise HTTPException(status_code=400, detail="Invalid folder")
        safe_parts.append(safe_part)

    if not safe_parts:
        raise HTTPException(status_code=400, detail="Invalid folder")
    return os.path.join(*safe_parts)


def _encode_upload_relative(relative: str) -> str:
    normalized = relative.replace(os.sep, "/").strip("/")
    if not normalized:
        return ""
    return "/".join(quote(unquote(part), safe="") for part in normalized.split("/"))


def _encode_upload_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return url

    if url.startswith(("http://", "https://")):
        return url

    relative = url.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/uploads/", "uploads/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix) :]
            break
    else:
        relative = os.path.basename(relative)

    return f"/uploads/{_encode_upload_relative(relative)}"


def _resolve_upload_path(url: str) -> str:
    relative = url.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/uploads/", "uploads/"):
        if relative.startswith(prefix):
            relative = relative[len(prefix) :]
            break
    else:
        relative = os.path.basename(relative)

    relative = unquote(relative)
    resolved = os.path.normpath(os.path.join(UPLOAD_DIR, relative))
    upload_root = os.path.abspath(UPLOAD_DIR)
    resolved_abs = os.path.abspath(resolved)
    if os.path.commonpath([upload_root, resolved_abs]) != upload_root:
        raise HTTPException(status_code=400, detail="Invalid upload path")
    return resolved_abs


def _upload_path_to_url(path: str) -> str:
    absolute_path = os.path.abspath(path)
    upload_root = os.path.abspath(UPLOAD_DIR)
    relative = os.path.relpath(absolute_path, upload_root).replace(os.sep, "/")
    return f"/uploads/{_encode_upload_relative(relative)}"


def _copy_upload_url_to_dir(url: str, target_dir: str, *, move: bool = False) -> tuple[str, str]:
    source_path = _resolve_upload_path(url)
    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="Source file not found")

    filename = os.path.basename(source_path)
    target_path = os.path.join(target_dir, filename)
    if os.path.abspath(source_path) == os.path.abspath(target_path):
        return _upload_path_to_url(target_path), target_path

    if move:
        shutil.move(source_path, target_path)
    else:
        shutil.copy2(source_path, target_path)

    return _upload_path_to_url(target_path), target_path


def _verify_album_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64)
        expected_digest = base64.b64decode(digest_b64)
    except (ValueError, TypeError, binascii.Error):
        return False

    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate_digest, expected_digest)


# --- helpers ---

def _user_doc_to_response(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "username": doc["username"]}


def _msg_doc_to_response(doc: dict) -> dict:
    resp = {
        "id": str(doc["_id"]),
        "sender_id": str(doc["sender_id"]),
        "receiver_id": str(doc["receiver_id"]),
        "content": doc.get("content"),
        "media_url": _encode_upload_url(doc.get("media_url")),
        "thumbnail_url": _encode_upload_url(doc.get("thumbnail_url")),
        "status": doc.get("status", "sent"),
        "is_media": doc.get("is_media", False),
        "sent_at": doc["sent_at"],
        "received_at": doc.get("received_at"),
        "read_at": doc.get("read_at"),
        "reply_to": doc.get("reply_to"),
    }
    return resp


def _album_file_to_response(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "album_id": str(doc["album_id"]),
        "filename": doc["filename"],
        "media_url": _encode_upload_url(doc["media_url"]),
        "thumbnail_url": _encode_upload_url(doc.get("thumbnail_url")),
        "media_type": doc["media_type"],
        "is_video": doc["is_video"],
        "file_size": doc.get("file_size", 0),
        "uploaded_at": doc["uploaded_at"],
    }


# --- lifespan (seed + indexes) ---

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # Ensure indexes
    await users_col.create_index("username", unique=True)
    await albums_col.create_index("name", unique=True)
    await album_files_col.create_index("album_id")
    for col in ROOM_COLLECTIONS.values():
        await col.create_index([("sender_id", 1), ("receiver_id", 1)])

    # Seed users
    seeds = [
        {"username": "mici", "password": "mi123"},
        {"username": "fufu", "password": "fu123"},
    ]
    for seed in seeds:
        existing = await users_col.find_one({"username": seed["username"]})
        if not existing:
            await users_col.insert_one(seed)

    # Seed / refresh album passwords using salted hashes.
    for album_name, password_hash in ALBUM_PASSWORD_HASHES.items():
        await albums_col.update_one(
            {"name": album_name},
            {
                "$set": {"name": album_name, "password_hash": password_hash},
                "$unset": {"password": ""},
            },
            upsert=True,
        )

    async for album in albums_col.find({}, {"name": 1}):
        _ensure_album_upload_dir(album["name"])
        _ensure_upload_subdir(os.path.join(album["name"], "thumbnail"))

    for room_folder in CHAT_ROOM_UPLOAD_FOLDERS.values():
        _ensure_upload_subdir(room_folder)
        _ensure_upload_subdir(os.path.join(room_folder, "thumbnail"))
    yield


app = FastAPI(title="ClickFire API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fire.rftuning.id:18000",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:9000",
        "https://app.rftuning.id/",
        "https://app.rftuning.id"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- endpoints ---

@app.post("/login", response_model=UserResponse)
async def login(creds: UserLogin):
    user = await users_col.find_one(
        {"username": creds.username, "password": creds.password}
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _user_doc_to_response(user)


@app.get("/contacts/{user_id}", response_model=List[UserResponse])
async def get_contacts(user_id: str):
    """Return all users except the requesting user (for 2-user demo)."""
    oid = ObjectId(user_id)
    docs = users_col.find({"_id": {"$ne": oid}})
    return [_user_doc_to_response(d) async for d in docs]


@app.get("/messages/unread/{user_id}")
async def get_unread_count(user_id: str, room: Optional[str] = None):
    """Unread count. If room is given, count for that room only; otherwise sum all rooms."""
    oid = ObjectId(user_id)
    query = {"receiver_id": oid, "status": {"$ne": "read"}}
    if room:
        col = get_messages_col(room)
        count = await col.count_documents(query)
    else:
        count = 0
        for col in ROOM_COLLECTIONS.values():
            count += await col.count_documents(query)
    return {"unread": count}


@app.get("/messages/{room}/{user_id}/{contact_id}", response_model=List[MessageResponse])
async def get_messages(
    room: str,
    user_id: str,
    contact_id: str,
    cursor: Optional[str] = None,
    limit: int = 20,
):
    """Cursor-based pagination using ObjectId.

    - First request: no cursor → returns the newest `limit` messages (DESC).
    - Subsequent requests: cursor=<last_id> → returns `limit` messages older
      than that ObjectId (for infinite-scroll "load older" pattern).
    """
    col = get_messages_col(room)
    uid = ObjectId(user_id)
    cid = ObjectId(contact_id)

    match = {
        "sender_id": {"$in": [uid, cid]},
        "receiver_id": {"$in": [uid, cid]},
    }
    if cursor:
        match["_id"] = {"$lt": ObjectId(cursor)}

    docs = (
        col.find(match)
        .sort("_id", -1)
        .limit(limit)
    )
    return [_msg_doc_to_response(d) async for d in docs]


@app.post("/messages/{room}", response_model=MessageResponse)
async def send_message(room: str, sender_id: str, msg: MessageCreate):
    col = get_messages_col(room)
    now = datetime.now(timezone.utc)
    doc = {
        "sender_id": ObjectId(sender_id),
        "receiver_id": ObjectId(msg.receiver_id),
        "content": msg.content,
        "media_url": msg.media_url,
        "thumbnail_url": msg.thumbnail_url,
        "is_media": msg.is_media,
        "status": MessageStatus.sent.value,
        "sent_at": now,
        "received_at": None,
        "read_at": None,
    }
    if msg.reply_to:
        doc["reply_to"] = msg.reply_to.model_dump()
    result = await col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _msg_doc_to_response(doc)


@app.put("/messages/{room}/status")
async def update_status(room: str, payload: StatusUpdate):
    col = get_messages_col(room)
    oids = [ObjectId(mid) for mid in payload.message_ids]
    now = datetime.now(timezone.utc)

    update: dict = {"$set": {"status": payload.status.value}}
    if payload.status == MessageStatus.received:
        update["$set"]["received_at"] = now
    elif payload.status == MessageStatus.read:
        update["$set"]["read_at"] = now

    await col.update_many({"_id": {"$in": oids}}, update)
    return {"msg": "Status updated successfully"}


@app.post("/media", response_model=str)
async def upload_media(file: UploadFile = File(...), folder: str = ""):
    safe_name = os.path.basename(file.filename)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    safe_folder = _safe_upload_folder_path(folder) if folder else ""
    target_dir = _ensure_upload_subdir(safe_folder) if safe_folder else UPLOAD_DIR
    filepath = os.path.join(target_dir, safe_name)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return _upload_path_to_url(filepath)


@app.delete("/messages/{room}/{message_id}")
async def delete_message(room: str, message_id: str):
    col = get_messages_col(room)
    result = await col.delete_one({"_id": ObjectId(message_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"msg": "Message deleted"}


@app.get("/messages/{room}/single/{message_id}", response_model=MessageResponse)
async def get_single_message(room: str, message_id: str):
    col = get_messages_col(room)
    doc = await col.find_one({"_id": ObjectId(message_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Message not found")
    return _msg_doc_to_response(doc)


# --- Album endpoints ---

@app.get("/albums", response_model=List[AlbumResponse])
async def list_albums():
    """Return all albums (name only, no passwords)."""
    docs = albums_col.find({}, {"name": 1})
    return [{"id": str(d["_id"]), "name": d["name"]} async for d in docs]


@app.post("/albums/auth")
async def authenticate_album(payload: AlbumAuth):
    """Verify album password. Returns success or 401."""
    album = await albums_col.find_one({"_id": ObjectId(payload.album_id)})
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if not _verify_album_password(payload.password, album.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"ok": True, "album_id": str(album["_id"]), "name": album["name"]}


@app.get("/albums/{album_id}/files", response_model=List[AlbumFileResponse])
async def list_album_files(album_id: str):
    """List all files in an album (newest first)."""
    docs = album_files_col.find({"album_id": ObjectId(album_id)}).sort("_id", -1)
    return [_album_file_to_response(d) async for d in docs]


@app.post("/albums/{album_id}/files", response_model=AlbumFileResponse)
async def upload_album_file(
    album_id: str,
    file: UploadFile = File(...),
    thumbnail: Optional[UploadFile] = File(None),
    filename: str = Form(""),
    media_type: str = Form(""),
    is_video: bool = Form(False),
    file_size: int = Form(0),
):
    """Upload an encrypted media file to an album."""
    # Verify album exists
    album = await albums_col.find_one({"_id": ObjectId(album_id)})
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    album_dir = _ensure_album_upload_dir(album["name"])
    album_thumb_dir = _ensure_upload_subdir(os.path.join(album["name"], "thumbnail"))

    # Save encrypted file inside the album folder.
    safe_name = f"album_{album_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{os.path.basename(file.filename or 'file.enc')}"
    filepath = os.path.join(album_dir, safe_name)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    media_url = _upload_path_to_url(filepath)

    # Save encrypted thumbnail in the same album folder if provided.
    thumbnail_url = None
    if thumbnail:
        thumb_name = f"thumb_{safe_name}"
        thumb_path = os.path.join(album_thumb_dir, thumb_name)
        with open(thumb_path, "wb") as buffer:
            shutil.copyfileobj(thumbnail.file, buffer)
        thumbnail_url = _upload_path_to_url(thumb_path)

    now = datetime.now(timezone.utc)
    doc = {
        "album_id": ObjectId(album_id),
        "filename": filename or file.filename or "unknown",
        "media_url": media_url,
        "thumbnail_url": thumbnail_url,
        "media_type": media_type or "application/octet-stream",
        "is_video": is_video,
        "file_size": file_size,
        "uploaded_at": now,
    }
    result = await album_files_col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _album_file_to_response(doc)


@app.delete("/albums/{album_id}/files/{file_id}")
async def delete_album_file(album_id: str, file_id: str):
    """Delete a file from an album."""
    doc = await album_files_col.find_one({
        "_id": ObjectId(file_id),
        "album_id": ObjectId(album_id),
    })
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    # Remove physical files
    for url_field in ["media_url", "thumbnail_url"]:
        url = doc.get(url_field)
        if url:
            fpath = _resolve_upload_path(url)
            if os.path.exists(fpath):
                os.remove(fpath)

    await album_files_col.delete_one({"_id": ObjectId(file_id)})
    return {"msg": "File deleted"}


@app.post("/save-to-album", response_model=AlbumFileResponse)
async def save_media_to_album(payload: SaveToAlbum):
    """Save a chat media file to an album by copying it into the album folder."""
    album = await albums_col.find_one({"_id": ObjectId(payload.album_id)})
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    album_dir = _ensure_album_upload_dir(album["name"])
    album_thumb_dir = _ensure_upload_subdir(os.path.join(album["name"], "thumbnail"))

    media_url, file_path = _copy_upload_url_to_dir(payload.media_url, album_dir)

    thumbnail_url = None
    if payload.thumbnail_url:
        try:
            thumbnail_url, _ = _copy_upload_url_to_dir(payload.thumbnail_url, album_thumb_dir)
        except HTTPException:
            thumbnail_url = None

    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    now = datetime.now(timezone.utc)
    doc = {
        "album_id": ObjectId(payload.album_id),
        "filename": payload.filename,
        "media_url": media_url,
        "thumbnail_url": thumbnail_url,
        "media_type": payload.media_type,
        "is_video": payload.is_video,
        "file_size": file_size,
        "uploaded_at": now,
    }
    result = await album_files_col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _album_file_to_response(doc)


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
