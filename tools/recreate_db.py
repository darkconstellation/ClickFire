"""Drop and recreate MongoDB collections.

Run from the repository root with: python tools/recreate_db.py
"""

import asyncio

from database import ROOM_COLLECTIONS, album_files_col, albums_col, db, users_col


async def main():
    print("Dropping collections...")
    collection_names = [
        users_col.name,
        albums_col.name,
        album_files_col.name,
        *[collection.name for collection in ROOM_COLLECTIONS.values()],
    ]

    for collection_name in dict.fromkeys(collection_names):
        await db.drop_collection(collection_name)

    print("Collections dropped. Restarting uvicorn will re-seed users via lifespan.")


if __name__ == "__main__":
    asyncio.run(main())
