import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from aiogram import Bot
import uvicorn
from database import init_db, get_user_config_db, update_user_settings_db

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()

class BypassNgrokMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        await init_db()
        response = await call_next(request)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response

app.add_middleware(BypassNgrokMiddleware)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

class SettingsPayload(BaseModel):
    user_id: int
    queries: list[str]
    stop_words: list[str]
    search_limit: int = 3

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))

@app.get("/api/settings/{user_id}")
async def get_settings(user_id: int):
    cfg = await get_user_config_db(user_id)
    return JSONResponse(cfg)

@app.post("/api/settings")
async def save_settings(data: SettingsPayload):
    current_cfg = await get_user_config_db(data.user_id)
    old_queries = set(current_cfg.get("queries", []))
    new_queries = [q.strip() for q in data.queries if q.strip()]
    clean_stop_words = [w.strip() for w in data.stop_words if w.strip()]

    await update_user_settings_db(
        data.user_id, 
        new_queries, 
        clean_stop_words, 
        data.search_limit
    )

    added_queries = [q for q in new_queries if q not in old_queries]
    if added_queries and BOT_TOKEN:
        try:
            bot = Bot(token=BOT_TOKEN)
            q_list = ", ".join([f"<code>{q}</code>" for q in added_queries])
            await bot.send_message(
                chat_id=data.user_id,
                text=f"⚡️ <b>Парсер запущен:</b> {q_list}\n<i>Слежу за новыми лотами в фоне.</i>",
                parse_mode="HTML"
            )
            await bot.session.close()
        except Exception as e:
            print(f"[app.py] notify error: {e}")

    return JSONResponse({"status": "ok"})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)