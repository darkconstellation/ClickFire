"""Quick MongoDB debug script.

Run from the repository root with: python tools/debug_api.py
"""

import asyncio

from database import ROOM_COLLECTIONS, users_col


async def main():
    print("Checking users...")
    users = await users_col.find().sort("_id", 1).to_list(length=2)
    for user in users:
        print(f"  User: {user['_id']} - {user['username']}")

    if len(users) < 2:
        print("\nNot enough users to query messages.")
        return

    uid, cid = users[0]["_id"], users[1]["_id"]

    for room_name, messages_col in ROOM_COLLECTIONS.items():
        print(f"\nMessages between first two users in {room_name} room...")
        cursor = messages_col.find(
            {
                "sender_id": {"$in": [uid, cid]},
                "receiver_id": {"$in": [uid, cid]},
            }
        ).sort("_id", -1).limit(10)
        msgs = await cursor.to_list(10)
        print(f"  Found {len(msgs)} messages.")
        for msg in msgs:
            print(f"  Msg {msg['_id']}: {msg.get('content')} at {msg.get('sent_at')}")


if __name__ == "__main__":
    asyncio.run(main())
