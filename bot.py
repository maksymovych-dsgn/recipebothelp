import os
import sys
import logging
import tempfile
import base64
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from openai import OpenAI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Стани
CHOOSE_MODE, INGREDIENTS, DISH_NAME, TIME, PREFERENCES = range(5)

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


# --- Клавіатури ---

def mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🥕 За інгредієнтами", callback_data="mode_ingredients")],
        [InlineKeyboardButton("🍽 Хочу конкретну страву", callback_data="mode_dish")],
    ])


def time_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("15 хвилин", callback_data="time_15"),
         InlineKeyboardButton("30 хвилин", callback_data="time_30")],
        [InlineKeyboardButton("45 хвилин", callback_data="time_45"),
         InlineKeyboardButton("1 година", callback_data="time_60")],
        [InlineKeyboardButton("Більше години", callback_data="time_90")],
    ])


def preferences_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Без побажань ➡️", callback_data="pref_none")],
        [InlineKeyboardButton("🥗 Дієтична", callback_data="pref_diet"),
         InlineKeyboardButton("🌶 Гостра", callback_data="pref_spicy")],
        [InlineKeyboardButton("👶 Для дітей", callback_data="pref_kids"),
         InlineKeyboardButton("🌾 Без глютену", callback_data="pref_gluten")],
    ])


def new_recipe_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍳 Новий рецепт", callback_data="new_recipe")],
    ])


# --- OpenAI функції ---

async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="uk"
        )
    return transcript.text


async def extract_ingredients_from_image(image_data: bytes) -> str:
    base64_image = base64.b64encode(image_data).decode("utf-8")
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                },
                {
                    "type": "text",
                    "text": """Подивись на це зображення і витягни список продуктів/інгредієнтів.
Це може бути: список покупок, магазинний чек, фото холодильника, фото продуктів.
Відповідай ТІЛЬКИ українською мовою.
Поверни ТІЛЬКИ список інгредієнтів через кому, без зайвого тексту.
Якщо є кількість — вкажи її. Якщо не можеш розпізнати — напиши 'Не вдалося розпізнати продукти'."""
                }
            ]
        }]
    )
    return response.choices[0].message.content


def generate_recipe_by_ingredients(ingredients: str, cook_time: str, preferences: str = "") -> str:
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
(один корисний лайфхак)"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=800,
        messages=[
            {"role": "system", "content": "Ти досвідчений шеф-кухар. Відповідаєш тільки українською мовою."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def generate_recipe_by_dish(dish_name: str, cook_time: str, preferences: str = "") -> str:
    preferences_text = f"\nДодаткові побажання: {preferences}" if preferences else ""
    prompt = f"""Користувач хоче приготувати: {dish_name}
Бажаний час приготування: {cook_time}{preferences_text}

Створи детальний покроковий рецепт. Відповідай ТІЛЬКИ українською мовою.

Формат відповіді:
🍽 **{dish_name}**

📝 **Інгредієнти:**
(повний список з точними кількостями на 2-4 порції)

⏱ **Час приготування:** X хвилин

👨‍🍳 **Приготування:**
(покрокова інструкція з нумерацією)

💡 **Порада шефа:**
(один корисний лайфхак)"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=800,
        messages=[
            {"role": "system", "content": "Ти досвідчений шеф-кухар. Відповідаєш тільки українською мовою."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


# --- Хендлери ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user_name = update.effective_user.first_name
    text = (
        f"👋 Привіт, {user_name}!\n\n"
        "Я — твій особистий AI-кухар 🍳\n\n"
        "Як будемо готувати?"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=mode_keyboard())
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=mode_keyboard())
    return CHOOSE_MODE


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🔄 Починаємо заново!")
    return await start(update, context)


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "mode_ingredients":
        context.user_data["mode"] = "ingredients"
        await query.edit_message_text(
            "🥕 Надішли інгредієнти будь-яким способом:\n\n"
            "✏️ *Текстом* — курка 500г, картопля 3шт\n"
            "🎤 *Голосом* — просто надиктуй\n"
            "📷 *Фото* — чек, список або фото продуктів",
            parse_mode="Markdown"
        )
        return INGREDIENTS

    elif query.data == "mode_dish":
        context.user_data["mode"] = "dish"
        await query.edit_message_text(
            "🍽 *Яку страву хочеш приготувати?*\n\n"
            "Напиши назву страви, наприклад:\n"
            "• _Борщ_\n"
            "• _Паста карбонара_\n"
            "• _Млинці з вишнею_",
            parse_mode="Markdown"
        )
        return DISH_NAME

    elif query.data == "new_recipe":
        return await start(update, context)


async def get_dish_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_name"] = update.message.text
    await update.message.reply_text(
        f"👌 Чудовий вибір! Готуємо *{update.message.text}*\n\n"
        "⏱ *Скільки часу є на приготування?*",
        parse_mode="Markdown",
        reply_markup=time_keyboard()
    )
    return TIME


async def get_ingredients_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ingredients"] = update.message.text
    return await ask_time(update, context)


async def get_ingredients_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        await update.message.reply_text("😔 Не вдалося розпізнати. Спробуй написати текстом.")
        return INGREDIENTS


async def get_ingredients_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            await update.message.reply_text("😔 Не вдалося розпізнати. Спробуй чіткіше фото або напиши текстом.")
            return INGREDIENTS
        await update.message.reply_text(
            f"✅ Знайдені продукти:\n_{ingredients}_\n\nЯкщо щось не так — напиши текстом.",
            parse_mode="Markdown"
        )
        context.user_data["ingredients"] = ingredients
        return await ask_time(update, context)
    except Exception as e:
        logger.error(f"Помилка обробки фото: {e}")
        await update.message.reply_text("😔 Не вдалося обробити фото. Спробуй написати текстом.")
        return INGREDIENTS


async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "⏱ *Скільки часу є на приготування?*",
        parse_mode="Markdown",
        reply_markup=time_keyboard()
    )
    return TIME


async def time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    time_map = {
        "time_15": "15 хвилин",
        "time_30": "30 хвилин",
        "time_45": "45 хвилин",
        "time_60": "1 година",
        "time_90": "Більше години",
    }
    context.user_data["cook_time"] = time_map.get(query.data, "30 хвилин")
    await query.edit_message_text(f"⏱ Час: *{context.user_data['cook_time']}*", parse_mode="Markdown")

    await query.message.reply_text(
        "🎯 *Є якісь побажання?*",
        parse_mode="Markdown",
        reply_markup=preferences_keyboard()
    )
    return PREFERENCES


async def preferences_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "new_recipe":
        return await start(update, context)

    pref_map = {
        "pref_none": "",
        "pref_diet": "дієтична страва",
        "pref_spicy": "гострий смак",
        "pref_kids": "для дітей",
        "pref_gluten": "без глютену",
    }
    preferences = pref_map.get(query.data, "")
    pref_label = preferences if preferences else "без побажань"
    await query.edit_message_text(f"🎯 Побажання: *{pref_label}*", parse_mode="Markdown")

    cook_time = context.user_data.get("cook_time", "30 хвилин")
    mode = context.user_data.get("mode", "ingredients")

    await query.message.reply_text(
        "👨‍🍳 Готую рецепт спеціально для тебе...\n_Зачекай кілька секунд_",
        parse_mode="Markdown"
    )

    try:
        if mode == "dish":
            dish_name = context.user_data.get("dish_name", "")
            recipe = generate_recipe_by_dish(dish_name, cook_time, preferences)
        else:
            ingredients = context.user_data.get("ingredients", "")
            recipe = generate_recipe_by_ingredients(ingredients, cook_time, preferences)

        await query.message.reply_text(recipe, parse_mode="Markdown")
        await query.message.reply_text("Смачного! 😋", reply_markup=new_recipe_keyboard())
    except Exception as e:
        logger.error(f"Помилка генерації рецепту: {e}")
        await query.message.reply_text("😔 Сталася помилка. Спробуй ще раз — напиши /start")

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Добре, зупинились 👋\nНапиши /start коли захочеш рецепт.")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Як користуватись ботом:*\n\n"
        "1️⃣ Напиши /start\n"
        "2️⃣ Вибери режим:\n"
        "   🥕 *За інгредієнтами* — надішли що є вдома\n"
        "   🍽 *Конкретна страва* — напиши назву\n"
        "3️⃣ Вибери час приготування\n"
        "4️⃣ Вибери побажання\n"
        "5️⃣ Отримай рецепт! 🍽\n\n"
        "Команди:\n"
        "/start — почати\n"
        "/restart — почати заново\n"
        "/cancel — скасувати\n"
        "/help — допомога",
        parse_mode="Markdown"
    )


def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("restart", restart),
        ],
        states={
            CHOOSE_MODE: [
                CallbackQueryHandler(mode_callback, pattern="^mode_|^new_recipe$"),
            ],
            INGREDIENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_ingredients_text),
                MessageHandler(filters.VOICE, get_ingredients_voice),
                MessageHandler(filters.PHOTO, get_ingredients_photo),
            ],
            DISH_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_dish_name),
            ],
            TIME: [
                CallbackQueryHandler(time_callback, pattern="^time_"),
            ],
            PREFERENCES: [
                CallbackQueryHandler(preferences_callback, pattern="^pref_|^new_recipe$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("restart", restart),
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Бот запущено! 🚀")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
