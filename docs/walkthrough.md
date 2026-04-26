# ClickFire Walkthrough

## Overview

ClickFire is the FastAPI backend for ClickApp. It runs on Python 3.12+, uses Motor for async MongoDB access, and serves the API that powers authentication, DM history, unread counters, and encrypted media uploads.

The production runtime is the `clickfire` Docker container on Orion. Local edits are synced to that container through the configured VS Code SFTP setup.

## Repository Layout

### Production code

| File | Purpose |
|------|---------|
| [main.py](../main.py) | FastAPI app, routes, startup seeding, and CORS |
| [database.py](../database.py) | MongoDB client, collection handles, and room helpers |
| [schemas.py](../schemas.py) | Pydantic schemas and status enums |
| [Dockerfile](../Dockerfile) | Container image for the backend |
| [requirements.txt](../requirements.txt) | Python dependencies |

### Documentation

| File | Purpose |
|------|---------|
| [walkthrough.md](walkthrough.md) | High-level backend and workflow notes |

### Tools

| File | Purpose |
|------|---------|
| [debug_api.py](../tools/debug_api.py) | MongoDB inspection helper |
| [recreate_db.py](../tools/recreate_db.py) | Drop helper for development resets |
| `server_log.txt` | Generated runtime log kept out of the production root |

## Runtime Model

- The backend runs only inside the `clickfire` container on Orion.
- Commands that need execution should target the remote container through SSH, for example `ssh orion "docker logs -f --tail 50 clickfire"`.
- Do not use `scp`; the workspace sync already handles file transfer.

## Database Model

- MongoDB runs in the `clickmongo` container on Orion.
- Database name: `clickdb`.
- Main collections:
  - `users`
  - `albums`
  - `album_files`
  - `messages_private`
  - `messages_work`
  - `messages_testing`
- Each chat room has its own message collection, and room selection must go through `ROOM_COLLECTIONS` or `get_messages_col(room)`.
- Album media is stored on disk under `/app/uploads/<AlbumName>/`, using the album names seeded by the backend (`DataScript`, `Tuning`, `Drivetest`, `Optimization`).
- Album passwords are stored in MongoDB as salted PBKDF2-SHA256 hashes; plaintext passwords are not persisted.
- `POST /albums/{album_id}/files` writes new uploads directly into that album folder.
- `POST /save-to-album` copies chat media into the target album folder and stores the new album-local path in MongoDB.
- Chat media from `private`, `work`, and `testing` is stored under `/app/uploads/Private/`, `/app/uploads/Work/`, and `/app/uploads/Testing/` respectively.
- `POST /media` accepts a `folder` value for the chat room folder and writes both image/video payloads and video thumbnails into that room folder.

## API Shape

The backend exposes async endpoints for:

- `POST /login`
- `GET /contacts/{user_id}`
- `GET /messages/unread/{user_id}?room=`
- `GET /messages/{room}/{user_id}/{contact_id}?cursor=&limit=`
- `POST /messages/{room}?sender_id=X`
- `PUT /messages/{room}/status`
- `POST /media`
- `GET /uploads/{filename}`
- album-related routes for encrypted media management

## Working Rules

1. Keep all endpoint handlers async.
2. Use ObjectId cursor pagination only; do not introduce `skip()` for chat history.
3. Keep media encrypted end to end. The backend must only store and return encrypted blobs.
4. Prefer the files in `docs/` for project context before editing the related code.
5. Use the files in `tools/` for diagnostics, maintenance, and one-off operations rather than production logic.
