import telegram
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import os
from rag_sources.qdrant_search import UniversityBot, LLMGenerator
import asyncio

# Настройки
QDRANT_URL = "http://212.192.220.24:6333"
QDRANT_API_KEY = "pii5z%cE1"
TELEGRAM_TOKEN = "8477777035:AAFyXdqYx3M2UKSo3Brqbc8TvmZV2aYwKIY"
CAILA_API_KEY = "1000097868.198240.pKeMJ9397Eh0C2Ish703JfH2InBrylvoVg5cKHX1"

# Инициализируем RAG бота
bot_rag = UniversityBot(
    qdrant_url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
    llm_api_key=CAILA_API_KEY,
)

# Храним состояние пользователя
user_states = {}


# Создаем Inline-кнопки
def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📅 Расписание", callback_data="menu_schedule"),
            InlineKeyboardButton("📚 Материалы", callback_data="menu_materials")
        ],
        [
            InlineKeyboardButton("🎓 Университет", callback_data="menu_university"),
            InlineKeyboardButton("❓ Помощь", callback_data="menu_help")
        ],
        [
            InlineKeyboardButton("💬 Задать вопрос", callback_data="menu_ask"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_schedule_menu():
    keyboard = [
        [
            InlineKeyboardButton("👥 По группе", callback_data="schedule_group"),
            InlineKeyboardButton("👨‍🏫 По преподавателю", callback_data="schedule_teacher")
        ],
        [
            InlineKeyboardButton("🏢 По аудитории", callback_data="schedule_room"),
            InlineKeyboardButton("📅 По дню недели", callback_data="schedule_day")
        ],
        [
            InlineKeyboardButton("🔍 Общий поиск", callback_data="schedule_search"),
            InlineKeyboardButton("🔙 Назад", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_materials_menu():
    keyboard = [
        [
            InlineKeyboardButton("📄 Документы", callback_data="materials_docs"),
            InlineKeyboardButton("💰 Мат. помощь", callback_data="materials_financial")
        ],
        [
            InlineKeyboardButton("🏛️ Деканаты", callback_data="materials_deans"),
            InlineKeyboardButton("📞 Контакты", callback_data="materials_contacts")
        ],
        [
            InlineKeyboardButton("🎓 Поступление", callback_data="materials_admission"),
            InlineKeyboardButton("🔙 Назад", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_quick_questions_menu():
    """Меню с быстрыми вопросами"""
    keyboard = [
        [
            InlineKeyboardButton("📅 Расписание на сегодня", callback_data="quick_today"),
            InlineKeyboardButton("📅 Расписание на завтра", callback_data="quick_tomorrow")
        ],
        [
            InlineKeyboardButton("📚 Где найти методички?", callback_data="quick_methods"),
            InlineKeyboardButton("💰 Как получить стипендию?", callback_data="quick_scholarship")
        ],
        [
            InlineKeyboardButton("🏛️ Где находится деканат?", callback_data="quick_dean"),
            InlineKeyboardButton("📞 Контакты учебного отдела", callback_data="quick_contacts")
        ],
        [
            InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# Обработчики событий tg
async def start(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """👋 *Добро пожаловать в университетский помощник ГУАП!*

Я помогу вам с:
• 📅 Расписанием занятий
• 📚 Учебными материалами  
• 🎓 Информацией об университете

Выберите категорию или напишите свой вопрос:"""

    # Сбрасываем состояние пользователя
    user_id = update.effective_user.id
    if user_id in user_states:
        del user_states[user_id]

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text=welcome_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )
    else:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )


async def help_command(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """🤖 *Справка по использованию бота*

*Основные возможности:*
• Поиск расписания по разным критериям
• Информация об учебных материалах
• Контакты отделов и деканатов
• Ответы на вопросы об университете

*Как использовать кнопки:*
1. Нажмите на кнопку категории (например "📅 Расписание")
2. Выберите конкретный тип поиска
3. Следуйте инструкциям или используйте готовые вопросы

*Примеры запросов:*
• `расписание группы 3333`
• `где находится деканат ФИСТ`
• `как получить мат помощь`
• `контакты учебного отдела`

*Для возврата в меню нажмите /start*"""

    await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_main_menu())


async def button_callback(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на Inline-кнопки"""
    query = update.callback_query
    await query.answer()  # ОБЯЗАТЕЛЬНО вызывать в начале

    user_id = update.effective_user.id
    data = query.data

    print(f"🔘 Нажата кнопка: {data} пользователем {user_id}")

    # Обработка основных меню
    if data == "menu_main":
        await start(update, context)
        return

    elif data == "menu_schedule":
        await query.edit_message_text(
            text="📅 *Поиск расписания*\n\nВыберите тип поиска:",
            parse_mode='Markdown',
            reply_markup=get_schedule_menu()
        )
        return

    elif data == "menu_materials":
        await query.edit_message_text(
            text="📚 *Учебные материалы*\n\nВыберите категорию:",
            parse_mode='Markdown',
            reply_markup=get_materials_menu()
        )
        return

    elif data == "menu_university":
        # Предлагаем быстрые вопросы об университете
        await query.edit_message_text(
            text="🎓 *Информация об университете*\n\nВыберите интересующий вопрос:",
            parse_mode='Markdown',
            reply_markup=get_quick_questions_menu()
        )
        return

    elif data == "menu_help":
        await query.edit_message_text(
            text="❓ *Помощь*\n\nНапишите /help для подробной справки\n\nИли задайте вопрос о работе бота.",
            parse_mode='Markdown'
        )
        return

    elif data == "menu_ask":
        await query.edit_message_text(
            text="💬 *Задать вопрос*\n\nНапишите ваш вопрос в чат, и я постараюсь помочь!\n\nИли выберите один из готовых вопросов:",
            parse_mode='Markdown',
            reply_markup=get_quick_questions_menu()
        )
        return

    # Обработка кнопок расписания
    elif data == "schedule_group":
        # Сохраняем состояние пользователя
        user_states[user_id] = {"waiting_for": "group_number"}

        # Создаем кнопки с примерами групп
        keyboard = [
            [
                InlineKeyboardButton("3333", callback_data="group_3333"),
                InlineKeyboardButton("4318", callback_data="group_4318"),
                InlineKeyboardButton("ПМ-101", callback_data="group_pm101")
            ],
            [
                InlineKeyboardButton("🔍 Другая группа", callback_data="group_custom"),
                InlineKeyboardButton("🔙 Назад", callback_data="menu_schedule")
            ]
        ]

        await query.edit_message_text(
            text="👥 *Поиск расписания по группе*\n\nВыберите группу из примеров или напишите номер своей группы в чат:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "schedule_teacher":
        user_states[user_id] = {"waiting_for": "teacher_name"}

        keyboard = [
            [
                InlineKeyboardButton("Иванов", callback_data="teacher_ivanov"),
                InlineKeyboardButton("Петрова", callback_data="teacher_petrova"),
            ],
            [
                InlineKeyboardButton("🔍 Другой преподаватель", callback_data="teacher_custom"),
                InlineKeyboardButton("🔙 Назад", callback_data="menu_schedule")
            ]
        ]

        await query.edit_message_text(
            text="👨‍🏫 *Поиск расписания по преподавателю*\n\nВыберите преподавателя или напишите фамилию в чат:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "schedule_room":
        user_states[user_id] = {"waiting_for": "room_number"}

        keyboard = [
            [
                InlineKeyboardButton("52-17", callback_data="room_52-17"),
                InlineKeyboardButton("21-04", callback_data="room_21-04"),
                InlineKeyboardButton("13-14", callback_data="room_13-14")
            ],
            [
                InlineKeyboardButton("🔍 Другая аудитория", callback_data="room_custom"),
                InlineKeyboardButton("🔙 Назад", callback_data="menu_schedule")
            ]
        ]

        await query.edit_message_text(
            text="🏢 *Поиск расписания по аудитории*\n\nВыберите аудиторию или напишите номер в чат:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "schedule_day":
        user_states[user_id] = {"waiting_for": "day_of_week"}

        keyboard = [
            [
                InlineKeyboardButton("Понедельник", callback_data="day_monday"),
                InlineKeyboardButton("Вторник", callback_data="day_tuesday"),
                InlineKeyboardButton("Среда", callback_data="day_wednesday")
            ],
            [
                InlineKeyboardButton("Четверг", callback_data="day_thursday"),
                InlineKeyboardButton("Пятница", callback_data="day_friday"),
                InlineKeyboardButton("Суббота", callback_data="day_saturday")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="menu_schedule")
            ]
        ]

        await query.edit_message_text(
            text="📅 *Поиск расписания по дню недели*\n\nВыберите день недели:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "schedule_search":
        await query.edit_message_text(
            text="🔍 *Общий поиск расписания*\n\nНапишите запрос в чат, например:\n\n• `расписание группы 3333`\n• `пары в аудитории 52-17`\n• `занятия в понедельник`\n• `расписание на следующую неделю`",
            parse_mode='Markdown'
        )
        return

    # Обработка быстрых вопросов
    elif data == "quick_today":
        await process_query_callback(query, "Какое расписание на сегодня?")
        return

    elif data == "quick_tomorrow":
        await process_query_callback(query, "Какое расписание на завтра?")
        return

    elif data == "quick_methods":
        await process_query_callback(query, "Где найти методические материалы?")
        return

    elif data == "quick_scholarship":
        await process_query_callback(query, "Как получить стипендию?")
        return

    elif data == "quick_dean":
        await process_query_callback(query, "Где находится деканат моего факультета?")
        return

    elif data == "quick_contacts":
        await process_query_callback(query, "Какие контакты учебного отдела?")
        return

    # Обработка кнопок материалов
    elif data == "materials_docs":
        await process_query_callback(query, "Какие документы нужны для поступления?")
        return

    elif data == "materials_financial":
        await process_query_callback(query, "Как получить материальную помощь?")
        return

    elif data == "materials_deans":
        await process_query_callback(query, "Где найти контакты деканатов всех факультетов?")
        return

    elif data == "materials_contacts":
        await process_query_callback(query, "Какие есть контакты отделов университета?")
        return

    elif data == "materials_admission":
        await process_query_callback(query, "Как поступить в университет? Какие есть направления?")
        return

    # Обработка конкретных групп
    elif data.startswith("group_"):
        group_name = data.replace("group_", "")
        if group_name == "custom":
            await query.edit_message_text(
                text="👥 *Введите номер группы*\n\nНапишите номер группы в чат (например: 3333, 4318, ПМ-101):",
                parse_mode='Markdown'
            )
        else:
            await process_query_callback(query, f"расписание группы {group_name}")
        return

    # Обработка конкретных преподавателей
    elif data.startswith("teacher_"):
        teacher_name = data.replace("teacher_", "")
        if teacher_name == "custom":
            await query.edit_message_text(
                text="👨‍🏫 *Введите фамилию преподавателя*\n\nНапишите фамилию преподавателя в чат:",
                parse_mode='Markdown'
            )
        else:
            await process_query_callback(query, f"расписание преподавателя {teacher_name}")
        return

    # Обработка конкретных аудиторий
    elif data.startswith("room_"):
        room_number = data.replace("room_", "")
        if room_number == "custom":
            await query.edit_message_text(
                text="🏢 *Введите номер аудитории*\n\nНапишите номер аудитории в чат (например: 52-17, 21-04):",
                parse_mode='Markdown'
            )
        else:
            await process_query_callback(query, f"расписание аудитории {room_number}")
        return

    # Обработка дней недели
    elif data.startswith("day_"):
        day_map = {
            "monday": "понедельник",
            "tuesday": "вторник",
            "wednesday": "среда",
            "thursday": "четверг",
            "friday": "пятница",
            "saturday": "суббота"
        }
        day_key = data.replace("day_", "")
        if day_key in day_map:
            await process_query_callback(query, f"расписание на {day_map[day_key]}")
        return

    # Если не обработали кнопку
    await query.answer("Эта кнопка еще не настроена", show_alert=True)


async def process_query_callback(query, question: str):
    """Обрабатывает запрос из callback"""
    try:
        print(f"🔍 Обработка запроса из callback: {question}")
        result = bot_rag.process_query(question, use_llm_for_general=True)
        response_text = result.get("formatted_results", "Не удалось получить ответ")

        print(f"📤 Получен ответ длиной {len(response_text)} символов")

        # Обрезаем если слишком длинный
        if len(response_text) > 4000:
            response_text = response_text[:4000] + "\n\n... (сообщение продолжается)"

        await query.edit_message_text(
            text=f"*Ваш вопрос:* {question}\n\n{response_text}\n\n👇 *Выберите следующее действие:*",
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )

    except Exception as e:
        print(f"❌ Ошибка в process_query_callback: {e}")
        import traceback
        traceback.print_exc()
        await query.edit_message_text(
            text=f"❌ Произошла ошибка при обработке запроса: {str(e)[:100]}...\n\nПопробуйте еще раз.",
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )


async def handle_message(update: telegram.Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения"""
    question = update.message.text
    user_id = update.effective_user.id

    print(f"\n📩 Вопрос от пользователя {user_id}: '{question}'")

    # Проверяем, ждет ли бот конкретный ввод от пользователя
    if user_id in user_states:
        state = user_states[user_id]
        waiting_for = state.get("waiting_for")

        if waiting_for == "group_number":
            # Формируем запрос о расписании группы
            question = f"расписание группы {question}"
            # Сбрасываем состояние
            del user_states[user_id]

        elif waiting_for == "teacher_name":
            question = f"расписание преподавателя {question}"
            del user_states[user_id]

        elif waiting_for == "room_number":
            question = f"расписание аудитории {question}"
            del user_states[user_id]

        elif waiting_for == "day_of_week":
            question = f"расписание на {question}"
            del user_states[user_id]

    try:
        result = bot_rag.process_query(question, use_llm_for_general=True)
        response_text = result.get("formatted_results", "Не удалось получить ответ")

        print(f"📤 Тип ответа: {result.get('type')}, символов: {len(response_text)}")

        # Добавляем кнопку меню под ответом
        reply_markup = get_main_menu()

        MAX_MESSAGE_LENGTH = 4000
        if len(response_text) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(
                f"{response_text}\n\n👇 *Используйте кнопки для быстрого доступа:*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            # Разбиваем на части
            for i in range(0, len(response_text), MAX_MESSAGE_LENGTH):
                if i == 0:
                    await update.message.reply_text(response_text[i:i + MAX_MESSAGE_LENGTH])
                else:
                    await update.message.reply_text(response_text[i:i + MAX_MESSAGE_LENGTH])

            # К последнему сообщению добавляем меню
            await update.message.reply_text(
                "👇 *Используйте кнопки для быстрого доступа к функциям бота:*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

    except Exception as e:
        print(f"❌ Ошибка в handle_message: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text(
            "Произошла ошибка. Попробуйте переформулировать вопрос.",
            reply_markup=get_main_menu()
        )


# Функция для тестирования бота
async def test_bot():
    """Тестовая функция для проверки работы бота"""
    print("\n🧪 Тестирование работы бота...")

    # Тестируем обработку запросов
    test_queries = [
        "расписание группы 3333",
        "кто ректор университета",
    ]

    for query in test_queries:
        print(f"\nТестовый запрос: '{query}'")
        try:
            result = bot_rag.process_query(query, use_llm_for_general=True)
            print(f"  Результат: {result.get('type')}, найдено: {result.get('results_count')}")
            if result.get('formatted_results'):
                print(f"  Ответ: {result['formatted_results'][:100]}...")
        except Exception as e:
            print(f"  Ошибка: {e}")


if __name__ == "__main__":
    # Тестируем работу бота перед запуском
    print("=== ПРЕДВАРИТЕЛЬНОЕ ТЕСТИРОВАНИЕ ===")

    # Запускаем тест синхронно
    import asyncio

    try:
        asyncio.run(test_bot())
    except Exception as e:
        print(f"⚠️ Ошибка при тестировании: {e}")

    # Запуск телеграм бота с Inline-меню
    print("\n=== ЗАПУСК TELEGRAM БОТА С ИНТЕРАКТИВНЫМ МЕНЮ ===")

    # Создаем приложение
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Добавляем обработчики в правильном порядке
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", start))

    # ВАЖНО: CallbackQueryHandler должен быть перед MessageHandler
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    # Обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        print(f"🔥 Критическая ошибка: {context.error}")
        if update and hasattr(update, 'effective_message'):
            try:
                await update.effective_message.reply_text(
                    "Произошла критическая ошибка. Попробуйте еще раз.",
                    reply_markup=get_main_menu()
                )
            except:
                pass


    app.add_error_handler(error_handler)

    print("🤖 Bot started with interactive menu...")
    print("✅ Бот готов к работе! Откройте Telegram и нажмите /start")

    # Запускаем бота
    app.run_polling(allowed_updates=telegram.Update.ALL_TYPES)