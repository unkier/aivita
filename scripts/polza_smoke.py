# /// script
# requires-python = ">=3.14"
# dependencies = ["openai-agents~=0.23.1"]
# ///
"""polza.ai + Jev smoke run (wayfinder ticket #7, handoff §17 step 2).

Real, billed calls. Stops starting new checks once the summed `cost_rub`
passes CAP_RUB. Reads POLZA_API_KEY from the nearest `.env` up the tree.

    uv run --script scripts/polza_smoke.py [out.json]
"""

import asyncio
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import httpx2
from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    RunConfig,
    RunHooks,
    Runner,
    function_tool,
    set_trace_processors,
    set_tracing_disabled,
)
from agents.run_config import ModelInputData
from openai import AsyncOpenAI, DefaultAsyncHttpx2Client
from openai.types.shared import Reasoning

CAP_RUB = 60.0
BASE = "https://polza.ai/api"

TALK = ["openai/gpt-5.6-luna", "google/gemini-3.8-flash", "anthropic/claude-sonnet-5"]
CHEAP = ["deepseek/deepseek-v4-flash", "openai/gpt-5-nano", "google/gemini-3.5-flash-lite"]
HAIKU = "anthropic/claude-haiku-4.5"  # default provider is drouter (max_tokens only)
ONLY_ANTHROPIC = {"only": ["anthropic"]}

RESULTS: list[dict] = []
SPENT = 0.0


def load_key() -> str:
    for d in [Path.cwd(), *Path.cwd().parents]:
        env = d / ".env"
        if env.is_file():
            for line in env.read_text().splitlines():
                if line.startswith("POLZA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    sys.exit("POLZA_API_KEY not found in any .env up the tree")


KEY = load_key()


class OverBudget(Exception):
    pass


def guard() -> None:
    if SPENT > CAP_RUB:
        raise OverBudget(f"spent {SPENT:.2f} > cap {CAP_RUB}")


def num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rec(check: str, **f) -> dict:
    global SPENT
    cost = num(f.get("cost_rub"))
    SPENT += cost or 0.0
    row = {"check": check, **f}
    RESULTS.append(row)
    keys = ("model", "variant", "ok", "status", "latency_s", "ttft_s", "cost_rub", "provider", "note")
    brief = " ".join(f"{k}={row[k]}" for k in keys if row.get(k) is not None)
    print(f"[{SPENT:7.3f} ₽] {check}: {brief}", flush=True)
    return row


def usage_fields(u: dict | None) -> dict:
    u = u or {}
    ptd = u.get("prompt_tokens_details") or {}
    ctd = u.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "reasoning_tokens": ctd.get("reasoning_tokens"),
        "cached_tokens": ptd.get("cached_tokens"),
        "cache_write_tokens": ptd.get("cache_write_tokens"),
        "cost_rub": u.get("cost_rub"),
        "cost_rub_type": type(u.get("cost_rub")).__name__,
    }


HTTP = httpx2.AsyncClient(
    base_url=BASE, headers={"Authorization": f"Bearer {KEY}"}, timeout=httpx2.Timeout(180.0)
)


async def chat(body: dict, *, stream: bool = False) -> dict:
    """POST /v1/chat/completions, raw. Returns a flat summary (never raises on HTTP errors)."""
    guard()
    body = {**body, "stream": stream}
    t0 = time.perf_counter()
    out: dict = {"stream": stream}
    if not stream:
        r = await HTTP.post("/v1/chat/completions", json=body)
        out["latency_s"] = round(time.perf_counter() - t0, 2)
        out["status"] = r.status_code
        try:
            j = r.json()
        except ValueError:
            out["error"] = r.text[:500]
            return out
        if r.status_code != 200 or "error" in j:
            out["error"] = j.get("error", j)
            return out
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        out |= {
            "provider": j.get("provider"),
            "model_echo": j.get("model"),
            "finish_reason": ch.get("finish_reason"),
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls"),
            "annotations": msg.get("annotations"),
            "has_reasoning_text": bool(msg.get("reasoning")),
            "usage": j.get("usage"),
            "top_level_keys": sorted(j.keys()),
            **usage_fields(j.get("usage")),
        }
        return out

    content, deltas_tc, first_tc_raw, chunks = [], {}, [], 0
    usage, finish, provider, err, usage_chunk_choices = None, None, None, None, None
    async with HTTP.stream("POST", "/v1/chat/completions", json=body) as r:
        out["status"] = r.status_code
        if r.status_code != 200:
            out["error"] = (await r.aread()).decode()[:500]
            out["latency_s"] = round(time.perf_counter() - t0, 2)
            return out
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            j = json.loads(data)
            chunks += 1
            provider = provider or j.get("provider")
            if j.get("error"):
                err = j["error"]
            if j.get("usage"):
                usage = j["usage"]
                usage_chunk_choices = len(j.get("choices") or [])
            for ch in j.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("content"):
                    if not content:
                        out["ttft_s"] = round(time.perf_counter() - t0, 2)
                    content.append(d["content"])
                for tc in d.get("tool_calls") or []:
                    if len(first_tc_raw) < 3:
                        first_tc_raw.append(tc)
                    if "ttft_s" not in out:
                        out["ttft_s"] = round(time.perf_counter() - t0, 2)
                    slot = deltas_tc.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                    fn = tc.get("function") or {}
                    slot["id"] = tc.get("id") or slot.get("id")
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    out |= {
        "latency_s": round(time.perf_counter() - t0, 2),
        "provider": provider,
        "chunks": chunks,
        "finish_reason": finish,
        "content": "".join(content),
        "tool_calls": list(deltas_tc.values()) or None,
        "first_tool_call_deltas": first_tc_raw or None,
        "usage_present": usage is not None,
        "usage_chunk_choices": usage_chunk_choices,
        "usage": usage,
        "error": err,
        **usage_fields(usage),
    }
    return out


def has_cyrillic(s: str | None) -> bool:
    return any("а" <= c.lower() <= "я" or c in "ёЁ" for c in (s or ""))


SYSTEM = "Ты Аивита, тёплая домашняя собеседница. Отвечай на языке собеседника, коротко, 1-2 предложения."
PROMPTS = {
    "ru": "Привет! Я Дмитрий, только что вернулся с прогулки. Как думаешь, чем заняться вечером?",
    "en": "Hi! I'm Dmitrii, just got back from a walk. What do you think I should do this evening?",
}


async def check_chat_languages() -> None:
    for model in TALK + CHEAP:
        for lang, prompt in PROMPTS.items():
            body = {
                "model": model,
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "reasoning": {"effort": "low"},
                "stream_options": {"include_usage": True},
            }
            r = await chat(body, stream=True)
            ok = r.get("status") == 200 and bool(r.get("content")) and not r.get("error")
            lang_ok = has_cyrillic(r.get("content")) == (lang == "ru")
            rec("chat_lang", model=model, variant=lang, ok=ok and lang_ok, lang_ok=lang_ok,
                tier="talk" if model in TALK else "cheap", **r)
    # Default flex provider vs non-flex, for latency (talk candidate).
    for prov in ({"only": ["openai"]},):
        body = {
            "model": "openai/gpt-5.6-luna",
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": PROMPTS["ru"]}],
            "max_tokens": 1024, "reasoning": {"effort": "low"},
            "stream_options": {"include_usage": True}, "provider": prov,
        }
        r = await chat(body, stream=True)
        rec("chat_lang", model="openai/gpt-5.6-luna", variant="ru provider=openai (non-flex)",
            ok=bool(r.get("content")), **r)


MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "mood": {"type": "string", "enum": ["happy", "neutral", "sad", "anxious", "angry"]},
        "summary": {"type": "string"},
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "relation": {"type": "string"}},
                "required": ["name", "relation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["mood", "summary", "people"],
    "additionalProperties": False,
}
EXTRACT_MSG = (
    "Извлеки факты из реплики. Реплика: «Сегодня ходил с сестрой Аней к маме в больницу, "
    "маме уже лучше, но я всё равно переживаю.»"
)


def validate_memory(content: str | None) -> tuple[bool, str]:
    if not content:
        return False, "empty"
    fenced = content.strip().startswith("```")
    try:
        j = json.loads(content)
    except ValueError:
        return False, "not json" + (" (fenced)" if fenced else "")
    if set(j) != {"mood", "summary", "people"}:
        return False, f"keys {sorted(j)}"
    if j["mood"] not in MEMORY_SCHEMA["properties"]["mood"]["enum"]:
        return False, f"mood {j['mood']!r}"
    if not all(set(p) == {"name", "relation"} for p in j["people"]):
        return False, "people shape"
    return True, "valid"


async def check_structured() -> None:
    rf = {"type": "json_schema", "json_schema": {"name": "memory", "strict": True, "schema": MEMORY_SCHEMA}}
    cases = [(m, None) for m in CHEAP] + [
        (HAIKU, ONLY_ANTHROPIC),
        ("anthropic/claude-sonnet-5", None),
    ]
    for model, prov in cases:
        body = {"model": model, "messages": [{"role": "user", "content": EXTRACT_MSG}],
                "response_format": rf, "max_tokens": 1500, "reasoning": {"effort": "low"}}
        if prov:
            body["provider"] = prov
        r = await chat(body)
        ok, why = validate_memory(r.get("content"))
        rec("json_schema_strict", model=model, variant=f"provider={prov}" if prov else "default",
            ok=ok, note=why, **r)


GET_WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                       "required": ["city"], "additionalProperties": False},
        "strict": True,
    },
}


async def check_drouter() -> None:
    """§14.3: default provider lacks tools/structured_outputs."""
    msgs = [{"role": "user", "content": "Какая погода в Казани? Используй инструмент."}]
    rf = {"type": "json_schema", "json_schema": {"name": "memory", "strict": True, "schema": MEMORY_SCHEMA}}
    variants = [
        ("tools, default provider", {"tools": [GET_WEATHER], "messages": msgs}),
        ("tools, require_parameters", {"tools": [GET_WEATHER], "messages": msgs,
                                       "provider": {"require_parameters": True}}),
        ("json_schema, default provider", {"response_format": rf,
                                           "messages": [{"role": "user", "content": EXTRACT_MSG}]}),
        ("json_schema, require_parameters", {"response_format": rf, "provider": {"require_parameters": True},
                                             "messages": [{"role": "user", "content": EXTRACT_MSG}]}),
    ]
    for name, extra in variants:
        r = await chat({"model": HAIKU, "max_tokens": 600, **extra})
        if "json_schema" in name:
            ok, why = validate_memory(r.get("content"))
        else:
            ok, why = bool(r.get("tool_calls")), "tool_call" if r.get("tool_calls") else "no tool_call"
        rec("drouter", model=HAIKU, variant=name, ok=ok, note=why, **r)
    # Non-streamed responses carry no `provider`; streamed chunks do. Which provider served?
    for name, extra in variants[:2]:
        r = await chat({"model": HAIKU, "max_tokens": 600, **extra}, stream=True)
        rec("drouter", model=HAIKU, variant=f"{name}, streamed", ok=bool(r.get("tool_calls")), **r)


async def check_tool_roundtrip_raw() -> None:
    """§14.1: tool round trip, streamed and non-streamed."""
    for model in ["openai/gpt-5.6-luna", "anthropic/claude-sonnet-5", "google/gemini-3.8-flash"]:
        for stream in (False, True):
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "Какая сейчас погода в Казани?"}]
            base = {"model": model, "tools": [GET_WEATHER], "max_tokens": 1024,
                    "reasoning": {"effort": "low"}, "stream_options": {"include_usage": True}}
            r1 = await chat({**base, "messages": msgs}, stream=stream)
            tcs = r1.get("tool_calls") or []
            row = {"step1_finish": r1.get("finish_reason"), "step1_tool_calls": tcs,
                   "first_tool_call_deltas": r1.get("first_tool_call_deltas"),
                   "step1_cost": r1.get("cost_rub"), "step1_error": r1.get("error")}
            if not tcs:
                rec("tool_roundtrip_raw", model=model, variant=f"stream={stream}", ok=False,
                    note="no tool call", cost_rub=r1.get("cost_rub"), **row)
                continue
            tc = tcs[0]
            call = {"id": tc.get("id"), "type": "function",
                    "function": {"name": tc.get("name") or tc["function"]["name"],
                                 "arguments": tc.get("arguments") or tc["function"]["arguments"]}}
            msgs2 = msgs + [{"role": "assistant", "content": None, "tool_calls": [call]},
                            {"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps({"temp_c": 7, "sky": "дождь"}, ensure_ascii=False)}]
            r2 = await chat({**base, "messages": msgs2}, stream=stream)
            ok = r1.get("finish_reason") == "tool_calls" and bool(r2.get("content"))
            rec("tool_roundtrip_raw", model=model, variant=f"stream={stream}", ok=ok,
                cost_rub=(num(r1.get("cost_rub")) or 0) + (num(r2.get("cost_rub")) or 0),
                latency_s=r1.get("latency_s"), final=r2.get("content"),
                step2_finish=r2.get("finish_reason"), provider=r1.get("provider"), **row)


async def check_stream_usage() -> None:
    """§14.4: cost_rub in the final chunk with and without include_usage."""
    for model in [CHEAP[0], TALK[0], "anthropic/claude-sonnet-5"]:
        for inc in (True, False):
            body = {"model": model, "messages": [{"role": "user", "content": "Скажи одно слово: привет."}],
                    "max_tokens": 300, "reasoning": {"effort": "low"}}
            if inc:
                body["stream_options"] = {"include_usage": True}
            r = await chat(body, stream=True)
            rec("stream_usage", model=model, variant=f"include_usage={inc}",
                ok=r.get("usage_present"), **r)


PUZZLE = ("Алиса старше Бориса, Борис старше Вики, Вика старше Глеба, а Глеб старше Даши. "
          "Кто третий по старшинству? Ответь одним именем.")


async def check_reasoning() -> None:
    """§14.5: reasoning.effort vs @reasoning_effort= vs top-level reasoning_effort."""
    for model in ["openai/gpt-5-nano", "deepseek/deepseek-v4-flash"]:
        variants = [
            ("no reasoning field", {}),
            ("top-level reasoning_effort=minimal", {"reasoning_effort": "minimal"}),
            ("reasoning.effort=minimal", {"reasoning": {"effort": "minimal"}}),
            ("suffix @reasoning_effort=minimal", {"model": f"{model}@reasoning_effort=minimal"}),
            ("top-level reasoning_effort=high", {"reasoning_effort": "high"}),
            ("reasoning.effort=high", {"reasoning": {"effort": "high"}}),
        ]
        for name, extra in variants:
            body = {"model": model, "messages": [{"role": "user", "content": PUZZLE}], "max_tokens": 4000,
                    **extra}
            r = await chat(body)
            rec("reasoning", model=model, variant=name, ok=r.get("status") == 200,
                note=f"reasoning_tokens={r.get('reasoning_tokens')}", **r)


def long_prefix(n_lines: int = 260) -> str:
    rooms = ["kitchen", "garden", "balcony", "study", "hallway", "bedroom", "attic", "garage"]
    things = ["a squeaky gate", "an old radio", "a jar of buttons", "a blue kettle", "a chess set",
              "a cracked mirror", "a stack of letters", "a wool blanket", "a brass lamp", "a fern"]
    lines = ["You are Aivita, a warm home companion. Stable background facts follow; never recite them."]
    for i in range(n_lines):
        lines.append(f"Fact {i:03d}: in the {rooms[i % 8]} there is {things[i % 10]}; "
                     f"it was moved there on day {(i * 7) % 365} and Dmitrii mentioned it {i % 5 + 1} times.")
    return "\n".join(lines)


PREFIX = long_prefix()


async def check_caching() -> None:
    """§14.6: automatic caching on a ≥1024-token prefix; Claude with/without cache_control."""
    cases = [
        ("openai/gpt-5-nano", None, "auto", False),
        ("deepseek/deepseek-v4-flash", None, "auto", False),
        ("google/gemini-3.5-flash-lite", None, "auto", False),
        (HAIKU, ONLY_ANTHROPIC, "no cache_control", False),
        (HAIKU, ONLY_ANTHROPIC, "cache_control 5m", True),
    ]
    for model, prov, name, mark in cases:
        sysmsg = ({"role": "system", "content": [{"type": "text", "text": PREFIX,
                                                    "cache_control": {"type": "ephemeral"}}]}
                  if mark else {"role": "system", "content": PREFIX})
        for i, q in enumerate(["Сколько будет 2+2? Одно число.", "Сколько будет 3+3? Одно число."]):
            body = {"model": model, "messages": [sysmsg, {"role": "user", "content": q}],
                    "max_tokens": 400, "reasoning": {"effort": "low"}}
            if prov:
                body["provider"] = prov
            r = await chat(body)
            rec("caching", model=model, variant=f"{name} call{i + 1}",
                ok=r.get("status") == 200,
                note=f"cached={r.get('cached_tokens')} write={r.get('cache_write_tokens')} "
                     f"prompt={r.get('prompt_tokens')}", **r)
            await asyncio.sleep(2)


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def embed(model: str, inputs: list[str], dims: int | None = None) -> dict:
    guard()
    body = {"model": model, "input": inputs}
    if dims:
        body["dimensions"] = dims
    t0 = time.perf_counter()
    r = await HTTP.post("/v1/embeddings", json=body)
    out = {"status": r.status_code, "latency_s": round(time.perf_counter() - t0, 2)}
    j = r.json()
    if r.status_code != 200 or "error" in j:
        out["error"] = j.get("error", j)
        return out
    out["vectors"] = [d["embedding"] for d in j["data"]]
    out["usage"] = j.get("usage")
    out["cost_rub"] = (j.get("usage") or {}).get("cost_rub")
    out["provider"] = j.get("provider")
    return out


async def check_embeddings() -> None:
    """§14.7: vector length, `dimensions` truncation, RU↔EN similarity."""
    texts = ["Я люблю гулять с собакой по утрам.", "I love walking my dog in the mornings.",
             "Квартальный налоговый отчёт сдаётся до пятнадцатого числа."]
    for model in ["qwen/qwen3-embedding-8b", "qwen/qwen3-embedding-4b", "baai/bge-m3"]:
        full = await embed(model, texts)
        if full.get("error"):
            rec("embeddings", model=model, variant="full", ok=False, **full)
            continue
        v = full["vectors"]
        rec("embeddings", model=model, variant="full", ok=True, dims=len(v[0]),
            cos_ru_en=round(cos(v[0], v[1]), 4), cos_ru_unrelated=round(cos(v[0], v[2]), 4),
            cos_en_unrelated=round(cos(v[1], v[2]), 4), latency_s=full["latency_s"],
            cost_rub=full["cost_rub"], provider=full.get("provider"), usage=full["usage"])
        if model.startswith("qwen"):
            tr = await embed(model, texts, dims=1024)
            if tr.get("error"):
                rec("embeddings", model=model, variant="dimensions=1024", ok=False, **tr)
                continue
            t = tr["vectors"]
            rec("embeddings", model=model, variant="dimensions=1024", ok=len(t[0]) == 1024,
                dims=len(t[0]), cos_vs_full_prefix=round(cos(t[0], v[0][: len(t[0])]), 4),
                norm=round(math.sqrt(sum(x * x for x in t[0])), 4),
                cos_ru_en=round(cos(t[0], t[1]), 4), cos_ru_unrelated=round(cos(t[0], t[2]), 4),
                cost_rub=tr["cost_rub"], provider=tr.get("provider"))


async def check_server_tools() -> None:
    """§14.8: polza:web_search and polza:web_fetch."""
    cases = [
        ("polza:web_search", {"type": "polza:web_search", "parameters": {"max_results": 3, "max_uses": 1}},
         "Найди в интернете: кто выиграл последний чемпионат мира по футболу? Ответь коротко со ссылкой."),
        ("polza:web_fetch", {"type": "polza:web_fetch", "parameters": {"max_characters": 4000}},
         "Прочитай https://polza.ai/docs/llms.txt и назови три первых раздела документации."),
        ("web_search + function tool", {"type": "polza:web_search", "parameters": {"max_results": 3,
                                                                                    "max_uses": 1}},
         "Найди в интернете курс доллара к рублю сегодня, а потом узнай погоду в Москве инструментом."),
    ]
    # The polza:* server tools are an org-level switch (400 "недоступны для организации" when off),
    # so also try the two other documented switches.
    search_q = "Найди в интернете: кто выиграл последний чемпионат мира по футболу? Ответь коротко со ссылкой."
    cases += [
        ("plugins: web", {"plugins": [{"id": "web", "max_results": 3}]}, search_q),
        ("web_search_options", {"web_search_options": {}}, search_q),
    ]
    for name, tool, prompt in cases:
        body = {"model": "openai/gpt-5-mini", "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000, "reasoning": {"effort": "low"}}
        if "type" in tool:
            body["tools"] = [tool] + ([GET_WEATHER] if "function" in name else [])
        else:
            body |= tool
        r = await chat(body)
        u = r.get("usage") or {}
        rec("server_tools", model="openai/gpt-5-mini", variant=name,
            ok=r.get("status") == 200 and not r.get("error"),
            annotations_n=len(r.get("annotations") or []),
            annotations_sample=(r.get("annotations") or [])[:2],
            cost_details=u.get("cost_details") or r.get("cost_details"),
            server_tool_use=u.get("server_tool_use"), **r)


async def check_images() -> None:
    """§14.9: client.images.generate with base /api/v1; sync vs pending."""
    guard()
    client = AsyncOpenAI(base_url=f"{BASE}/v1", api_key=KEY, timeout=180)
    model = "tongyi-mai/z-image"
    t0 = time.perf_counter()
    try:
        # z-image wants an aspect ratio in `size` ("1:1"); "1024x1024", a top-level `aspect_ratio`
        # or `input.aspect_ratio` all get 400 IMAGE_REQUEST_ERROR. The reply is 201 {"requestId"}
        # at once (async), not a sync result.
        resp = await client.images.generate(model=model, prompt="Уютная кухня вечером, акварель",
                                            size="1:1")  # type: ignore[arg-type]
        raw = resp.model_dump()
        lat = round(time.perf_counter() - t0, 2)
        extra = resp.model_extra or {}
        gen_id = extra.get("requestId") or raw.get("id") or extra.get("id")
        poll, t_done = None, None
        if not raw.get("data") and gen_id:
            for _ in range(60):
                await asyncio.sleep(3)
                p = (await HTTP.get(f"/v1/media/{gen_id}")).json()
                if p.get("status") not in ("pending", "processing", "queued"):
                    poll, t_done = p, round(time.perf_counter() - t0, 2)
                    break
        data = raw.get("data") or (poll or {}).get("data") or []
        cost = ((raw.get("usage") or {}).get("cost_rub") or ((poll or {}).get("usage") or {}).get("cost_rub"))
        rec("images", model=model, variant="images.generate size=1:1", ok=bool(data),
            latency_s=lat, done_after_s=t_done, gen_id=gen_id, cost_rub=cost,
            url=(data[0].get("url") if data else None), sdk_dump=raw, sdk_extra=extra, poll=poll)
    except Exception as e:
        rec("images", model=model, variant="images.generate sync", ok=False,
            error=repr(e)[:800], latency_s=round(time.perf_counter() - t0, 2))


JEV_STATE = {
    "recent_turns": [
        {"from": "Дмитрий", "text": "Сижу на созвоне с работой, потом напишу"},
        {"from": "Аивита", "text": "Хорошо! Удачи на созвоне."},
        {"from": "Дмитрий", "text": "ок"},
    ],
    "candidate_thought": "Спросить Дмитрия, поправилась ли его мама",
}
REACTION_OPTS = ["loved", "liked", "neutral", "ignored", "annoyed"]


async def jev(body: dict) -> dict:
    guard()
    t0 = time.perf_counter()
    r = await HTTP.post("/v1/systemone", json=body)
    out = {"status": r.status_code, "latency_s": round(time.perf_counter() - t0, 2)}
    try:
        j = r.json()
    except ValueError:
        out["error"] = r.text[:500]
        return out
    if r.status_code != 200 or "error" in j:
        out["error"] = j.get("error", j)
        out["detail"] = j.get("detail")
        return out
    u = j.get("usage") or {}
    out |= {"model_echo": j.get("model"), "answers": j.get("answers"), "usage": u,
            "cost_rub": u.get("cost_rub"), "cost_rub_type": type(u.get("cost_rub")).__name__,
            "top_level_keys": sorted(j.keys())}
    return out


async def check_jev() -> None:
    def reaction(opts: list[str], lang: str) -> dict:
        instr = {"ru": "Как Дмитрий отреагировал на последнее сообщение Аивиты в `recent_turns`?",
                 "en": "How did Dmitrii react to Aivita's last message in `recent_turns`?"}[lang]
        return {"type": "choice", "instructions": instr, "criteria": {o: None for o in opts}}

    questions = {
        "busy_ru": {"type": "noul", "instructions": "Занят ли сейчас Дмитрий чем-то другим, судя по `recent_turns`?"},
        "busy_en": {"type": "noul", "instructions": "Is Dmitrii busy with something else right now, judging by `recent_turns`?"},
        "natural_ru": {"type": "noul", "instructions": "Будет ли уместно прямо сейчас сказать Дмитрию `candidate_thought`, учитывая `recent_turns`?"},
        "natural_en": {"type": "noul", "instructions": "Would it feel natural to say `candidate_thought` to Dmitrii right now, given `recent_turns`?"},
        "absorbed_ru": {"type": "score", "instructions": "Насколько Дмитрий поглощён другим делом в `recent_turns`?",
                        "criteria": ["Свободен и болтает", "Чем-то занят, но может коротко ответить",
                                     "Занят созвоном, встречей или сосредоточенной работой"]},
        "absorbed_en": {"type": "score", "instructions": "How absorbed in something else is Dmitrii in `recent_turns`?",
                        "criteria": ["Free and chatting", "Doing something but can talk briefly",
                                     "Busy with a call, meeting or focused work"]},
        "reaction_fwd_ru": reaction(REACTION_OPTS, "ru"),
        "reaction_rev_ru": reaction(REACTION_OPTS[::-1], "ru"),
        "reaction_fwd_en": reaction(REACTION_OPTS, "en"),
    }
    r = await jev({"model": "typesafe/jev", "state": JEV_STATE, "questions": questions})
    rec("jev_batch", model="typesafe/jev", variant=f"{len(questions)} questions RU+EN",
        ok=r.get("status") == 200 and not r.get("error"), **r)
    # Same thing with the state as a plain string, and with the pinned version id.
    one = {"busy_ru": questions["busy_ru"]}
    r = await jev({"model": "jev-1.13.0", "state": json.dumps(JEV_STATE, ensure_ascii=False), "questions": one})
    rec("jev_pinned", model="jev-1.13.0", variant="string state, 1 question",
        ok=r.get("status") == 200 and not r.get("error"), **r)
    r = await jev({"model": "typesafe/jev", "state": JEV_STATE,
                   "questions": {"bad": {"type": "score", "instructions": "x", "criteria": ["only one"]}}})
    rec("jev_error_shape", model="typesafe/jev", variant="score with 1 level (invalid)",
        ok=r.get("status") != 200, **r)
    r = await jev({"model": "typesafe/jev", "state": JEV_STATE,
                   "questions": {"bad": {"type": "choice", "instructions": "x"}}})
    rec("jev_error_shape", model="typesafe/jev", variant="choice without criteria (invalid)",
        ok=r.get("status") != 200, **r)


# ---------------------------------------------------------------- Agents SDK

REQ_LOG: list[dict] = []
CUT = "\n\n<<volatile>>\n\n"


class CacheMarkTransport(httpx2.AsyncBaseTransport):
    """Splits the first system message at CUT and marks the prefix ephemeral; logs request bodies."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(await request.aread())
            msgs = body.get("messages") or []
            first = msgs[0] if msgs else None
            if first and first["role"] == "system" and isinstance(first["content"], str) and CUT in first["content"]:
                prefix, tail = first["content"].split(CUT, 1)
                first["content"] = [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                                    {"type": "text", "text": tail}]
            REQ_LOG.append({"model": body.get("model"), "roles": [m["role"] for m in msgs],
                            "keys": sorted(k for k in body if k != "messages"),
                            "reasoning": body.get("reasoning"), "reasoning_effort": body.get("reasoning_effort"),
                            "stream_options": body.get("stream_options")})
            headers = [(k, v) for k, v in request.headers.items() if k.lower() != "content-length"]
            request = httpx2.Request(request.method, request.url, headers=headers,
                                     content=json.dumps(body).encode())
        return await self._inner.handle_async_request(request)


SDK_CLIENT = AsyncOpenAI(
    base_url=f"{BASE}/v1", api_key=KEY, max_retries=0,
    http_client=DefaultAsyncHttpx2Client(transport=CacheMarkTransport(httpx2.AsyncHTTPTransport()),
                                         timeout=180),
)


class CostHooks(RunHooks):
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._t0 = 0.0

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self._t0 = time.perf_counter()

    async def on_llm_end(self, context, agent, response) -> None:
        u = response.usage
        self.calls.append({
            "latency_s": round(time.perf_counter() - self._t0, 2),
            "raw_usage": response.raw_usage,
            "cost_rub": (response.raw_usage or {}).get("cost_rub"),
            "sdk_usage": {"input": u.input_tokens, "output": u.output_tokens,
                          "cached": u.input_tokens_details.cached_tokens,
                          "reasoning": u.output_tokens_details.reasoning_tokens},
        })

    @property
    def cost(self) -> float:
        return sum(num(c["cost_rub"]) or 0.0 for c in self.calls)


def sdk_model(name: str) -> OpenAIChatCompletionsModel:
    return OpenAIChatCompletionsModel(model=name, openai_client=SDK_CLIENT)


def settings(effort: str | None = "low", provider: dict | None = None, **kw) -> ModelSettings:
    extra = {}
    if effort:
        extra["reasoning"] = {"effort": effort}
    if provider:
        extra["provider"] = provider
    return ModelSettings(include_usage=True, preserve_raw_usage=True, extra_body=extra or None, **kw)


@function_tool
def get_reminder(person: str) -> str:
    """Look up what Aivita promised to remind this person about."""
    return "Позвонить маме в 19:00 и спросить про анализы"


async def sdk_streamed(agent: Agent, inp, run_config: RunConfig | None = None) -> dict:
    guard()
    hooks = CostHooks()
    t0 = time.perf_counter()
    events, ttft, err = [], None, None
    result = Runner.run_streamed(agent, inp, hooks=hooks, run_config=run_config, max_turns=4)
    try:
        async for ev in result.stream_events():
            if ev.type == "raw_response_event" and getattr(ev.data, "type", "") == "response.output_text.delta":
                ttft = ttft or round(time.perf_counter() - t0, 2)
            elif ev.type == "run_item_stream_event":
                events.append(ev.name)
    except Exception as e:
        err = repr(e)[:600]
    return {"latency_s": round(time.perf_counter() - t0, 2), "ttft_s": ttft, "events": events,
            "final": result.final_output, "error": err, "llm_calls": hooks.calls, "cost_rub": hooks.cost,
            "costs_per_call": [c["cost_rub"] for c in hooks.calls]}


async def check_sdk_tool_roundtrip() -> None:
    """SDK tool round trip + streamed cost (include_usage + preserve_raw_usage)."""
    for model in TALK:
        agent = Agent(name="aivita", model=sdk_model(model), tools=[get_reminder],
                      instructions=SYSTEM + " Если спрашивают о напоминании, вызови get_reminder.",
                      model_settings=settings("low"))
        r = await sdk_streamed(agent, "Аивита, о чём ты обещала мне напомнить? Я Дмитрий.")
        ok = ("tool_called" in r["events"] and "tool_output" in r["events"] and bool(r["final"])
              and all(c is not None for c in r["costs_per_call"]))
        rec("sdk_tool_roundtrip", model=model, variant="run_streamed", ok=ok, **r)


async def check_sdk_cache() -> None:
    """Claude cache_control via the transport: cached_tokens on the second call."""
    for model, prov in [(HAIKU, ONLY_ANTHROPIC), ("anthropic/claude-sonnet-5", None)]:
        agent = Agent(name="aivita", model=sdk_model(model),
                      instructions=PREFIX + CUT + "Person: Dmitrii. Channel: text.",
                      model_settings=settings("low", prov, max_tokens=300))
        for i, q in enumerate(["Сколько будет 2+2? Одно число.", "Сколько будет 3+3? Одно число."]):
            r = await sdk_streamed(agent, q)
            raw = (r["llm_calls"] or [{}])[0].get("raw_usage") or {}
            ptd = raw.get("prompt_tokens_details") or {}
            rec("sdk_cache_control", model=model, variant=f"call{i + 1}", ok=r["error"] is None,
                cached_tokens=ptd.get("cached_tokens"), cache_write_tokens=ptd.get("cache_write_tokens"),
                note=f"cached={ptd.get('cached_tokens')} write={ptd.get('cache_write_tokens')}",
                **r)
            await asyncio.sleep(2)


async def check_sdk_reasoning() -> None:
    """extra_body reasoning changes reasoning_tokens; ModelSettings.reasoning (top-level) shouldn't."""
    model = "openai/gpt-5-nano"
    variants = [
        ("extra_body reasoning.effort=minimal", settings("minimal", max_tokens=4000)),
        # At max_tokens=4000 this run spent everything on reasoning and the SDK raised
        # ModelBehaviorError (finish_reason=length, no text) before on_llm_end: billed, cost lost.
        ("extra_body reasoning.effort=high", settings("high", max_tokens=16000)),
        ("ModelSettings.reasoning effort=minimal (top-level)",
         settings(None, max_tokens=4000, reasoning=Reasoning(effort="minimal"))),
    ]
    for name, ms in variants:
        agent = Agent(name="solver", model=sdk_model(model), instructions="Solve the puzzle.", model_settings=ms)
        before = len(REQ_LOG)
        r = await sdk_streamed(agent, PUZZLE)
        sent = REQ_LOG[before] if len(REQ_LOG) > before else {}
        reasoning_tokens = ((r["llm_calls"] or [{}])[0].get("sdk_usage") or {}).get("reasoning")
        rec("sdk_reasoning", model=model, variant=name, ok=r["error"] is None,
            note=f"reasoning_tokens={reasoning_tokens}", reasoning_tokens=reasoning_tokens,
            sent_reasoning=sent.get("reasoning"), sent_reasoning_effort=sent.get("reasoning_effort"), **r)


async def check_sdk_mid_system() -> None:
    """Layout B: a system message injected before the newest user message."""
    rule = "Особое правило на этот ответ: закончи ответ словом ПИНГВИН."

    def inject(data) -> ModelInputData:
        items = list(data.model_data.input)
        last_user = max(i for i, it in enumerate(items) if isinstance(it, dict) and it.get("role") == "user")
        items.insert(last_user, {"role": "system", "content": rule})
        return ModelInputData(input=items, instructions=data.model_data.instructions)

    history = [
        {"role": "user", "content": "Привет!"},
        {"role": "assistant", "content": "Привет, Дмитрий! Как прошёл день?"},
        {"role": "user", "content": "Нормально. Посоветуй, что почитать вечером?"},
    ]
    models = [(m, None) for m in TALK] + [(CHEAP[0], None), (HAIKU, ONLY_ANTHROPIC)]
    for model, prov in models:
        agent = Agent(name="aivita", model=sdk_model(model), instructions=SYSTEM,
                      model_settings=settings("low", prov, max_tokens=800))
        before = len(REQ_LOG)
        r = await sdk_streamed(agent, history, run_config=RunConfig(call_model_input_filter=inject))
        sent = REQ_LOG[before] if len(REQ_LOG) > before else {}
        obeyed = "ПИНГВИН" in (r["final"] or "").upper()
        rec("sdk_mid_system", model=model, variant="system before newest user msg",
            ok=r["error"] is None and obeyed, obeyed=obeyed, sent_roles=sent.get("roles"), **r)


async def money() -> dict:
    b = (await HTTP.get("/v2/balance")).json()
    k = (await HTTP.get("/v1/key")).json()
    k = k.get("data", k)
    return {"balance": b.get("amount"), "spent_total": b.get("spentAmount"),
            "key_usage": k.get("usage"), "key_usage_daily": k.get("usage_daily")}


CHECKS = [
    check_chat_languages,
    check_structured,
    check_drouter,
    check_tool_roundtrip_raw,
    check_stream_usage,
    check_reasoning,
    check_caching,
    check_embeddings,
    check_server_tools,
    check_images,
    check_jev,
    check_sdk_tool_roundtrip,
    check_sdk_cache,
    check_sdk_reasoning,
    check_sdk_mid_system,
]


async def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "polza-smoke.json")
    set_tracing_disabled(True)
    set_trace_processors([])
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    only = set(os.environ.get("ONLY", "").split(",")) - {""}
    before = await money()
    print("before:", before, flush=True)
    started = time.time()
    for check in CHECKS:
        if only and check.__name__ not in only:
            continue
        try:
            await check()
        except OverBudget as e:
            rec(check.__name__, ok=False, note=f"skipped: {e}")
        except Exception as e:
            rec(check.__name__, ok=False, error=repr(e)[:800], tb=traceback.format_exc()[-1500:])
    await asyncio.sleep(5)
    after = await money()
    print("after:", after, flush=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
               "duration_s": round(time.time() - started), "sum_cost_rub": round(SPENT, 4),
               "money_before": before, "money_after": after, "sdk_requests": REQ_LOG}
    out.write_text(json.dumps({"summary": summary, "results": RESULTS}, ensure_ascii=False, indent=1,
                              default=str))
    print(f"wrote {out}; summed cost_rub={SPENT:.3f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
