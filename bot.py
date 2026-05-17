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

CHOOSE_MODE, INGREDIENTS, DISH_NAME, TIME, PREFERENCES, SERVINGS = range(6)

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
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_input")],
    ])


def preferences_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Без побажань ➡️", callback_data="pref_none")],
        [InlineKeyboardButton("🥗 Дієтична", callback_data="pref_diet"),
         InlineKeyboardButton("🌶 Гостра", callback_data="pref_spicy")],
        [InlineKeyboardButton("👶 Для дітей", callback_data="pref_kids"),
         InlineKeyboardButton("🌾 Без глютену", callback_data="pref_gluten")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_time")],
    ])


def servings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 особа", callback_data="srv_1"),
         InlineKeyboardButton("2 особи", callback_data="srv_2")],
        [InlineKeyboardButton("3 особи", callback_data="srv_3"),
         InlineKeyboardButton("4 особи", callback_data="srv_4")],
        [InlineKeyboardButton("6 осіб", callback_data="srv_6"),
         InlineKeyboardButton("8 осіб", callback_data="srv_8")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_preferences")],
    ])


def new_recipe_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍳 Новий рецепт", callback_data="new_recipe"),
         InlineKeyboardButton("🔄 Рестарт", callback_data="restart")],
    ])


def new_recipe_keyboard_with_save():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Зберегти рецепт", callback_data="save_recipe")],
        [InlineKeyboardButton("🍳 Новий рецепт", callback_data="new_recipe"),
         InlineKeyboardButton("🔄 Рестарт", callback_data="restart")],
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
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                {"type": "text", "text": """Подивись на це зображення і витягни список продуктів/інгредієнтів.
Це може бути: список покупок, магазинний чек, фото холодильника, фото продуктів.
Відповідай ТІЛЬКИ українською мовою.
Поверни ТІЛЬКИ список інгредієнтів через кому, без зайвого тексту.
Якщо є кількість — вкажи її. Якщо не можеш розпізнати — напиши 'Не вдалося розпізнати продукти'."""}
            ]
        }]
    )
    return response.choices[0].message.content


async def identify_dish_from_image(image_data: bytes) -> str:
    base64_image = base64.b64encode(image_data).decode("utf-8")
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                {"type": "text", "text": """Що за страва на фото? Відповідай ТІЛЬКИ українською мовою.
Поверни ТІЛЬКИ назву страви, без зайвого тексту.
Якщо не можеш визначити страву — напиши 'Не вдалося визначити страву'."""}
            ]
        }]
    )
    return response.choices[0].message.content


def generate_recipe_by_ingredients(ingredients: str, cook_time: str, preferences: str = "", servings: int = 4) -> str:
    preferences_text = f"\nДодаткові побажання: {preferences}" if preferences else ""
    prompt = f"""Інгредієнти (з кількістю):
{ingredients}

Бажаний час приготування: {cook_time}
Кількість порцій: {servings}{preferences_text}

Створи детальний рецепт страви на {servings} порцій. Відповідай ТІЛЬКИ українською мовою.

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


def generate_recipe_by_dish(dish_name: str, cook_time: str, preferences: str = "", servings: int = 4) -> str:
    preferences_text = f"\nДодаткові побажання: {preferences}" if preferences else ""
    prompt = f"""Користувач хоче приготувати: {dish_name}
Бажаний час приготування: {cook_time}
Кількість порцій: {servings}{preferences_text}

Створи детальний покроковий рецепт на {servings} порцій. Відповідай ТІЛЬКИ українською мовою.

Формат відповіді:
🍽 **{dish_name}**

📝 **Інгредієнти:**
(повний список з точними кількостями на {servings} порцій)

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


# --- Допоміжні функції показу екранів ---

async def show_mode_screen(message, user_name: str = ""):
    text = f"👋 Привіт{', ' + user_name if user_name else ''}!\n\nЯ — твій особистий AI-кухар 🍳\n\nЯк будемо готувати?"
    await message.reply_text(text, reply_markup=mode_keyboard())


async def show_ingredients_screen(message):
    await message.reply_text(
        "🥕 Надішли інгредієнти будь-яким способом:\n\n"
        "✏️ *Текстом* — курка 500г, картопля 3шт\n"
        "🎤 *Голосом* — просто надиктуй\n"
        "📷 *Фото* — чек, список або фото продуктів\n\n"
        "◀️ /back — назад до вибору режиму",
        parse_mode="Markdown"
    )


async def show_dish_screen(message):
    await message.reply_text(
        "🍽 Надішли страву будь-яким способом:\n\n"
        "✏️ *Текстом* — Борщ, Паста карбонара\n"
        "🎤 *Голосом* — надиктуй назву страви\n"
        "📷 *Фото* — надішли фото страви\n\n"
        "◀️ /back — назад до вибору режиму",
        parse_mode="Markdown"
    )


async def show_time_screen(message):
    await message.reply_text(
        "⏱ *Скільки часу є на приготування?*",
        parse_mode="Markdown",
        reply_markup=time_keyboard()
    )


async def show_preferences_screen(message):
    await message.reply_text(
        "🎯 *Є якісь побажання?*",
        parse_mode="Markdown",
        reply_markup=preferences_keyboard()
    )


# --- Хендлери ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    user_name = update.effective_user.first_name
    await show_mode_screen(update.message, user_name)
    return CHOOSE_MODE


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🔄 Починаємо заново!")
    user_name = update.effective_user.first_name
    await show_mode_screen(update.message, user_name)
    return CHOOSE_MODE


async def back_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /back — повертає на крок назад."""
    current_state = context.user_data.get("current_state", CHOOSE_MODE)

    if current_state == INGREDIENTS or current_state == DISH_NAME:
        context.user_data.pop("ingredients", None)
        context.user_data.pop("dish_name", None)
        await update.message.reply_text("◀️ Повертаємось до вибору режиму")
        await show_mode_screen(update.message)
        context.user_data["current_state"] = CHOOSE_MODE
        return CHOOSE_MODE

    elif current_state == TIME:
        mode = context.user_data.get("mode", "ingredients")
        context.user_data.pop("cook_time", None)
        await update.message.reply_text("◀️ Повертаємось до введення")
        if mode == "dish":
            await show_dish_screen(update.message)
            context.user_data["current_state"] = DISH_NAME
            return DISH_NAME
        else:
            await show_ingredients_screen(update.message)
            context.user_data["current_state"] = INGREDIENTS
            return INGREDIENTS

    elif current_state == PREFERENCES:
        context.user_data.pop("preferences", None)
        await update.message.reply_text("◀️ Повертаємось до вибору часу")
        await show_time_screen(update.message)
        context.user_data["current_state"] = TIME
        return TIME

    else:
        await show_mode_screen(update.message)
        return CHOOSE_MODE


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "mode_ingredients":
        context.user_data["mode"] = "ingredients"
        context.user_data["current_state"] = INGREDIENTS
        await query.edit_message_text(
            "🥕 Надішли інгредієнти будь-яким способом:\n\n"
            "✏️ *Текстом* — курка 500г, картопля 3шт\n"
            "🎤 *Голосом* — просто надиктуй\n"
            "📷 *Фото* — чек, список або фото продуктів\n\n"
            "◀️ /back — назад до вибору режиму",
            parse_mode="Markdown"
        )
        return INGREDIENTS

    elif query.data == "mode_dish":
        context.user_data["mode"] = "dish"
        context.user_data["current_state"] = DISH_NAME
        await query.edit_message_text(
            "🍽 Надішли страву будь-яким способом:\n\n"
            "✏️ *Текстом* — Борщ, Паста карбонара\n"
            "🎤 *Голосом* — надиктуй назву страви\n"
            "📷 *Фото* — надішли фото страви\n\n"
            "◀️ /back — назад до вибору режиму",
            parse_mode="Markdown"
        )
        return DISH_NAME

    elif query.data == "new_recipe":
        context.user_data.clear()
        await query.message.reply_text("Як будемо готувати?", reply_markup=mode_keyboard())
        return CHOOSE_MODE

    elif query.data == "restart":
        context.user_data.clear()
        await query.message.reply_text("🔄 Починаємо заново!\n\nЯк будемо готувати?", reply_markup=mode_keyboard())
        return CHOOSE_MODE


# --- Навігація назад через кнопки ---

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_input":
        mode = context.user_data.get("mode", "ingredients")
        context.user_data.pop("cook_time", None)
        if mode == "dish":
            await query.edit_message_text(
                "🍽 Надішли страву будь-яким способом:\n\n"
                "✏️ *Текстом* — Борщ, Паста карбонара\n"
                "🎤 *Голосом* — надиктуй назву страви\n"
                "📷 *Фото* — надішли фото страви\n\n"
                "◀️ /back — назад до вибору режиму",
                parse_mode="Markdown"
            )
            context.user_data["current_state"] = DISH_NAME
            return DISH_NAME
        else:
            await query.edit_message_text(
                "🥕 Надішли інгредієнти будь-яким способом:\n\n"
                "✏️ *Текстом* — курка 500г, картопля 3шт\n"
                "🎤 *Голосом* — просто надиктуй\n"
                "📷 *Фото* — чек, список або фото продуктів\n\n"
                "◀️ /back — назад до вибору режиму",
                parse_mode="Markdown"
            )
            context.user_data["current_state"] = INGREDIENTS
            return INGREDIENTS

    elif query.data == "back_to_time":
        context.user_data.pop("preferences", None)
        await query.edit_message_text(
            "⏱ *Скільки часу є на приготування?*",
            parse_mode="Markdown",
            reply_markup=time_keyboard()
        )
        context.user_data["current_state"] = TIME
        return TIME


# --- Режим: конкретна страва ---

async def get_dish_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["dish_name"] = update.message.text
    context.user_data["current_state"] = TIME
    await update.message.reply_text(
        f"👌 Чудовий вибір! Готуємо *{update.message.text}*\n\n"
        "⏱ *Скільки часу є на приготування?*",
        parse_mode="Markdown",
        reply_markup=time_keyboard()
    )
    return TIME


async def get_dish_name_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🎤 Розпізнаю голосове повідомлення...")
    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await voice_file.download_to_drive(tmp.name)
            text = await transcribe_voice(tmp.name)
            os.unlink(tmp.name)
        await update.message.reply_text(f"✅ Розпізнано: _{text}_", parse_mode="Markdown")
        context.user_data["dish_name"] = text
        context.user_data["current_state"] = TIME
        await update.message.reply_text(
            f"👌 Готуємо *{text}*\n\n⏱ *Скільки часу є на приготування?*",
            parse_mode="Markdown",
            reply_markup=time_keyboard()
        )
        return TIME
    except Exception as e:
        logger.error(f"Помилка розпізнавання голосу: {e}")
        await update.message.reply_text("😔 Не вдалося розпізнати. Спробуй написати текстом.")
        return DISH_NAME


async def get_dish_name_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📷 Визначаю страву на фото...")
    try:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await photo_file.download_to_drive(tmp.name)
            with open(tmp.name, "rb") as f:
                image_data = f.read()
            os.unlink(tmp.name)
        dish_name = await identify_dish_from_image(image_data)
        if "Не вдалося визначити" in dish_name:
            await update.message.reply_text("😔 Не вдалося визначити страву. Спробуй написати назву текстом.")
            return DISH_NAME
        context.user_data["dish_name"] = dish_name
        context.user_data["current_state"] = TIME
        await update.message.reply_text(
            f"✅ Визначено страву: *{dish_name}*\n\n⏱ *Скільки часу є на приготування?*",
            parse_mode="Markdown",
            reply_markup=time_keyboard()
        )
        return TIME
    except Exception as e:
        logger.error(f"Помилка обробки фото страви: {e}")
        await update.message.reply_text("😔 Не вдалося обробити фото. Спробуй написати текстом.")
        return DISH_NAME


# --- Режим: за інгредієнтами ---

async def get_ingredients_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["ingredients"] = update.message.text
    context.user_data["current_state"] = TIME
    await update.message.reply_text(
        "⏱ *Скільки часу є на приготування?*",
        parse_mode="Markdown",
        reply_markup=time_keyboard()
    )
    return TIME


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
        context.user_data["current_state"] = TIME
        await update.message.reply_text(
            "⏱ *Скільки часу є на приготування?*",
            parse_mode="Markdown",
            reply_markup=time_keyboard()
        )
        return TIME
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
        context.user_data["current_state"] = TIME
        await update.message.reply_text(
            "⏱ *Скільки часу є на приготування?*",
            parse_mode="Markdown",
            reply_markup=time_keyboard()
        )
        return TIME
    except Exception as e:
        logger.error(f"Помилка обробки фото: {e}")
        await update.message.reply_text("😔 Не вдалося обробити фото. Спробуй написати текстом.")
        return INGREDIENTS


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
    context.user_data["current_state"] = PREFERENCES
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
        context.user_data.clear()
        await query.message.reply_text("Як будемо готувати?", reply_markup=mode_keyboard())
        return CHOOSE_MODE

    if query.data == "restart":
        context.user_data.clear()
        await query.message.reply_text("🔄 Починаємо заново!\n\nЯк будемо готувати?", reply_markup=mode_keyboard())
        return CHOOSE_MODE

    pref_map = {
        "pref_none": "",
        "pref_diet": "дієтична страва",
        "pref_spicy": "гострий смак",
        "pref_kids": "для дітей",
        "pref_gluten": "без глютену",
    }
    preferences = pref_map.get(query.data, "")
    pref_label = preferences if preferences else "без побажань"
    context.user_data["preferences"] = preferences
    context.user_data["current_state"] = SERVINGS
    await query.edit_message_text(f"🎯 Побажання: *{pref_label}*", parse_mode="Markdown")

    await query.message.reply_text(
        "👥 *На скільки людей готуємо?*",
        parse_mode="Markdown",
        reply_markup=servings_keyboard()
    )
    return SERVINGS



async def servings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_preferences":
        context.user_data.pop("preferences", None)
        context.user_data["current_state"] = PREFERENCES
        await query.edit_message_text(
            "🎯 *Є якісь побажання?*",
            parse_mode="Markdown",
            reply_markup=preferences_keyboard()
        )
        return PREFERENCES

    servings_map = {
        "srv_1": 1, "srv_2": 2, "srv_3": 3,
        "srv_4": 4, "srv_6": 6, "srv_8": 8,
    }
    servings = servings_map.get(query.data, 4)
    context.user_data["servings"] = servings
    await query.edit_message_text(f"👥 Порцій: *{servings}*", parse_mode="Markdown")

    cook_time = context.user_data.get("cook_time", "30 хвилин")
    mode = context.user_data.get("mode", "ingredients")
    preferences = context.user_data.get("preferences", "")

    await query.message.reply_text(
        "👨‍🍳 Готую рецепт спеціально для тебе...\n_Зачекай кілька секунд_",
        parse_mode="Markdown"
    )

    try:
        if mode == "dish":
            dish_name = context.user_data.get("dish_name", "")
            recipe = generate_recipe_by_dish(dish_name, cook_time, preferences, servings)
        else:
            ingredients = context.user_data.get("ingredients", "")
            recipe = generate_recipe_by_ingredients(ingredients, cook_time, preferences, servings)

        context.user_data["last_recipe"] = recipe
        await query.message.reply_text(recipe, parse_mode="Markdown")
        await query.message.reply_text("Смачного! 😋", reply_markup=new_recipe_keyboard_with_save())
    except Exception as e:
        logger.error(f"Помилка генерації рецепту: {e}")
        await query.message.reply_text("😔 Сталася помилка. Спробуй ще раз — напиши /start")

    return ConversationHandler.END


async def save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    recipe = context.user_data.get("last_recipe", "")
    if not recipe:
        await query.answer("😔 Рецепт не знайдено", show_alert=True)
        return ConversationHandler.END

    try:
        # Пересилаємо рецепт у Saved Messages (chat_id = user_id)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=f"❤️ *Збережений рецепт*\n\n{recipe}",
            parse_mode="Markdown"
        )
        await query.answer("✅ Рецепт збережено в Saved Messages!", show_alert=True)
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Збережено", callback_data="saved_done")],
                [InlineKeyboardButton("🍳 Новий рецепт", callback_data="new_recipe"),
                 InlineKeyboardButton("🔄 Рестарт", callback_data="restart")],
            ])
        )
    except Exception as e:
        logger.error(f"Помилка збереження: {e}")
        await query.answer("😔 Не вдалося зберегти", show_alert=True)

    return ConversationHandler.END


async def saved_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("Вже збережено ✅")
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
        "   🥕 *За інгредієнтами* — текст / голос / фото продуктів\n"
        "   🍽 *Конкретна страва* — текст / голос / фото страви\n"
        "3️⃣ Вибери час приготування\n"
        "4️⃣ Вибери побажання\n"
        "5️⃣ Отримай рецепт! 🍽\n\n"
        "Навігація:\n"
        "◀️ Кнопка *Назад* — повернутись на крок\n"
        "/back — повернутись на крок\n\n"
        "Команди:\n"
        "/start — почати\n"
        "/restart — почати заново\n"
        "/back — крок назад\n"
        "/cancel — скасувати\n"
        "/help — допомога",
        parse_mode="Markdown"
    )


def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("restart", restart_command),
            CallbackQueryHandler(mode_callback, pattern="^new_recipe$|^restart$"),
            CallbackQueryHandler(save_callback, pattern="^save_recipe$"),
            CallbackQueryHandler(saved_done_callback, pattern="^saved_done$"),
        ],
        states={
            CHOOSE_MODE: [
                CallbackQueryHandler(mode_callback, pattern="^mode_|^new_recipe$|^restart$"),
            ],
            INGREDIENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_ingredients_text),
                MessageHandler(filters.VOICE, get_ingredients_voice),
                MessageHandler(filters.PHOTO, get_ingredients_photo),
                CommandHandler("back", back_command),
            ],
            DISH_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_dish_name_text),
                MessageHandler(filters.VOICE, get_dish_name_voice),
                MessageHandler(filters.PHOTO, get_dish_name_photo),
                CommandHandler("back", back_command),
            ],
            TIME: [
                CallbackQueryHandler(time_callback, pattern="^time_"),
                CallbackQueryHandler(back_callback, pattern="^back_to_input$"),
                CommandHandler("back", back_command),
            ],
            PREFERENCES: [
                CallbackQueryHandler(preferences_callback, pattern="^pref_|^new_recipe$|^restart$"),
                CallbackQueryHandler(back_callback, pattern="^back_to_time$"),
                CommandHandler("back", back_command),
            ],
            SERVINGS: [
                CallbackQueryHandler(servings_callback, pattern="^srv_|^back_to_preferences$"),
                CallbackQueryHandler(mode_callback, pattern="^new_recipe$|^restart$"),
                CallbackQueryHandler(saved_done_callback, pattern="^saved_done$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("restart", restart_command),
            CommandHandler("back", back_command),
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Бот запущено! 🚀")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
