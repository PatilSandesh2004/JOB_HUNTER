import logging
from langgraph.graph import StateGraph, END, START
from ai_service.app.agents.search_agent.state import SearchAgentState
from ai_service.app.services.search.search_service import SearchService
from ai_service.app.schemas.search import SearchResultItem
from ai_service.app.integrations.llm.llm_client import LLMClient

logger = logging.getLogger("jobpilot.search_agent")


# Async LangGraph node for AI-powered query recreation and expansion using Groq LLM.
async def generate_queries_node(state: SearchAgentState) -> SearchAgentState:
    request = state["request"]
    base_queries = []
    
    for role in request.roles:
        if request.locations:
            for loc in request.locations:
                q = f"{role} {loc}"
                if request.remote_only:
                    q += " remote"
                base_queries.append(q)
        else:
            q = role
            if request.remote_only:
                q += " remote"
            base_queries.append(q)

    # Groq LLM Query Re-creator & Expansion
    llm_client = LLMClient()
    expanded_queries = list(base_queries)
    
    try:
        system_prompt = "You are an expert recruitment search engine optimizer."
        user_prompt = (
            f"Given these target job roles: {', '.join(request.roles)} and locations: {', '.join(request.locations)}.\n"
            f"Generate 2 optimized boolean web search queries (one per line, no numbering or markdown) to discover direct career postings."
        )
        llm_response = await llm_client.generate_completion(system_prompt, user_prompt)
        ai_generated_queries = [line.strip() for line in llm_response.split("\n") if line.strip() and not line.startswith("Here")]
        for q in ai_generated_queries[:2]:
            if q and q not in expanded_queries:
                expanded_queries.append(q)
    except Exception as e:
        logger.warning(f"Query recreation LLM expansion skipped: {e}")

    state["generated_queries"] = expanded_queries
    state["current_query_index"] = 0
    state["raw_results"] = []
    state["normalized_results"] = []
    state["errors"] = []
    return state


# LangGraph node for executing search queries asynchronously using SearchService.
async def execute_search_node(state: SearchAgentState, search_service: SearchService) -> SearchAgentState:
    queries = state["generated_queries"]
    idx = state["current_query_index"]
    
    if idx < len(queries):
        query = queries[idx]
        try:
            results = await search_service.search(query=query)
            state["raw_results"].extend(results)
            
            for item in results:
                state["normalized_results"].append(
                    SearchResultItem(
                        title=item.get("title", "Untitled"),
                        url=item.get("url", ""),
                        content=item.get("content"),
                        engine=item.get("engine"),
                    )
                )
        except Exception as e:
            state["errors"].append(f"Query '{query}' failed: {str(e)}")
            
        state["current_query_index"] = idx + 1
        
    return state


# Conditional edge decision function checking if more queries remain to execute.
def should_continue(state: SearchAgentState) -> str:
    if state["current_query_index"] < len(state["generated_queries"]):
        return "execute_search"
    return END


# Function compiling and returning the complete LangGraph search workflow graph.
def create_search_graph(search_service: SearchService):
    builder = StateGraph(SearchAgentState)
    
    async def run_gen_queries(state: SearchAgentState) -> SearchAgentState:
        return await generate_queries_node(state)

    async def run_search(state: SearchAgentState) -> SearchAgentState:
        return await execute_search_node(state, search_service)

    builder.add_node("generate_queries", run_gen_queries)
    builder.add_node("execute_search", run_search)
    
    builder.add_edge(START, "generate_queries")
    builder.add_edge("generate_queries", "execute_search")
    builder.add_conditional_edges("execute_search", should_continue)
    
    return builder.compile()
