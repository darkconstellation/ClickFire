---
description: "Use when working on ClickFire backend files, docs, tools, FastAPI routes, Pydantic schemas, Motor/MongoDB access, Docker runtime, or Orion deployment."
name: "ClickFire Project Instructions"
applyTo:
  - "**/*.py"
  - "requirements.txt"
  - "Dockerfile"
  - "**/*.md"
  - "docs/**"
  - "tools/**"
---

# ClickFire Context

- ClickFire is the FastAPI backend for ClickApp. It uses Python 3.12+, Uvicorn, Motor, and Pydantic v2.
- The service runs only on the Orion Ubuntu host inside the `clickfire` Docker container.
- Access the Linux host with `ssh orion`. When runtime commands are needed, target the remote container through SSH rather than working locally.
- Local saves are already synced to the container through the configured SFTP extension, so do not use `scp`.
- Restarting the backend container after a code change is allowed when it helps validation or recovery.
- Files in `docs/` are the source of truth for architecture notes, walkthroughs, and operator-facing documentation. Read them before changing related code.
- Files in `tools/` are non-production helpers such as debug scripts, maintenance scripts, test fixtures, and generated logs. Treat them as operator tooling, not runtime code.
- MongoDB runs on Orion in the `clickmongo` container at `orion.rftuning.id:27017`, using the `clickdb` database.
- All endpoints must stay async. Use cursor-based pagination with ObjectId `_id` cursors only; never fall back to `skip()` for chat history.
- Keep the room collections isolated: `messages_private`, `messages_work`, and `messages_testing`.
- Runtime backend code must keep media encrypted end-to-end. The backend stores and serves encrypted blobs only and must never handle media keys or plaintext files.
- For photos and videos, treat the uploaded file itself as the encrypted payload in runtime code; do not persist or transform plaintext media, extracted frames, or other unencrypted derivatives.
- Operator tooling under `tools/` may temporarily decrypt media for maintenance tasks such as thumbnail repair, but it must re-store only encrypted blobs and should never become production logic.
- Album passwords are stored as salted PBKDF2-SHA256 hashes in MongoDB (`password_hash`). Seed or migrate album passwords by refreshing the hash, not by persisting plaintext `password` values.
- Seeded users are `mici/mi123` and `fufu/fu123`; keep non-secret constants out of environment variables and never commit plaintext secrets.
- The main run command is `uvicorn main:app --port 18000 --reload`.
- When debugging, prefer direct inspection of the host, containers, or MongoDB over speculative changes.