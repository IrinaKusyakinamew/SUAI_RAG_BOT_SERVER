import asyncio
import hashlib
from datetime import datetime
from typing import Awaitable, Callable

from aiogram import Bot, Dispatcher
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import Message, Update

from core.service import agent_service
from dao.chat_history_dao import chat_history_dao
from db.session import set_db_session_context
from utils.config import CONFIG
from utils.logger import get_logger

log = get_logger("TelegramService")


class TelegramService:
    def __init__(self):
        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self.polling_task: asyncio.Task | None = None
        self.message_handler: Callable[[Message], None | Awaitable[None]] | None = None

    async def start(self):
        if not CONFIG.telegram.enabled:
            log.info("Telegram bot is disabled in configuration")
            return

        if not CONFIG.telegram.bot_token:
            log.warning("Telegram bot token is not configured")
            return

        log.info(f"Starting Telegram bot in {CONFIG.telegram.mode} mode...")
        self.bot = Bot(token=CONFIG.telegram.bot_token)
        self.dispatcher = Dispatcher()

        @self.dispatcher.message(Command("clear"))
        async def handle_clear_command(message: Message):
            try:
                user_id = str(message.from_user.id)
                session_id = f"tg_user_{message.from_user.id}"

                log.info(f"Clearing history for user {user_id}")

                # Set up database session context
                session_context_id = int(
                    hashlib.sha256(f"clear_{user_id}_{datetime.now().isoformat()}".encode()).hexdigest()[:8],
                    16,
                )
                set_db_session_context(session_id=session_context_id)

                try:
                    deleted_count = await chat_history_dao.delete_user_history(
                        user_id=user_id,
                        session_id=session_id,
                    )
                    await message.answer(
                        f"✅ История диалога очищена ({deleted_count} сообщений удалено).\nНачнем с чистого листа!"
                    )
                    log.info(f"Cleared {deleted_count} messages for user {user_id}")
                except Exception as e:
                    log.error(f"Error clearing history: {e}", exc_info=True)
                    await message.answer("❌ Ошибка при очистке истории диалога.")
                finally:
                    set_db_session_context(session_id=None)

            except Exception as e:
                log.error(f"Error handling /clear command: {e}", exc_info=True)
                await message.answer("❌ Произошла ошибка при обработке команды.")

        @self.dispatcher.message(Command("start"))
        async def handle_start_command(message: Message):
            """Handle /start command."""
            await message.answer(
                "👋 Привет! Я AI-ассистент.\n\n"
                "Задавайте мне вопросы, и я постараюсь помочь!\n\n"
                "Команды:\n"
                "/clear - очистить историю диалога\n"
                "/start - показать это сообщение"
            )

        @self.dispatcher.message()
        async def handle_message(message: Message):
            log.info(f"Received message from {message.from_user.id}: {message.text}")

            if message.text:
                try:
                    await self.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

                    user_id = str(message.from_user.id)
                    # Use user_id as session_id to maintain context across all chats for this user
                    session_id = f"tg_user_{message.from_user.id}"

                    response = await agent_service.process_message(
                        user_id=user_id,
                        message=message.text,
                        session_id=session_id,
                        save_history=True,
                    )

                    await message.answer(response)

                except Exception as e:
                    log.error(f"Error processing message: {e}", exc_info=True)
                    await message.answer("Извините, произошла ошибка при обработке вашего сообщения.")

            if self.message_handler:
                await self.message_handler(message)

        if CONFIG.telegram.mode == "polling":
            self.polling_task = asyncio.create_task(self._run_polling())
            log.info("Telegram bot started in polling mode")
        elif CONFIG.telegram.mode == "webhook":
            log.info("Telegram bot started in webhook mode")
            raise NotImplementedError  # TODO Implement
        else:
            log.error(f"Unknown Telegram mode: {CONFIG.telegram.mode}")

    async def _run_polling(self):
        try:
            log.info("Starting Telegram polling...")
            await self.dispatcher.start_polling(self.bot, handle_signals=False)
        except asyncio.CancelledError:
            log.info("Telegram polling cancelled")
        except Exception as e:
            log.error(f"Error in Telegram polling: {e}", exc_info=True)

    async def stop(self):
        log.info("Stopping Telegram bot...")

        if CONFIG.telegram.mode == "polling" and self.polling_task:
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
        elif CONFIG.telegram.mode == "webhook" and self.bot:
            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
                log.info("Webhook deleted")
            except Exception as e:
                log.error(f"Error deleting webhook: {e}")

        if self.bot:
            await self.bot.session.close()

        log.info("Telegram bot stopped")

    def set_message_handler(self, handler: Callable[[Message], None]):
        self.message_handler = handler

    async def send_message(self, chat_id: int, text: str):
        if self.bot:
            await self.bot.send_message(chat_id=chat_id, text=text)

    async def process_update(self, update: Update):
        if self.dispatcher:
            await self.dispatcher.feed_update(self.bot, update)


telegram_service = TelegramService()
