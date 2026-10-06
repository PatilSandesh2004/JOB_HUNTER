"""LangGraph application workflow: prepare materials -> fill (and optionally submit) the form."""

from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ai_service.app.integrations.browser.form_filler import ApplicantPacket, FillResult, fill_application
from ai_service.app.schemas.candidate import CandidateProfile
from ai_service.app.schemas.job import NormalizedJob
from ai_service.app.services.applications.tailoring_service import ApplicationTailoringService


class ApplicationAgentState(TypedDict, total=False):
    candidate: CandidateProfile
    job: NormalizedJob
    matched_skills: list[str]
    resume_path: str | None
    cover_letter: str | None
    cover_letter_source: str | None
    submit: bool
    screenshot_path: Path
    fill_result: FillResult


def build_packet(candidate: CandidateProfile, cover_letter: str | None, resume_path: str | None) -> ApplicantPacket:
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
    )


class ApplicationAgent:
    def __init__(self, tailoring: ApplicationTailoringService, filler=fill_application) -> None:
        self.tailoring = tailoring
        self.filler = filler
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
        if state.get("cover_letter"):
            return {"cover_letter_source": state.get("cover_letter_source") or "user"}
        letter, source = await self.tailoring.generate_cover_letter(
            state["candidate"], state["job"], state.get("matched_skills")
        )
        return {"cover_letter": letter, "cover_letter_source": source}

    async def fill_form(self, state: ApplicationAgentState) -> dict:
        packet = build_packet(state["candidate"], state["cover_letter"], state.get("resume_path"))
        result = await self.filler(
            state["job"].application_url,
            packet,
            submit=state.get("submit", False),
            screenshot_path=state["screenshot_path"],
        )
        return {"fill_result": result}
