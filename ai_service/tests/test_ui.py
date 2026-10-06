"""The real web UI in headless Chromium against the API (fake search/LLM/form filler, local only).

Catches JavaScript errors and broken wiring between the UI and the API, which unit tests cannot see.
"""

import asyncio
import socket
from types import SimpleNamespace

import pytest
import uvicorn
from playwright.async_api import async_playwright, expect

from ai_service.app.core.config import settings
from ai_service.app.integrations.browser.form_filler import FillOutcome, FillResult
from ai_service.app.main import app
from ai_service.tests.fakes import RESUME

QUESTION = "How did you hear about us? *"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def ui(client, tmp_path):
    port = _free_port()
    # lifespan off: no real task runner; tests drive `client.runner` so the fake form filler is used.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 (uvicorn exposes only this flag)
        await asyncio.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    errors: list[str] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        page.set_default_timeout(15_000)  # fail fast instead of hanging on a blocked click
        # Stay offline: fonts and icons come from CDNs; the app itself must not need them.
        await page.route(
            "**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort()
        )
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: (
                errors.append(msg.text) if msg.type == "error" and "Failed to load resource" not in msg.text else None
            ),
        )
        resume = tmp_path / "cv.txt"
        resume.write_bytes(RESUME)
        yield SimpleNamespace(page=page, base=base, errors=errors, client=client, resume=resume)
        await browser.close()
    server.should_exit = True
    await serving


async def test_end_to_end_in_the_browser(ui):
    page, client = ui.page, ui.client
    await page.goto(ui.base)

    # No profile yet: the Profile tab opens. Upload the resume through the drop zone input.
    await expect(page.locator("#profile-tab")).to_have_class("tab-content active")
    await page.set_input_files("#resume-input", str(ui.resume))
    await expect(page.locator("#p-email")).to_have_value("asha.rao@example.com")
    await expect(page.locator("#nav-name")).to_have_text("Asha Rao")

    # Answer bank: add, edit, delete.
    await page.fill("#answer-question", "Pronouns")
    await page.fill("#answer-text", "she/her")
    await page.click("#answer-form button[type=submit]")
    row = page.locator(".answer-row")
    await expect(row).to_have_count(1)
    await row.locator(".answer-input").fill("they/them")
    await row.locator("[data-action=update-answer]").click()
    await expect(page.locator(".toast").last).to_have_text("Answer saved")
    await row.locator("[data-action=delete-answer]").click()
    await expect(page.locator(".answer-row")).to_have_count(0)

    # Streamed search shows per-stage progress, then ranked job cards.
    await page.click("[data-tab=discover-tab]")
    await page.fill("#role-input", "Backend Engineer")
    await page.fill("#location-input", "")
    await page.locator("label.toggle-field", has=page.locator("#exact-toggle")).click()  # all locations
    # Record every text the status line shows: with the fake search, progress is replaced within milliseconds.
    await page.evaluate("""() => {
        window.metaHistory = [];
        const meta = document.getElementById('search-meta');
        new MutationObserver(() => window.metaHistory.push(meta.textContent))
            .observe(meta, { childList: true, characterData: true, subtree: true });
    }""")
    await page.click("#btn-search")
    await expect(page.locator("#search-meta")).to_contain_text("jobs in any location")
    history = await page.evaluate("window.metaHistory")
    assert any("✓ Searching job boards" in h and "✓ Ranking against your profile" in h for h in history), history
    acme = page.locator(".job-card", has_text="Acme")
    await expect(acme).to_have_count(1)

    # Prepare: the agent leaves one question open and drafts an answer for it.
    result = FillResult(FillOutcome.FILLED, {"Email": "email"}, missing_required=[QUESTION])
    result.unanswered = [{"label": QUESTION, "kind": "text", "options": [], "required": True}]
    client.filler.script = [result]
    client.suggester.answers = {QUESTION: "Through LinkedIn"}
    await acme.locator("[data-action=prepare]").click()
    await expect(acme.locator(".job-footer")).to_contain_text("Processing")
    await client.runner.run_due_once()

    await page.click("[data-tab=applications-tab]")
    question = page.locator("[data-question-input]")
    await expect(question).to_have_value("Through LinkedIn", timeout=10_000)  # picked up by polling
    await expect(page.locator(".question-hint")).to_contain_text("Drafted by AI")
    await question.fill("LinkedIn post")
    await page.click("[data-action=save-answers]")
    await expect(page.locator(".app-card .status-pill")).to_contain_text("Preparing", timeout=10_000)
    await client.runner.run_due_once()
    await expect(page.locator(".app-card .status-pill")).to_have_text("Pending Approval", timeout=10_000)
    await expect(page.locator(".questions")).to_have_count(0)

    # The saved answer reached the answer bank and the form filler.
    assert client.filler.calls[-1]["packet"].answers.saved == {"how did you hear about us": "LinkedIn post"}
    await page.click("[data-tab=profile-tab]")
    await expect(page.locator(".answer-row .answer-input")).to_have_value("LinkedIn post")

    # Timeline lists what happened, oldest first.
    await page.click("[data-tab=applications-tab]")
    timeline = page.locator("details.timeline")
    await timeline.locator("summary").click()
    steps = await timeline.locator("li strong").all_inner_texts()
    assert steps[0] == "Application created" and "Re-filling the form" in steps

    assert ui.errors == []


async def test_token_prompt_unlocks_the_ui(ui, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "s3cret")
    page = ui.page
    await page.goto(ui.base)
    await expect(page.locator("#modal-title")).to_have_text("Access token required")
    await page.fill("#token-input", "s3cret")
    await page.click("#token-form button[type=submit]")
    await expect(page.locator("#modal")).not_to_have_class("modal-overlay active")
    # Data loaded with the token: the empty database sends the user to the Profile tab.
    await expect(page.locator("#profile-tab")).to_have_class("tab-content active")
    assert await page.evaluate("localStorage.getItem('jobpilot.apiToken')") == "s3cret"
    assert ui.errors == [] or all("401" in e for e in ui.errors)


async def test_hiding_and_job_sources_in_the_browser(ui, tmp_path):
    import httpx

    from ai_service.app.api import deps
    from ai_service.app.services.search.board_source import BoardSearchSource

    def lever(request: httpx.Request) -> httpx.Response:
        if "api.lever.co/v0/postings/acme" in str(request.url):
            return httpx.Response(200, json=[{"text": "AI Engineer", "hostedUrl": "https://jobs.lever.co/acme/1"}])
        return httpx.Response(404)

    boards = BoardSearchSource(tmp_path / "boards.json", transport=httpx.MockTransport(lever), seeds={})
    app.dependency_overrides[deps.get_board_source] = lambda: boards
    page, client = ui.page, ui.client
    await client.post("/api/v1/candidates/me/resume", files={"file": ("cv.txt", RESUME, "text/plain")})
    await client.post("/api/v1/search", json={"roles": ["Backend Engineer"], "strict_location": False})

    await page.goto(ui.base)
    acme = page.locator(".job-card", has_text="Acme")
    await expect(acme).to_have_count(1)

    # Not interested, then Undo.
    await acme.locator("[data-action=hide-job]").click()
    await expect(acme).to_have_count(0)
    await page.locator(".toast-action").click()
    await expect(acme).to_have_count(1)

    # Hide a whole company (confirm dialog), reflected in the profile.
    page.once("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
    remote_first = page.locator(".job-card", has_text="Remote First Inc")
    await remote_first.locator("[data-action=block-company]").click()
    await expect(remote_first).to_have_count(0)
    await expect(page.locator("#p-blocked")).to_have_value("Remote First Inc")

    # System tab: inbox not configured in tests; watch and unwatch a company.
    await page.click("[data-tab=system-tab]")
    await expect(page.locator("#inbox-status")).to_contain_text("Not set up")
    await expect(page.locator("#btn-check-inbox")).to_be_hidden()
    await page.fill("#board-url", "https://jobs.lever.co/acme")
    await page.click("#board-form button[type=submit]")
    await expect(page.locator(".board-row")).to_contain_text("Acme")
    await expect(page.locator(".toast").last).to_contain_text("Watching Acme (1 open job right now)")
    await page.locator("[data-action=remove-board]").click()
    await expect(page.locator(".board-row")).to_have_count(0)

    assert ui.errors == []
