# 🍳 AI Recipe Bot — Telegram

Telegram-бот, який генерує рецепти на основі твоїх інгредієнтів за допомогою Claude AI.

## Як це працює

1. Користувач вводить інгредієнти та кількість
2. Вибирає бажаний час приготування
3. Додає побажання (дієтичне, гостре тощо)
4. Бот генерує покроковий рецепт через Claude AI

---

## 🚀 Деплой (безкоштовно) на Railway

### Крок 1 — Отримай токени

**Telegram токен:**
1. Відкрий Telegram, знайди `@BotFather`
2. Напиши `/newbot`
3. Дай ім'я та username боту
4. Скопіюй токен

**Anthropic API Key:**
1. Зайди на https://console.anthropic.com
2. Settings → API Keys → Create Key
3. Скопіюй ключ

### Крок 2 — Деплой на Railway

1. Зареєструйся на https://railway.app (безкоштовно)
2. Натисни **New Project → Deploy from GitHub repo**
3. Завантаж цю папку на GitHub (або використай Railway CLI)
4. У налаштуваннях проєкту додай змінні середовища:
   ```
   TELEGRAM_TOKEN = твій_токен_від_botfather
   ANTHROPIC_API_KEY = твій_ключ_від_anthropic
   ```
5. Railway автоматично запустить бота через `Procfile`

### Альтернатива — Render.com

1. Зареєструйся на https://render.com
2. New → Background Worker
3. Підключи GitHub репо
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python bot.py`
6. Додай Environment Variables

---

## 🏃 Локальний запуск

```bash
# Встанови залежності
pip install -r requirements.txt

# Створи .env файл
cp .env.example .env
# Відредагуй .env — встав свої токени

# Запусти
python bot.py
```

---

## 📁 Структура проєкту

```
recipe-bot/
├── bot.py              # Основний код бота
├── requirements.txt    # Python залежності
├── Procfile           # Для деплою на Railway/Render
├── .env.example       # Приклад змінних середовища
└── README.md          # Ця інструкція
```

---

## 💡 Ідеї для розвитку MVP

- [ ] Зберігання улюблених рецептів (база даних)
- [ ] Фото страви через DALL-E / Stable Diffusion
- [ ] Підрахунок калорій
- [ ] Список покупок із рецепту
- [ ] Вибір кухні (українська, італійська тощо)
- [ ] Преміум підписка через Telegram Stars
