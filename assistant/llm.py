"""Client for LFM3 behind `geniex serve` (OpenAI-compatible). Standard library only.

Every request is capped (max_completion_tokens) and sent with enable_think=false.
An empty or zero-token reply is retried once with the request made unique.
"""

import json
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

_THINK = re.compile(r"<think>.*?</think>", re.S)


@dataclass
class LLMResult:
    text: str
    ok: bool
    ms: float
    tokens: int = 0
    finish: str | None = None
    retried: bool = False
    error: str | None = None


class LFMClient:
    def __init__(self, url: str, model: str, max_tokens: int, timeout: float):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.url = url.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _post(self, messages: list[dict]) -> LLMResult:
        body = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
            "enable_think": False,
            "temperature": 0,
            "stream": False,
        }
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        ms = (time.perf_counter() - t0) * 1000
        choice = data["choices"][0]
        text = _THINK.sub("", (choice.get("message") or {}).get("content") or "").strip()
        tokens = (data.get("usage") or {}).get("completion_tokens", 0)
        return LLMResult(text, bool(text), ms, tokens, choice.get("finish_reason"))

    def chat(self, messages: list[dict]) -> LLMResult:
        try:
            result = self._post(messages)
            if not result.ok:
                # Empty replies happen occasionally; one retry with a unique tag on the last message.
                tagged = [*messages[:-1], {**messages[-1], "content": messages[-1]["content"] + f"\n[request {uuid.uuid4().hex[:8]}]"}]
                first_ms = result.ms
                result = self._post(tagged)
                result.retried, result.ms = True, result.ms + first_ms
                if not result.ok:
                    result.error = "empty reply after retry"
            return result
        except urllib.error.HTTPError as e:
            return LLMResult("", False, 0, error=f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}")
        except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as e:
            return LLMResult("", False, 0, error=f"{type(e).__name__}: {e}"[:200])
