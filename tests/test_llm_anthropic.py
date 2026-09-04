"""Anthropic 請求契約測試（無網路、不需 API key，直接跑：python3 tests/test_llm_anthropic.py）

釘住 Claude 5 世代（Fable / Mythos / Opus 5 / Sonnet 5）的三個硬性限制，
這三項都是 400 或例外，而且都不會在語法檢查階段被抓到：
  1. 取樣參數已移除 —— 傳 temperature 會 400
  2. adaptive thinking 恆開 —— 傳任何 thinking 設定會 400，且 thinking token 計入 max_tokens
  3. 回應可能夾帶 thinking block —— 舊寫法 content[0].text 會取到錯的東西或直接爆
"""

import logging
import os
import sys
import types

logging.disable(logging.CRITICAL)

# 本機/CI 不一定裝 anthropic SDK；_call_anthropic 只用到兩個例外類別
_fake = types.ModuleType("anthropic")


class _RateLimitError(Exception):
    pass


class _APIError(Exception):
    pass


_fake.RateLimitError = _RateLimitError
_fake.APIError = _APIError
sys.modules.setdefault("anthropic", _fake)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import llm  # noqa: E402


class Block:
    def __init__(self, type_, **kw):
        self.type = type_
        self.__dict__.update(kw)


class Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class Response:
    def __init__(self, content, stop_reason="end_turn", i=1000, o=500):
        self.content, self.stop_reason, self.usage = content, stop_reason, Usage(i, o)


SENT = []


class _FakeMessages:
    def __init__(self, resp):
        self.resp = resp

    def create(self, **kwargs):
        SENT.append(kwargs)
        return self.resp


class _FakeClient:
    def __init__(self, resp):
        self.messages = _FakeMessages(resp)


def make_client(resp):
    """繞過 __init__（會要求 ANTHROPIC_API_KEY），只裝配 _call_anthropic 需要的欄位。"""
    c = object.__new__(llm.LLMClient)
    c.provider = "anthropic"
    c.client = _FakeClient(resp)
    c.total_input_tokens = c.total_output_tokens = c.call_count = 0
    c.tracked_cost_usd = 0.0
    return c


FAILED = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(label)
    print(f"  {'✅' if ok else '❌'} {label}")
    if not ok:
        print(f"     得到 {got!r}，期望 {want!r}")


def main():
    deep = llm.MODELS["anthropic"]["sonnet"]
    fast = llm.MODELS["anthropic"]["haiku"]

    print(f"── 深度分析層 {deep}（adaptive thinking 恆開）──")
    SENT.clear()
    c = make_client(Response([Block("text", text="OK")]))
    out = c.call("hi", model_key="sonnet", max_tokens=6000, temperature=0.2)
    check("不送 temperature（送了會 400）", "temperature" in SENT[0], False)
    check("不送 thinking（送了會 400）", "thinking" in SENT[0], False)
    check("max_tokens 由 6000 拉到下限 16000（thinking 計入額度，太低會截斷 JSON）",
          SENT[0]["max_tokens"], llm.MIN_MAX_TOKENS_WITH_THINKING)
    check("回傳文字", out, "OK")
    check("依 Fable 費率計價", round(c.tracked_cost_usd, 6),
          round((1000 * 10 + 500 * 50) / 1e6, 6))

    print(f"\n── 快篩層 {fast}（仍是舊契約）──")
    SENT.clear()
    c = make_client(Response([Block("text", text="OK")]))
    c.call("hi", model_key="haiku", max_tokens=4096, temperature=0.2)
    check("仍送 temperature", SENT[0].get("temperature"), 0.2)
    check("max_tokens 不被拉高", SENT[0]["max_tokens"], 4096)
    check("依 Haiku 費率計價", round(c.tracked_cost_usd, 6),
          round((1000 * 1 + 500 * 5) / 1e6, 6))

    print("\n── 回應形狀的邊界 ──")
    c = make_client(Response([Block("thinking", thinking="嗯…"), Block("text", text="真正的答案")]))
    check("夾帶 thinking block 時仍取到 text（舊寫法 content[0].text 會取到 thinking）",
          c.call("hi", model_key="sonnet"), "真正的答案")
    c = make_client(Response([], stop_reason="refusal"))
    check("安全分類器擋下時回 None，不 IndexError", c.call("hi", model_key="sonnet"), None)
    c = make_client(Response([Block("thinking", thinking="…")], stop_reason="max_tokens"))
    check("只有 thinking 沒有 text 時回 None", c.call("hi", model_key="sonnet"), None)

    print("\n── 成本回報 ──")
    c = make_client(Response([Block("text", text="OK")]))
    c.call("a", model_key="sonnet")
    c.call("b", model_key="haiku")
    want = round((1000 * 10 + 500 * 50) / 1e6 + (1000 * 1 + 500 * 5) / 1e6, 4)
    check("兩層混用逐次計價（單一費率乘總量會低估 10 倍）",
          c.get_usage_summary()["estimated_cost_usd"], want)

    print("\n── 每個 anthropic 型號都要有價目，否則成本靜默歸零 ──")
    for key, model_id in llm.MODELS["anthropic"].items():
        check(f"{key} → {model_id} 有價目", model_id in llm.ANTHROPIC_PRICING, True)

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
        sys.exit(1)
    print("🎉 全部通過")


if __name__ == "__main__":
    main()
