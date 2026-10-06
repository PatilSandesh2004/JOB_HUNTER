"""Match an employer's email to one of your applications and decide whether its status should move.

Conservative on purpose: the company must be named in the email's sender or subject (a mention in the
body is not enough), exactly one company must match, and a status only ever moves forward.
"""

import re

from ai_service.app.models.application import ApplicationModel
from ai_service.app.schemas.application import ApplicationStatus as S

# new status -> statuses it may replace
FORWARD: dict[S, set[S]] = {
    S.APPLIED: {S.AWAITING_CONFIRMATION, S.PENDING_APPROVAL, S.NEEDS_MANUAL, S.FAILED},
    S.INTERVIEW: {S.APPLIED, S.AWAITING_CONFIRMATION, S.PENDING_APPROVAL, S.NEEDS_MANUAL, S.FAILED},
    S.REJECTED: {S.APPLIED, S.INTERVIEW, S.AWAITING_CONFIRMATION, S.PENDING_APPROVAL, S.NEEDS_MANUAL, S.FAILED},
}
TRACKED = set().union(*FORWARD.values())
_SUFFIX_RE = re.compile(
    r"[,.]?\s+(inc|llc|ltd|limited|pvt|private|plc|gmbh|corp|corporation|co|ai|labs|technologies|tech)\.?$", re.I
)


def company_key(name: str) -> str:
    """'Acme Technologies Pvt Ltd' -> 'acme'."""
    key = name.strip().lower()
    while True:
        shorter = _SUFFIX_RE.sub("", key).strip()
        if shorter == key or not shorter:
            return key
        key = shorter


def names_company(company: str, sender: str, subject: str) -> bool:
    key = company_key(company)
    if len(key) < 3:
        return False
    text = f"{sender} {subject}".lower()
    if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text):
        return True
    # Sender domains squash spaces: "Acme Corp" mails from @acmecorp.com
    squashed = re.sub(r"[^a-z0-9]", "", key)
    domain = sender.lower().rpartition("@")[2]
    return len(squashed) >= 4 and squashed in domain


def match_application(apps: list[ApplicationModel], sender: str, subject: str) -> ApplicationModel | None:
    """The one tracked application this email is about, or None when unclear."""
    matched = [a for a in apps if S(a.status) in TRACKED and names_company(a.company, sender, subject)]
    if len({company_key(a.company) for a in matched}) != 1:
        return None
    return max(matched, key=lambda a: a.updated_at)


def next_status(current: S, classified: S | None) -> S | None:
    if classified is None or current not in FORWARD.get(classified, set()):
        return None
    return classified
