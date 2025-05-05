import os
import logging
import json
from dotenv import load_dotenv
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread.exceptions import WorksheetNotFound
import asyncio

from db import init_db, add_user, get_all_user_ids

load_dotenv()

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Стани бота
class Form(StatesGroup):
    main_menu = State()
    event_info = State()
    payment_confirmation = State()
    payment_screenshot = State()
    customer_details = State()
    institute = State()
    ticket_quantity = State()
    pickup_date = State()
    select_location = State()
    select_time = State()
    feedback = State()

class AdminStates(StatesGroup):
    admin_menu = State()
    view_orders = State()
    process_order = State()

# Налаштування Google Таблиць
try:
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('google-credentials.json', scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open("Продаж квитків")
    
    try:
        sheet = spreadsheet.worksheet("Продажі")
    except WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Продажі", rows=100, cols=12)
        sheet.append_row([
            "Дата заявки", "Ім'я", "Інститут", "Кількість квитків", 
            "Дата отримання", "Місце отримання", "Час отримання", 
            "ID скріншоту", "ID користувача", "Username", "Статус"
        ])
    
    try:
        feedback_sheet = spreadsheet.worksheet("Feedback")
    except WorksheetNotFound:
        feedback_sheet = spreadsheet.add_worksheet(title="Feedback", rows=100, cols=5)
        feedback_sheet.append_row(["Дата", "Username", "Повідомлення", "Статус", "Відповідь"])

    try:
        tikets_sheet = spreadsheet.worksheet("Квитки")
    except WorksheetNotFound:
        tikets_sheet = spreadsheet.add_worksheet(title="Квитки", rows=100, cols=3)
        tikets_sheet.append_row(["Дата", "Місця", "Час"])

except Exception as e:
    logger.error(f"Помилка підключення до Google Sheets: {e}")
    raise

# Токен бота та ID адміністратора
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id_str.strip()) for id_str in os.getenv('TELEGRAM_ADMIN_IDS').split(',')]

if not TOKEN or not ADMIN_IDS:
    raise ValueError("Будь ласка, перевірте налаштування .env файлу - TELEGRAM_BOT_TOKEN та TELEGRAM_ADMIN_ID мають бути встановлені")

# Ініціалізація бота та диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Інформація про подію
EVENT_INFO_TEXT = """
🎟️ <b>Назва події: Останній оман</b>  
📅 <b>Дата:</b> 15 квітня 2025  
📍 <b>Місце:</b> Актова зала 1 навч. корпусу НУЛП  
🕐 <b>Час:</b> 19:30
💰 <b>Ціна:</b> Донат від 100 грн 

🌍 Земляни, так, у Вас багато проблем. Але, чи задумувались Ви, хоч на хвилину, які біди можуть бути поза межами Вашого життя? Як щодо Космосу? Які проблеми там? А найголовніше, хто і як рятує від цих проблем? 👩‍🚀

Забронюй місце на космічному борті просто зараз!  
<a href="https://send.monobank.ua/jar/29kTEwBH6b">Посилання для оплати в Monobank</a>  
Рахунок: 4441111125015101
"""

async def update_data_for_buttons(selected_date=None):
    """Отримує унікальні дати або слоти для конкретної дати"""
    records = tikets_sheet.get_all_records()
    
    if not selected_date:
        # Повертаємо унікальні дати (без дублікатів)
        return sorted({r["Дата"] for r in records if r.get("Дата")})
    
    # Повертаємо всі записи для обраної дати
    return [r for r in records if r.get("Дата") == selected_date]

async def set_bot_commands(bot: Bot, admin_ids: list[int]) -> None:
    admin_commands = [
        types.BotCommand(command="admin", description="Адмін-панель"),
        types.BotCommand(command="broadcast", description="Розсилка повідомлень")
    ]

    user_commands = [
        types.BotCommand(command="start", description="Почати роботу"),
    ]
    
    await bot.set_my_commands(user_commands)

    for admin_id in admin_ids:
        await bot.set_my_commands(commands=admin_commands + user_commands, scope=types.BotCommandScopeChat(chat_id=admin_id))
        logger.info(f"Встановлено команди для адміна {admin_id}: {[c.command for c in admin_commands + user_commands]}")

async def send_to_admin(admin_id: int, text: str) -> bool:
    try:
        await bot.send_message(admin_id, text)
        return True
    except TelegramForbiddenError:
        logger.warning(f"Бот заблокований адміном {admin_id}")
    except TelegramRetryAfter as e:
        logger.warning(f"Ліміт Telegram для адміна {admin_id}. Чекаємо {e.retry_after} сек.")
        await asyncio.sleep(e.retry_after)
        return await send_to_admin(admin_id, text)
    except Exception as e:
        logger.error(f"Помилка відправки адміну {admin_id}: {str(e)}")
    return False

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    asyncio.create_task(
        add_user(
            user_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username
        )
    )

    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Купити квиток",
        callback_data="buy_ticket")
    )
    builder.add(types.InlineKeyboardButton(
        text="Зворотній зв'язок",
        callback_data="feedback")
    )
    builder.add(types.InlineKeyboardButton(
        text='Врятувати всесвіт!',
        web_app=types.WebAppInfo(url=f'https://vchechulina.github.io/game/?username={message.from_user.username or message.from_user.id}')
    ))
    builder.adjust(2)
    
    await message.answer(
        "На бортовому компʼютері три кнопки, обирайте 👀",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.main_menu)

@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"Ваш ID: {message.from_user.id}")

@dp.callback_query(F.data == "buy_ticket", Form.main_menu)
async def process_buy_ticket(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Я оплатив(ла)",
        callback_data="paid")
    )
    
    await callback.message.edit_text(
        text=EVENT_INFO_TEXT,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.payment_confirmation)
    await callback.answer()

@dp.callback_query(F.data == "paid", Form.payment_confirmation)
async def process_paid(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(text="Будь ласка, надішліть скріншот підтвердження оплати.")
    await state.set_state(Form.payment_screenshot)
    await callback.answer()

@dp.message(Form.payment_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    
    await state.update_data(
        screenshot_file_id=photo.file_id,
        user_id=message.from_user.id,
        username=message.from_user.username
    )
    
    await message.answer("Дякуємо! Тепер введіть ваше ім'я та прізвище:")
    await state.set_state(Form.customer_details)

@dp.message(Form.customer_details)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("З якого ви інституту?")
    await state.set_state(Form.institute)

@dp.message(Form.institute)
async def process_institute(message: types.Message, state: FSMContext):
    await state.update_data(institute=message.text)
    await message.answer("Введіть кількість квитків яку ви купили:")
    await state.set_state(Form.ticket_quantity)

@dp.message(Form.ticket_quantity)
async def process_ticket_quantity(message: types.Message, state: FSMContext):
    try:
        ticket_count = int(message.text)
        if ticket_count <= 0:
            await message.answer("Будь ласка, введіть додатнє число:")
            return
            
        await state.update_data(ticket_count=ticket_count)
        
        # Отримуємо доступні дати
        dates = await update_data_for_buttons()

        if not dates:
            dates = [datetime.now().strftime('%d.%m.%Y')]
        
        builder = InlineKeyboardBuilder()
        for date in dates:
            builder.add(types.InlineKeyboardButton(
                text=date,
                callback_data=f"date_{date}")
            )
        builder.adjust(1)
        
        await message.answer(
            "Оберіть дату отримання квитка:",
            reply_markup=builder.as_markup()
        )
        await state.set_state(Form.pickup_date)
        
    except ValueError:
        await message.answer("Будь ласка, введіть число:")

@dp.callback_query(F.data == "back_to_dates", Form.select_location)
async def back_to_dates(callback: types.CallbackQuery, state: FSMContext):
    # Отримуємо доступні дати
    dates = await update_data_for_buttons()
    
    if not dates:
        dates = [datetime.now().strftime('%d.%m.%Y')]
    
    builder = InlineKeyboardBuilder()
    for date in dates:
        builder.add(types.InlineKeyboardButton(
            text=date,
            callback_data=f"date_{date}")
        )
    builder.adjust(1)
    
    await callback.message.edit_text(
        "Оберіть дату отримання квитка:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.pickup_date)
    await callback.answer()

@dp.callback_query(F.data.startswith("date_"), Form.pickup_date)
async def process_pickup_date(callback: types.CallbackQuery, state: FSMContext):
    selected_date = callback.data.replace("date_", "")
    records = await update_data_for_buttons(selected_date)
    
    # Отримуємо унікальні місця для дати
    locations = {r["Місця"] for r in records if r.get("Місця")}
    
    builder = InlineKeyboardBuilder()
    for loc in sorted(locations):
        builder.add(types.InlineKeyboardButton(
            text=loc,
            callback_data=f"loc_{selected_date}_{loc}")
        )
    builder.add(types.InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_dates")
    )
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📍 Оберіть місце отримання на {selected_date}:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.select_location)
    await state.update_data(selected_date=selected_date)

@dp.callback_query(F.data.startswith("loc_"), Form.select_location)
async def process_pickup_location(callback: types.CallbackQuery, state: FSMContext):

    _, selected_date, location = callback.data.split("_", 2)
    records = await update_data_for_buttons(selected_date)
    
    # Знаходимо всі часові слоти для обраного місця
    times = []
    for r in records:
        if r.get("Місця") == location and r.get("Час"):
            times.extend(t.strip() for t in r["Час"].split(","))
    
    builder = InlineKeyboardBuilder()
    for time in sorted(set(times)):
        builder.add(types.InlineKeyboardButton(
            text=time,
            callback_data=f"time_{selected_date}_{location}_{time}")
        )
    builder.add(types.InlineKeyboardButton(
        text="Назад",
        callback_data=f"back_to_locs_{selected_date}")
    )
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"🕒 Оберіть час отримання для {location}:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.select_time)
    await state.update_data(pickup_location=location)

@dp.callback_query(F.data.startswith("back_to_locs_"), Form.select_time)
async def back_to_locations(callback: types.CallbackQuery, state: FSMContext):
    selected_date = callback.data.replace("back_to_locs_", "")
    records = await update_data_for_buttons(selected_date)
    
    locations = {r["Місця"] for r in records if r.get("Місця")}
    
    builder = InlineKeyboardBuilder()
    for loc in sorted(locations):
        builder.add(types.InlineKeyboardButton(
            text=loc,
            callback_data=f"loc_{selected_date}_{loc}")
        )
    builder.add(types.InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_dates")
    )
    builder.adjust(1)
    
    await callback.message.edit_text(
        f"📍 Оберіть місце отримання на {selected_date}:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(Form.select_location)
    await state.update_data(selected_date=selected_date)
    await callback.answer()

@dp.callback_query(F.data.startswith("time_"), Form.select_time)
async def process_pickup_time(callback: types.CallbackQuery, state: FSMContext):
    _, date, location, time = callback.data.split("_", 3)
    user_data = await state.get_data()
    
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_data.get('name', ''),
        user_data.get('institute', ''),
        user_data.get('ticket_count', ''),
        date,
        location,
        time,
        user_data.get('screenshot_file_id', ''),
        user_data.get('user_id', ''),
        user_data.get('username', ''),
        "New"
    ]
    
    sheet.append_row(row)
    
    await callback.message.edit_text(
        text=f"<b>Дякуємо за покупку!</b>\nВаші дані збережено. Чекайте на підтвердження: \n\n"
             f"📅 Дата: {date}\n"
             f"📍 Місце: {location}\n"
             f"🕒 Час: {time}",
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "feedback", Form.main_menu)
async def process_feedback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(text="Будь ласка, напишіть ваш відгук або питання:")
    await state.set_state(Form.feedback)
    await callback.answer()

@dp.message(Form.feedback)
async def process_feedback_message(message: types.Message, state: FSMContext):
    feedback_sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        message.from_user.username,
        message.text,
        "Новий",
        "",
        message.from_user.id
    ])
    
    text = (
        f"🆕 Новий відгук від @{message.from_user.username}:\n\n"
        f"{message.text}\n\n"
        f"Щоб відповісти: /reply @{message.from_user.username} [текст]"
    )

    tasks = [send_to_admin(admin_id, text) for admin_id in ADMIN_IDS]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(results)
    logger.info(f"Надіслано {success_count}/{len(ADMIN_IDS)} адмінам")
    
    await message.answer("Дякуємо за ваш відгук! Ми з вами скоро зв'яжемось.")
    await state.clear()

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    if not message.text.startswith('/broadcast '):
        await message.answer("Використовуйте: /broadcast [текст повідомлення]")
        return
    
    broadcast_text = message.text.split('/broadcast ', 1)[1]
    asyncio.create_task(send_broadcast_to_all(broadcast_text, message.from_user.id))
    
    await message.answer("🔔 Розсилка розпочата. Повідомлення буде надіслано в фоновому режимі.")

async def send_broadcast_to_all(text: str, admin_id: int):
    try:
        user_ids = await get_all_user_ids()
        total = len(user_ids)
        success = 0
        failed = 0
        
        for user_id in user_ids:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"📢 <b>Оголошення:</b>\n\n{text}",
                    parse_mode="HTML"
                )
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.error(f"Помилка відправки user_id {user_id}: {e}")
        
        report = (
            f"📊 <b>Результат розсилки:</b>\n"
            f"• Усього отримувачів: {total}\n"
            f"• Успішно: {success}\n"
            f"• Не вдалося: {failed}"
        )
        await bot.send_message(admin_id, report, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Помилка розсилки: {e}")
        await bot.send_message(admin_id, f"❌ Помилка під час розсилки: {str(e)}")

@dp.message(Command("reply"))
async def cmd_reply(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("Неправильний формат. Використовуйте: /reply @username текст")
            return
            
        username = parts[1].replace('@', '').strip()
        reply_text = parts[2]
        
        feedback_records = feedback_sheet.get_all_records()
        
        user_feedback = None
        for record in reversed(feedback_records):
            if record.get("Username") == username:
                user_feedback = record
                break
                
        if not user_feedback:
            await message.answer(f"Відгуків від @{username} не знайдено")
            return
            
        user_id = user_feedback.get("user_id")
        if not user_id:
            await message.answer(f"Для @{username} не знайдено user_id")
            return
            
        row_num = feedback_records.index(user_feedback) + 2
        feedback_sheet.update_cell(row_num, 4, "Відповідь надіслано")
        feedback_sheet.update_cell(row_num, 5, reply_text)
        
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"📨<b>Відповідь адміністратора:</b>\n\n{reply_text}",
                parse_mode="HTML"
            )
            await message.answer(f"Повідомлення відправлено @{username}")
        except Exception as e:
            feedback_sheet.update_cell(row_num, 4, f"Помилка: {str(e)[:50]}")
            await message.answer(f"Помилка відправки: {e}")
            
    except Exception as e:
        await message.answer(f"Помилка: {e}\nВикористовуйте: /reply @username текст")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Доступ заборонено")
        return
    
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📋 Переглянути заявки"))
    builder.adjust(1)
    
    await message.answer(
        "Ви увійшли в адмін-панель:",
        reply_markup=builder.as_markup(resize_keyboard=True)
    )
    await state.set_state(AdminStates.admin_menu)

@dp.message(F.text == "📋 Переглянути заявки", AdminStates.admin_menu)
async def process_view_orders(message: types.Message, state: FSMContext):
    orders = sheet.get_all_records()
    
    unprocessed_order = None
    for order in orders:
        if order.get("Статус", "") == "New":
            unprocessed_order = order
            break
    
    if not unprocessed_order:
        await message.answer("✅ Всі заявки переглянуті! Ви вийшли з адмін-панелі", reply_markup=types.ReplyKeyboardRemove())
        return
    
    row_num = orders.index(unprocessed_order) + 2
    
    order_info = (
        f"📌 Нова заявка:\n\n"
        f'Ім`я: {unprocessed_order.get("Ім\'я", "Немає")}\n'
        f'Інститут: {unprocessed_order.get("Інститут", "Немає")}\n'
        f"Кількість квитків: {unprocessed_order.get('Кількість квитків', 'Немає')}\n"
        f"Дата отримання: {unprocessed_order.get('Дата отримання', 'Немає')}\n"
        f"Місце отримання: {unprocessed_order.get('Місце отримання', 'Немає')}\n"
        f"Час отримання: {unprocessed_order.get('Час отримання', 'Немає')}\n"
        f"Username: @{unprocessed_order.get('Username', 'Немає')}")
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve_{row_num}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{row_num}"),
            ],
            [InlineKeyboardButton(text="Закінчити перегляд", callback_data=f"stop_{row_num}")]
        ]
    )
    
    screenshot_id = unprocessed_order.get("ID скріншоту")
    if screenshot_id:
        try:
            await message.answer_photo(
                photo=screenshot_id,
                caption=order_info,
                reply_markup=keyboard
            )
        except Exception as e:
            await message.answer(f"Не вдалося відправити скріншот: {e}")
            await message.answer(
                order_info,
                reply_markup=keyboard
            )
    else:
        await message.answer(
            order_info,
            reply_markup=keyboard
        )
    
    await state.set_state(AdminStates.process_order)
    await state.update_data(current_row=row_num)

@dp.callback_query(F.data.startswith("approve_"), AdminStates.process_order)
async def process_approve(callback: types.CallbackQuery, state: FSMContext):
    row_num = int(callback.data.split("_")[1])
    
    sheet.update_cell(row_num, 11, "Підтверджено")
    
    order_data = sheet.row_values(row_num)
    if len(order_data) > 9:
        try:
            await bot.send_message(
                chat_id=order_data[8],
                text=f"🎉 Вашу оплату підтверджено! Ви зможете забрати квиток: \n\nДата: {order_data[4]}\nМісце: {order_data[5]}\nЧас: {order_data[6]}."
            )
        except Exception as e:
            logger.error(f"Не вдалося повідомити користувача: {e}")
    
    await callback.message.answer("✅ Заявку підтверджено")
    await show_next_order(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"), AdminStates.process_order)
async def process_reject(callback: types.CallbackQuery, state: FSMContext):
    row_num = int(callback.data.split("_")[1])
    
    sheet.update_cell(row_num, 11, "Відхилено")
    
    order_data = sheet.row_values(row_num)
    if len(order_data) > 9:
        try:
            await bot.send_message(
                chat_id=order_data[8],
                text="❌ Вашу оплату відхилено. Будь ласка, зверніться до адміністратора."
            )
        except Exception as e:
            logger.error(f"Не вдалося повідомити користувача: {e}")
    
    await callback.message.answer("❌ Заявку відхилено")
    await show_next_order(callback.message, state)
    await callback.answer()

@dp.callback_query(F.data.startswith("stop_"), AdminStates.process_order)
async def process_stop(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Перегляд заявок завершено. Ви вийшли з адмін-панелі", reply_markup=types.ReplyKeyboardRemove())
    await state.clear()
    await callback.answer()

async def show_next_order(message: types.Message, state: FSMContext):
    orders = sheet.get_all_records()
    
    unprocessed_order = None
    for order in orders:
        if order.get("Статус", "") == "New":
            unprocessed_order = order
            break
    
    if not unprocessed_order:
        await message.answer("✅ Всі заявки переглянуті!\nВи вийшли з адмін-панелі", reply_markup=types.ReplyKeyboardRemove())
        await state.clear()
        return
    
    row_num = orders.index(unprocessed_order) + 2
    order_info = f"📌 Нова заявка:\n\nІм\'я: {unprocessed_order.get('Ім\'я', 'Немає')}\nІнститут: {unprocessed_order.get('Інститут', 'Немає')}\nКількість квитків: {unprocessed_order.get('Кількість квитків', 'Немає')}\nДата: {unprocessed_order.get('Дата отримання', 'Немає')}\nМісце: {unprocessed_order.get('Місце отримання', 'Немає')}\nЧас: {unprocessed_order.get('Час отримання', 'Немає')}\nUsername: @{unprocessed_order.get('Username', 'Немає')}"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"approve_{row_num}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{row_num}"),
            ],
            [InlineKeyboardButton(text="Закінчити перегляд", callback_data=f"stop_{row_num}")]
        ]
    )
    
    screenshot_id = unprocessed_order.get("ID скріншоту")
    if screenshot_id:
        try:
            await message.answer_photo(photo=screenshot_id, caption=order_info, reply_markup=keyboard)
        except:
            await message.answer(order_info, reply_markup=keyboard)
    else:
        await message.answer(order_info, reply_markup=keyboard)
    
    await state.update_data(current_row=row_num)

async def on_startup(bot: Bot):
    await init_db()
    await set_bot_commands(bot, ADMIN_IDS)
    await update_data_for_buttons()

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())