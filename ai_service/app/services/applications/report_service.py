"""Your job-search progress: what you sent, what came back, and which kinds of roles get replies."""

import html
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.app.models.application import ApplicationModel
from ai_service.app.repositories.application_repository import follow_up_due
from ai_service.app.schemas.application import ApplicationStatus as S
from ai_service.app.services.matching.roles import describe

SENT = {S.APPLIED.value, S.INTERVIEW.value, S.OFFER.value, S.REJECTED.value}
RESPONDED = {S.INTERVIEW.value, S.OFFER.value, S.REJECTED.value}
POSITIVE = {S.INTERVIEW.value, S.OFFER.value}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _percent(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


async def progress_report(session: AsyncSession, days: int = 7) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    rows = list((await session.scalars(select(ApplicationModel))).all())

    def in_period(row: ApplicationModel, status: str) -> bool:
        return row.status == status and (_aware(row.updated_at) or now) >= since

    sent = [r for r in rows if r.status in SENT]
    applied_recently = [r for r in sent if (_aware(r.applied_at) or _aware(r.created_at) or now) >= since]
    kinds: dict[str, Counter] = {}
    for row in sent:
        kind = describe(row.job_title)
        kinds.setdefault(kind, Counter())["applied"] += 1
        if row.status in POSITIVE:
            kinds[kind]["interviews"] += 1
    by_kind = sorted(
        (
            {
                "kind": kind,
                "applied": c["applied"],
                "interviews": c["interviews"],
                "interview_rate": _percent(c["interviews"], c["applied"]),
            }
            for kind, c in kinds.items()
        ),
        key=lambda k: (-k["applied"], k["kind"]),
    )
    return {
        "period_days": days,
        "since": since.isoformat(),
        "period": {
            "applied": len(applied_recently),
            "interviews": sum(in_period(r, S.INTERVIEW.value) for r in rows),
            "offers": sum(in_period(r, S.OFFER.value) for r in rows),
            "rejections": sum(in_period(r, S.REJECTED.value) for r in rows),
        },
        "totals": {
            "saved": sum(r.status == S.SAVED.value for r in rows),
            "applied": len(sent),
            "responses": sum(r.status in RESPONDED for r in rows),
            "interviews": sum(r.status in POSITIVE for r in rows),
            "offers": sum(r.status == S.OFFER.value for r in rows),
            "response_rate": _percent(sum(r.status in RESPONDED for r in sent), len(sent)),
            "interview_rate": _percent(sum(r.status in POSITIVE for r in sent), len(sent)),
        },
        "follow_ups_due": sum(follow_up_due(r, now) for r in rows),
        "by_kind": by_kind,
    }


def report_email(report: dict[str, Any]) -> tuple[str, str, str]:
    """(subject, html, text) for the weekly progress email."""
    p, t = report["period"], report["totals"]
    lines = [
        f"Applied: {p['applied']}",
        f"Interviews: {p['interviews']}",
        f"Offers: {p['offers']}",
        f"Rejections: {p['rejections']}",
        f"Overall interview rate: {t['interview_rate']}% of {t['applied']} applications",
    ]
    if report["follow_ups_due"]:
        lines.append(f"Follow-ups due: {report['follow_ups_due']}")
    kinds = [f"{k['kind']}: {k['applied']} applied, {k['interviews']} interviews" for k in report["by_kind"][:5]]
    subject = f"JobPilot weekly: {p['applied']} applied, {p['interviews']} interviews"
    body = "".join(f"<li>{html.escape(line)}</li>" for line in lines)
    kind_rows = "".join(f"<li>{html.escape(k)}</li>" for k in kinds)
    html_body = f"<h2>Your week in job search</h2><ul>{body}</ul>" + (
        f"<h3>By kind of role</h3><ul>{kind_rows}</ul>" if kind_rows else ""
    )
    text = "\n".join(lines + ([""] + kinds if kinds else []))
    return subject, html_body, text
