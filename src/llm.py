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
    # key 是「層級」不是型號：haiku=快篩（每天約 26 次）、sonnet=深度分析（每天約 3.4 次）。
    # 換型號只要動這裡，不必動 scorer.py / process_manuals.py。
    "anthropic": {
        "haiku": "claude-haiku-4-5",
        "sonnet": "claude-fable-5-1",
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

# Claude 5 世代（Fable / Mythos / Opus 5 / Sonnet 5）的請求限制：
#   - 取樣參數被移除，傳 temperature / top_p / top_k 會回 400
#   - adaptive thinking 恆開，傳任何 thinking 設定（含 disabled）也會回 400
#   - thinking token 計入 max_tokens，額度不足會把 JSON 輸出截斷
ADAPTIVE_THINKING_PREFIXES = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
)

# thinking 恆開時的 max_tokens 下限。max_tokens 是上限不是預付額度，
# 調高不會多花錢，但調太低會讓推理吃光額度、正文被截斷。
MIN_MAX_TOKENS_WITH_THINKING = 16000

# 每百萬 token 單價 (input, output)，用於成本估算。
# 兩層差 10 倍，必須逐次依實際型號累計，不能用單一費率乘總量。
ANTHROPIC_PRICING = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
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
        self.tracked_cost_usd = 0.0   # 逐次依實際型號累計（目前只有 anthropic 走這條）
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

        params = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if model_id.startswith(ADAPTIVE_THINKING_PREFIXES):
            # 這一代不吃 temperature（400），thinking 也不能傳；改用 max_tokens 留推理空間
            params["max_tokens"] = max(max_tokens, MIN_MAX_TOKENS_WITH_THINKING)
        else:
            params["temperature"] = temperature

        for attempt in range(retries):
            try:
                response = self.client.messages.create(**params)
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens
                self.call_count += 1
                in_rate, out_rate = ANTHROPIC_PRICING.get(model_id, (0.0, 0.0))
                self.tracked_cost_usd += (
                    response.usage.input_tokens * in_rate
                    + response.usage.output_tokens * out_rate
                ) / 1_000_000

                # 安全分類器擋下時 stop_reason="refusal"，content 可能沒有 text block
                if getattr(response, "stop_reason", None) == "refusal":
                    logger.error(f"Request refused by safety classifier ({model_id})")
                    return None
                # thinking 恆開的型號回應可能夾帶 thinking block，不能直接取 content[0]
                text = next((b.text for b in response.content if b.type == "text"), None)
                if text is None:
                    logger.error(
                        f"No text block in response (stop_reason={getattr(response, 'stop_reason', None)})"
                    )
                    return None
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
        # anthropic 走逐次實際型號累計（兩層單價差 10 倍，用單一費率會嚴重低估）。
        # 其餘 provider 仍用單層費率估算，屬下限值。
        if self.provider == "anthropic":
            est_cost = self.tracked_cost_usd
        else:
            rates = {
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
