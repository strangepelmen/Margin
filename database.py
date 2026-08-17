import os
import json
import asyncio

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = False
pool = None
JSON_FALLBACK = "settings.json"

def _load_json():
    if os.path.exists(JSON_FALLBACK):
        try:
            with open(JSON_FALLBACK, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(data):
    try:
        with open(JSON_FALLBACK, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[database] json save error: {e}")

async def init_db():
    global pool, USE_POSTGRES
    if pool is not None:
        return
    if DATABASE_URL:
        try:
            import asyncpg
            
            pool = await asyncpg.create_pool(
                dsn=DATABASE_URL, 
                min_size=1, 
                max_size=5, 
                timeout=10.0,
                statement_cache_size=0
            )
            
            try:
                async with pool.acquire() as conn:
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS user_settings (
                            user_id BIGINT PRIMARY KEY,
                            queries TEXT[] DEFAULT '{}',
                            stop_words TEXT[] DEFAULT '{}',
                            search_limit INT DEFAULT 3
                        );
                        CREATE TABLE IF NOT EXISTS seen_ads (
                            user_id BIGINT,
                            ad_id VARCHAR(64),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, ad_id)
                        );
                    """)
            except Exception as tbl_err:
                # Игнорируем гонку создания таблиц, если они уже существуют в Postgres
                print(f"[database] Таблицы уже инициализированы или заняты: {tbl_err}")

            USE_POSTGRES = True
            print("[database] Успешно подключено к PostgreSQL / Supabase")
            return
        except Exception as e:
            print(f"[database] PostgreSQL/Supabase недоступен ({e}). Переключение на локальное хранилище...")
    USE_POSTGRES = False

async def get_user_config_db(user_id: int) -> dict:
    if USE_POSTGRES and pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT queries, stop_words, search_limit FROM user_settings WHERE user_id = $1", user_id)
            if not row:
                await conn.execute("INSERT INTO user_settings (user_id, queries, stop_words, search_limit) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING", user_id, [], [], 3)
                return {"queries": [], "stop_words": [], "search_limit": 3}
            return {
                "queries": row["queries"] or [],
                "stop_words": row["stop_words"] or [],
                "search_limit": row["search_limit"] or 3
            }
    else:
        data = _load_json()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {"queries": [], "stop_words": [], "seen_ids": [], "search_limit": 3}
            _save_json(data)
        return data[uid]

async def update_user_settings_db(user_id: int, queries: list, stop_words: list, search_limit: int):
    if USE_POSTGRES and pool:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_settings (user_id, queries, stop_words, search_limit)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    queries = EXCLUDED.queries,
                    stop_words = EXCLUDED.stop_words,
                    search_limit = EXCLUDED.search_limit;
            """, user_id, queries, stop_words, search_limit)
    else:
        data = _load_json()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {"queries": [], "stop_words": [], "seen_ids": [], "search_limit": 3}
        data[uid]["queries"] = queries
        data[uid]["stop_words"] = stop_words
        data[uid]["search_limit"] = search_limit
        _save_json(data)

async def get_all_users_with_queries_db():
    if USE_POSTGRES and pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id, queries, stop_words, search_limit FROM user_settings WHERE array_length(queries, 1) > 0;")
            return [dict(r) for r in rows]
    else:
        data = _load_json()
        res = []
        for uid, val in data.items():
            if val.get("queries"):
                res.append({
                    "user_id": int(uid),
                    "queries": val.get("queries", []),
                    "stop_words": val.get("stop_words", []),
                    "search_limit": val.get("search_limit", 3)
                })
        return res

async def is_ad_seen_db(user_id: int, ad_id: str) -> bool:
    if USE_POSTGRES and pool:
        async with pool.acquire() as conn:
            val = await conn.fetchval("SELECT 1 FROM seen_ads WHERE user_id = $1 AND ad_id = $2", user_id, str(ad_id))
            return val is not None
    else:
        data = _load_json()
        seen = data.get(str(user_id), {}).get("seen_ids", [])
        return str(ad_id) in seen

async def add_seen_ads_db(user_id: int, ad_ids: list[str]):
    if not ad_ids:
        return
    if USE_POSTGRES and pool:
        async with pool.acquire() as conn:
            records = [(user_id, str(aid)) for aid in ad_ids]
            await conn.executemany("INSERT INTO seen_ads (user_id, ad_id) VALUES ($1, $2) ON CONFLICT DO NOTHING;", records)
    else:
        data = _load_json()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {"queries": [], "stop_words": [], "seen_ids": [], "search_limit": 3}
        seen = set(data[uid].get("seen_ids", []))
        for aid in ad_ids:
            seen.add(str(aid))
        data[uid]["seen_ids"] = list(seen)
        _save_json(data)