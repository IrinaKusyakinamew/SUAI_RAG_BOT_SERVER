import telegram
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import os
from rag_sources.qdrant_search import UniversityRAGBot, LLMGenerator

# Настройки
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" # вот эту фигню поменять
COLLECTIONS = ["schedules_embeddings", "text_embeddings"]
QDRANT_URL = "http://212.192.220.24:6333"
QDRANT_API_KEY = "pii5z%cE1"

# Я хз, наверное, за такое бьют палками
TELEGRAM_TOKEN = "8477777035:AAFyXdqYx3M2UKSo3Brqbc8TvmZV2aYwKIY"

# Инициализируем RAG бота
bot_rag = UniversityRAGBot(
    embed_model=EMBED_MODEL,
    qdrant_url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    collection_names=COLLECTIONS,
)

# Инициализируем llm
llm = LLMGenerator(
    provider="caila",
    api_key="1000097868.198240.pKeMJ9397Eh0C2Ish703JfH2InBrylvoVg5cKHX1",
)

# Обработчики событий tg
async def start(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    # Отправляется при вводе команды /start
    await update.message.reply_text("Привет! Задай мне вопрос про университет.")


async def handle_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    # Обрабатывает текстовое сообщение от пользователя
    question = update.message.text

    # Поиск релевантных документов в qdrant
    docs = bot_rag.search_documents(question, top_k=10)
    # Формирование контекста для llm
    context_text = bot_rag.build_context(docs)

    # Генерация ответа
    answer = llm.generate_answer(question, context_text)

    # Отправка ответа пользователю
    await update.message.reply_text(answer)


if __name__ == "__main__":
    token = TELEGRAM_TOKEN

    # Создаем объект приложения tg бота
    app = ApplicationBuilder().token(token).build()

    # Добавляем обработчик команды /start
    app.add_handler(CommandHandler("start", start))
    # Добавляем обработчик всех текстовых сообщений (кроме команд)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started...")
    # Проверка новых сообщений
    app.run_polling()