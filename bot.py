import os
import sys
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from openai import OpenAI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Стани розмови
INGREDIENTS, TIME, PREFERENCES = range(3)

# Читаємо змінні
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Діагностика
print(f"[STARTUP] TELEGRAM_TOKEN present: {bool(TELEGRAM_TOKEN)}", file=sys.stderr)
print(f"[STARTUP] OPENAI_API_KEY present: {bool(OPENAI_API_KEY)}", file=sys.stderr)

# Перевірка одразу на старті
if not TELEGRAM_TOKEN:
    print("[ERROR] TELEGRAM_TOKEN не встановлено!", file=sys.stderr)
    sys.exit(1)

if not OPENAI_API_KEY:
    print("[ERROR] OPENAI_API_KEY не встановлено!", file=sys.stderr)
    sys.exit(1)

# Ініціалізація клієнта тільки після перевірки
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def generate_recipe(ingredients: str, cook_time: str, preferences: str = "") -> str:
    """Генерує рецепт через OpenAI API."""

    preferences_text = f"\nДодаткові побажання: {preferences}" if preferences else ""

    prompt = f"""Інгредієнти (з кількістю):
{ingredients}

Бажаний час приготування: {cook_time}{preferences_text}

Створи детальний рецепт страви. Відповідай ТІЛЬКИ українською мовою.

Формат відповіді:
🍽 **Назва страви**

📝 **Інгредієнти:**
(список з точними кількостями)

⏱ **Час приготування:** X хвилин

👨‍🍳 **Приготування:**
(покрокова інструкція з нумерацією)

💡 **Порада шефа:**
(один корисний лайфхак)

Якщо з наданих інгредієнтів неможливо приготувати нічого розумного за вказаний час — чесно скажи про це і запропонуй альтернативу."""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=800,
        messages=[
            {"role": "system", "content": "Ти досвідчений шеф-кухар. Відповідаєш тільки українською мовою."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Привіт, {user_name}!\n\n"
        "Я — твій особистий AI-кухар 🍳\n\n"
        "Розкажи мені, які продукти є в тебе вдома — і я придумаю смачний рецепт!\n\n"
        "🥕 *Напиши інгредієнти та їх кількість*\n"
        "Наприклад: _курка 500г, картопля 3шт, цибуля 1шт, олія_",
        parse_mode="Markdown"
    )
    return INGREDIENTS


async def get_ingredients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ingredients"] = update.message.text
    keyboard = [["15 хвилин", "30 хвилин"], ["45 хвилин", "1 година"], ["Більше години"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "✅ Чудово! Записав інгредієнти.\n\n"
        "⏱ *Скільки часу є на приготування?*\n"
        "Вибери варіант або напиши свій:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return TIME


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["cook_time"] = update.message.text
    keyboard = [["Без побажань ➡️"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "🎯 *Є якісь побажання?*\n\n"
        "Наприклад:\n"
        "• _дієтична страва_\n"
        "• _гострий смак_\n"
        "• _для дітей_\n"
        "• _без глютену_\n\n"
        "Або натисни кнопку, щоб пропустити:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return PREFERENCES


async def generate_and_send_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preferences = update.message.text
    if preferences == "Без побажань ➡️":
        preferences = ""

    ingredients = context.user_data.get("ingredients", "")
    cook_time = context.user_data.get("cook_time", "")

    await update.message.reply_text(
        "👨‍🍳 Готую рецепт спеціально для тебе...\n_Зачекай кілька секунд_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

    try:
        recipe = generate_recipe(ingredients, cook_time, preferences)
        await update.message.reply_text(recipe, parse_mode="Markdown")
        keyboard = [["🍳 Новий рецепт"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Смачного! 😋\n\nХочеш ще один рецепт?", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Помилка генерації рецепту: {e}")
        await update.message.reply_text(
            "😔 На жаль, сталася помилка при генерації рецепту.\n"
            "Спробуй ще раз — напиши /start"
        )

    context.user_data.clear()
    return ConversationHandler.END


async def new_recipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🥕 *Напиши інгредієнти та їх кількість*\n"
        "Наприклад: _яйця 3шт, сир 100г, зелень_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return INGREDIENTS


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Добре, зупинились 👋\nКоли захочеш рецепт — просто напиши /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Як користуватись ботом:*\n\n"
        "1️⃣ Напиши /start\n"
        "2️⃣ Вкажи продукти і кількість\n"
        "   _Приклад: курка 400г, рис 1 склянка, морква 1шт_\n"
        "3️⃣ Вибери час приготування\n"
        "4️⃣ Додай побажання (за бажанням)\n"
        "5️⃣ Отримай рецепт! 🍽\n\n"
        "Команди:\n"
        "/start — почати\n"
        "/cancel — скасувати\n"
        "/help — допомога",
        parse_mode="Markdown"
    )


def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🍳 Новий рецепт$"), new_recipe),
        ],
        states={
            INGREDIENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ingredients)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            PREFERENCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_and_send_recipe)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Бот запущено! 🚀")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
