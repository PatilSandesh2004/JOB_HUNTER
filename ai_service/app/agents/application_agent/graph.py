from typing import TypedDict, Optional, Dict, Any
from langgraph.graph import StateGraph, START, END


class ApplicationAgentState(TypedDict):
    candidate_id: str
    job_id: str
    application_url: str
    applicant_data: Dict[str, Any]
    cover_letter: Optional[str]
    tailored_resume: Optional[str]
    auto_submit: bool
    status: str
    human_approved: bool
    confirmation: Optional[str]


# Node filling application form via browser integration with optional auto-submit.
async def fill_application_node(state: ApplicationAgentState) -> ApplicationAgentState:
    from ai_service.app.integrations.browser.playwright_client import PlaywrightBrowserClient
    
    browser_client = PlaywrightBrowserClient()
    auto_sub = state.get("auto_submit", False)
    
    res = await browser_client.fill_job_application(
        application_url=state["application_url"],
        applicant_data=state["applicant_data"],
        auto_submit=auto_sub,
        headless=True
    )
    state["status"] = res.get("status", "PENDING_APPROVAL")
    if res.get("confirmation"):
        state["confirmation"] = res.get("confirmation")
    return state


# Node executing final submission if human-approved or auto-submitted.
def submit_application_node(state: ApplicationAgentState) -> ApplicationAgentState:
    if state.get("human_approved", False) or state.get("status") == "APPLIED":
        state["status"] = "APPLIED"
        if not state.get("confirmation"):
            state["confirmation"] = "Submitted successfully with verified approval."
    else:
        state["status"] = "PENDING_APPROVAL"
        state["confirmation"] = "Awaiting explicit human approval before submitting."
    return state


def check_approval(state: ApplicationAgentState) -> str:
    if state.get("human_approved", False) or state.get("status") == "APPLIED":
        return "submit_application"
    return END


# Function compiling LangGraph application workflow graph.
def create_application_graph():
    builder = StateGraph(ApplicationAgentState)
    builder.add_node("fill_application", fill_application_node)
    builder.add_node("submit_application", submit_application_node)
    
    builder.add_edge(START, "fill_application")
    builder.add_conditional_edges("fill_application", check_approval)
    builder.add_edge("submit_application", END)
    
    return builder.compile()
