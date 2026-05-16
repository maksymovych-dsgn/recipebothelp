import os
import sys
import logging
import tempfile
import base64
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

INGREDIENTS, TIME, PREFERENCES = range(3)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

print(f"[STARTUP] TELEGRAM_TOKEN present: {bool(TELEGRAM_TOKEN)}", file=sys.stderr)
print(f"[STARTUP] OPENAI_API_KEY present: {bool(OPENAI_API_KEY)}", file=sys.stderr)

if not TELEGRAM_TOKEN:
    print("[ERROR] TELEGRAM_TOKEN не встановлено!", file=sys.stderr)
    sys.exit(1)

if not OPENAI_API_KEY:
    print("[ERROR] OPENAI_API_KEY не встановлено!", file=sys.stderr)
    sys.exit(1)

openai_client = OpenAI(api_key=OPENAI_API_KEY)


async def transcribe_voice(file_path: str) -> str:
    """Транскрибує голосове повідомлення через Whisper."""
    with open(file_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="uk"
        )
    return transcript.text


async def extract_ingredients_from_image(image_data: bytes) -> str:
    """Витягує інгредієнти з фото через GPT-4o Vision."""
    base64_image = base64.b64encode(image_data).decode("utf-8")

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    },
                    {
                        "type": "text",
                        "text": """Подивись на це зображення і витягни список продуктів/інгредієнтів.
Це може бути: список покупок, магазинний чек, фото холодильника, фото продуктів.
Відповідай ТІЛЬКИ українською мовою.
Поверни ТІЛЬКИ список інгредієнтів через кому, без зайвого тексту.
Якщо є кількість — вкажи її. Якщо не можеш розпізнати продукти — напиши 'Не вдалося розпізнати продукти'."""
                    }
                ]
            }
        ]
    )
    return response.choices[0].message.content


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
        "Надішли мені інгредієнти будь-яким способом:\n\n"
        "✏️ *Текстом* — курка 500г, картопля 3шт\n"
        "🎤 *Голосом* — просто надиктуй\n"
        "📷 *Фото* — чек, список покупок або фото продуктів",
        parse_mode="Markdown"
    )
    return INGREDIENTS


async def get_ingredients_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка текстових інгредієнтів."""
    context.user_data["ingredients"] = update.message.text
    return await ask_time(update, context)


async def get_ingredients_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка голосового повідомлення."""
    await update.message.reply_text("🎤 Розпізнаю голосове повідомлення...")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await voice_file.download_to_drive(tmp.name)
            text = await transcribe_voice(tmp.name)
            os.unlink(tmp.name)

        await update.message.reply_text(f"✅ Розпізнано: _{text}_", parse_mode="Markdown")
        context.user_data["ingredients"] = text
        return await ask_time(update, context)

    except Exception as e:
        logger.error(f"Помилка розпізнавання голосу: {e}")
        await update.message.reply_text(
            "😔 Не вдалося розпізнати голосове повідомлення.\nСпробуй написати текстом."
        )
        return INGREDIENTS


async def get_ingredients_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробка фото (чек, список, продукти)."""
    await update.message.reply_text("📷 Аналізую фото...")

    try:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await photo_file.download_to_drive(tmp.name)
            with open(tmp.name, "rb") as f:
                image_data = f.read()
            os.unlink(tmp.name)

        ingredients = await extract_ingredients_from_image(image_data)

        if "Не вдалося розпізнати" in ingredients:
            await update.message.reply_text(
                "😔 Не вдалося розпізнати продукти на фото.\n"
                "Спробуй надіслати чіткіше фото або напиши текстом."
            )
            return INGREDIENTS

        await update.message.reply_text(
            f"✅ Знайдені продукти:\n_{ingredients}_\n\n"
            "Якщо щось не так — напиши інгредієнти текстом.",
            parse_mode="Markdown"
        )
        context.user_data["ingredients"] = ingredients
        return await ask_time(update, context)

    except Exception as e:
        logger.error(f"Помилка обробки фото: {e}")
        await update.message.reply_text(
            "😔 Не вдалося обробити фото.\nСпробуй написати текстом."
        )
        return INGREDIENTS


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Питає про час приготування."""
    keyboard = [["15 хвилин", "30 хвилин"], ["45 хвилин", "1 година"], ["Більше години"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
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
        "Надішли інгредієнти:\n\n"
        "✏️ *Текстом* — курка 500г, картопля 3шт\n"
        "🎤 *Голосом* — просто надиктуй\n"
        "📷 *Фото* — чек, список або фото продуктів",
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
        "2️⃣ Надішли інгредієнти:\n"
        "   ✏️ текстом — _курка 400г, рис 1 склянка_\n"
        "   🎤 голосом — надиктуй список\n"
        "   📷 фото — чек, список покупок, фото продуктів\n"
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
            INGREDIENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_ingredients_text),
                MessageHandler(filters.VOICE, get_ingredients_voice),
                MessageHandler(filters.PHOTO, get_ingredients_photo),
            ],
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
