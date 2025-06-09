import asyncio, os, random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
USERNAME = os.getenv("IG_USER")
PASSWORD = os.getenv("IG_PASS")

WELCOME_TEXT = "🎉 Welcome {name}!"
PING_TEXT = "Hey {mentions}, koi online aaye? 😄"
INACTIVE_HOURS = 3
PING_COUNT = 4

async def send_message(page, text):
    try:
        box = await page.query_selector('textarea')
        if box:
            await box.type(text)
            await box.press("Enter")
    except Exception as e:
        print(f"❌ Error sending message: {e}")

async def get_all_group_threads(page):
    await page.goto("https://www.instagram.com/direct/inbox/")
    await page.wait_for_selector("div[role='dialog'] a[href*='/direct/t/']", timeout=15000)
    links = await page.query_selector_all("div[role='dialog'] a[href*='/direct/t/']")
    group_threads = {}
    for l in links:
        title = (await l.inner_text()).strip()
        href = await l.get_attribute("href")
        if "/direct/t/" in href:
            thread_id = href.split("/")[-2]
            group_threads[thread_id] = {
                "title": title,
                "last_activity": datetime.now(timezone.utc),
                "participants": []
            }
    return group_threads

async def fetch_participants(page):
    try:
        btn = await page.query_selector("header button[aria-label*='Chat details']")
        if btn:
            await btn.click()
            await page.wait_for_selector("div[role='dialog']", timeout=10000)
            user_imgs = await page.query_selector_all("div[role='dialog'] img[alt]")
            names = []
            for u in user_imgs:
                alt = await u.get_attribute("alt")
                if alt and USERNAME not in alt:
                    name = alt.split("'s")[0].strip()
                    if name:
                        names.append(name)
            await page.keyboard.press("Escape")
            return list(set(names))
    except Exception as e:
        print(f"⚠️ Failed to fetch participants: {e}")
    return []

async def handle_group(page, thread_id, state):
    group_url = f"https://www.instagram.com/direct/t/{thread_id}/"
    await page.goto(group_url)
    await page.wait_for_selector('textarea', timeout=15000)

    participants = await fetch_participants(page)
    state["participants"] = participants

    async def on_response(resp):
        if "/direct-v2/threads/" not in resp.url:
            return
        try:
            data = await resp.json()
        except:
            return
        for item in data.get("items", []):
            txt = item.get("text", "")
            ts = item.get("timestamp")
            if ts:
                # Instagram timestamps are usually in microseconds, adjust accordingly
                # But sometimes it's milliseconds, try both
                try:
                    state["last_activity"] = datetime.fromtimestamp(int(ts) / 1e6, timezone.utc)
                except:
                    try:
                        state["last_activity"] = datetime.fromtimestamp(int(ts) / 1e3, timezone.utc)
                    except:
                        pass
            if "joined" in txt.lower():
                new_user = txt.split("joined")[0].strip()
                if new_user and new_user not in state["participants"]:
                    await send_message(page, WELCOME_TEXT.format(name=new_user))
                    state["last_activity"] = datetime.now(timezone.utc)
                    state["participants"].append(new_user)

    page.on("response", on_response)

    print(f"✅ Monitoring group: {state['title']}")
    while True:
        now = datetime.now(timezone.utc)
        if now - state["last_activity"] > timedelta(hours=INACTIVE_HOURS):
            active_users = [u for u in state["participants"] if u != USERNAME]
            if len(active_users) >= 1:
                ping_list = random.sample(active_users, min(PING_COUNT, len(active_users)))
                mentions = " ".join([f"@{u}" for u in ping_list])
                await send_message(page, PING_TEXT.format(mentions=mentions))
                state["last_activity"] = datetime.now(timezone.utc)
        await asyncio.sleep(60)

async def login(page):
    try:
        await page.goto("https://www.instagram.com/accounts/login/")
        await page.wait_for_selector('input[name="username"]', timeout=60000)
        await page.fill('input[name="username"]', USERNAME)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_selector("nav", timeout=15000)
        print("✅ Login successful!")
        return True
    except Exception as e:
        print(f"❌ Login failed: {e}")
        content = await page.content()
        print("Page content at failure:\n", content[:1000])  # print first 1000 chars
        return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # debug mode
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US"
        )
        page = await context.new_page()

        success = await login(page)
        if not success:
            return

        group_threads = await get_all_group_threads(page)
        if not group_threads:
            print("❌ No groups found!")
            return
        print(f"🔍 Found {len(group_threads)} groups.")

        tasks = []
        for thread_id, state in group_threads.items():
            new_page = await context.new_page()
            tasks.append(handle_group(new_page, thread_id, state))

        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
    
