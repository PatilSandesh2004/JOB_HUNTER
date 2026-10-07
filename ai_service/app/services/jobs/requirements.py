"""What a posting asks for, read from its text: years of experience, required vs nice-to-have skills, salary.

Descriptions arrive as flattened text (HTML stripped, whitespace collapsed), so section headings such as
"Requirements" or "Nice to have" are found inline and the text between them is labelled by its heading.
"""

import re
from dataclasses import dataclass

from ai_service.app.services.skills.catalog import find_skills

# ---- sections ---------------------------------------------------------------------------------
REQUIRED, PREFERRED, OTHER, IGNORED = "required", "preferred", "other", "ignored"

_HEADINGS: list[tuple[str, re.Pattern[str]]] = [
    (
        PREFERRED,
        re.compile(
            r"\b(nice[- ]to[- ]haves?|good[- ]to[- ]haves?|preferred (?:qualifications|skills|experience)|"
            r"bonus(?: points)?|pluses|it'?s a plus|would be a plus|desirable(?: skills)?|"
            r"what would make you stand out|extra credit|preferred:)",
            re.I,
        ),
    ),
    (
        REQUIRED,
        re.compile(
            r"\b(requirements|required (?:qualifications|skills|experience)|must[- ]haves?|minimum qualifications|"
            r"basic qualifications|what you(?:'ll| will)? (?:need|bring)|what we(?:'re| are) looking for|who you are|"
            r"skills required|key skills|desired (?:profile|skills)|candidate profile|qualifications)\b",
            re.I,
        ),
    ),
    (
        OTHER,
        re.compile(
            r"\b(responsibilities|what you(?:'ll| will) do|the role|your role|day[- ]to[- ]day|key result areas|"
            r"about (?:this|the) (?:role|position|job|opportunity))\b",
            re.I,
        ),
    ),
    (
        IGNORED,
        re.compile(
            r"\b(about (?:us|the company|the team)|who we are|benefits|perks|why (?:join|work)|what we offer|our offer|"
            r"equal (?:employment )?opportunity|how to apply|privacy notice)\b",
            re.I,
        ),
    ),
    # "About Hevo", "About Stripe": the company's own blurb (case-sensitive: a capitalised name follows).
    (IGNORED, re.compile(r"\bAbout (?!(?:this|the|you|us|our)\b)[A-Z][\w&.-]+")),
]
_INLINE_PREFERRED = re.compile(
    r"^[^.;]{0,40}?\b(preferred|is a plus|a plus|nice to have|bonus|desirable|ideally)\b", re.I
)


def section_spans(text: str) -> list[tuple[int, str]]:
    """[(start offset, label)] in order; text before the first heading is OTHER."""
    marks = [(0, OTHER)]
    for label, pattern in _HEADINGS:
        marks += [(m.start(), label) for m in pattern.finditer(text)]
    marks.sort()
    return marks


def _label_at(spans: list[tuple[int, str]], position: int) -> str:
    label = OTHER
    for start, name in spans:
        if start > position:
            break
        label = name
    return label


def split_skills(text: str) -> tuple[list[str], list[str]]:
    """(required, preferred) catalogue skills. A skill is preferred only if every mention is in a nice-to-have
    section or marked inline as a plus; skills only mentioned under benefits/about-us are dropped."""
    spans = section_spans(text)
    seen_required: list[str] = []
    seen_preferred: list[str] = []
    for mention in find_skills(text):
        label = _label_at(spans, mention.start)
        if label == IGNORED:
            continue
        if label == PREFERRED or _INLINE_PREFERRED.search(text[mention.start : mention.start + 60]):
            seen_preferred.append(mention.name)
        else:
            seen_required.append(mention.name)
    required = list(dict.fromkeys(seen_required))
    preferred = [s for s in dict.fromkeys(seen_preferred) if s not in required]
    return required, preferred


# ---- experience -------------------------------------------------------------------------------
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
}  # fmt: skip
_WORD_NUMBER_RE = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")\b(?=\s*(?:\(\d+\)\s*)?(?:\+|plus)?\s*(?:or more\s+)?(?:years?|yrs?)\b)", re.I
)
_NUM = r"(\d{1,2}(?:\.\d)?)"
_YEARS = r"\s*\+?\s*(?:years?|yrs?)\b"
_RANGE_RE = re.compile(_NUM + r"\s*\+?\s*(?:-|–|—|to)\s*" + _NUM + _YEARS, re.I)
_MIN_RE = re.compile(
    r"(?:(?:minimum|min\.?|at least|over|more than)\s+(?:of\s+)?)?"
    + _NUM
    + r"\s*(?:\+|plus)?\s*(?:or more\s+)?(?:years?|yrs?)\b",
    re.I,
)
_EXPERIENCE_CONTEXT = re.compile(r"\b(experience|exp\b|experienced|background|track record|hands[- ]on)", re.I)
_COMPANY_CONTEXT = re.compile(
    r"\b(founded|in business|we(?:'ve| have| are)\b|our (?:team|company|founders|leaders)|company has|history|ago\b|"
    r"since \d{4}|anniversary|old\b|customers?|clients? for)",
    re.I,
)
_SENTENCE_END = re.compile(r"[.;!?](?:\s|$)")
_ENTRY_LEVEL = re.compile(
    r"\b(freshers?|no (?:prior )?experience (?:is )?(?:required|needed)|entry[- ]level|new grad(?:uate)?s?|"
    r"recent graduates?|graduate (?:program|role|engineer))\b",
    re.I,
)


@dataclass(frozen=True)
class ExperienceRequirement:
    min_years: float
    max_years: float | None
    preferred: bool


def _statements(text: str) -> list[ExperienceRequirement]:
    text = _WORD_NUMBER_RE.sub(lambda m: str(_WORD_NUMBERS[m.group(1).lower()]), text)
    spans = section_spans(text)
    found: list[tuple[int, int, float, float | None]] = []
    for m in _RANGE_RE.finditer(text):
        found.append((m.start(), m.end(), float(m.group(1)), float(m.group(2))))
    taken = [(s, e) for s, e, *_ in found]
    for m in _MIN_RE.finditer(text):
        if not any(s <= m.start() < e for s, e in taken):
            found.append((m.start(), m.end(), float(m.group(1)), None))

    statements = []
    for start, end, low, high in found:
        # Context stays within the sentence: "...for 12 years. Need 4+ years experience" is two statements.
        before = _SENTENCE_END.split(text[max(0, start - 70) : start])[-1]
        after = _SENTENCE_END.split(text[end : end + 70])[0]
        if not (_EXPERIENCE_CONTEXT.search(after) or _EXPERIENCE_CONTEXT.search(before[-40:])):
            continue  # "a 10 year old company", "2 years of free coaching"
        if _COMPANY_CONTEXT.search(before[-45:]) or _COMPANY_CONTEXT.search(after[:25]):
            continue  # "we have been building for 15 years", "15 years ago"
        if low > 20 or (high is not None and (high > 25 or high < low)):
            continue
        label = _label_at(spans, start)
        if label == IGNORED:
            continue
        preferred = label == PREFERRED or bool(_INLINE_PREFERRED.search(after[:50]))
        statements.append(ExperienceRequirement(low, high, preferred))
    return statements


def experience_range(text: str) -> tuple[float | None, float | None]:
    """(minimum years, maximum years or None). The main requirement is the largest required minimum: postings
    state the overall bar first and smaller per-skill bars after ("5+ years in software, 2+ with Kafka")."""
    statements = _statements(text)
    pool = [s for s in statements if not s.preferred] or statements
    if pool:
        main = max(pool, key=lambda s: (s.min_years, -(s.max_years or 99)))
        return main.min_years, main.max_years
    if _ENTRY_LEVEL.search(text):
        return 0.0, 1.0
    return None, None


# ---- salary -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Salary:
    minimum: float
    maximum: float
    currency: str
    period: str  # year | month | hour


_LAKH_RANGE = re.compile(
    r"(?:₹|inr|rs\.?)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:lpa|lakhs?|l)?\s*(?:-|–|to)\s*(?:₹|inr|rs\.?)?\s*"
    r"(\d{1,3}(?:\.\d{1,2})?)\s*(?:lpa\b|lakhs?(?:\s+per\s+annum|\s*p\.?\s*a\.?)?\b|l(?=[\s,.;)]|$))",
    re.I,
)
_LAKH_SINGLE = re.compile(r"(?:₹|inr|rs\.?)?\s*(\d{1,3}(?:\.\d{1,2})?)\s*(?:lpa|lakhs?\s+per\s+annum)\b", re.I)
_INR_AMOUNT = r"(\d{1,2}(?:,\d{2})*,\d{3}|\d{5,8})"
_INR_RANGE = re.compile(
    r"(?:₹|inr|rs\.?)\s*" + _INR_AMOUNT + r"\s*(?:-|–|to)\s*(?:₹|inr|rs\.?)?\s*" + _INR_AMOUNT, re.I
)
_SYMBOL_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}
_CODE_CURRENCY = {"usd": "USD", "eur": "EUR", "gbp": "GBP", "cad": "CAD", "aud": "AUD", "sgd": "SGD"}
_AMOUNT = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k)?"
_CURRENCY_CODE = r"usd|eur|gbp|cad|aud|sgd"
_FOREIGN_RANGE = re.compile(
    rf"(?:([$€£])|\b({_CURRENCY_CODE})\s*)" + _AMOUNT + rf"\s*(?:-|–|to)\s*(?:[$€£]|{_CURRENCY_CODE})?\s*" + _AMOUNT
    + r"(?!\s*(?:m\b|mm\b|million|billion|bn\b|b\b))",
    re.I,
)  # fmt: skip
_HOURLY = re.compile(r"^\s*(?:/\s*h(?:ou)?r|per hour|an hour|hourly)", re.I)
_MONTHLY = re.compile(r"^\s*(?:/\s*mo(?:nth)?|per month|a month|monthly|p\.?\s*m\.?\b)", re.I)


def _number(value: str, thousands: str | None = None) -> float:
    amount = float(value.replace(",", ""))
    return amount * 1000 if thousands else amount


def _period(after: str) -> str:
    if _HOURLY.search(after):
        return "hour"
    if _MONTHLY.search(after):
        return "month"
    return "year"


def _plausible(salary: Salary) -> bool:
    limits = {"year": (1_000, 5_000_000), "month": (100, 1_000_000), "hour": (5, 1_000)}
    low, high = limits[salary.period]
    if salary.currency == "INR":
        low, high = low * 50, high * 50
    return low <= salary.minimum <= salary.maximum <= high


def parse_salary(text: str) -> Salary | None:
    """The first plausible salary range in the text, or None."""
    for m in _LAKH_RANGE.finditer(text):
        found = Salary(float(m.group(1)) * 100_000, float(m.group(2)) * 100_000, "INR", "year")
        if _plausible(found):
            return found
    for m in _INR_RANGE.finditer(text):
        found = Salary(_number(m.group(1)), _number(m.group(2)), "INR", _period(text[m.end() : m.end() + 20]))
        if _plausible(found):
            return found
    for m in _FOREIGN_RANGE.finditer(text):
        currency = _SYMBOL_CURRENCY.get(m.group(1) or "") or _CODE_CURRENCY[(m.group(2) or "").lower()]
        low, high = _number(m.group(3), m.group(4)), _number(m.group(5), m.group(6) or m.group(4))
        found = Salary(low, high, currency, _period(text[m.end() : m.end() + 20]))
        if _plausible(found):
            return found
    m = _LAKH_SINGLE.search(text)
    if m:
        amount = float(m.group(1)) * 100_000
        found = Salary(amount, amount, "INR", "year")
        if _plausible(found):
            return found
    return None
