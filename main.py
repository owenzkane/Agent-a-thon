"""
OpenTable Reservation Agent — Human-in-the-loop
Run: python agent.py
First run: the browser opens; log in to OpenTable manually, then press Enter.
Session is saved to ./auth_state.json for subsequent runs.
"""

import os
import json
import asyncio
from pathlib import Path
from anthropic import Anthropic
from playwright.async_api import async_playwright, Page
from dotenv import load_dotenv

load_dotenv()
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

AUTH_STATE = Path("auth_state.json")


# ───────────────────────────── Browser layer ─────────────────────────────

class Browser:
    """Wraps a single Playwright page the agent drives."""

    def __init__(self):
        self.page: Page | None = None
        self._pw = None
        self._browser = None
        self._context = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=False)
        storage = str(AUTH_STATE) if AUTH_STATE.exists() else None
        self._context = await self._browser.new_context(storage_state=storage)
        self.page = await self._context.new_page()

        if not AUTH_STATE.exists():
            await self.page.goto("https://www.opentable.com/")
            print("\n>>> Log in to OpenTable in the browser window, then press Enter here...")
            input()
            await self._context.storage_state(path=str(AUTH_STATE))
            print("Session saved.\n")

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()


# ───────────────────────────── Tool implementations ─────────────────────────────
# These are what Claude can call. Each returns a JSON-serializable result.

async def search_restaurants(browser: Browser, cuisine: str, location: str,
                             date_time: str, party_size: int) -> dict:
    """Navigate OpenTable search and scrape result cards."""
    page = browser.page
    url = (f"https://www.opentable.com/s?"
           f"term={cuisine.replace(' ', '+')}"
           f"&covers={party_size}"
           f"&dateTime={date_time}"
           f"&metroId=")  # you'd resolve location → metroId properly
    await page.goto(url)
    await page.wait_for_selector('[data-test="restaurant-card"]', timeout=10000)

    cards = await page.locator('[data-test="restaurant-card"]').all()
    results = []
    for i, card in enumerate(cards[:8]):
        try:
            name = await card.locator('h2, [data-test="restaurant-name"]').first.inner_text()
            # OpenTable's DOM changes; treat these selectors as a starting point
            price = await card.locator('[data-test="price-band"]').inner_text() \
                if await card.locator('[data-test="price-band"]').count() else "?"
            cuisine_txt = await card.locator('[data-test="cuisine"]').inner_text() \
                if await card.locator('[data-test="cuisine"]').count() else cuisine
            results.append({
                "index": i,
                "name": name.strip(),
                "price": price,
                "cuisine": cuisine_txt,
            })
        except Exception as e:
            continue
    return {"results": results}


async def open_restaurant(browser: Browser, index: int) -> dict:
    """Click into a restaurant from the current search results."""
    page = browser.page
    cards = page.locator('[data-test="restaurant-card"]')
    await cards.nth(index).click()
    await page.wait_for_load_state("networkidle")
    return {"status": "opened", "url": page.url}


async def select_time_slot(browser: Browser, time: str) -> dict:
    """Click an available time slot button on the restaurant detail page."""
    page = browser.page
    # Time slot buttons are usually <a> or <button> with the time as text
    btn = page.get_by_role("link", name=time).or_(page.get_by_role("button", name=time)).first
    if await btn.count() == 0:
        slots = await page.locator('[data-test*="time-slot"]').all_inner_texts()
        return {"status": "unavailable", "alternatives": slots[:6]}
    await btn.click()
    await page.wait_for_load_state("networkidle")
    return {"status": "slot_selected", "url": page.url}


async def prepare_booking(browser: Browser, notes: str = "") -> dict:
    """Fill the booking form up to — but not including — final confirm."""
    page = browser.page
    if notes:
        notes_field = page.get_by_label("Special requests", exact=False)
        if await notes_field.count():
            await notes_field.fill(notes)

    # DO NOT click the final confirm button. Scroll it into view and stop.
    confirm = page.get_by_role("button", name=lambda n: "complete" in n.lower() or "confirm" in n.lower())
    if await confirm.count():
        await confirm.first.scroll_into_view_if_needed()

    return {
        "status": "ready_for_user_confirmation",
        "message": "Booking form is prepared. User must click the final confirm button in the browser."
    }


# ───────────────────────────── Tool routing ─────────────────────────────

TOOLS = [
    {
        "name": "search_restaurants",
        "description": "Search OpenTable for restaurants. Returns a list of options with an index you can refer to later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cuisine": {"type": "string", "description": "e.g. 'italian', 'sushi', 'steakhouse'"},
                "location": {"type": "string", "description": "e.g. 'Brooklyn, NY'"},
                "date_time": {"type": "string", "description": "ISO datetime, e.g. '2026-04-18T19:00'"},
                "party_size": {"type": "integer"},
            },
            "required": ["cuisine", "location", "date_time", "party_size"],
        },
    },
    {
        "name": "open_restaurant",
        "description": "Open a restaurant's detail page from the current search results by its index.",
        "input_schema": {
            "type": "object",
            "properties": {"index": {"type": "integer"}},
            "required": ["index"],
        },
    },
    {
        "name": "select_time_slot",
        "description": "Select a specific time slot on the currently open restaurant page.",
        "input_schema": {
            "type": "object",
            "properties": {"time": {"type": "string", "description": "e.g. '7:00 PM'"}},
            "required": ["time"],
        },
    },
    {
        "name": "prepare_booking",
        "description": "Fill out the booking form and STOP at the confirm button. The user will click confirm themselves.",
        "input_schema": {
            "type": "object",
            "properties": {"notes": {"type": "string"}},
        },
    },
]


async def dispatch(browser: Browser, name: str, args: dict) -> dict:
    fn = {
        "search_restaurants": search_restaurants,
        "open_restaurant": open_restaurant,
        "select_time_slot": select_time_slot,
        "prepare_booking": prepare_booking,
    }[name]
    return await fn(browser, **args)


# ───────────────────────────── Agent loop ─────────────────────────────

SYSTEM = """You are a restaurant booking assistant. Help the user find and book
a reservation on OpenTable. Workflow:
1. Use search_restaurants to find options based on their request.
2. Present 3-5 options with short descriptions. Ask which one they want.
3. When they pick one, use open_restaurant, then select_time_slot.
4. Use prepare_booking to fill the form, then STOP and tell the user to review
   the browser window and click the final confirm button themselves.

Never claim a booking is complete — only the user's click finalizes it."""


async def chat_loop(browser: Browser):
    messages = []
    print("\nReservation agent ready. Type your request (or 'quit'):\n")

    while True:
        user_input = input("you> ").strip()
        if user_input.lower() in {"quit", "exit"}:
            break
        messages.append({"role": "user", "content": user_input})

        # Inner loop: let Claude call tools until it produces a final text reply
        while True:
            resp = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=1024,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            )

            if resp.stop_reason == "tool_use":
                tool_results = []
                assistant_blocks = resp.content
                for block in assistant_blocks:
                    if block.type == "tool_use":
                        print(f"  [calling {block.name}({json.dumps(block.input)})]")
                        result = await dispatch(browser, block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                messages.append({"role": "assistant", "content": assistant_blocks})
                messages.append({"role": "user", "content": tool_results})
                continue  # let Claude react to the tool results

            # Normal text response — print and break
            text = "".join(b.text for b in resp.content if b.type == "text")
            print(f"\nagent> {text}\n")
            messages.append({"role": "assistant", "content": resp.content})
            break


async def main():
    browser = Browser()
    await browser.start()
    try:
        await chat_loop(browser)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())