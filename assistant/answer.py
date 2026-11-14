"""Answer a question from the top manual pages with one capped LFM3 call, citing [manual, p. N]."""

import re
import sqlite3
import time
from dataclasses import dataclass, field

from .config import Config, load_config
from .llm import LFMClient, LLMResult
from .search import Hit, query_terms, search

NOT_FOUND = "Not found in the manuals."

SYSTEM_PROMPT = (
    "You are an assistant for maintenance technicians. Answer the question using ONLY the manual "
    "pages provided. Be brief: at most 3 short bullet points, no introduction. Cite the page you used "
    "after each fact, exactly as labelled, for example [grundfos_cr_cri_crn_pump, p. 35]. Never use "
    f"outside knowledge and never guess. If the pages do not contain the answer, say: {NOT_FOUND}"
)

# The model words refusals in several ways; only the first line is checked so an answer that
# merely mentions a missing detail later on still counts as an answer.
_REFUSAL = re.compile(r"not found in the|(do|does) not (contain|include|cover|mention|provide)|none of (the|these)", re.I)

# [manual, p. 12], (manual, p. 12), [manual, page 12]
_CITATION = re.compile(r"[\[(]([A-Za-z0-9_.\-]+),\s*p(?:age|\.)?\s*(\d+)[\])]")


def label(manual: str, page: int) -> str:
    return f"[{manual}, p. {page}]"


@dataclass
class Answer:
    question: str
    text: str
    hits: list[Hit]                 # pages given to the model (empty if none passed the threshold)
    citations: list[tuple[str, int]] = field(default_factory=list)  # valid citations in the text
    found: bool = True
    search_ms: float = 0.0
    llm: LLMResult | None = None    # None when the LLM wasn't called


def _line_scores(lines: list[str], question: str) -> list[int]:
    """How many question terms each line contains (5-letter prefixes stand in for stemming)."""
    words, phrases = set(), []
    for t in query_terms(question):
        if " " in t:
            phrases.append(f" {t} ")
        else:
            words.add(t[:5])
    scores = []
    for line in lines:
        tokens = re.findall(r"[a-z0-9]+", line.lower())
        joined = f" {' '.join(tokens)} "
        scores.append(len({w[:5] for w in tokens} & words) + sum(p in joined for p in phrases))
    return scores


def excerpt(text: str, question: str, max_chars: int) -> str:
    """The whole page if it fits, else the run of lines with the most question-term matches."""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    scores = _line_scores(lines, question)
    best, best_i, best_j = -1, 0, 0
    i = total = size = 0
    for j, line in enumerate(lines):
        size += len(line) + 1
        total += scores[j]
        while size > max_chars and i <= j:
            size -= len(lines[i]) + 1
            total -= scores[i]
            i += 1
        if total > best:
            best, best_i, best_j = total, i, j + 1
    out = "\n".join(lines[best_i:best_j])
    return ("… " if best_i > 0 else "") + out + (" …" if best_j < len(lines) else "")


def build_messages(question: str, hits: list[Hit], page_chars: int) -> list[dict]:
    blocks = []
    for h in hits:
        section = f"Section: {h.heading}\n" if h.heading else ""
        blocks.append(f"{label(h.manual, h.page)}\n{section}{excerpt(h.text, question, page_chars)}")
    user = "Manual pages:\n\n" + "\n\n---\n\n".join(blocks) + f"\n\n---\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def trim_truncated(text: str) -> str:
    """Drop the unfinished tail of a reply cut off by the token cap."""
    text = re.sub(r"[\[(][^\])]*$", "", text).rstrip()  # dangling citation
    if text.endswith((".", "]", ")", "!", "?")):
        return text
    cut = max(text.rfind("\n"), text.rfind(". "))
    return text[: cut + 1].rstrip() if cut > 0 else text


def check_citations(text: str, hits: list[Hit]) -> tuple[str, list[tuple[str, int]]]:
    """Keep citations that point at a page the model was given; drop invented ones."""
    allowed = {(h.manual, h.page) for h in hits}
    valid: list[tuple[str, int]] = []

    def keep(m: re.Match) -> str:
        ref = (m.group(1), int(m.group(2)))
        if ref in allowed:
            if ref not in valid:
                valid.append(ref)
            return label(*ref)
        return ""

    cleaned = re.sub(r"[ \t]+([.,;])", r"\1", _CITATION.sub(keep, text)).strip()
    return cleaned, valid


def mock_reply(question: str, hits: list[Hit]) -> LLMResult:
    """Offline stand-in for the LLM: the lines of the top page that share the most question terms."""
    t0 = time.perf_counter()
    top = hits[0]
    lines = top.text.splitlines()
    ranked = sorted(zip(_line_scores(lines, question), range(len(lines))), key=lambda s: (-s[0], s[1]))
    picked = sorted(i for score, i in ranked[:3] if score > 0) or [0]
    reply = f"(mock) {' '.join(lines[i] for i in picked)} {label(top.manual, top.page)}"
    return LLMResult(reply, True, (time.perf_counter() - t0) * 1000, tokens=len(reply.split()))


def answer(question: str, cfg: Config | None = None, *, conn: sqlite3.Connection | None = None) -> Answer:
    cfg = cfg or load_config()
    t0 = time.perf_counter()
    hits = [h for h in search(question, cfg.top_k, conn=conn) if h.score >= cfg.min_score]
    search_ms = (time.perf_counter() - t0) * 1000
    if not hits:
        return Answer(question, NOT_FOUND, [], found=False, search_ms=search_ms)

    if cfg.llm_mock:
        result = mock_reply(question, hits)
    else:
        client = LFMClient(cfg.llm_url, cfg.llm_model, cfg.llm_max_tokens, cfg.llm_timeout_s)
        result = client.chat(build_messages(question, hits, cfg.page_chars))
    if not result.ok:
        return Answer(question, f"LLM error: {result.error}", hits, found=False, search_ms=search_ms, llm=result)

    if _REFUSAL.search(result.text.strip().splitlines()[0]):
        return Answer(question, NOT_FOUND, hits, found=False, search_ms=search_ms, llm=result)
    raw = trim_truncated(result.text) if result.finish == "length" else result.text
    text, citations = check_citations(raw, hits)
    if not citations:
        # Every answer must cite a source: name the pages it was drawn from.
        text += "\n(From: " + "; ".join(label(h.manual, h.page) for h in hits) + ")"
    return Answer(question, text, hits, citations, True, search_ms, result)
