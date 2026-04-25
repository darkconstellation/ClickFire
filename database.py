from motor.motor_asyncio import AsyncIOMotorClient
import os

MONGO_HOST = os.getenv("MONGO_HOST", "orion.rftuning.id")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_USER = os.getenv("MONGO_USER", "gemini31")
MONGO_PASS = os.getenv("MONGO_PASS", "bangsatloe")
MONGO_AUTH_DB = os.getenv("MONGO_AUTH_DB", "admin")
MONGO_DB = os.getenv("MONGO_DB", "clickdb")

MONGO_URL = (
    f"mongodb://{MONGO_USER}:{MONGO_PASS}"
    f"@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
    f"?authSource={MONGO_AUTH_DB}"
)

client = AsyncIOMotorClient(MONGO_URL)
db = client[MONGO_DB]

# Collections
users_col = db["users"]
albums_col = db["albums"]
album_files_col = db["album_files"]

# Per-room message collections
ROOM_COLLECTIONS = {
    "private": db["messages_private"],
    "work": db["messages_work"],
    "testing": db["messages_testing"],
}

def get_messages_col(room: str):
    """Return the messages collection for the given room name."""
    col = ROOM_COLLECTIONS.get(room)
    if col is None:
        raise ValueError(f"Unknown room: {room}")
    return col
