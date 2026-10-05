from typing import Optional
from ai_service.app.schemas.job import VisaSponsorshipEvidence, VisaSponsorshipStatus


class VisaIntelligenceService:

    # Strict evidence extractor for visa sponsorship. Never guesses or assumes status.
    def evaluate_sponsorship(self, description_text: str, source_url: Optional[str] = None) -> VisaSponsorshipEvidence:
        text_lower = description_text.lower()

        # Explicit positive evidence keywords
        positive_keywords = [
            "visa sponsorship available",
            "h1b sponsorship provided",
            "will sponsor visa",
            "sponsorship is available",
            "open to sponsoring",
        ]

        # Explicit negative evidence keywords
        negative_keywords = [
            "no visa sponsorship",
            "cannot sponsor visa",
            "must be authorized to work without sponsorship",
            "u.s. citizenship required",
            "no h1b",
        ]

        for pos in positive_keywords:
            if pos in text_lower:
                return VisaSponsorshipEvidence(
                    status=VisaSponsorshipStatus.YES,
                    evidence=f"Matched explicit statement: '{pos}'",
                    source_url=source_url,
                    confidence="HIGH",
                )

        for neg in negative_keywords:
            if neg in text_lower:
                return VisaSponsorshipEvidence(
                    status=VisaSponsorshipStatus.NO,
                    evidence=f"Matched explicit exclusion statement: '{neg}'",
                    source_url=source_url,
                    confidence="HIGH",
                )

        # Default fallback when no reliable evidence exists
        return VisaSponsorshipEvidence(
            status=VisaSponsorshipStatus.UNKNOWN,
            evidence="No explicit visa sponsorship statement found in source description.",
            source_url=source_url,
            confidence="LOW",
        )
