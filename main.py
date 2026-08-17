import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from database import (
    add_seen_ads_db,
    get_all_users_with_queries_db,
    init_db,
    is_ad_seen_db,
)
from dotenv import load_dotenv
from handlers import ads_cache
from handlers import router as margin_router
from keyboards import get_card_keyboard
from parser import scrape_kufar

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").rstrip("/")


async def setup_bot_ui(bot: Bot):
  commands = [
      BotCommand(command="search", description="Разовый поиск лотов"),
      BotCommand(
          command="track", description="Добавить товар в авто-мониторинг"
      ),
      BotCommand(command="test", description="Быстрый тест активных запросов"),
      BotCommand(command="list", description="Список активных запросов"),
      BotCommand(command="stop", description="Остановить мониторинг"),
  ]
  await bot.set_my_commands(commands)

  if WEBAPP_URL:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Margin App", web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )


async def margin_background_watcher(bot: Bot):
  while True:
    try:
      users = await get_all_users_with_queries_db()
      for u in users:
        user_id = u["user_id"]
        queries = u.get("queries", [])
        stop_words = u.get("stop_words", [])

        for query in queries:
          fresh_ads = await scrape_kufar(query, limit=3, stop_words=stop_words)
          for ad in fresh_ads:
            ad_id = str(ad["id"])
            already_seen = await is_ad_seen_db(user_id, ad_id)

            if not already_seen:
              await add_seen_ads_db(user_id, [ad_id])
              ads_cache[ad_id] = ad

              kb = get_card_keyboard(ad, WEBAPP_URL, user_id=user_id)
              caption = (
                  f"⚡️ <b>НОВОЕ ОБЪЯВЛЕНИЕ</b> <code>[{query}]</code>\n"
                  f"<code>━━━━━━━━━━━━━━━━━━━━</code>\n"
                  f"📦 <b>{ad['title']}</b>\n"
                  f"▫️ <b>Цена:</b> <code>{ad['price']}</code>\n"
                  f"▫️ <b>Локация:</b> {ad['location']}\n"
                  f"<code>━━━━━━━━━━━━━━━━━━━━</code>"
              )
              try:
                if ad.get("image"):
                  await bot.send_photo(
                      chat_id=user_id,
                      photo=ad["image"],
                      caption=caption,
                      parse_mode="HTML",
                      reply_markup=kb,
                  )
                else:
                  await bot.send_message(
                      chat_id=user_id,
                      text=caption,
                      parse_mode="HTML",
                      reply_markup=kb,
                  )
              except Exception as send_err:
                print(f"[watcher] send error: {send_err}")
              await asyncio.sleep(1)

      await asyncio.sleep(45)
    except Exception as e:
      print(f"[watcher] loop error: {e}")
      await asyncio.sleep(10)


async def main():
  await init_db()
  session = AiohttpSession(timeout=30.0)
  bot = Bot(token=BOT_TOKEN, session=session)
  dp = Dispatcher()
  dp.include_router(margin_router)

  await setup_bot_ui(bot)
  asyncio.create_task(margin_background_watcher(bot))

  print("[main] Margin Bot service started with PostgreSQL")
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())