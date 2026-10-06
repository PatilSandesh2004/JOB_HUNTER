"""Groq chat-completions client with a model fallback chain and JSON-mode helper."""

import json
import logging
import re
from typing import Any

from ai_service.app.core.config import Settings, settings
from ai_service.app.core.errors import LLMUnavailableError

logger = logging.getLogger("jobpilot.llm")

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMClient:
    def __init__(self, config: Settings = settings) -> None:
        self._config = config
        self._models = list(dict.fromkeys([config.groq_model, *config.groq_fallback_models]))
        self._client = None
        if config.llm_enabled:
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=config.groq_api_key)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def primary_model(self) -> str:
        return self._models[0]

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the first non-empty completion across the model chain, or raise LLMUnavailableError."""
        if self._client is None:
            raise LLMUnavailableError("GROQ_API_KEY is not configured")

        last_error: Exception | None = None
        for model in self._models:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self._config.llm_temperature if temperature is None else temperature,
                "max_tokens": max_tokens or self._config.llm_max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if model.startswith("openai/gpt-oss"):
                # Reasoning tokens count against max_tokens; extraction/writing needs little of it.
                kwargs["reasoning_effort"] = "low"
            try:
                response = await self._client.chat.completions.create(**kwargs)
                content = (response.choices[0].message.content or "").strip()
                if content:
                    return content
                last_error = ValueError(f"empty completion from {model}")
            except Exception as exc:  # provider errors vary; try the next model
                last_error = exc
                logger.warning("LLM call failed on model %s: %s", model, exc)

        raise LLMUnavailableError(f"All LLM models failed: {last_error}")

    async def complete_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> dict[str, Any]:
        raw = await self.complete(system_prompt, user_prompt, json_mode=True, **kwargs)
        return parse_json_object(raw)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences or surrounding prose."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(text)
        if not match:
            raise LLMUnavailableError("LLM did not return JSON") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise LLMUnavailableError("LLM returned JSON that is not an object")
    return value
