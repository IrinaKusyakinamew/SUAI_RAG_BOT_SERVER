"""Test conversation context."""

import asyncio
import hashlib
from datetime import datetime

# Set up path
import sys
sys.path.insert(0, '/home/gerbylev/SUAI_RAG_BOT_SERVER/src')

from dao.chat_history_dao import chat_history_dao
from db.session import set_db_session_context
from core.service import agent_service


async def test_conversation():
    """Test multi-turn conversation with context."""

    user_id = "test_user_123"
    session_id = f"tg_user_{user_id}"

    print(f"🧪 Testing conversation context for user: {user_id}")
    print(f"   Session ID: {session_id}\n")

    # Clear old test data
    session_context_id = int(hashlib.sha256(f"test_{datetime.now().isoformat()}".encode()).hexdigest()[:8], 16)
    set_db_session_context(session_id=session_context_id)

    try:
        deleted = await chat_history_dao.delete_user_history(user_id=user_id, session_id=session_id)
        print(f"✅ Cleared {deleted} old test messages\n")
    except Exception as e:
        print(f"⚠️  Warning clearing history: {e}\n")
    finally:
        set_db_session_context(session_id=None)

    # Test conversation
    messages = [
        "Привет! Меня зовут Алекс",
        "Как меня зовут?",
        "А сколько мне лет?",
    ]

    for i, msg in enumerate(messages, 1):
        print(f"\n{'='*60}")
        print(f"Message {i}: {msg}")
        print('='*60)

        # Process message
        response = await agent_service.process_message(
            user_id=user_id,
            message=msg,
            session_id=session_id,
            save_history=True
        )

        print(f"\n🤖 Bot: {response[:200]}...")

        # Check history
        session_context_id = int(hashlib.sha256(f"check_{datetime.now().isoformat()}".encode()).hexdigest()[:8], 16)
        set_db_session_context(session_id=session_context_id)

        try:
            history = await chat_history_dao.get_recent_context(
                user_id=user_id,
                limit=10,
                session_id=session_id
            )
            print(f"\n📚 History loaded: {len(history)} messages")
            for h in history:
                role = h.get('role', 'unknown')
                content = h.get('content', '')[:50]
                print(f"   - {role}: {content}...")

        finally:
            set_db_session_context(session_id=None)

        await asyncio.sleep(1)

    print("\n\n✅ Test completed!")


if __name__ == "__main__":
    asyncio.run(test_conversation())
