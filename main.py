import asyncio, os, re, random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
USERNAME = os.getenv("IG_USER")
PASSWORD = os.getenv("IG_PASS")

WELCOME_TEXT = "🎉 Welcome {name}!"
PING_TEXT    = "Hey {mentions}, koi online aaye? 😄"
INACTIVE_HOURS = 3
PING_COUNT = 4
JOIN_REGEX = re.compile(r"(.+?) joined the group")

async def send_message(page, text):
    box = await page.query_selector('textarea[placeholder="Message..."]')
    await box.type(text)
    await box.press("Enter")

async def get_all_group_threads(page):
    await page.goto("https://www.instagram.com/direct/inbox/")
    await page.wait_for_selector("div[role='dialog'] a[href*='/direct/t/']")
    links = await page.query_selector_all("div[role='dialog'] a[href*='/direct/t/']")
    group_threads = {}
    for l in links:
        title = (await l.inner_text()).strip()
        href = await l.get_attribute("href")
        if "/direct/t/" in href:
            thread_id = href.split("/")[-2]
            group_threads[thread_id] = {"title": title, "last_activity": datetime.now(timezone.utc), "participants": []}
    return group_threads

async def fetch_participants(page):
    try:
        btn = await page.query_selector("header button[aria-label*='Chat details']")
        if btn: await btn.click()
        await page.wait_for_selector("div[role='dialog']")
        user_imgs = await page.query_selector_all("div[role='dialog'] img[alt]")
        names = []
        for u in user_imgs:
            alt = await u.get_attribute("alt")
            if alt and USERNAME not in alt:
                name = alt.split("'s")[0].strip()
                if name: names.append(name)
        await page.keyboard.press("Escape")
        return list(set(names))
    except:
        return []

async def handle_group(page, thread_id, state):
    group_url = f"https://www.instagram.com/direct/t/{thread_id}/"
    await page.goto(group_url)
    await page.wait_for_selector('textarea[placeholder="Message..."]')

    participants = await fetch_participants(page)
    state["participants"] = participants

    async def on_response(resp):
        if "/direct-v2/threads/" not in resp.url: return
        try:
            data = await resp.json()
        except:
            return
        for item in data.get("items", []):
            txt = item.get("text", "")
            ts = item.get("timestamp")
            if ts:
                state["last_activity"] = datetime.fromtimestamp(int(ts)/1e6, timezone.utc)
            m = JOIN_REGEX.match(txt)
            if m:
                new_user = m.group(1).strip()
                await send_message(page, WELCOME_TEXT.format(name=new_user))
                state["last_activity"] = datetime.now(timezone.utc)
                state["participants"].append(new_user)

    page.on("response", on_response)

    print(f"✅ Monitoring group: {state['title']}")
    while True:
        now = datetime.now(timezone.utc)
        if now - state["last_activity"] > timedelta(hours=INACTIVE_HOURS):
            ping_list = random.sample(
                [u for u in state["participants"] if u != USERNAME],
                min(PING_COUNT, len(state["participants"]))
            )
            mentions = " ".join([f"@{u}" for u in ping_list])
            await send_message(page, PING_TEXT.format(mentions=mentions))
            state["last_activity"] = datetime.now(timezone.utc)
        await asyncio.sleep(60)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # 1. Login
        await page.goto("https://www.instagram.com/accounts/login/")
        await page.fill('input[name="username"]', USERNAME)
        await page.fill('input[name="password"]', PASSWORD)
        await page.click("button[type='submit']")
        await page.wait_for_url("https://www.instagram.com/*")

        # 2. Get all group chats
        group_threads = await get_all_group_threads(page)
        if not group_threads:
            print("❌ No groups found!")
            return

        print(f"🔍 Found {len(group_threads)} groups.")

        # 3. Launch handler for each group
        tasks = []
        for thread_id, state in group_threads.items():
            new_page = await context.new_page()
            tasks.append(handle_group(new_page, thread_id, state))

        await asyncio.gather(*tasks)

asyncio.run(main())
