# ClickFire (Backend - FastAPI)

## Tech Stack
- **Runtime:** Python 3.12+, FastAPI, Uvicorn
- **Database Driver:** Motor (async MongoDB driver for Python)
- **Validation:** Pydantic v2

## 🌐 ENVIRONMENT: REMOTE SERVER (ORION)

- **Runtime:** This service runs STRICTLY on the **Remote Server `Orion`** (Ubuntu 22 LTS).
- **Nature:** Background Process (Headless).
- **Sync Status:** Source code is edited locally (Windows) but **EXECUTION IS 100% REMOTE**.

## ⌨️ COMMAND EXECUTION RULES

**CRITICAL:** ClickFire berjalan **HANYA** di dalam Docker container `clickfire` di server `Orion`.

- **Container Name:** `clickfire` (berada di server Orion).
- **Access Protocol:** **STRICTLY SSH**. Use `ssh orion` to connect.
- ✅ **REQUIRED:** All commands must target the remote container via SSH with pattern: `ssh orion "docker [perintah]"`

**Contoh Commands:**

- **Restart Worker:** `ssh orion "docker restart clickfire"`
- **Check Logs:** `ssh orion "docker logs -f --tail 50 clickfire"`
- **Enter Container:** `ssh orion "docker exec -it clickfire /bin/bash"`
- **No manual SCP needed:** SFTP sync is already configured in VSCode - just save the file.

## Project Structure
```
ClickFire/
├── main.py          # FastAPI app, async endpoints, CORS, startup seeding
├── schemas.py       # Pydantic schemas + MessageStatus enum
├── database.py      # Motor client, db handle, collection references
├── docs/            # Walkthroughs, architecture notes, operator-facing docs
├── tools/           # Debug scripts, maintenance helpers, generated logs
├── tools/recreate_db.py   # Drop collections helper
├── tools/debug_api.py     # Quick MongoDB debug script
└── uploads/         # Encrypted media blob storage
```

## Database — MongoDB
- **Engine:** MongoDB running in Docker container `clickmongo` on Orion
- **Host:** orion.rftuning.id
- **Port:** 27017
- **User:** gemini31
- **Auth DB:** admin
- **Target Database:** clickdb
- Password supplied via environment variable `MONGO_PASS` — never hardcode.
- **Collections:** `users` (unique index on `username`), `messages_private`, `messages_work`, `messages_testing` (each with compound index on `sender_id` + `receiver_id`)
- Each chat room (private, work, testing) has its own messages collection for full data isolation.
- All IDs are MongoDB ObjectId, serialized as strings in API responses.

## API Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/login` | Authenticate user |
| GET | `/contacts/{user_id}` | List other users (contacts) |
| GET | `/messages/unread/{user_id}?room=` | Unread message count (optional room filter) |
| GET | `/messages/{room}/{user_id}/{contact_id}?cursor=&limit=` | **Cursor-based** DM history (ObjectId cursor, DESC) |
| POST | `/messages/{room}?sender_id=X` | Send a message to a room |
| PUT | `/messages/{room}/status` | Batch update message status in a room |
| POST | `/media` | Upload encrypted media blob |
| GET | `/uploads/{filename}` | Serve encrypted media blob |

## Rooms
- **private** → `messages_private` collection
- **work** → `messages_work` collection
- **testing** → `messages_testing` collection
- Valid room names are defined in `ROOM_COLLECTIONS` dict in `database.py`.

## Collections (NoSQL Schema)
- **users:** `{ _id: ObjectId, username: str, password: str }`
- **messages_private / messages_work / messages_testing:** `{ _id: ObjectId, sender_id: ObjectId, receiver_id: ObjectId, content: str?, media_url: str?, is_media: bool, status: "sent"|"received"|"read", sent_at: datetime, received_at: datetime?, read_at: datetime? }`

## Coding Rules
1. **All endpoints must be `async`** — motor is non-blocking.
2. **Pagination: Cursor-based ONLY** — use `_id` (ObjectId) as cursor. NEVER use `skip()` for chat pagination.
3. **Media Storage (Paranoid Level 4):**
    - Backend ONLY receives, stores, and sends ENCRYPTED blobs.
    - Backend NEVER holds or processes encryption keys.
    - Client-Side Decryption only.
    - Photos and videos must be physically encrypted at the file/blob level before upload; never send or persist plaintext media or unencrypted derivatives.
4. **No plaintext passwords in committed code** — use `.env` or env vars.
5. **CORS:** Currently `allow_origins=["*"]` for development — restrict in production.
6. **Seeded Users:** `mici`/`mi123`, `fufu`/`fu123` — created on startup via lifespan.
7. **Run command:** `uvicorn main:app --port 18000 --reload`
8. **Docs and Tools:** Treat `docs/` as the source of truth for walkthroughs and architecture notes, and `tools/` as non-production helpers and logs. Read them before changing related backend code.
