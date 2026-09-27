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
        """Fetch assignments via Moodle AJAX calendar API + course fallback."""
        try:
            await self._page.goto(f"{MOODLE_URL}/my/", wait_until="domcontentloaded")

            # Extract sesskey from multiple locations
            sesskey = await self._page.evaluate("""
                () => {
                    if (window.M && window.M.cfg && window.M.cfg.sesskey)
                        return window.M.cfg.sesskey;
                    const m = document.cookie.match(/MoodleSession[^=]*=([^;]+)/);
                    const el = document.querySelector('[data-sesskey]');
                    if (el) return el.dataset.sesskey;
                    const inp = document.querySelector('input[name="sesskey"]');
                    if (inp) return inp.value;
                    return null;
                }
            """)

            results = []

            if sesskey:
                # Wide range: 30 days back → 90 days forward (catch overdue + upcoming)
                past   = int((datetime.now() - timedelta(days=30)).timestamp())
                future = int((datetime.now() + timedelta(days=90)).timestamp())

                raw = await self._page.evaluate(f"""
                    async () => {{
                        const r = await fetch('/lib/ajax/service.php?sesskey={sesskey}&info=core_calendar_get_action_events_by_timesort', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify([{{
                                methodname: 'core_calendar_get_action_events_by_timesort',
                                args: {{ timesortfrom: {past}, timesortto: {future}, limitnum: 100 }}
                            }}])
                        }});
                        return await r.json();
                    }}
                """)

                events = []
                if raw and isinstance(raw, list) and raw[0].get("data"):
                    events = raw[0]["data"].get("events", [])

                for ev in events:
                    ts = ev.get("timesort", 0)
                    results.append({
                        "id": str(ev.get("id", "")),
                        "title": ev.get("name", "").strip(),
                        "course": (ev.get("course") or {}).get("fullname", ""),
                        "due_timestamp": ts,
                        "due_date": datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M") if ts else "",
                        "url": ev.get("url", ""),
                        "module": ev.get("modulename", "assign"),
                        "submitted": False,
                    })

            # If calendar API returned nothing, scan each enrolled course directly
            if not results:
                print("[moodle] calendar API empty — trying course scan")
                results = await self._scan_courses()

            # Final fallback: scrape dashboard HTML
            if not results:
                results = await self._fallback_scrape()

            return results

        except Exception as e:
            print(f"[moodle] get_assignments error: {e}")
            return []

    async def _scan_courses(self) -> list[dict]:
        """Scan each enrolled course for assignment activities."""
        results = []
        try:
            # Get course list from nav or course overview
            await self._page.goto(f"{MOODLE_URL}/my/courses.php", wait_until="domcontentloaded")
            course_links = await self._page.eval_on_selector_all(
                "a[href*='/course/view.php'], a[href*='course/view']",
                "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))"
            )
            # Also try dashboard if no courses found on courses page
            if not course_links:
                await self._page.goto(f"{MOODLE_URL}/my/", wait_until="domcontentloaded")
                course_links = await self._page.eval_on_selector_all(
                    "a[href*='/course/view.php'], a[href*='course/view']",
                    "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))"
                )
            # Deduplicate
            seen_urls = set()
            courses = []
            for c in course_links:
                href = c["href"]
                text = c["text"]
                if href not in seen_urls and text and "id=" in href:
                    seen_urls.add(href)
                    cid = href.split("id=")[-1].split("&")[0]
                    courses.append({"id": cid, "name": text, "url": href})

            for course in courses[:10]:  # limit to 10 courses
                try:
                    assign_url = f"{MOODLE_URL}/mod/assign/index.php?id={course['id']}"
                    await self._page.goto(assign_url, wait_until="domcontentloaded")
                    rows = await self._page.eval_on_selector_all(
                        "table.generaltable tr:not(:first-child)",
                        """rows => rows.map(r => {
                            const a = r.querySelector("a");
                            const cells = r.querySelectorAll("td");
                            return {
                                title: a ? a.innerText.trim() : "",
                                url:   a ? a.href : "",
                                due:   cells[2] ? cells[2].innerText.trim() : "",
                                status: cells[3] ? cells[3].innerText.trim() : "",
                            };
                        })"""
                    )
                    for i, row in enumerate(rows):
                        if not row.get("title"):
                            continue
                        uid = f"{course['id']}-{i}"
                        results.append({
                            "id": uid,
                            "title": row["title"],
                            "course": course["name"],
                            "due_timestamp": 0,
                            "due_date": row["due"],
                            "url": row["url"],
                            "module": "assign",
                            "submitted": "submitted" in row.get("status", "").lower(),
                        })
                except Exception as ce:
                    print(f"[moodle] course scan error {course['id']}: {ce}")
        except Exception as e:
            print(f"[moodle] _scan_courses error: {e}")
        return results

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

    # ── Debug ─────────────────────────────────────────────────────────────────

    async def debug_scan(self) -> dict:
        """Return diagnostic info to understand why scan might return 0 results."""
        report: dict = {"steps": []}

        def log(step: str, data):
            report["steps"].append({"step": step, "data": data})

        try:
            # Step 1: dashboard
            await self._page.goto(f"{MOODLE_URL}/my/", wait_until="domcontentloaded")
            log("dashboard_url", self._page.url)
            log("dashboard_title", await self._page.title())

            # Step 2: sesskey
            sesskey = await self._page.evaluate("""
                () => {
                    if (window.M && window.M.cfg && window.M.cfg.sesskey)
                        return window.M.cfg.sesskey;
                    const el = document.querySelector('[data-sesskey]');
                    if (el) return el.dataset.sesskey;
                    const inp = document.querySelector('input[name="sesskey"]');
                    if (inp) return inp.value;
                    return null;
                }
            """)
            log("sesskey", sesskey)

            # Step 3: calendar API raw response
            if sesskey:
                past   = int((datetime.now() - timedelta(days=30)).timestamp())
                future = int((datetime.now() + timedelta(days=90)).timestamp())
                raw = await self._page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('/lib/ajax/service.php?sesskey={sesskey}&info=core_calendar_get_action_events_by_timesort', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify([{{
                                    methodname: 'core_calendar_get_action_events_by_timesort',
                                    args: {{ timesortfrom: {past}, timesortto: {future}, limitnum: 100 }}
                                }}])
                            }});
                            const text = await r.text();
                            return text.substring(0, 2000);
                        }} catch(e) {{ return 'fetch error: ' + e.message; }}
                    }}
                """)
                log("calendar_api_raw", raw)

            # Step 4: courses page
            await self._page.goto(f"{MOODLE_URL}/my/courses.php", wait_until="domcontentloaded")
            log("courses_page_url", self._page.url)
            log("courses_page_title", await self._page.title())
            course_links = await self._page.eval_on_selector_all(
                "a[href*='/course/view.php']",
                "els => els.slice(0,10).map(e => ({href: e.href, text: e.innerText.trim()}))"
            )
            log("course_links_found", course_links)

            # Step 5: if no course/view links, try broader link search
            if not course_links:
                all_links = await self._page.eval_on_selector_all(
                    "a[href*='course']",
                    "els => els.slice(0,20).map(e => ({href: e.href, text: e.innerText.trim().substring(0,60)}))"
                )
                log("all_course_links_broad", all_links)

            # Step 6: try dashboard timeline/assignments block
            await self._page.goto(f"{MOODLE_URL}/my/", wait_until="domcontentloaded")
            timeline_items = await self._page.eval_on_selector_all(
                "[data-action='view-event'], .event-name, .assignment, a[href*='/mod/assign/view.php']",
                "els => els.slice(0,10).map(e => ({tag: e.tagName, text: e.innerText.trim().substring(0,80), href: e.href||''}))"
            )
            log("dashboard_assignment_items", timeline_items)

            # Step 7: check if enrolled courses via API
            if sesskey:
                courses_api = await self._page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('/lib/ajax/service.php?sesskey={sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify([{{
                                    methodname: 'core_course_get_enrolled_courses_by_timeline_classification',
                                    args: {{ offset: 0, limit: 20, classification: 'inprogress', sort: 'ul.timeaccess desc' }}
                                }}])
                            }});
                            const text = await r.text();
                            return text.substring(0, 3000);
                        }} catch(e) {{ return 'fetch error: ' + e.message; }}
                    }}
                """)
                log("enrolled_courses_api", courses_api)

        except Exception as e:
            log("exception", str(e))

        return report

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
