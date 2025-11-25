"""Apply database migration for chat history."""

import asyncio
import asyncpg


async def main():
    # Database connection parameters
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="JustOleg1!",
        database="rag_server"
    )

    try:
        # Check if table exists
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'chat_history'
            )
            """
        )

        if exists:
            print("✅ Table chat_history already exists!")

            # Show table structure
            columns = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'chat_history'
                ORDER BY ordinal_position
                """
            )
            print("\nTable structure:")
            for col in columns:
                print(f"  - {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']})")

            # Count records
            count = await conn.fetchval("SELECT COUNT(*) FROM chat_history")
            print(f"\nTotal messages in history: {count}")

        else:
            print("❌ Table chat_history does not exist. Applying migration...")

            # Read migration file
            with open('/home/gerbylev/SUAI_RAG_BOT_SERVER/migrations/002_chat_history.sql', 'r') as f:
                migration_sql = f.read()

            # Apply migration
            await conn.execute(migration_sql)
            print("✅ Migration applied successfully!")

            # Verify
            exists_now = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'chat_history'
                )
                """
            )

            if exists_now:
                print("✅ Table chat_history created successfully!")
            else:
                print("❌ Failed to create table!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
