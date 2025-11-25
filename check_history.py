"""Check chat history in database."""

import asyncio
import asyncpg
from datetime import datetime


async def main():
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="JustOleg1!",
        database="rag_server"
    )

    try:
        # Get all messages
        messages = await conn.fetch(
            """
            SELECT id, user_id, session_id, message_type, content, created_at
            FROM chat_history
            ORDER BY created_at DESC
            LIMIT 20
            """
        )

        print(f"📝 Last {len(messages)} messages in database:\n")
        for msg in messages:
            created = msg['created_at'].strftime('%Y-%m-%d %H:%M:%S') if msg['created_at'] else 'N/A'
            content_preview = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
            print(f"[{created}] {msg['message_type']:10} | User: {msg['user_id']:15} | Session: {msg['session_id']}")
            print(f"   Content: {content_preview}")
            print()

        # Get unique users and sessions
        stats = await conn.fetch(
            """
            SELECT
                COUNT(DISTINCT user_id) as users,
                COUNT(DISTINCT session_id) as sessions,
                COUNT(*) as total_messages
            FROM chat_history
            """
        )

        print("\n📊 Statistics:")
        print(f"  Unique users: {stats[0]['users']}")
        print(f"  Unique sessions: {stats[0]['sessions']}")
        print(f"  Total messages: {stats[0]['total_messages']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
