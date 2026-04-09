"""
LLM abstraction layer.
Supports Claude (Haiku/Sonnet) and Google Gemini with easy switching.

Switch provider via LLM_PROVIDER env var:
  - "anthropic" (default): uses ANTHROPIC_API_KEY
  - "gemini": uses GEMINI_API_KEY
"""

import os
import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Model mapping per provider
MODELS = {
    "anthropic": {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6-20250514",
    },
    "gemini": {
        "haiku": "gemini-2.5-flash",
        "sonnet": "gemini-2.5-pro",
    },
}


class LLMClient:
    """Unified LLM client with retry logic and cost tracking."""

    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
        if self.provider not in MODELS:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider}. Available: {list(MODELS.keys())}")

        if self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "gemini":
            self._init_gemini()

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        logger.info(f"LLM provider: {self.provider}")

    def _init_anthropic(self):
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)

    def _init_gemini(self):
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        self.client = genai.Client(api_key=api_key)

    def call(
        self,
        prompt: str,
        model_key: str = "haiku",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        retries: int = 3,
    ) -> Optional[str]:
        """Call the LLM with retry logic. Returns text response or None."""
        model_id = MODELS[self.provider].get(model_key)
        if not model_id:
            raise ValueError(f"Unknown model key: {model_key}")

        if self.provider == "anthropic":
            return self._call_anthropic(prompt, model_id, max_tokens, temperature, retries)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, model_id, max_tokens, temperature, retries)

    def _call_anthropic(self, prompt, model_id, max_tokens, temperature, retries):
        import anthropic
        for attempt in range(retries):
            try:
                response = self.client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens
                self.call_count += 1
                return response.content[0].text

            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
            except anthropic.APIError as e:
                logger.error(f"API error: {e} (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return None

        logger.error(f"Failed after {retries} attempts")
        return None

    def _call_gemini(self, prompt, model_id, max_tokens, temperature, retries):
        from google.genai import types
        for attempt in range(retries):
            try:
                response = self.client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                # Track usage
                usage = response.usage_metadata
                if usage:
                    self.total_input_tokens += usage.prompt_token_count or 0
                    self.total_output_tokens += usage.candidates_token_count or 0
                self.call_count += 1
                return response.text

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait}s (attempt {attempt + 1}/{retries})")
                    time.sleep(wait)
                else:
                    logger.error(f"Gemini API error: {e} (attempt {attempt + 1}/{retries})")
                    if attempt < retries - 1:
                        time.sleep(2)
                    else:
                        return None

        logger.error(f"Failed after {retries} attempts")
        return None

    def call_json(
        self,
        prompt: str,
        model_key: str = "haiku",
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Optional[dict]:
        """Call LLM and parse response as JSON."""
        raw = self.call(prompt, model_key, max_tokens, temperature)
        if not raw:
            return None

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}\nRaw response:\n{raw[:500]}")
            return None

    def get_usage_summary(self) -> dict:
        """Return usage stats for logging."""
        haiku_input_rate = 1.0 / 1_000_000
        haiku_output_rate = 5.0 / 1_000_000
        est_cost = (
            self.total_input_tokens * haiku_input_rate
            + self.total_output_tokens * haiku_output_rate
        )
        return {
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(est_cost, 4),
        }
