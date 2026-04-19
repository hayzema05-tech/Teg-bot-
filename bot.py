# =========================
# Telegram Bot (aiogram 3.x)
# Полноценная версия под ТЗ
# =========================

import asyncio
import random
import time
import string
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

import aiosqlite

# =========================
# 🔑 ВСТАВЬ СВОЙ ТОКЕН
# =========================
TOKEN = "8592460653:AAEqZdqydZPN2wvqWB-W129Q1RRY-Q5H_h8"

# ⏱ ВРЕМЯ ПОИСКА (60 сек для теста, потом 86400)
SEARCH_DURATION = 60

bot = Bot(TOKEN)
dp = Dispatcher()
DB = "bot.db"

# =========================
# FSM (состояния)
# =========================
class Form(StatesGroup):
    deposit = State()
    search = State()

# =========================
# КНОПКИ
# =========================
def menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="💰 Пополнить"), KeyboardButton(text="🔍 Поиск")],
            [KeyboardButton(text="📜 История"), KeyboardButton(text="💸 Вывод")]
        ],
        resize_keyboard=True
    )

# =========================
# БАЗА ДАННЫХ
# =========================
async def init_db():
    async with aiosqlite.connect(DB) as db:
        # Пользователи
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            total_checks INTEGER DEFAULT 0,
            total_win REAL DEFAULT 0
        )
        """)

        # Задачи поиска
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_time INTEGER,
            end_time INTEGER,
            checks_count INTEGER,
            result_sum REAL DEFAULT 0,
            status TEXT
        )
        """)

        # История пополнений (опционально)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT
        )
        """)

        await db.commit()

# Получить или создать пользователя
async def get_user(user_id):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = await cur.fetchone()

        if not user:
            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
            return await get_user(user_id)

        return user

# =========================
# ГЕНЕРАЦИЯ СУММ (с весами)
# =========================
WEIGHTS = [
    (1, 5, 0.70),
    (6, 10, 0.20),
    (11, 20, 0.07),
    (21, 50, 0.025),
    (100, 100, 0.005)
]

def generate_amount():
    r = random.random()
    s = 0
    for low, high, w in WEIGHTS:
        s += w
        if r <= s:
            base = random.randint(low, high)

            # иногда добавляем "копейки"
            if random.random() < 0.5:
                return round(base + random.choice([0.10,0.20,0.30,0.40,0.50,0.75]), 2)

            return float(base)

def format_amount(x):
    # 1 → "1", 1.2 → "1.20"
    return str(int(x)) if x.is_integer() else f"{x:.2f}"

def generate_code():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))

# =========================
# СТАРТ
# =========================
@dp.message(Command("start"))
async def start(msg: Message):
    await get_user(msg.from_user.id)
    await msg.answer("Бот запущен", reply_markup=menu())

# =========================
# ПРОФИЛЬ
# =========================
@dp.message(Command("profile"))
@dp.message(F.text == "👤 Профиль")
async def profile(msg: Message):
    u = await get_user(msg.from_user.id)

    await msg.answer(
        f"ID: {u[0]}\n"
        f"Баланс: {u[1]} USDT\n"
        f"Чеков найдено: {u[2]}\n"
        f"Общий выигрыш: {u[3]} USDT"
    )

# =========================
# ПОПОЛНЕНИЕ (просто тест)
# =========================
@dp.message(Command("deposit"))
@dp.message(F.text == "💰 Пополнить")
async def deposit(msg: Message, state: FSMContext):
    await state.set_state(Form.deposit)
    await msg.answer("Введите сумму пополнения (10–100 USDT):")

@dp.message(Form.deposit)
async def deposit2(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text)
    except:
        return await msg.answer("Ошибка ввода")

    if amount < 10 or amount > 100:
        return await msg.answer("Можно от 10 до 100")

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (amount, msg.from_user.id)
        )
        await db.commit()

    await state.clear()
    await msg.answer(f"Баланс пополнен на {amount} USDT", reply_markup=menu())

# =========================
# ПОИСК ЧЕКОВ
# =========================
@dp.message(Command("search"))
@dp.message(F.text == "🔍 Поиск")
async def search(msg: Message, state: FSMContext):
    await state.set_state(Form.search)
    await msg.answer("Введите количество чеков (1–100):")

@dp.message(Form.search)
async def search2(msg: Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("Введите число")

    k = int(msg.text)
    uid = msg.from_user.id

    if k < 1 or k > 100:
        return await msg.answer("Диапазон 1–100")

    async with aiosqlite.connect(DB) as db:
        # проверка активной задачи
        cur = await db.execute(
            "SELECT 1 FROM tasks WHERE user_id=? AND status='pending'", (uid,))
        if await cur.fetchone():
            return await msg.answer("У вас уже есть активный поиск")

        # проверка баланса
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
        balance = (await cur.fetchone())[0]

        if balance < k:
            return await msg.answer("Недостаточно средств")

        # списание
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (k, uid))

        now = int(time.time())

        await db.execute("""
        INSERT INTO tasks (user_id, start_time, end_time, checks_count, status)
        VALUES (?, ?, ?, ?, 'pending')
        """, (uid, now, now + SEARCH_DURATION, k))

        await db.commit()

    await state.clear()
    await msg.answer("Поиск запущен (~1 минута)", reply_markup=menu())

# =========================
# ИСТОРИЯ
# =========================
@dp.message(Command("history"))
@dp.message(F.text == "📜 История")
async def history(msg: Message):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("""
        SELECT checks_count, result_sum, start_time
        FROM tasks
        WHERE user_id=? AND status='completed'
        ORDER BY id DESC LIMIT 10
        """, (msg.from_user.id,))
        rows = await cur.fetchall()

    if not rows:
        return await msg.answer("История пуста")

    text = "📜 Последние заказы:\n\n"
    for k, s, t in rows:
        dt = datetime.fromtimestamp(t)
        text += f"{dt.strftime('%d.%m %H:%M')} | {k} чеков | {s} USDT\n"

    await msg.answer(text)

# =========================
# ВЫВОД (тест)
# =========================
@dp.message(Command("withdraw"))
@dp.message(F.text == "💸 Вывод")
async def withdraw(msg: Message):
    u = await get_user(msg.from_user.id)

    if u[1] < 100:
        return await msg.answer(f"Минимум 100 USDT\nВаш баланс: {u[1]}")

    await msg.answer("Тестовый вывод выполнен")

# =========================
# WORKER (фоновые задачи)
# =========================
async def worker():
    while True:
        async with aiosqlite.connect(DB) as db:
            now = int(time.time())

            cur = await db.execute("""
            SELECT id, user_id, checks_count
            FROM tasks
            WHERE status='pending' AND end_time<=?
            """, (now,))

            tasks = await cur.fetchall()

            for tid, uid, k in tasks:
                results = []
                lines = []

                for i in range(1, k + 1):
                    amt = generate_amount()
                    results.append(amt)

                    lines.append(
                        f"{i}) https://t.me/send?start=CQ{generate_code()} - {format_amount(amt)} usdt"
                    )

                total = round(sum(results), 2)

                # обновляем статистику
                await db.execute("""
                UPDATE users
                SET total_checks = total_checks + ?, total_win = total_win + ?
                WHERE user_id=?
                """, (k, total, uid))

                # завершаем задачу
                await db.execute("""
                UPDATE tasks SET status='completed', result_sum=?
                WHERE id=?
                """, (total, tid))

                await db.commit()

                # username или fallback
                user = await bot.get_chat(uid)
                username = user.username if user.username else f"id{uid}"

                # реальный баланс
                cur2 = await db.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
                real_balance = (await cur2.fetchone())[0]

                # отправка результата
                await bot.send_message(
                    uid,
                    "Результат парсинга чеков с балансом:\n\n"
                    + "\n".join(lines)
                    + f"\n\n✔️Всего активировано на баланс пользователя {username} - {total}$"
                    + f"\n\nВаш общий баланс: {real_balance}$"
                )

        await asyncio.sleep(5)

# =========================
# ЗАПУСК
# =========================
async def main():
    await init_db()
    asyncio.create_task(worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())