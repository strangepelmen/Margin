import asyncio
import re
from urllib.parse import quote
from playwright.async_api import async_playwright

DEFAULT_STOP_WORDS = [
    "чехол", "стекло", "пленка", "ремешок", "коробка", "кабель", 
    "запчасти", "на запчасти", "диск", "эвакуатор", "перевозка", 
    "услуги", "аренда", "доставка", "ремонт"
]

async def scrape_kufar(query: str, limit: int = 5, stop_words: list = None, max_pages: int = 3):
    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS

    encoded_query = quote(query.strip())
    ads_data = []
    collected_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Блокируем только медиа и шрифты для быстрой загрузки
        await page.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in ["media", "font"] 
            else route.continue_()
        ))

        try:
            for current_page in range(1, max_pages + 1):
                if len(ads_data) >= limit:
                    break

                # Формируем URL с номером страницы
                url = f"https://www.kufar.by/l/r~belarus?query={encoded_query}&sort=lst.d&page={current_page}"
                
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    await page.wait_for_selector('a[class*="styles_wrapper"]', state="attached", timeout=6000)
                except Exception:
                    # Если на странице нет карточек (дошли до конца выдачи)
                    break

                cards = await page.query_selector_all('a[class*="styles_wrapper"]')
                if not cards:
                    break

                for card in cards:
                    if len(ads_data) >= limit:
                        break

                    title_elem = await card.query_selector('h3[class*="styles_title"]')
                    title = (await title_elem.inner_text()).strip() if title_elem else "Без названия"

                    # Проверка на минус-слова
                    if any(bad_word.lower() in title.lower() for bad_word in stop_words if bad_word.strip()):
                        continue

                    raw_href = await card.get_attribute("href")
                    if not raw_href or "/item/" not in raw_href:
                        continue
                    ad_url = raw_href.split("?")[0]
                    
                    id_match = re.search(r'/item/(\d+)', ad_url)
                    ad_id = id_match.group(1) if id_match else str(len(ads_data) + 1)

                    if ad_id in collected_ids:
                        continue

                    price_elem = await card.query_selector('span[class*="styles_price"]') or await card.query_selector('div[class*="styles_price_block"]')
                    price = (await price_elem.inner_text()).strip() if price_elem else "0 BYN"

                    img_elem = await card.query_selector("img")
                    img_url = None
                    if img_elem:
                        img_url = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src")

                    info_elem = await card.query_selector('div[class*="styles_secondary"]')
                    info = (await info_elem.inner_text()).strip() if info_elem else "Беларусь"

                    collected_ids.add(ad_id)
                    ads_data.append({
                        "id": ad_id,
                        "title": title,
                        "price": price,
                        "url": ad_url,
                        "image": img_url,
                        "location": info
                    })

        except Exception as e:
            print(f"[scraper] parse error [{query}]: {e}")
        finally:
            await browser.close()

    return ads_data