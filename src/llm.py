"""
LLM abstraction layer.
Supports Claude (Haiku/Sonnet) with easy switching.
Future: can add Gemini, OpenAI, etc.
"""

import os
import json
import time
import logging
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

# Model mapping
MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6-20250514",
}


class LLMClient:
    """Unified LLM client with retry logic and cost tracking."""

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0

    def call(
        self,
        prompt: str,
        model_key: str = "haiku",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        retries: int = 3,
    ) -> Optional[str]:
        """
        Call the LLM with retry logic.
        Returns the text response or None on failure.
        """
        model_id = MODELS.get(model_key)
        if not model_id:
            raise ValueError(f"Unknown model key: {model_key}. Available: {list(MODELS.keys())}")

        for attempt in range(retries):
            try:
                response = self.client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )

                # Track usage
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens
                self.call_count += 1

                text = response.content[0].text
                logger.debug(
                    f"[{model_key}] {response.usage.input_tokens} in / "
                    f"{response.usage.output_tokens} out"
                )
                return text

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

    def call_json(
        self,
        prompt: str,
        model_key: str = "haiku",
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> Optional[dict]:
        """
        Call LLM and parse response as JSON.
        Handles common issues like markdown fences.
        """
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
        # Approximate cost calculation
        haiku_input_rate = 1.0 / 1_000_000  # $1 per 1M tokens
        haiku_output_rate = 5.0 / 1_000_000
        # Rough estimate (actual split between haiku/sonnet not tracked here)
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
