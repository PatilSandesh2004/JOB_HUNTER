import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger("jobpilot.email_tracker")


class EmailStatusTrackerWorker:
    """
    Automated Email Application Tracker Worker:
    Parses employer email headers & body text to update application status:
    - 'Interview Request' / 'Schedule Interview' -> INTERVIEW_SCHEDULED
    - 'Thank you for applying' / 'Application Received' -> APPLIED
    - 'Not moving forward' / 'Regret to inform' -> REJECTED
    """

    def parse_email_status(self, subject: str, body: str) -> Dict[str, Any]:
        full_text = f"{subject} {body}".lower()

        if any(term in full_text for term in ["interview", "schedule a call", "next steps", "speak with"]):
            return {
                "detected_status": "INTERVIEW_SCHEDULED",
                "confidence": "HIGH",
                "summary": "Employer requested an interview call.",
            }
        elif any(term in full_text for term in ["regret", "unfortunately", "not moving forward", "other candidates"]):
            return {
                "detected_status": "REJECTED",
                "confidence": "HIGH",
                "summary": "Employer sent non-selection response.",
            }
        elif any(term in full_text for term in ["received your application", "thank you for applying", "application confirmed"]):
            return {
                "detected_status": "APPLIED",
                "confidence": "HIGH",
                "summary": "Application confirmation email detected.",
            }

        return {
            "detected_status": "UNKNOWN",
            "confidence": "LOW",
            "summary": "No conclusive application status change detected.",
        }
