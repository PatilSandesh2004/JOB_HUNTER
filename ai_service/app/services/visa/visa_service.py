"""Evidence-based visa sponsorship detection. Returns UNKNOWN unless the text says so explicitly."""

import re

from ai_service.app.schemas.job import Confidence, VisaSponsorshipEvidence, VisaSponsorshipStatus

# Negative patterns are checked first: "we do not offer visa sponsorship" contains positive words too.
_NEGATIVE = [
    r"(?:no|not|unable to|cannot|can't|won't|will not|do not|don't|does not|doesn't)\s+(?:\w+\s+){0,3}"
    r"(?:offer|provide|support|sponsor)\w*\s+(?:\w+\s+){0,2}(?:visa|sponsorship|h-?1b)",
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?not\s+(?:available|offered|provided|possible)",
    r"without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+)?(?:visa\s+)?sponsorship",
    r"must\s+(?:be\s+)?(?:legally\s+)?(?:authori[sz]ed|eligible)\s+to\s+work\s+.{0,40}without\s+sponsorship",
    r"(?:u\.?s\.?|us)\s+citizenship\s+(?:is\s+)?required",
    r"security\s+clearance\s+required",
    r"no\s+(?:visa\s+)?sponsorship",
    r"no\s+h-?1b",
]
_POSITIVE = [
    r"visa\s+sponsorship\s+(?:is\s+)?(?:available|offered|provided|possible)",
    r"(?:we|will|can|able to|happy to|open to)\s+(?:\w+\s+){0,2}sponsor\w*\s+(?:\w+\s+){0,2}(?:visa|h-?1b|work permit)",
    r"(?:offer|provide|provides|offers|including)\s+(?:\w+\s+){0,2}(?:visa|h-?1b)\s+sponsorship",
    r"h-?1b\s+(?:visa\s+)?(?:sponsorship|transfer)\s+(?:available|provided|offered|supported)",
    r"relocation\s+(?:and|&)\s+visa\s+(?:support|sponsorship)",
    r"visa\s+support",
]
_NEGATIVE_RE = [re.compile(p, re.IGNORECASE) for p in _NEGATIVE]
_POSITIVE_RE = [re.compile(p, re.IGNORECASE) for p in _POSITIVE]


class VisaIntelligenceService:
    def evaluate_sponsorship(self, text: str, source_url: str | None = None) -> VisaSponsorshipEvidence:
        for status, patterns in ((VisaSponsorshipStatus.NO, _NEGATIVE_RE), (VisaSponsorshipStatus.YES, _POSITIVE_RE)):
            for pattern in patterns:
                match = pattern.search(text or "")
                if match:
                    return VisaSponsorshipEvidence(
                        status=status,
                        evidence=_quote(text, match.start(), match.end()),
                        source_url=source_url,
                        confidence=Confidence.HIGH,
                    )
        return VisaSponsorshipEvidence(status=VisaSponsorshipStatus.UNKNOWN, source_url=source_url)


def _quote(text: str, start: int, end: int, pad: int = 40) -> str:
    left, right = max(0, start - pad), min(len(text), end + pad)
    return ("…" if left else "") + text[left:right].strip() + ("…" if right < len(text) else "")
