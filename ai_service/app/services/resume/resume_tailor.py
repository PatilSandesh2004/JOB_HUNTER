"""A per-job resume built from the candidate's real profile, ordered to lead with what the posting asks for.

Nothing is rewritten or invented. Bullets are taken verbatim from the work-experience descriptions and
skills from the profile; only their order and emphasis change. Roles stay in chronological order.
"""

import html
import re
from dataclasses import dataclass

from ai_service.app.schemas.candidate import CandidateProfile, WorkExperience
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.skills.catalog import normalize_skill_list, skill_pattern

# Bullet separators: line breaks, bullet glyphs, or sentence ends inside a paragraph.
_BULLET_SPLIT_RE = re.compile(r"\n+|\s*[•·▪‣◦]\s*|(?<=[.!?])\s+(?=[A-Z])")
_LEADING_MARK_RE = re.compile(r"^[\s\-–—*]+")


@dataclass
class TailoredResume:
    html: str
    report: dict


class ResumeTailor:
    def report(self, candidate: CandidateProfile, job: NormalizedJob) -> dict:
        """Keyword-gap report: which of the posting's skills the profile covers (cheap; no PDF)."""
        have = {s.lower() for s in normalize_skill_list(candidate.skills)}
        wanted = normalize_skill_list(job.required_skills)
        matched = [s for s in wanted if s.lower() in have]
        bullets = [b for w in candidate.work_experience for b in _bullets(w.description)]
        return {
            "matched_skills": matched,
            "missing_skills": [s for s in wanted if s.lower() not in have],
            "emphasised_bullets": sum(1 for b in bullets if _hits(b, matched)),
            "keyword_coverage": round(100 * len(matched) / len(wanted), 1) if wanted else 0.0,
        }

    def build(self, candidate: CandidateProfile, job: NormalizedJob) -> TailoredResume | None:
        """None when the profile is too thin to produce a resume worth attaching."""
        if not candidate.name or not (candidate.skills or candidate.work_experience):
            return None
        report = self.report(candidate, job)
        return TailoredResume(html=_render(candidate, report["matched_skills"]), report=report)


def _bullets(description: str | None) -> list[str]:
    parts = (_LEADING_MARK_RE.sub("", p).strip() for p in _BULLET_SPLIT_RE.split(description or ""))
    return [p for p in parts if len(p) > 2]


def _hits(text: str, skills: list[str]) -> int:
    return sum(1 for s in skills if skill_pattern(s).search(text))


def _emphasise(text: str, skills: list[str]) -> str:
    """HTML-escape `text`, then bold the posting's skills where they appear."""
    escaped = html.escape(text)
    if not skills:
        return escaped
    # One combined pass, so a later skill can never match inside markup added for an earlier one.
    combined = re.compile("|".join(f"(?:{skill_pattern(s).pattern})" for s in skills), re.IGNORECASE)
    return combined.sub(lambda m: f"<strong>{m.group(0)}</strong>", escaped)


def _ordered_skills(candidate: CandidateProfile, matched: list[str]) -> list[str]:
    own = normalize_skill_list(candidate.skills)
    first = [s for s in own if s.lower() in {m.lower() for m in matched}]
    return first + [s for s in own if s not in first]


def _experience_html(work: WorkExperience, matched: list[str]) -> str:
    # Most relevant bullets first; ties keep the candidate's own order.
    bullets = sorted(_bullets(work.description), key=lambda b: -_hits(b, matched))
    dates = " – ".join(p for p in (work.start_date, work.end_date or "Present") if p)
    items = "".join(f"<li>{_emphasise(b, matched)}</li>" for b in bullets)
    return (
        f'<div class="role"><div class="role-head"><span><b>{html.escape(work.title)}</b>, '
        f"{html.escape(work.company)}{', ' + html.escape(work.location) if work.location else ''}</span>"
        f'<span class="dates">{html.escape(dates)}</span></div>'
        f"{f'<ul>{items}</ul>' if items else ''}</div>"
    )


def _render(candidate: CandidateProfile, matched: list[str]) -> str:
    contact = " · ".join(
        html.escape(v)
        for v in (
            candidate.email,
            candidate.phone,
            candidate.location,
            candidate.linkedin_url,
            candidate.github_url,
            candidate.portfolio_url,
        )
        if v
    )
    matched_lower = {m.lower() for m in matched}
    skills = ", ".join(
        f"<strong>{html.escape(s)}</strong>" if s.lower() in matched_lower else html.escape(s)
        for s in _ordered_skills(candidate, matched)
    )
    sections = []
    if candidate.summary:
        sections.append(f"<h2>Summary</h2><p>{html.escape(candidate.summary)}</p>")
    if skills:
        sections.append(f"<h2>Skills</h2><p>{skills}</p>")
    if candidate.work_experience:
        roles = "".join(_experience_html(w, matched) for w in candidate.work_experience)
        sections.append(f"<h2>Experience</h2>{roles}")
    if candidate.education:
        rows = "".join(
            "<p>"
            + html.escape(
                ", ".join(p for p in (e.degree, e.field_of_study) if p)
                + (" — " if e.degree or e.field_of_study else "")
            )
            + f"{html.escape(e.institution)}{f' ({e.graduation_year})' if e.graduation_year else ''}</p>"
            for e in candidate.education
        )
        sections.append(f"<h2>Education</h2>{rows}")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(candidate.name)}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; color: #111; line-height: 1.4; margin: 0; }}
  h1 {{ font-size: 20pt; margin: 0 0 2pt; }}
  .contact {{ color: #444; font-size: 9.5pt; margin-bottom: 10pt; }}
  h2 {{ font-size: 11pt; text-transform: uppercase; letter-spacing: .06em; border-bottom: 1px solid #999;
        margin: 12pt 0 5pt; padding-bottom: 2pt; }}
  p {{ margin: 0 0 4pt; }}
  .role {{ margin-bottom: 7pt; page-break-inside: avoid; }}
  .role-head {{ display: flex; justify-content: space-between; gap: 12pt; }}
  .dates {{ color: #444; white-space: nowrap; }}
  ul {{ margin: 3pt 0 0 14pt; padding: 0; }}
  li {{ margin-bottom: 2pt; }}
</style></head><body>
<h1>{html.escape(candidate.name)}</h1>
<div class="contact">{contact}</div>
{"".join(sections)}
</body></html>"""
