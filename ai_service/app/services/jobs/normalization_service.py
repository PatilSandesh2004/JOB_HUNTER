from typing import Any, Dict, List
import uuid
from ai_service.app.schemas.job import NormalizedJob, RemoteScope, VisaSponsorshipEvidence, VisaSponsorshipStatus


class JobNormalizationService:
    
    # Adapter method transforming raw search engine or ATS result dictionary into a NormalizedJob model.
    def normalize_raw_result(self, raw: Dict[str, Any], source: str = "searxng") -> NormalizedJob:
        title = raw.get("title", "Untitled Job")
        url = raw.get("url", raw.get("link", ""))
        snippet = raw.get("content", raw.get("snippet", ""))
        
        # Simple heuristic extraction of remote status from title/snippet
        combined = f"{title} {snippet}".lower()
        if "remote" in combined:
            if "india" in combined:
                workplace = RemoteScope.REMOTE_INDIA_ONLY
            elif "us" in combined or "united states" in combined:
                workplace = RemoteScope.REMOTE_US_ONLY
            else:
                workplace = RemoteScope.REMOTE_WORLDWIDE
        elif "hybrid" in combined:
            workplace = RemoteScope.HYBRID
        elif "on-site" in combined or "onsite" in combined:
            workplace = RemoteScope.ONSITE
        else:
            workplace = RemoteScope.UNKNOWN
            
        # Visa sponsorship check (strict evidence required)
        visa_status = VisaSponsorshipStatus.UNKNOWN
        evidence_text = None
        if "visa sponsorship available" in combined or "h1b sponsorship" in combined:
            visa_status = VisaSponsorshipStatus.YES
            evidence_text = "Explicit sponsorship mention in listing snippet"
        elif "no visa sponsorship" in combined or "no h1b" in combined:
            visa_status = VisaSponsorshipStatus.NO
            evidence_text = "Explicit no-sponsorship statement in listing snippet"

        return NormalizedJob(
            id=str(uuid.uuid4()),
            title=title,
            company=raw.get("engine", raw.get("company", "Unknown Company")),
            description=snippet,
            location="Unknown",
            workplace_type=workplace,
            remote_scope=workplace,
            visa_sponsorship=VisaSponsorshipEvidence(
                status=visa_status,
                evidence=evidence_text,
                source_url=url,
                confidence="MEDIUM" if visa_status != VisaSponsorshipStatus.UNKNOWN else "LOW",
            ),
            application_url=url,
            source=source,
            source_job_id=raw.get("source_job_id"),
        )
