"""Playwright automation for Moodle."""
import os
from datetime import datetime, timedelta
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, Playwright

MOODLE_URL = os.environ.get("MOODLE_URL", "https://du.luguniv.edu.ua")


class MoodleClient:
    def __init__(self):
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self.logged_in = False
        self.username = ""

    async def start(self):
        self._pw = await async_playwright().start()
        # Use pre-installed Chromium; fall back to auto-detect
        import os as _os
        _exe = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
        launch_kwargs: dict = {"headless": True}
        if _os.path.exists(_exe):
            launch_kwargs["executable_path"] = _exe
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        self._page = await ctx.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self.logged_in = False

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self, username: str, password: str) -> dict:
        try:
            await self._page.goto(f"{MOODLE_URL}/login/index.php", wait_until="domcontentloaded")
            await self._page.fill("#username", username)
            await self._page.fill("#password", password)
            await self._page.click("#loginbtn")
            await self._page.wait_for_load_state("networkidle", timeout=20000)

            if "/login/" in self._page.url:
                err = await self._page.query_selector(".loginerrors, .alert-danger")
                msg = (await err.inner_text()).strip() if err else "Неверный логин или пароль"
                return {"success": False, "message": msg}

            self.logged_in = True
            self.username = username
            return {"success": True, "message": "Вход выполнен"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def logout(self):
        try:
            await self._page.goto(f"{MOODLE_URL}/login/logout.php", wait_until="domcontentloaded")
        except Exception:
            pass
        self.logged_in = False
        self.username = ""

    # ── Assignments ───────────────────────────────────────────────────────────

    async def get_assignments(self) -> list[dict]:
        """Fetch upcoming assignments via Moodle AJAX calendar API."""
        try:
            await self._page.goto(f"{MOODLE_URL}/my/", wait_until="domcontentloaded")

            sesskey = await self._page.evaluate("""
                () => window.M && window.M.cfg ? window.M.cfg.sesskey : null
            """)
            if not sesskey:
                return await self._fallback_scrape()

            now = int(datetime.now().timestamp())
            future = int((datetime.now() + timedelta(days=30)).timestamp())

            raw = await self._page.evaluate(f"""
                async () => {{
                    const r = await fetch('/lib/ajax/service.php?sesskey={sesskey}&info=core_calendar_get_action_events_by_timesort', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify([{{
                            methodname: 'core_calendar_get_action_events_by_timesort',
                            args: {{ timesortfrom: {now}, timesortto: {future}, limitnum: 50 }}
                        }}])
                    }});
                    return await r.json();
                }}
            """)

            events = []
            if raw and isinstance(raw, list) and raw[0].get("data"):
                events = raw[0]["data"].get("events", [])

            result = []
            for ev in events:
                ts = ev.get("timesort", 0)
                result.append({
                    "id": str(ev.get("id", "")),
                    "title": ev.get("name", "").strip(),
                    "course": (ev.get("course") or {}).get("fullname", ""),
                    "due_timestamp": ts,
                    "due_date": datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M") if ts else "",
                    "url": ev.get("url", ""),
                    "module": ev.get("modulename", "assign"),
                    "submitted": False,
                })
            return result

        except Exception as e:
            print(f"[moodle] get_assignments error: {e}")
            return []

    async def _fallback_scrape(self) -> list[dict]:
        result = []
        try:
            items = await self._page.query_selector_all(".event, [data-event-id]")
            for item in items:
                a = await item.query_selector("a")
                title = (await a.inner_text()).strip() if a else "?"
                url = await a.get_attribute("href") if a else ""
                d = await item.query_selector(".date, time")
                date_str = (await d.inner_text()).strip() if d else ""
                result.append({
                    "id": url.split("id=")[-1] if "id=" in url else str(len(result)),
                    "title": title,
                    "course": "",
                    "due_date": date_str,
                    "due_timestamp": 0,
                    "url": url,
                    "module": "assign",
                    "submitted": False,
                })
        except Exception as e:
            print(f"[moodle] fallback error: {e}")
        return result

    # ── Details ───────────────────────────────────────────────────────────────

    async def get_details(self, url: str) -> dict:
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            await self._page.wait_for_load_state("networkidle", timeout=12000)

            description = ""
            for sel in ["#intro .no-overflow", "#intro", ".box.generalbox", ".activity-description"]:
                el = await self._page.query_selector(sel)
                if el:
                    description = (await el.inner_text()).strip()
                    break

            sub_el = await self._page.query_selector(".submissionstatustable")
            submitted = False
            if sub_el:
                txt = (await sub_el.inner_text()).lower()
                submitted = any(w in txt for w in ["submitted", "відправлено", "отправлено"])

            can_submit = bool(await self._page.query_selector(
                'a[href*="editsubmission"], button:has-text("Подати"), button:has-text("Добавить")'
            ))

            return {
                "description": description or "Опис не знайдено.",
                "submitted": submitted,
                "can_submit": can_submit,
            }
        except Exception as e:
            return {"description": "", "submitted": False, "can_submit": False, "error": str(e)}

    # ── Submit ────────────────────────────────────────────────────────────────

    async def submit(self, url: str, text: str) -> dict:
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            await self._page.wait_for_load_state("networkidle", timeout=12000)

            # Open edit submission form
            edit_link = None
            for sel in ['a[href*="editsubmission"]', 'a[href*="action=editsubmission"]']:
                edit_link = await self._page.query_selector(sel)
                if edit_link:
                    break

            if edit_link:
                await edit_link.click()
                await self._page.wait_for_load_state("networkidle", timeout=12000)

            # Fill text editor — Atto first, then TinyMCE, then textarea
            filled = False

            atto = await self._page.query_selector(".editor_atto_content[contenteditable='true']")
            if atto:
                await atto.click()
                await self._page.keyboard.press("Control+a")
                await atto.type(text, delay=0)
                filled = True

            if not filled:
                frame_el = await self._page.query_selector("iframe[id*='onlinetext'], iframe[id*='assignsubmission']")
                if frame_el:
                    frame = await frame_el.content_frame()
                    if frame:
                        body = await frame.query_selector("body")
                        if body:
                            await body.click()
                            await frame.keyboard.press("Control+a")
                            await body.type(text, delay=0)
                            filled = True

            if not filled:
                ta = await self._page.query_selector("textarea[name*='onlinetext'], textarea[name*='text']")
                if ta:
                    await ta.fill(text)
                    filled = True

            if not filled:
                return {"success": False, "message": "Поле для відповіді не знайдено"}

            save = await self._page.query_selector(
                'input[name="savesubmission"], button[type="submit"]:not([name="cancel"])'
            )
            if not save:
                return {"success": False, "message": "Кнопку збереження не знайдено"}

            await save.click()
            await self._page.wait_for_load_state("networkidle", timeout=15000)
            return {"success": True, "message": "Відповідь надіслана!"}

        except Exception as e:
            return {"success": False, "message": str(e)}
