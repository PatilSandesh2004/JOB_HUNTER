"""Classify employer emails into application status updates.

Rejections are checked first because they often reuse interview vocabulary
("we will not be moving forward to the interview stage").
"""

import re
from dataclasses import dataclass

from ai_service.app.schemas.application import ApplicationStatus

_RULES: list[tuple[ApplicationStatus, re.Pattern[str]]] = [
    (
        ApplicationStatus.REJECTED,
        re.compile(
            r"regret to inform|unfortunately|not (be )?moving forward|decided to (pursue|move forward with) other|"
            r"position has been filled|not (been )?selected",
            re.I,
        ),
    ),
    (
        ApplicationStatus.INTERVIEW,
        re.compile(
            r"schedule (an? )?(interview|call|chat)|invite you to (an? )?interview|availability for|next round", re.I
        ),
    ),
    (
        ApplicationStatus.APPLIED,
        re.compile(
            r"received your application|thank you for (applying|your application)|application (was )?received", re.I
        ),
    ),
]


@dataclass(frozen=True)
class EmailClassification:
    status: ApplicationStatus | None
    matched_phrase: str | None


def classify_email(subject: str, body: str) -> EmailClassification:
    text = f"{subject}\n{body}"
    for status, pattern in _RULES:
        match = pattern.search(text)
        if match:
            return EmailClassification(status, match.group(0))
    return EmailClassification(None, None)
