"""LangGraph application workflow: prepare materials -> fill (and optionally submit) the form."""

import asyncio
import logging
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ai_service.app.core.timeline import timeline_event
from ai_service.app.integrations.browser.form_filler import ApplicantPacket, FillResult, fill_application
from ai_service.app.integrations.browser.pdf_renderer import render_pdf
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.applications.tailoring_service import ApplicationTailoringService
from ai_service.app.services.resume.resume_layout import analyze_resume_layout
from ai_service.app.services.resume.resume_tailor import ResumeTailor
from ai_service.app.services.screening.answer_bank import AnswerBook

logger = logging.getLogger("jobpilot.application_agent")


class ApplicationAgentState(TypedDict, total=False):
    candidate: CandidateProfile
    job: NormalizedJob
    matched_skills: list[str]
    resume_path: str | None
    cover_letter: str | None
    cover_letter_source: str | None
    submit: bool
    screenshot_path: Path
    answers: AnswerBook
    tailor_resume: bool
    tailored_resume_target: Path | None  # where to write a tailored PDF
    existing_tailored_resume: str | None  # reuse the PDF made for an earlier fill of this application
    # Outputs
    tailored_resume_path: str | None
    resume_report: dict[str, Any]
    events: list[dict[str, Any]]
    fill_result: FillResult


def build_packet(
    candidate: CandidateProfile, cover_letter: str | None, resume_path: str | None, answers: AnswerBook | None = None
) -> ApplicantPacket:
    return ApplicantPacket(
        full_name=candidate.name,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        email=candidate.email,
        phone=candidate.phone,
        location=candidate.location,
        linkedin_url=candidate.linkedin_url,
        github_url=candidate.github_url,
        portfolio_url=candidate.portfolio_url,
        current_company=candidate.current_company,
        current_role=candidate.current_role,
        years_of_experience=candidate.years_of_experience or None,
        expected_salary=candidate.preferences.expected_salary,
        notice_period=candidate.preferences.notice_period,
        cover_letter=cover_letter,
        resume_path=resume_path,
        requires_sponsorship=candidate.preferences.visa_sponsorship_required,
        answers=answers or AnswerBook(willing_to_relocate=candidate.preferences.willing_to_relocate),
    )


class ApplicationAgent:
    def __init__(
        self,
        tailoring: ApplicationTailoringService,
        filler=fill_application,
        resume_tailor: ResumeTailor | None = None,
        pdf_renderer=render_pdf,
    ) -> None:
        self.tailoring = tailoring
        self.filler = filler
        self.resume_tailor = resume_tailor or ResumeTailor()
        self.pdf_renderer = pdf_renderer
        self.graph = self._build()

    async def run(self, **state) -> ApplicationAgentState:
        return await self.graph.ainvoke(state)

    def _build(self):
        builder = StateGraph(ApplicationAgentState)
        builder.add_node("prepare_materials", self.prepare_materials)
        builder.add_node("fill_form", self.fill_form)
        builder.add_edge(START, "prepare_materials")
        builder.add_edge("prepare_materials", "fill_form")
        builder.add_edge("fill_form", END)
        return builder.compile()

    async def prepare_materials(self, state: ApplicationAgentState) -> dict:
        events: list[dict[str, Any]] = []
        if state.get("cover_letter"):
            letter, source = state["cover_letter"], state.get("cover_letter_source") or "user"
            events.append(timeline_event("Using your cover letter" if source == "user" else "Using the drafted letter"))
        else:
            letter, source = await self.tailoring.generate_cover_letter(
                state["candidate"], state["job"], state.get("matched_skills")
            )
            how = "by AI from your profile" if source == "llm" else "from a template (LLM unavailable)"
            events.append(timeline_event("Cover letter written", how))

        resume = await self._prepare_resume(state, events)
        return {"cover_letter": letter, "cover_letter_source": source, "events": events, **resume}

    async def _prepare_resume(self, state: ApplicationAgentState, events: list[dict[str, Any]]) -> dict:
        candidate, job = state["candidate"], state["job"]
        report = self.resume_tailor.report(candidate, job)
        out: dict[str, Any] = {"resume_report": report, "tailored_resume_path": None}
        existing = state.get("existing_tailored_resume")
        if existing and await asyncio.to_thread(Path(existing).is_file):
            events.append(timeline_event("Attaching the tailored resume made earlier"))
            return out | {"resume_path": existing, "tailored_resume_path": existing}

        target = state.get("tailored_resume_target")
        if not state.get("tailor_resume") or target is None:
            return out
        # state["resume_path"] is still the user's uploaded file here; mirror its look.
        layout = await asyncio.to_thread(analyze_resume_layout, state.get("resume_path"))
        built = self.resume_tailor.build(candidate, job, layout)
        if built is None:
            events.append(timeline_event("Resume not tailored", "Add skills or work experience to your profile first"))
            return out
        try:
            await self.pdf_renderer(built.html, target)
        except Exception as exc:
            logger.warning("Tailored resume rendering failed: %s", exc)
            events.append(timeline_event("Resume not tailored", f"PDF rendering failed ({exc}); original attached"))
            return out
        matched, wanted = len(report["matched_skills"]), matched_plus_missing(report)
        events.append(
            timeline_event("Tailored resume created", f"Leads with {matched} of {wanted} skills the posting asks for")
        )
        return out | {"resume_path": str(target), "tailored_resume_path": str(target)}

    async def fill_form(self, state: ApplicationAgentState) -> dict:
        packet = build_packet(state["candidate"], state["cover_letter"], state.get("resume_path"), state.get("answers"))
        result = await self.filler(
            state["job"].application_url,
            packet,
            submit=state.get("submit", False),
            screenshot_path=state["screenshot_path"],
        )
        return {"fill_result": result}


def matched_plus_missing(report: dict) -> int:
    return len(report["matched_skills"]) + len(report["missing_skills"])
