"""
LLM abstraction layer.
Supports Claude (Haiku/Sonnet), Google Gemini, and Groq (Llama) with easy switching.

Switch provider via LLM_PROVIDER env var:
  - "groq" (default): uses GROQ_API_KEY — free tier, Llama 3.x
  - "anthropic": uses ANTHROPIC_API_KEY
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
    "groq": {
        "haiku": "llama-3.1-8b-instant",
        "sonnet": "llama-3.3-70b-versatile",
    },
}


class LLMClient:
    """Unified LLM client with retry logic and cost tracking."""

    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "groq").lower()
        if self.provider not in MODELS:
            raise ValueError(f"Unknown LLM_PROVIDER: {self.provider}. Available: {list(MODELS.keys())}")

        if self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "gemini":
            self._init_gemini()
        elif self.provider == "groq":
            self._init_groq()

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

    def _init_groq(self):
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        self.client = Groq(api_key=api_key)

    def call(
        self,
        prompt: str,
        model_key: str = "haiku",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        retries: int = 3,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Call the LLM with retry logic. Returns text response or None.

        json_mode: hint to providers that support structured-output enforcement
        (currently only used by Groq, which requires response_format AND the
        word "json" in the prompt). Other providers ignore the flag and rely on
        prompt-level instructions, which has been adequate so far.
        """
        model_id = MODELS[self.provider].get(model_key)
        if not model_id:
            raise ValueError(f"Unknown model key: {model_key}")

        if self.provider == "anthropic":
            return self._call_anthropic(prompt, model_id, max_tokens, temperature, retries)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, model_id, max_tokens, temperature, retries)
        elif self.provider == "groq":
            return self._call_groq(prompt, model_id, max_tokens, temperature, retries, json_mode)

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

    def _call_groq(self, prompt, model_id, max_tokens, temperature, retries, json_mode=False):
        import groq
        kwargs = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            # Llama models on Groq need both response_format AND the literal
            # word "json" in the prompt (validator hard-requires it). The
            # caller (call_json) handles the prompt prefix.
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(**kwargs)
                usage = response.usage
                if usage:
                    self.total_input_tokens += usage.prompt_tokens or 0
                    self.total_output_tokens += usage.completion_tokens or 0
                self.call_count += 1
                if not response.choices:
                    logger.warning("Groq returned empty choices (likely safety filter)")
                    return None
                return response.choices[0].message.content

            except groq.RateLimitError:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Groq rate limited, waiting {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
            except groq.APIError as e:
                logger.error(f"Groq API error: {e} (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Unexpected Groq error: {e}")
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
        # Prepending this serves two purposes:
        # (1) nudges every provider toward clean JSON output,
        # (2) Groq's response_format validator hard-requires the literal token
        #     "json" somewhere in the prompt — without it the API rejects the
        #     request when json_mode=True.
        prompt = "Respond with valid JSON only, no prose, no markdown fences.\n\n" + prompt
        raw = self.call(prompt, model_key, max_tokens, temperature, json_mode=True)
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
        """Return usage stats for logging. Cost estimate is provider-aware."""
        # Per-provider haiku-tier rates ($/token). Sonnet calls are billed higher
        # but we don't track per-call which model was used, so this is a lower
        # bound — use mainly to sanity-check that we're not silently exploding.
        rates = {
            "anthropic": (1.0 / 1_000_000, 5.0 / 1_000_000),  # Haiku 4.5
            "gemini": (0.075 / 1_000_000, 0.30 / 1_000_000),  # 2.5 Flash
            "groq": (0.0, 0.0),  # free tier
        }
        in_rate, out_rate = rates.get(self.provider, (0.0, 0.0))
        est_cost = (
            self.total_input_tokens * in_rate
            + self.total_output_tokens * out_rate
        )
        return {
            "provider": self.provider,
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(est_cost, 4),
        }
