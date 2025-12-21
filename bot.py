import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional
import logging
import os
import sys

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command, CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, time
import os

# ========== КОНФИГУРАЦИЯ ПУТЕЙ ==========
import os

# Основной путь для хранения данных (куда подключен volume)
VOLUME_PATH = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")

# Путь к базе данных ВНУТРИ volume
DB_PATH = os.path.join(VOLUME_PATH, 'voting.db')

# Путь для экспорта файлов JSON ВНУТРИ volume
JSON_EXPORT_PATH = os.path.join(VOLUME_PATH, 'exports')
os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

# Все остальные настройки (токен, ID каналов и т.д.) оставьте как есть
BOT_TOKEN = os.getenv("BOT_TOKEN")


print("=== DEBUG ENV ===")
print(f"BOT_TOKEN length: {len(os.getenv('BOT_TOKEN', 'NOT_FOUND'))}")
print(f"All keys: {list(os.environ.keys())}")
print("=== END DEBUG ===")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("CRITICAL: BOT_TOKEN is empty!")
    exit(1)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

# ========== СОЗДАНИЕ DISPATCHER (ОБЯЗАТЕЛЬНО ДО ДЕКОРАТОРОВ) ==========
dp = Dispatcher(storage=MemoryStorage())

# ========== КОНФИГУРАЦИЯ (RAILWAY) ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001178736983"))
CHANNEL_ID_2 = int(os.getenv("CHANNEL_ID_2", "-1003633293081"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@new_people32")
CHANNEL_USERNAME_2 = os.getenv("CHANNEL_USERNAME_2", "@genesis_bryansk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1388134102"))

# Пути для Railway
#BASE_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ".")
#DB_PATH = os.path.join(BASE_DIR, 'voting.db')
#JSON_EXPORT_PATH = os.path.join(BASE_DIR, 'exports')

os.makedirs(JSON_EXPORT_PATH, exist_ok=True)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_finished BOOLEAN DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        nomination_id TEXT,
        nomination_title TEXT,
        answer_text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, nomination_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bot_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message_id INTEGER,
        chat_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("БД инициализирована")

init_db()

# ========== НОМИНАЦИИ ==========
NOMINATIONS = [
    {"id": "public_space", "title": "1. Общественное пространство года", 
     "desc": "Парки, скверы, набережные и библиотеки — места в Брянске, где лично вы любите проводить время просто так, без повода"},
    {"id": "cozy_place", "title": "2. Уютное место года", 
     "desc": "Атмосферная локация в Брянске, где пауза за чашкой кофе или вечерняя встреча превращаются в маленькое личное событие"},
    {"id": "coffee_shop", "title": "3. Кофейня года", 
     "desc": "Тот самый адрес в Брянске, куда вы идете за любимым напитком, теплой атмосферой и неизменно хорошим настроением"},
    {"id": "gastro_project", "title": "4. Гастропроект года", 
     "desc": "Гастрономическое явление — ресторан, фуд-маркет или локальный бренд в Брянске, который покорил ваше сердце (и желудок)"},
    {"id": "night_location", "title": "5. Ночная локация года", 
     "desc": "Брянские бары, лаунжи и клубы с особой энергетикой, где рождаются самые запоминающиеся вечера и знакомства"},
    {"id": "discovery", "title": "6. Открытие года", 
     "desc": "Самое яркое новое место в Брянске, которое появилось в этом году в вашей жизни и мгновенно заняло место в сердце"},
    {"id": "event", "title": "7. Событие года", 
     "desc": "Брянский фестиваль, праздник или форум, который привлек вас и весь город, оставив после себя море эмоций и воспоминаний"},
    {"id": "person", "title": "8. Личность года", 
     "desc": "Политик, художник, активист или предприниматель, чьи идеи и энергия меняют Брянск к лучшему и вдохновляют вас и других"},
    {"id": "responsible_business", "title": "9. Сообщество года", 
     "desc": "Брянские сообщества, которые вкладывают душу в город: помогают, развивают, заботятся и делают жизнь вокруг ярче"},
     {"id": "responsible_business", "title": "10. Инициатива года", 
     "desc": "Соседский субботник, локальный флешмоб, предложение властей или экологический проект – нечто, что объединяет людей и делает Брянск лучше"}
]


# ========== FSM ==========
class VotingStates(StatesGroup):
    checking_subscription = State()
    voting_process = State()
    finished = State()

# ========== ФУНКЦИИ ==========
def save_message_id(user_id: int, message_id: int, chat_id: int):
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO bot_messages (user_id, message_id, chat_id) VALUES (?, ?, ?)', 
                     (user_id, message_id, chat_id))
        conn.commit()
    finally:
        conn.close()

async def delete_old_messages(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT message_id, chat_id FROM bot_messages WHERE user_id = ?', (user_id,))
        messages = cursor.fetchall()
        
        for msg_id, chat_id in messages:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                await asyncio.sleep(0.05)
            except:
                pass
        
        cursor.execute('DELETE FROM bot_messages WHERE user_id = ?', (user_id,))
        conn.commit()
    finally:
        conn.close()

async def check_subscription(user_id: int) -> bool:
    """Проверяет подписку на ОБА канала"""
    channels = [
        CHANNEL_ID,
        CHANNEL_ID_2
    ]
    
    for channel_id in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True  # Подписан на все каналы


async def ask_next_nomination(message: types.Message, state: FSMContext, user_id: int, current_index: int):
    if current_index >= len(NOMINATIONS):
        conn = get_db_connection()
        conn.execute('UPDATE users SET is_finished = 1 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        await message.answer(
            "🎉 Спасибо за ответы! Результаты будут в каналах позже. Следите за постами!\n\n"
            "<i>Вы также можете изменить свои ответы с помощью <code>/revote</code></i>",
        parse_mode="HTML"
    )
        await state.set_state(VotingStates.finished)
        return

    nomination = NOMINATIONS[current_index]
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="➡️ Пропустить", callback_data="skip_nomination"))
    
    text = f"<b>{nomination['title']}</b>\n\n<i>{nomination['desc']}</i>\n\n✏️ <b>Ваш вариант:</b>"
    
    msg = await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    save_message_id(user_id, msg.message_id, msg.chat.id)
    
    await state.update_data(current_index=current_index)
    await state.set_state(VotingStates.voting_process)

# ========== ХЕНДЛЕРЫ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    await delete_old_messages(user_id)
    
    # Текст акции
    start_text = (
        "🎉 <b>Акция «Люди любят»</b>\n\n"
        "Это открытая премия, в которой вы, как и любой другой житель Брянска, "
        "можете предложить номинантов: место, инициативу или человека, "
        "которыми вы искренне гордитесь или хотите поддержать\n\n"
        "Идея премии — заметить тех, кого любят люди, и поддержать локальные "
        "бизнесы, сообщества, личности\n\n"
        "Если вы готовы, то давайте начнем!"
    )
    
    # Создаём клавиатуру с двумя кнопками
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📖 Механика акции", callback_data="mechanics"),
        InlineKeyboardButton(text="✏️ Предложить номинантов", callback_data="start_voting")
    )
    
    msg = await message.answer(start_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    save_message_id(user_id, msg.message_id, msg.chat.id)
    
@dp.callback_query(F.data == "mechanics")
async def show_mechanics(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    mechanics_text = (
        "🔧 <b>Механика акции</b>\n\n"
        "1. <b>Сбор заявок</b>\n"
        "Через этого бота жители Брянска предлагают своих номинантов в заданных номинациях\n\n"
        "2. <b>Формирование лонг-листа</b>\n"
        "Мы получаем ваши ответы и собираем полный перечень всех предложенных мест и людей\n\n"
        "3. <b>Формирование шорт-листа</b>\n"
        "Экспертная группа формирует список финалистов – люди, места и события, "
        "которые чаще всего указывали люди\n\n"
        "4. <b>Народное голосование</b>\n"
        "Финальное голосование, где вы сможете выбрать победителей в каждой из номинаций, "
        "также будет проходить через бот, чтобы у всех была возможность поддержать фаворитов\n\n"
        "5. <b>Итоговый ивент</b>\n"
        "В конце акции мы проведем награждение: позовем жителей Брянска, "
        "пригласим номинантов и наградим победителей"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start"))
    
    msg = await callback.message.answer(mechanics_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    save_message_id(user_id, msg.message_id, msg.chat.id)
    
@dp.callback_query(F.data == "start_voting")
async def start_voting_process(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    
    # Удаляем старые сообщения
    await delete_old_messages(user_id)
    
    # ПРОВЕРКА ПОДПИСКИ НА ДВЕ ГРУППЫ
    if not await check_subscription(user_id):
        builder = InlineKeyboardBuilder()
        builder.add(
            InlineKeyboardButton(text="📢 1-й канал", url=f"https://t.me/new_people32"),
            InlineKeyboardButton(text="📢 2-й канал", url=f"https://t.me/genesis_bryansk")
        )
        builder.add(InlineKeyboardButton(text="✅ Подписался на оба", callback_data="check_sub"))
        builder.adjust(2, 1)  # ← ВАЖНО: эта строка должна быть ВНУТРИ блока if
        
        msg = await callback.message.answer(
            f"❗️ Для участия подпишись на <b>оба канала</b>:\n"
            f"• @new_people32\n"
            f"• @genesis_bryansk\n\n"
            f"После подписки нажми кнопку ⬇️",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        save_message_id(user_id, msg.message_id, msg.chat.id)
        await state.set_state(VotingStates.checking_subscription)  # ← Эта строка тоже ВНУТРИ if
        return  # ← Этот return ВНУТРИ if
    
    # Если подписан на оба - начинаем голосование (этот блок с ОТДЕЛЬНЫМ отступом)
    conn = get_db_connection()
    cursor = conn.execute('SELECT COUNT(*) FROM votes WHERE user_id = ?', (user_id,))
    answered_count = cursor.fetchone()[0]
    conn.close()
    
    await ask_next_nomination(callback.message, state, user_id, answered_count)
    
@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await delete_old_messages(user_id)
    
    # Повторно используем текст из cmd_start
    start_text = (
        "🎉 <b>Акция «Люди любят»</b>\n\n"
        "Это открытая премия, в которой вы, как и любой другой житель Брянска, "
        "можете предложить номинантов: место, инициативу или человека, "
        "которыми вы искренне гордитесь или хотите поддержать\n\n"
        "Идея премии — заметить тех, кого любят люди, и поддержать локальные "
        "бизнесы, сообщества, личности\n\n"
        "Если вы готовы, то давайте начнем!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📖 Механика акции", callback_data="mechanics"),
        InlineKeyboardButton(text="✏️ Предложить номинантов", callback_data="start_voting")
    )
    
    msg = await callback.message.answer(start_text, reply_markup=builder.as_markup(), parse_mode="HTML")
    save_message_id(user_id, msg.message_id, msg.chat.id)


@dp.callback_query(F.data == "check_sub", VotingStates.checking_subscription)
async def check_sub_cb(callback: types.CallbackQuery, state: FSMContext):
    if await check_subscription(callback.from_user.id):
        await callback.message.delete()
        await callback.answer("✅ Спасибо!")
        await ask_next_nomination(callback.message, state, callback.from_user.id, 0)
    else:
        await callback.answer("❌ Подпишитесь на канал!", show_alert=True)

@dp.message(VotingStates.voting_process, F.text)
async def handle_vote_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if len(message.text) > 200:
        await message.answer("⚠️ Ответ короче 200 символов.")
        return

    data = await state.get_data()
    current_index = data.get("current_index", 0)
    nomination = NOMINATIONS[current_index]
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO votes (user_id, nomination_id, nomination_title, answer_text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination["id"], nomination["title"], message.text))
    conn.commit()
    conn.close()

    save_message_id(user_id, message.message_id, message.chat.id)
    await delete_old_messages(user_id)
    await ask_next_nomination(message, state, user_id, current_index + 1)

@dp.callback_query(F.data == "skip_nomination", VotingStates.voting_process)
async def skip_vote(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    data = await state.get_data()
    current_index = data.get("current_index", 0)
    nomination = NOMINATIONS[current_index]
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO votes (user_id, nomination_id, nomination_title, answer_text)
        VALUES (?, ?, ?, ?)
    ''', (user_id, nomination["id"], nomination["title"], "ПРОПУЩЕНО"))
    conn.commit()
    conn.close()

    await callback.answer()
    await delete_old_messages(user_id)
    await ask_next_nomination(callback.message, state, user_id, current_index + 1)

# ========== АДМИН ==========
@dp.message(Command("results"))
async def admin_results(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    text = "📊 <b>ТОП ОТВЕТОВ</b>\n\n"
    
    for nom in NOMINATIONS:
        text += f"🔸 <b>{nom['title']}</b>\n"
        cursor.execute('''
            SELECT answer_text, COUNT(*) as cnt 
            FROM votes 
            WHERE nomination_id = ? AND answer_text != 'ПРОПУЩЕНО'
            GROUP BY LOWER(TRIM(answer_text)) 
            ORDER BY cnt DESC LIMIT 3
        ''', (nom['id'],))
        
        rows = cursor.fetchall()
        for ans, cnt in rows:
            text += f"▫️ {ans}: {cnt}\n"
        text += "\n"
    
    await message.answer(text[:4000], parse_mode="HTML")
    conn.close()

@dp.message(Command("export"))
async def admin_export(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    export_data = {"votes": []}
    
    cursor.execute('SELECT v.nomination_title, v.answer_text, u.username FROM votes v JOIN users u ON v.user_id = u.user_id')
    for row in cursor.fetchall():
        export_data["votes"].append({
            "nomination": row[0],
            "answer": row[1],
            "user": row[2]
        })
    
    filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    filepath = os.path.join(JSON_EXPORT_PATH, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
        
    await message.answer_document(FSInputFile(filepath), caption="📁 Экспорт")
    conn.close()

@dp.message(Command("testvote"))
async def admin_test(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
        
    user_id = message.from_user.id
    conn = get_db_connection()
    conn.execute('DELETE FROM votes WHERE user_id = ?', (user_id,))
    conn.execute('UPDATE users SET is_finished = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer("🔄 Тест сброшен. /start")
    
@dp.message(Command("revote"))
async def user_revote(message: types.Message, state: FSMContext):
    """Переголосовать — удаляет ВСЕ старые ответы пользователя"""
    user_id = message.from_user.id
    
    # Удаляем ВСЕ голоса пользователя
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM votes WHERE user_id = ?', (user_id,))
    cursor.execute('UPDATE users SET is_finished = 0 WHERE user_id = ?', (user_id,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    # Очищаем сообщения
    await delete_old_messages(user_id)
    
    await state.clear()
    
    await message.answer(
        f"🔄 <b>Переголосование активировано!</b>\n\n"
        f"🗑️ Удалено {deleted_count} старых ответов\n"
        f"✅ Теперь можете проголосовать заново: /start",
        parse_mode="HTML"
    )

@dp.message(Command("cleanup"))
async def admin_cleanup(message: types.Message):
    if message.from_user.id != ADMIN_ID: 
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Только удаляем старые сообщения - без VACUUM
        deleted = cursor.execute('DELETE FROM bot_messages WHERE created_at < datetime("now", "-1 day")').rowcount
        conn.commit()
        
        cursor.execute('SELECT COUNT(*) FROM votes')
        votes_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        
        await message.answer(
            f"🧹 <b>Очистка завершена!</b>\n\n"
            f"🗑️ Удалено сообщений: {deleted}\n"
            f"✅ Голосов сохранено: {votes_count}\n"
            f"👥 Пользователей: {users_count}",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()
        
@dp.message(Command("resetall"))
async def admin_reset_all(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db_connection()
    conn.execute('UPDATE users SET is_finished = 0')
    conn.commit()
    conn.close()
    await message.answer("🔄 Сброшены состояния ВСЕХ пользователей")



# ========== АВТОМАТИЧЕСКАЯ ОЧИСТКА (РАЗ В ДЕНЬ) ==========
async def daily_cleanup():
    """Автоматическая очистка - только удаление старых сообщений"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bot_messages WHERE created_at < datetime("now", "-1 day")')
        conn.commit()
        logger.info(f"✅ Ежедневная очистка: удалено {cursor.rowcount} записей")
    except Exception as e:
        logger.error(f"Ошибка очистки: {e}")
    finally:
        conn.close()


async def schedule_daily_cleanup():
    """Планировщик очистки - проверяет каждый час"""
    while True:
        now = datetime.now().time()
        cleanup_time = time(3, 0)  # 03:00
        
        if now.hour == cleanup_time.hour and now.minute == cleanup_time.minute:
            await daily_cleanup()
            await asyncio.sleep(60)  # Ждём минуту
        await asyncio.sleep(3600)  # Проверяем каждый час


# ========== ЗАПУСК ==========
async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return
    
    retry_count = 0
    max_retries = None  # Бесконечные попытки
    
    while True:
        try:
            logger.info("🚀 Бот запускается...")
            await bot.delete_webhook(drop_pending_updates=True)
            
            # Запускаем планировщик очистки в фоне
            asyncio.create_task(schedule_daily_cleanup())
            
            retry_count = 0  # Сброс счётчика при успешном запуске
            logger.info("✅ Бот успешно запущен и слушает обновления")
            await dp.start_polling(bot)
            
        except asyncio.CancelledError:
            logger.info("⚠️ Бот остановлен")
            raise
        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Ошибка в боте (попытка {retry_count}): {e}", exc_info=True)
            await asyncio.sleep(5)  # Ждём 5 секунд перед перезапуском
            logger.info(f"🔄 Перезапуск бота...")

if __name__ == "__main__":
    asyncio.run(main())