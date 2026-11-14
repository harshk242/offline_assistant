import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from assistant.answer import NOT_FOUND, answer, check_citations, excerpt
from assistant.config import Config
from assistant.search import Hit


class FakeGenieX:
    """OpenAI-compatible stub that records requests and replies with queued answers."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                content = outer.replies.pop(0)
                data = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                        "usage": {"completion_tokens": len(content.split())}}
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def fake():
    servers = []

    def make(*replies):
        s = FakeGenieX(replies)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.server.shutdown()


def cfg_for(server, **kw):
    return dataclasses.replace(Config(), **{"llm_url": server.url, "llm_mock": False, "min_score": 0.5, **kw})


def test_one_capped_call_without_thinking(conn, fake):
    srv = fake("Replace the fuses [pump, p. 35].")
    a = answer("The fuses are blown", cfg_for(srv), conn=conn)
    assert len(srv.requests) == 1
    path, body = srv.requests[0]
    assert path == "/v1/chat/completions"
    assert body["max_completion_tokens"] == Config().llm_max_tokens
    assert body["enable_think"] is False and body["stream"] is False
    assert body["model"] == "LiquidAI/LFM3-1.7B-GGUF:Q4_0"
    prompt = body["messages"][-1]["content"]
    assert "[pump, p. 35]" in prompt and "Question: The fuses are blown" in prompt
    assert a.found and a.citations == [("pump", 35)]
    assert a.text == "Replace the fuses [pump, p. 35]."


def test_leaked_reasoning_is_dropped(conn, fake):
    srv = fake("The user asks about fuses.</think>Replace the fuses [pump, p. 35].")
    a = answer("The fuses are blown", cfg_for(srv), conn=conn)
    assert a.text == "Replace the fuses [pump, p. 35]."


def test_reworded_refusal_counts_as_not_found(conn, fake):
    srv = fake("Not found in the provided manuals.")
    a = answer("The fuses are blown", cfg_for(srv), conn=conn)
    assert not a.found and a.text == NOT_FOUND


def test_not_found_skips_the_llm(conn, fake):
    srv = fake()
    a = answer("Carrier rooftop unit reset", cfg_for(srv), conn=conn)
    assert a.text == NOT_FOUND and not a.found and a.llm is None
    assert srv.requests == []


def test_score_threshold_skips_the_llm(conn, fake):
    srv = fake()
    a = answer("fuses", cfg_for(srv, min_score=1000), conn=conn)
    assert not a.found and srv.requests == []


def test_model_refusal_is_reported_as_not_found(conn, fake):
    srv = fake("Not found in the manuals.")
    a = answer("What is the torque for the pump motor bolts?", cfg_for(srv), conn=conn)
    assert not a.found and a.text == NOT_FOUND


def test_empty_reply_is_retried_once(conn, fake):
    srv = fake("", "Replace the fuses [pump, p. 35].")
    a = answer("blown fuses", cfg_for(srv), conn=conn)
    assert len(srv.requests) == 2 and a.llm.retried and a.found


def test_uncited_answer_gets_its_sources_appended(conn, fake):
    srv = fake("Replace the fuses.")
    a = answer("blown fuses", cfg_for(srv), conn=conn)
    assert a.found and "(From: [pump, p. 35]" in a.text


def test_server_down_is_an_error_not_a_crash(conn):
    cfg = dataclasses.replace(Config(), llm_url="http://127.0.0.1:9", llm_mock=False, min_score=0.5, llm_timeout_s=2)
    a = answer("blown fuses", cfg, conn=conn)
    assert not a.found and a.text.startswith("LLM error")


def test_mock_mode_needs_no_server(conn):
    a = answer("blown fuses", dataclasses.replace(Config(), llm_mock=True, min_score=0.5), conn=conn)
    assert a.found and a.citations == [("pump", 35)] and a.text.startswith("(mock)")


def test_invented_citations_are_dropped():
    hits = [Hit("pump", 35, "", "", 5.0)]
    text, cites = check_citations("Replace fuses [pump, p. 35]. Check seal [pump, p. 99].", hits)
    assert cites == [("pump", 35)] and "p. 99" not in text


def test_citation_variants_are_normalised():
    hits = [Hit("pump", 35, "", "", 5.0)]
    text, cites = check_citations("Replace fuses [pump, page 35].", hits)
    assert cites == [("pump", 35)] and text == "Replace fuses [pump, p. 35]."


def test_excerpt_centres_on_matching_lines():
    lines = [f"filler line {i} about nothing in particular" for i in range(200)]
    lines[150] = "f.HF | High DC bus voltage fault | Mains voltage too high"
    text = "\n".join(lines)
    out = excerpt(text, "What's an HF fault?", 500)
    assert "f.HF" in out and len(out) <= 510 and out.startswith("…")
    assert excerpt("short page", "anything", 500) == "short page"


def test_parenthesised_citations_are_normalised():
    hits = [Hit("pump", 35, "", "", 5.0)]
    assert check_citations("Replace fuses (pump, p. 35).", hits) == ("Replace fuses [pump, p. 35].", [("pump", 35)])


def test_truncated_reply_is_trimmed_to_last_complete_line():
    from assistant.answer import trim_truncated
    assert trim_truncated("- Replace fuses [pump, p. 35].\n- Check the breaker [pump, p.") == "- Replace fuses [pump, p. 35]."
    assert trim_truncated("- Replace fuses [pump, p. 35]") == "- Replace fuses [pump, p. 35]"
