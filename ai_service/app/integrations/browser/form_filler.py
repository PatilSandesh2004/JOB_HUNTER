"""Playwright-driven application form filler.

Fields are classified from their label / name / placeholder / aria-label / autocomplete attributes and
filled only with data the candidate actually provided: profile fields, plus screening answers the user
wrote or approved (see services/screening/answer_bank.py). Submission happens only when explicitly
requested, every required field is filled and no visible CAPTCHA is present; anything else is handed
back to the human with a screenshot and a list of the questions that still need an answer.
"""

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ai_service.app.core.config import settings
from ai_service.app.core.timeline import timeline_event
from ai_service.app.integrations.browser.runtime import in_browser_thread
from ai_service.app.services.jobs.ats import apply_page_url
from ai_service.app.services.screening.answer_bank import CHOICE_KINDS, AnswerBook, choose_option, real_options

logger = logging.getLogger("jobpilot.browser")

ANSWER_BANK = "answer"  # filled_fields value for fields answered from the answer bank


class FillOutcome(StrEnum):
    FILLED = "FILLED"  # form populated, not submitted
    SUBMITTED = "SUBMITTED"  # submitted and confirmation detected
    NEEDS_MANUAL = "NEEDS_MANUAL"
    FAILED = "FAILED"


@dataclass
class ApplicantPacket:
    full_name: str
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    current_company: str | None = None
    current_role: str | None = None
    years_of_experience: float | None = None
    expected_salary: str | None = None
    notice_period: str | None = None
    cover_letter: str | None = None
    resume_path: str | None = None
    requires_sponsorship: bool | None = None
    answers: AnswerBook = field(default_factory=AnswerBook)

    def value_for(self, key: str) -> str | None:
        if key == "years_of_experience":
            return f"{self.years_of_experience:g}" if self.years_of_experience else None
        if key in ("resume", "cover_letter_file"):
            return self.resume_path if key == "resume" else None
        value = getattr(self, key, None)
        return str(value) if value else None


@dataclass
class FillResult:
    outcome: FillOutcome
    filled_fields: dict[str, str] = field(default_factory=dict)  # field label -> semantic key (or ANSWER_BANK)
    missing_required: list[str] = field(default_factory=list)
    # Required questions left empty, with what the UI needs to ask the user: {label, kind, options, required}.
    unanswered: list[dict[str, Any]] = field(default_factory=list)
    captcha_detected: bool = False
    screenshot_path: str | None = None
    confirmation: str | None = None
    message: str | None = None
    final_url: str | None = None
    # True once the submit button was clicked: from then on a retry could create a duplicate application.
    submit_attempted: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)  # timeline entries (core/timeline.py)


# (semantic key, descriptor regex, allowed element kinds or None for text-like inputs)
_FIELD_RULES: list[tuple[str, re.Pattern[str], set[str] | None]] = [
    ("resume", re.compile(r"resume|r[ée]sum[ée]|\bcv\b|curriculum"), {"file"}),
    ("cover_letter_file", re.compile(r"cover"), {"file"}),
    (
        "cover_letter",
        re.compile(r"cover.?letter|motivation|why .{0,40}(join|interested|apply)|additional information"),
        {"textarea"},
    ),
    ("email", re.compile(r"e-?mail"), None),
    ("phone", re.compile(r"phone|mobile|\btel\b|contact number"), None),
    ("first_name", re.compile(r"first.?name|given.?name|\bfname\b|preferred first"), None),
    ("last_name", re.compile(r"last.?name|family.?name|surname|\blname\b"), None),
    ("linkedin_url", re.compile(r"linkedin"), None),
    ("github_url", re.compile(r"github"), None),
    ("portfolio_url", re.compile(r"portfolio|website|personal (site|url)|\bblog\b"), None),
    ("current_company", re.compile(r"current (company|employer)|^\s*company\s*$|organi[sz]ation"), None),
    ("current_role", re.compile(r"current (job )?(title|role|position)"), None),
    ("years_of_experience", re.compile(r"years? of (professional |relevant )?experience|how many years"), None),
    (
        "expected_salary",
        re.compile(
            r"(salary|compensation|pay|ctc) (expectation|requirement|range)s?|"
            r"(expected|desired) (salary|compensation|pay|ctc)|salary_expect|expected_ctc"
        ),
        None,
    ),
    (
        "notice_period",
        re.compile(r"notice.?period|when can you start|earliest (possible )?start|available to start"),
        None,
    ),
    ("requires_sponsorship", re.compile(r"(require|need).{0,40}sponsor|sponsorship"), {"select", "radio"}),
    ("location", re.compile(r"\blocation\b|\bcity\b|where are you (currently )?(based|located)"), None),
    ("full_name", re.compile(r"full.?name|^\s*name\s*\*?\s*$|your name|\bname\b"), None),
]
_NAME_EXCLUDE = re.compile(r"company|school|university|user|reference|manager|emergency|referr|recruiter")
_TEXT_TYPES = {"text", "email", "tel", "url", "number", "textarea"}
_CONTACT_KEYS = {
    "email",
    "phone",
    "first_name",
    "last_name",
    "full_name",
    "location",
    "current_company",
    "current_role",
    "linkedin_url",
    "github_url",
    "portfolio_url",
}
_REPEATABLE_KEYS = {"email", "requires_sponsorship"}
# Input type that best fits a key when a form has several candidates (e.g. a country-code box + a tel input).
_PREFERRED_KIND = {"email": "email", "phone": "tel", "linkedin_url": "url", "github_url": "url", "portfolio_url": "url"}

_CONFIRMATION_RE = re.compile(
    r"thank(s| you) for (applying|your application|your interest|submitting)|"
    r"application (has been |was )?(successfully )?(received|submitted)|"
    r"we('ve| have) received your application|successfully (submitted|applied)",
    re.I,
)
_CAPTCHA_FRAME_RE = re.compile(r"hcaptcha\.com|challenges\.cloudflare\.com|recaptcha/api2/(anchor|bframe)", re.I)
_APPLY_BUTTON_RE = re.compile(r"^\s*(apply( for this (job|position|role))?( now)?|i'?m interested)\s*$", re.I)
_SUBMIT_BUTTON_RE = re.compile(r"submit( (my |your )?application)?|send application|^\s*apply\s*$", re.I)

_DISCOVER_JS = """
() => {
  const isVisible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const text = (n) => (n && n.innerText ? n.innerText : '').replace(/\\s+/g, ' ').trim();
  const forLabel = (el) => el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  const labelFor = (el) => {
    const parts = [];
    const l = forLabel(el); if (l) parts.push(text(l));
    const wrap = el.closest('label'); if (wrap) parts.push(text(wrap));
    (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
      .forEach((id) => parts.push(text(document.getElementById(id))));
    if (!parts.join('').trim()) {
      const box = el.closest('.field, .application-question, .form-group, fieldset, li, [class*="field"], [class*="question"]');
      if (box) { const l = box.querySelector('label, legend, [class*="label"]'); if (l) parts.push(text(l)); }
    }
    return parts.join(' ').slice(0, 200);
  };
  // The question a radio group answers: fieldset legend, radiogroup label, or the nearest text above it.
  const groupQuestion = (el, optionLabels) => {
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg && text(lg)) return text(lg).slice(0, 200); }
    const rg = el.closest('[role="radiogroup"]');
    if (rg) {
      const named = rg.getAttribute('aria-label') || text(document.getElementById(rg.getAttribute('aria-labelledby') || ''));
      if (named) return named.slice(0, 200);
    }
    let box = el.parentElement;
    for (let depth = 0; box && depth < 5; depth++, box = box.parentElement) {
      const found = Array.from(box.querySelectorAll('label, legend, [class*="label"], [class*="question"], p, span'))
        .find((n) => !n.querySelector('input') && text(n) && !optionLabels.includes(text(n)));
      if (found) return text(found).slice(0, 200);
    }
    return '';
  };

  const out = [];
  document.querySelectorAll('input, textarea, select').forEach((el, i) => {
    const kind = el.tagName === 'INPUT' ? (el.getAttribute('type') || 'text').toLowerCase() : el.tagName.toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search', 'password', 'checkbox', 'radio'].includes(kind)) return;
    if (el.disabled || el.readOnly) return;
    if (kind !== 'file' && !isVisible(el)) return;
    const id = `jp-${i}`;
    const label = labelFor(el);
    const display = (label || el.placeholder || el.name || el.id || id).slice(0, 80);
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\\*\\s*$/.test(label);
    el.setAttribute('data-jobpilot-id', id);
    el.setAttribute('data-jobpilot-label', display);
    if (required) el.setAttribute('data-jobpilot-required', '1');
    out.push({
      id, kind, label, display, required, option_ids: [],
      descriptor: [el.name, el.id, el.placeholder, el.getAttribute('aria-label'), el.getAttribute('autocomplete'), label]
        .filter(Boolean).join(' | '),
      options: el.tagName === 'SELECT' ? Array.from(el.options).map((o) => o.text.trim()) : [],
    });
  });

  // Radio buttons are grouped into one question each (they are often visually replaced by their labels).
  const groups = new Map();
  document.querySelectorAll('input[type="radio"]').forEach((el) => {
    if (el.disabled) return;
    const key = el.name || `__${el.id}`;
    if (!groups.has(key)) groups.set(key, { inputs: [], labels: [] });
    groups.get(key).inputs.push(el);
    groups.get(key).labels.push((labelFor(el) || el.value || '').slice(0, 120));
  });
  let n = 0;
  groups.forEach((group) => {
    if (!group.inputs.some((el) => isVisible(el) || isVisible(el.closest('label')) || isVisible(forLabel(el)))) return;
    const first = group.inputs[0];
    const question = groupQuestion(first, group.labels);
    const id = `jp-rg-${n++}`;
    const display = (question || first.name || id).slice(0, 80);
    const required = group.inputs.some((el) => el.required || el.getAttribute('aria-required') === 'true')
      || /\\*\\s*$/.test(question);
    const optionIds = group.inputs.map((el, k) => {
      el.setAttribute('data-jobpilot-id', `${id}-${k}`);
      if (required) el.setAttribute('data-jobpilot-required-radio', id);
      return `${id}-${k}`;
    });
    first.setAttribute('data-jobpilot-label', display);
    out.push({
      id, kind: 'radio', label: question, display, required, option_ids: optionIds, options: group.labels,
      descriptor: [first.name, question].filter(Boolean).join(' | '),
    });
  });
  return out;
}
"""

_EMPTY_REQUIRED_JS = """
() => {
  const missing = Array.from(document.querySelectorAll('[data-jobpilot-required]'))
    .filter((el) => el.type === 'file' ? !(el.files && el.files.length) : !(el.value || '').trim())
    .map((el) => el.getAttribute('data-jobpilot-label'));
  const groups = new Map();
  const choices = 'input[type=checkbox][required], input[type=radio][required], input[data-jobpilot-required-radio]';
  document.querySelectorAll(choices).forEach((el) => {
    const groupId = el.getAttribute('data-jobpilot-required-radio');
    const key = groupId || el.name || el.id;
    if (!groups.has(key)) {
      const first = groupId ? document.querySelector(`[data-jobpilot-id="${groupId}-0"]`) : null;
      const label = (first && first.getAttribute('data-jobpilot-label'))
        || ((el.closest('label') || {}).innerText || el.name || 'checkbox').replace(/\\s+/g, ' ').trim();
      groups.set(key, { label, checked: false });
    }
    if (el.checked) groups.get(key).checked = true;
  });
  groups.forEach((g) => { if (!g.checked) missing.push(g.label.slice(0, 80)); });
  return missing;
}
"""


def classify_field(descriptor: str, kind: str) -> str | None:
    """Map a form control to a semantic applicant field, or None if we should not touch it."""
    text = descriptor.lower()
    for key, pattern, kinds in _FIELD_RULES:
        if kinds is not None and kind not in kinds:
            continue
        if kinds is None and kind not in _TEXT_TYPES:
            continue
        if key == "full_name" and _NAME_EXCLUDE.search(text):
            continue
        # A question ("What are your compensation requirements ... location?") is not a contact field.
        if key in _CONTACT_KEYS and ("?" in text or len(text) > 160):
            continue
        if pattern.search(text):
            return key
    return None


def question_text(f: dict[str, Any]) -> str:
    """The wording used to look a field up in (and save it to) the answer bank."""
    return f.get("label") or f.get("display") or ""


async def fill_application(url: str, packet: ApplicantPacket, *, submit: bool, screenshot_path: Path) -> FillResult:
    """Run the filler in a dedicated thread/event loop (Playwright needs subprocess support on Windows).

    Screenshots are saved next to `screenshot_path` as `<stem>-<step>.png`.
    """
    return await in_browser_thread(lambda: _FormFillSession(packet, screenshot_path).run(url, submit))


class _FormFillSession:
    def __init__(self, packet: ApplicantPacket, screenshot_path: Path) -> None:
        self.packet = packet
        self.screenshot_base = screenshot_path
        self.latest_screenshot: Path | None = None
        self.events: list[dict[str, Any]] = []

    def _event(self, step: str, detail: str = "", screenshot: str | None = None) -> None:
        self.events.append(timeline_event(step, detail, screenshot))

    async def run(self, url: str, submit: bool) -> FillResult:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=settings.browser_headless)
            context = await browser.new_context(viewport={"width": 1280, "height": 1600})
            context.set_default_timeout(settings.browser_timeout_ms)
            page = await context.new_page()
            try:
                result = await self._run_on_page(page, url, submit)
            except Exception as exc:
                logger.exception("Form filling failed for %s", url)
                shot = await self._screenshot(page, "error")
                self._event("Error", f"{type(exc).__name__}: {exc}", shot)
                result = FillResult(
                    FillOutcome.FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                    screenshot_path=self._saved_screenshot(),
                    final_url=page.url,
                )
            finally:
                await browser.close()
        result.events = self.events
        return result

    async def _run_on_page(self, page: Any, url: str, submit: bool) -> FillResult:
        await self._goto(page, apply_page_url(url))
        self._event("Opened the application page", page.url)
        frame, fields = await self._find_form(page)
        if not fields and await self._click_apply(page):
            self._event("Clicked Apply", page.url)
            frame, fields = await self._find_form(page)

        if not fields:
            login_wall = await page.locator("input[type='password']").count() > 0
            message = "Login required to apply" if login_wall else "No application form found on the page"
            self._event(message, page.url, await self._screenshot(page, "no-form"))
            return FillResult(
                FillOutcome.NEEDS_MANUAL, message=message, screenshot_path=self._saved_screenshot(), final_url=page.url
            )

        recognised = sum(1 for f in fields if f["key"])
        self._event("Found the application form", f"{len(fields)} fields, {recognised} recognised from your profile")
        filled = await self._fill_fields(frame, fields)
        missing = [m for m in await frame.evaluate(_EMPTY_REQUIRED_JS) if m]
        unanswered = _unanswered(fields, missing)
        captcha = await self._captcha_visible(page)
        answered = sum(1 for source in filled.values() if source == ANSWER_BANK)
        detail = f"{len(filled)} fields" + (f", {answered} from your answer bank" if answered else "")
        if "resume" in filled.values():
            detail += ", resume attached"
        self._event("Filled the form", detail, await self._screenshot(page, "filled"))
        if missing:
            self._event("Needs your input", ", ".join(missing[:8]))
        if captcha:
            self._event("CAPTCHA on the page", "This one has to be submitted by you")
        result = FillResult(
            FillOutcome.FILLED,
            filled_fields=filled,
            missing_required=missing,
            unanswered=unanswered,
            captcha_detected=captcha,
            screenshot_path=self._saved_screenshot(),
            final_url=page.url,
        )

        if not submit:
            return result
        if captcha:
            result.outcome, result.message = FillOutcome.NEEDS_MANUAL, "CAPTCHA present; submit this one yourself"
            return result
        if missing:
            result.outcome = FillOutcome.NEEDS_MANUAL
            result.message = "Required fields need your input: " + ", ".join(missing[:8])
            return result
        return await self._submit(page, frame, result)

    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded")
        await self._settle(page)

    @staticmethod
    async def _settle(page: Any) -> None:
        # Long-polling pages never go idle; after the timeout the DOM is ready enough.
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=8000)

    async def _find_form(self, page: Any) -> tuple[Any, list[dict[str, Any]]]:
        """Pick the frame (main page or embedded ATS iframe) with the most recognisable fields."""
        best_frame, best_fields = page.main_frame, []
        for frame in page.frames:
            try:
                discovered = await frame.evaluate(_DISCOVER_JS)
            except Exception:
                continue
            fields = [f | {"key": classify_field(f["descriptor"], f["kind"])} for f in discovered]
            recognised = [f for f in fields if f["key"]]
            if len(recognised) > len([f for f in best_fields if f["key"]]):
                best_frame, best_fields = frame, fields
        return best_frame, best_fields if any(f["key"] for f in best_fields) else []

    async def _click_apply(self, page: Any) -> bool:
        for role in ("link", "button"):
            target = page.get_by_role(role, name=_APPLY_BUTTON_RE).first
            if await target.count() == 0:
                continue
            href = await target.get_attribute("href") if role == "link" else None
            if href and not href.startswith(("#", "javascript:")):
                await self._goto(page, await page.evaluate("(h) => new URL(h, location.href).href", href))
            else:
                await target.click()
                await self._settle(page)
            return True
        return False

    async def _fill_fields(self, frame: Any, fields: list[dict[str, Any]]) -> dict[str, str]:
        """Fill recognised profile fields, then answer other questions from the answer bank."""
        filled: dict[str, str] = {}
        used_keys: set[str] = set()
        has_split_name = any(f["key"] in ("first_name", "last_name") for f in fields)
        # Best candidate per key first: preferred input type, then required fields. Unrecognised fields last.
        ordered = sorted(
            fields,
            key=lambda f: (f["key"] is None, f["kind"] != _PREFERRED_KIND.get(f["key"], f["kind"]), not f["required"]),
        )
        for f in ordered:
            key, label = f["key"], (f["label"] or f["display"] or f["descriptor"])[:80]
            # "Confirm email" and repeated sponsorship questions legitimately repeat; the rest is filled once.
            if key and ((key in used_keys and key not in _REPEATABLE_KEYS) or (key == "full_name" and has_split_name)):
                continue
            if not key and f["kind"] == "file":
                continue
            try:
                source = await self._fill_one(frame, f, key)
            except Exception as exc:
                logger.info("Could not fill '%s' (%s): %s", label, key, exc)
                continue
            if source:
                filled[label] = key if source == "profile" else ANSWER_BANK
                if key:
                    used_keys.add(key)
        return filled

    def _value(self, f: dict[str, Any], key: str | None) -> tuple[str | None, str]:
        """(value, source) for a field: source is 'profile' or 'answer' (answer bank)."""
        if key == "requires_sponsorship":
            if self.packet.requires_sponsorship is None:
                return None, ""
            return ("Yes" if self.packet.requires_sponsorship else "No"), "profile"
        if key:
            value = self.packet.value_for(key)
            if value or key in ("resume", "cover_letter_file"):
                return value, "profile"
        answer = self.packet.answers.answer_for(question_text(f), f["kind"], f["options"])
        return answer, "answer"

    async def _fill_one(self, frame: Any, f: dict[str, Any], key: str | None) -> str | None:
        """Fill one control. Returns the value's source, or None when it was left empty."""
        value, source = self._value(f, key)
        if not value:
            return None
        locator = frame.locator(f'[data-jobpilot-id="{f["id"]}"]')
        if f["kind"] == "file":
            if not await asyncio.to_thread(Path(value).is_file):
                return None
            await locator.set_input_files(value)
        elif f["kind"] in CHOICE_KINDS:
            option = choose_option(f["options"], value)
            if option is None:
                return None
            if f["kind"] == "select":
                await locator.select_option(label=option)
            else:
                radio = frame.locator(f'[data-jobpilot-id="{f["option_ids"][f["options"].index(option)]}"]')
                try:
                    await radio.check(timeout=3000)
                except Exception:
                    await radio.check(force=True)  # styled radios hide the input behind their label
        else:
            await locator.fill(value)
        return source

    async def _submit(self, page: Any, frame: Any, result: FillResult) -> FillResult:
        button = frame.locator("button[type='submit'], input[type='submit']").first
        if await button.count() == 0:
            button = frame.get_by_role("button", name=_SUBMIT_BUTTON_RE).first
        if await button.count() == 0:
            result.outcome, result.message = FillOutcome.NEEDS_MANUAL, "Could not find the submit button"
            self._event(result.message)
            return result

        result.submit_attempted = True
        self._event("Clicked Submit")
        await button.click()
        await self._settle(page)
        await page.wait_for_timeout(1500)
        shot = await self._screenshot(page, "submitted")
        result.screenshot_path = self._saved_screenshot()
        result.final_url = page.url

        for candidate in [page.main_frame, *page.frames]:
            try:
                body = await candidate.locator("body").inner_text(timeout=3000)
            except Exception:
                continue
            match = _CONFIRMATION_RE.search(body)
            if match:
                result.outcome = FillOutcome.SUBMITTED
                result.confirmation = body[max(0, match.start() - 60) : match.end() + 120].strip()
                self._event("Confirmation received", match.group(0), shot)
                return result

        result.outcome = FillOutcome.NEEDS_MANUAL
        result.message = (
            "Submit was clicked but no confirmation message was detected. "
            "Check the screenshot before retrying to avoid a duplicate application."
        )
        self._event("No confirmation message detected", page.url, shot)
        return result

    @staticmethod
    async def _captcha_visible(page: Any) -> bool:
        for frame in page.frames:
            if _CAPTCHA_FRAME_RE.search(frame.url or "") and "size=invisible" not in (frame.url or ""):
                try:
                    element = await frame.frame_element()
                    box = await element.bounding_box()
                    if box and box["width"] > 10 and box["height"] > 10:
                        return True
                except Exception:
                    return True
        return False

    async def _screenshot(self, page: Any, step: str) -> str | None:
        """Save `<stem>-<step>.png` next to the requested path; returns the file name."""
        path = self.screenshot_base.with_name(f"{self.screenshot_base.stem}-{step}.png")
        try:
            await page.screenshot(path=str(path), full_page=True)
        except Exception as exc:
            logger.info("Screenshot failed: %s", exc)
            return None
        self.latest_screenshot = path
        return path.name

    def _saved_screenshot(self) -> str | None:
        return str(self.latest_screenshot) if self.latest_screenshot and self.latest_screenshot.exists() else None


def _unanswered(fields: list[dict[str, Any]], missing_labels: list[str]) -> list[dict[str, Any]]:
    """Required questions still empty after filling, in the shape the UI needs to ask the user."""
    missing = set(missing_labels)
    seen: set[str] = set()
    questions = []
    for f in fields:
        question = question_text(f)
        if f["kind"] == "file" or f["display"] not in missing or not question or question in seen:
            continue
        seen.add(question)
        options = real_options(f["options"]) if f["kind"] in CHOICE_KINDS else []
        questions.append({"label": question, "kind": f["kind"], "options": options, "required": True})
    return questions
