import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest
from parser import scrape_kufar, DEFAULT_STOP_WORDS
from keyboards import get_card_keyboard
from database import (
    get_user_config_db, 
    update_user_settings_db, 
    add_seen_ads_db
)
import os
from dotenv import load_dotenv

load_dotenv()



router = Router()

WEBAPP_URL = os.getenv("WEBAPP_URL")
ads_cache = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    text = (
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "⚡️ <b>MARGIN BOT</b>\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>\n"
        "Сервис мониторинга объявлений и расчета маржинальности.\n\n"
        "<b>Команды управления:</b>\n"
        "▫️ <code>/search &lt;товар&gt;</code> — разовый поиск\n"
        "▫️ <code>/track &lt;товар&gt;</code> — добавить товар в мониторинг\n"
        "▫️ <code>/test</code> — быстрый тест всех активных запросов\n"
        "▫️ <code>/list</code> — список активных запросов\n"
        "▫️ <code>/stop</code> — остановить весь мониторинг\n"
        "<code>━━━━━━━━━━━━━━━━━━━━━━━━━━━━</code>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("test"))
async def cmd_test(message: Message):
    cfg = await get_user_config_db(message.from_user.id)
    queries = cfg.get("queries", [])
    
    if not queries:
        await message.answer("⚠️ <b>У вас нет активных запросов.</b>\nДобавьте их через Mini App или команду: <code>/track PS5</code>", parse_mode="HTML")
        return

    status = await message.answer(f"🧪 <i>Запуск быстрого теста по {len(queries)} запросам...</i>", parse_mode="HTML")

    for query in queries:
        ads = await scrape_kufar(query, limit=1, stop_words=cfg.get("stop_words", DEFAULT_STOP_WORDS))
        if ads:
            ad = ads[0]
            ads_cache[str(ad["id"])] = ad
            kb = get_card_keyboard(ad, WEBAPP_URL, user_id=message.from_user.id)
            caption = (
                f"🧪 <b>ТЕСТОВЫЙ ЛОТ</b> <code>[{query}]</code>\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
                f"📦 <b>{ad['title']}</b>\n"
                f"▫️ <b>Цена:</b> <code>{ad['price']}</code>\n"
                f"▫️ <b>Локация:</b> {ad['location']}\n"
                f"<code>━━━━━━━━━━━━━━━━━━━━</code>"
            )
            if ad.get("image"):
                await message.answer_photo(photo=ad["image"], caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await message.answer(text=caption, parse_mode="HTML", reply_markup=kb)
            await asyncio.sleep(1)
        else:
            await message.answer(f"ℹ️ По запросу <code>{query}</code> свежих объявлений не найдено.", parse_mode="HTML")

    try:
        await status.delete()
    except Exception:
        pass

@router.message(Command("search"))
async def cmd_search(message: Message):
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer("⚠️ <b>Укажите название:</b> <code>/search PS5</code>", parse_mode="HTML")
        return

    status = await message.answer(f"🔍 <i>Поиск по запросу:</i> <code>{query}</code>...", parse_mode="HTML")
    cfg = await get_user_config_db(message.from_user.id)
    
    user_limit = int(cfg.get("search_limit", 3))
    ads = await scrape_kufar(query, limit=user_limit, stop_words=cfg.get("stop_words", DEFAULT_STOP_WORDS), max_pages=3)
    
    try:
        await status.delete()
    except Exception:
        pass

    if not ads:
        await message.answer(f"❌ <b>По запросу <code>{query}</code> ничего не найдено.</b>\nПопробуйте уточнить название.", parse_mode="HTML")
        return

    for ad in ads:
        ads_cache[str(ad["id"])] = ad
        kb = get_card_keyboard(ad, WEBAPP_URL, user_id=message.from_user.id)
        caption = (
            f"📦 <b>{ad['title']}</b>\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
            f"▫️ <b>Цена:</b> <code>{ad['price']}</code>\n"
            f"▫️ <b>Локация:</b> {ad['location']}\n"
            f"<code>━━━━━━━━━━━━━━━━━━━━</code>"
        )
        if ad.get("image"):
            await message.answer_photo(photo=ad["image"], caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(text=caption, parse_mode="HTML", reply_markup=kb)

@router.message(Command("track"))
async def cmd_track(message: Message):
    query = message.text.replace("/track", "").strip()
    if not query:
        await message.answer("⚠️ <b>Укажите товар:</b> <code>/track PS5</code>", parse_mode="HTML")
        return

    cfg = await get_user_config_db(message.from_user.id)
    queries = cfg.get("queries", [])
    if query not in queries:
        queries.append(query)
        await update_user_settings_db(
            message.from_user.id, 
            queries, 
            cfg.get("stop_words", []), 
            cfg.get("search_limit", 3)
        )

    initial_ads = await scrape_kufar(query, limit=10, stop_words=cfg.get("stop_words", DEFAULT_STOP_WORDS))
    await add_seen_ads_db(message.from_user.id, [str(ad["id"]) for ad in initial_ads])

    await message.answer(
        f"⚡️ <b>Парсер Margin запущен:</b> <code>{query}</code>\n"
        f"<i>Слежу за новыми лотами в фоне.</i>",
        parse_mode="HTML"
    )

@router.message(Command("list"))
async def cmd_list(message: Message):
    cfg = await get_user_config_db(message.from_user.id)
    queries = cfg.get("queries", [])
    if not queries:
        await message.answer("ℹ️ У вас пока нет активных запросов. Добавьте: <code>/track товар</code>", parse_mode="HTML")
        return

    items = "\n".join([f"▫️ <code>{q}</code>" for q in queries])
    text = (
        "📋 <b>Ваши активные запросы:</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"{items}\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        "Чтобы остановить: <code>/stop</code>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("stop"))
async def cmd_stop(message: Message):
    cfg = await get_user_config_db(message.from_user.id)
    await update_user_settings_db(
        message.from_user.id, 
        [], 
        cfg.get("stop_words", []), 
        cfg.get("search_limit", 3)
    )
    await message.answer("🛑 <b>Все задачи мониторинга остановлены.</b>", parse_mode="HTML")

@router.callback_query(F.data.startswith("full_desc:"))
async def show_full_description(call: CallbackQuery):
    ad_id = call.data.split(":")[1]
    ad = ads_cache.get(ad_id)

    if not ad:
        await call.answer("⚠️ Данные устарели. Повторите поиск.", show_alert=True)
        return

    full_text = (
        f"📦 <b>{ad['title']}</b>\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
        f"▫️ <b>Цена:</b> <code>{ad['price']}</code>\n"
        f"▫️ <b>Локация:</b> {ad['location']}\n"
        f"▫️ <b>Ссылка:</b> {ad['url']}\n"
        f"<code>━━━━━━━━━━━━━━━━━━━━</code>"
    )

    try:
        if call.message.caption:
            await call.message.edit_caption(caption=full_text, parse_mode="HTML", reply_markup=call.message.reply_markup)
        else:
            await call.message.edit_text(text=full_text, parse_mode="HTML", reply_markup=call.message.reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise e
            
    await call.answer()