import os
import logging
from typing import Optional, List
from groq import AsyncGroq
from ai_service.app.core.config import settings

logger = logging.getLogger("jobpilot.llm")


class LLMClient:
    """
    LLM Client powered by Groq API (openai/gpt-oss-120b / qwen/qwen3.8-27b).
    Generates dynamic, job-specific cover letters and query expansions.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or settings.groq_api_key or os.environ.get("GROQ_API_KEY", "")
        self.primary_model = model or settings.groq_model or "openai/gpt-oss-120b"
        self.fallback_models = [self.primary_model, "qwen/qwen3.8-27b", "allam-2-7b"]
        
        if self.api_key:
            try:
                self.groq_client = AsyncGroq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed initializing Groq client: {e}")
                self.groq_client = None
        else:
            self.groq_client = None

    async def generate_completion(self, system_prompt: str, user_prompt: str) -> str:
        if self.groq_client:
            for model_name in self.fallback_models:
                try:
                    response = await self.groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.7,
                        max_tokens=1024,
                    )
                    content = response.choices[0].message.content or ""
                    if content.strip():
                        return content
                except Exception as e:
                    logger.warning(f"Groq API call failed for model '{model_name}': {e}")

        # Emergency fallback if all API calls fail
        return (
            f"Dear Hiring Manager,\n\n"
            f"I am writing to express my enthusiastic interest in your open position. "
            f"With extensive hands-on experience in software engineering, artificial intelligence systems, "
            f"and high-performance backend architectures, I am well-equipped to drive immediate impact for your team.\n\n"
            f"Sincerely,\nJobPilot Applicant"
        )
