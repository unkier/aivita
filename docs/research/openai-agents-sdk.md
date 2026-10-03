# OpenAI Agents SDK fit for the talk core

Ticket [#5](https://github.com/unkier/aivita/issues/5). Researched 2026-10-03.

**What was read:** `openai-agents` **0.23.1** (tag `v0.23.1`, the same `src/agents` as `main` at `81f0ccf`), its docs, `openai` 3.24.0, the polza.ai docs, and the tinyaisense SDK at `442045a`.

**How claims were checked:** source paths below are relative to `https://github.com/openai/openai-agents-python/blob/v0.23.1/` and are written `SDK:path:line`. The behaviour claims were also checked with an **offline probe**: the real SDK on Python 3.14, with an `httpx2.MockTransport` standing in for polza. It made no live LLM calls. Results marked *(probe)* come from that run.

Note on terms: in the SDK, a "turn" is one model call (`max_turns`, `current_turn`). An Aivita **Turn** is one message. The SDK's `Session` protocol is what Aivita calls a **History** (tinyaisense already imports it as `Session as History`).

## Verdict

**Fit: yes, for the talk tier.** Everything we need works through `OpenAIChatCompletionsModel` on a custom `AsyncOpenAI` client pointed at polza:
- tool-call round trips;
- streaming text deltas;
- strict `json_schema` output;
- `extra_body` passthrough;
- `cost_rub` for each call;
- a custom History over our own `turn` table;
- dynamic per-run instructions;
- concurrent runs for different people in one event loop.

The SDK is MIT-licensed. The tinyaisense `VoiceAgent` and `HubMcpServer` are built on it, so it stays in the dependency tree for M3 whatever we choose.

**Friction points.** Each one has a small fix, and the fixes are checked offline.

1. **`cache_control` is stripped.** `instructions` must be a single string, sent as one plain-string system message. The chat-completions converter drops any `cache_control` key on content parts. To mark the frozen prefix ephemeral for Claude models, we need a ~25-line `httpx2` transport that rewrites the request body *(probe: works)*. OpenAI, DeepSeek, Gemini and Grok models cache prefixes on polza automatically and don't need it.
2. **Reasoning effort goes in a field polza ignores.** `ModelSettings.reasoning.effort` is sent as a top-level `reasoning_effort`, and polza **silently ignores** that field. Send `extra_body={"reasoning": {"effort": ...}}` instead, or use the `model@reasoning_effort=` suffix, and leave `ModelSettings.reasoning` unset.
3. **Cost reporting needs two opt-ins.** The SDK only asks for streamed usage from `api.openai.com`, so set `include_usage=True`. Its normalised `Usage` has no cost field, so set `preserve_raw_usage=True` to keep polza's `cost_rub`. A stream cancelled before its last chunk reports no usage, so its cost is unknown.
4. **History is an item store, `turn` is text-only.** The SDK's History stores Responses-format items: messages, `function_call`, `function_call_output`, reasoning. A text-only `turn` table keeps the messages and drops the tool items, which is fine because tool calls go to `action_log`.
   - `pop_item` and `clear_session` clash with append-only.
   - The SDK only calls `pop_item` for server-managed conversations, which chat completions never uses, so both can raise.
5. **Nothing serializes one person's turns.** The SDK does not lock a History. Two concurrent runs on the same person interleave their items, so the talk core needs a per-person `asyncio.Lock`. `VoiceAgent` would bypass that lock.
6. **`VoiceAgent` passes only `agent`, `input` and `session=`.** It passes no `context=`, `run_config=` or `hooks=`. So for voice:
   - the person must be bound into the Agent itself;
   - cost hooks go on `Agent.hooks`;
   - tracing must be off globally;
   - its interrupted-turn convention needs mapping onto `turn.interrupted_heard`.
7. **Tracing is on by default and exports to `api.openai.com`.** `set_tracing_disabled(True)` is enough to stop export. There is also a key-leak trap: `set_default_openai_client(client)` defaults to `use_for_tracing=True`, which makes the polza key the trace-export key.
8. **Mid-stream errors are handled, but nothing is retried after output has started.** polza sends them with HTTP 200, as a chunk with an `error` field. The `openai` client raises `openai.APIError` from `stream_events()` *(probe)*. The text already streamed has reached the channel, the reply is not saved, and the SDK never retries a stream once output has started. A chunk with only `finish_reason: "error"` and no `error` field would end the run as a normal, truncated reply.
9. **Churn and weight.**
   - A minor version, which may contain breaking changes, ships about every 2-3 weeks: 17 minors in 2026 so far.
   - The 0.23.1 install is 38 packages and 49 MB, and the core package is ~67k lines without its optional sandbox, realtime and voice parts.
   - This weighs against handoff §3 principle 10 ("no heavy frameworks in core"). Pin it, and keep it behind `talk/`.

**Cost of a hand-rolled loop instead:**
- About 300-400 lines plus tests (~1-2 days) on the plain `openai` SDK, which already accumulates streamed tool-call deltas (`chat.completions.stream`) and parses strict pydantic output (`chat.completions.parse`).
- We would control message layout, `cache_control`, reasoning and cost directly, with no Responses-to-chat translation layer.
- We would lose:
  - `@function_tool` schema generation;
  - the MCP client that `HubMcpServer` needs;
  - `VoiceAgent` reuse;
  - `ScriptedModel` test fakes;
  - human-in-the-loop approvals.
- The History, prompt builder, cost logging and per-person lock are needed either way.

**Recommendation:**
- Use the SDK for the **talk** tier only, pinned `openai-agents~=0.23.1`, behind Aivita's own `talk/` interface: a `TurnHistory` adapter, the prompt builder, a cost hook and the cache-marking transport. That way a hand-rolled loop can replace it without touching channels.
- Keep the **cheap** and **deep** tiers and `LLMDecider` on the plain `openai` client (`chat.completions.parse`). They are one-shot calls and gain nothing from a Runner.

## 1. `OpenAIChatCompletionsModel` on polza

Wiring, as the SDK docs show for non-OpenAI providers (`docs/models/index.md`, "Non-OpenAI models"):

```python
client = AsyncOpenAI(base_url="https://polza.ai/api/v1", api_key=os.environ["POLZA_API_KEY"])
model = OpenAIChatCompletionsModel(model=cfg.talk_model, openai_client=client)
agent = Agent[TalkCtx](name="aivita", instructions=build_instructions, model=model, tools=[...],
                       model_settings=ModelSettings(include_usage=True, preserve_raw_usage=True,
                                                    extra_body={"reasoning": {"effort": "low"}}))
```

Always pass a model object. An Agent with no model falls back to the SDK default OpenAI model, which is `gpt-5.6-luna` since 0.20 (`docs/release.md`, 0.20.0).

**Request shape.** `_fetch_response` builds the request in `SDK:src/agents/models/openai_chatcompletions.py:605-742`:
- It converts the History plus new input to chat messages.
- It inserts `instructions` as `{"role": "system", "content": <str>}` at index 0 (`:629-636`).
- It calls `client.chat.completions.create(**kwargs)` (`:742`).
- Fields that are `None` are omitted, and `store` and `stream_options` are only defaulted for `api.openai.com` (`SDK:src/agents/models/chatcmpl_helpers.py:47-67`).

*(probe)* A tool-using request sent only `model`, `messages`, `tools` and the `extra_body` keys.

**Tool calls.** Function tools become `{"type": "function", "function": {name, description, parameters, strict}}` (`SDK:src/agents/models/chatcmpl_converter.py:1018-1032`). Hosted tools raise `UserError` on this path (`:1034-1037`). MCP tools are converted to `FunctionTool` first (`SDK:src/agents/mcp/util.py:518-526`), so `HubMcpServer` tools work.

*(probe)* For a `function_call` → tool → final text exchange, the second request carried `system, user, assistant(tool_calls), tool` and the run ended with the model's text. polza's documented tool-call shape is the standard OpenAI one ([polza chat reference](https://polza.ai/docs/api-reference/chat/completions.md), "Tool Calling").

Two options for flaky providers:
- `OpenAIChatCompletionsModel(..., buffer_streamed_tool_calls=True)` waits for the whole stream before emitting tool calls (`SDK:...openai_chatcompletions.py:66,480-483`; `docs/models/index.md` "Chat Completions compatibility options").
- `strict_feature_validation=True` raises an error instead of silently dropping Responses-only features.

**Streaming.** `ChatCmplStreamHandler` turns chunks into Responses-API events: `ResponseCreatedEvent`, `ResponseTextDeltaEvent`, `ResponseCompletedEvent` and so on (`SDK:src/agents/models/chatcmpl_stream_handler.py:649,921,1361`).

*(probe)* `Runner.run_streamed` gave `RawResponsesStreamEvent`s with `ResponseTextDeltaEvent` deltas `["При", "вет"]` and a final `ResponseCompletedEvent`. These are exactly the events `VoiceAgent` consumes.

Cancelling a streamed run: `RunResultStreaming.cancel("immediate" | "after_turn")` (`SDK:src/agents/result.py:878-890`).

**Mid-stream errors.** polza sends an error that happens after the reply has started with HTTP **200**, as `data: {"id":"error_...","error":{"code":"TOO_MANY_REQUESTS","message":"..."},"choices":[{"delta":{"content":""},"finish_reason":"error"}]}` and then `[DONE]`. A 402 for a short reserve arrives the same way. Failed requests, mid-stream ones included, are not billed and are safe to retry ([polza API intro](https://polza.ai/docs/api-reference/introduction.md), "Ошибки в стриме", "Повторы запросов").

Who catches it:
- **The `openai` client, before the Agents SDK sees the chunk.** `AsyncStream.__stream__` raises `openai.APIError(message, body=data["error"])` for any SSE `data` with a truthy `error` key, and sets `.code` from `body["code"]` (`openai/_streaming.py:209-221`, `openai/_exceptions.py:65-74`).
- **The exception leaves `RunResultStreaming.stream_events()`.**

*(probe, documented chunk after two deltas)*:
- The deltas `['Hello, ', 'I was']` were delivered first.
- Then `openai.APIError: provider limit` was raised, with `code='TOO_MANY_REQUESTS'`.
- `final_output` was `None`.
- The History kept only the user message, because the stream input was saved before the call and the partial reply was not.

What the talk core must therefore do:
- **Catch `openai.APIError` around `stream_events()`.** `VoiceAgent` already catches every exception there and speaks what was streamed.
- **Decide what to tell the channel.** The person has already seen or heard the partial text.
- **Retry deliberately, if at all.** The SDK will not retry: runner-managed retries are opt-in through `ModelSettings(retry=...)`, and even then "streamed runs after output has already started" are never replayed (`docs/models/index.md`, "Safety boundaries"). A retry is a new run with the same input. That run saves the user message again, so `TurnHistory.add_items` should skip a `person` turn whose correlation id is already stored.
- **HTTP-status errors before streaming starts** raise `openai.APIStatusError` subclasses (`RateLimitError` etc.). The `openai` client retries 408/409/429/5xx itself (`max_retries`, default 2).
- **A non-streaming 200 with no `choices`** raises `agents.ModelBehaviorError("ChatCompletion response has no choices (possible provider error payload): ...")` (`SDK:...openai_chatcompletions.py:262-268`).

Residual risk *(probe)*: in two shapes, the SDK does not treat the stream as failed. It completes the run with the truncated text as `final_output` and saves it to the History:
- a chunk with `finish_reason: "error"` and **no** `error` field;
- a stream that ends with no `finish_reason` at all.

The handler checks for a finish reason only for `api.openai.com` (`require_finish_reason=ChatCmplHelpers.is_openai(client)`, `SDK:...openai_chatcompletions.py:497`), and it does not special-case `finish_reason == "error"` (`SDK:...chatcmpl_stream_handler.py:688-692`). polza documents the `error` field, so this only matters if polza deviates from its docs. If it does, the same `httpx2` transport hook can inspect SSE lines and raise.

**Structured output.** `output_type=PydanticModel` becomes `response_format={"type": "json_schema", "json_schema": {"name": "final_output", "strict": true, "schema": ...}}` (`SDK:...chatcmpl_converter.py:107-120`). The schema is made strict, with `additionalProperties: false` and every field required (`SDK:src/agents/agent_output.py:85-125`).

*(probe)* `Label(label='warm', score=0.8)` was parsed from the JSON reply. polza supports `json_schema` (chat reference, "Response Format"), but which models honour it is ticket #2's question.

For one-shot structured calls (cheap tier, `LLMDecider`), `openai`'s own `client.chat.completions.parse(response_format=Model)` does the same without a Runner (`openai/resources/chat/completions/completions.py`, `parse`).

**Provider-specific fields.** `ModelSettings` has `extra_body`, `extra_headers`, `extra_query` and `extra_args` (`SDK:src/agents/model_settings.py:171-183`). They are passed to `create()` as `extra_body=` etc., and `extra_args` is merged as keyword arguments (`SDK:...openai_chatcompletions.py:711-740`). The `openai` client merges `extra_body` into the top-level JSON body shallowly, and `extra_body` wins on duplicate keys (`openai/_base_client.py:591-595, 2336-2345`). This works for top-level fields:
- `reasoning`;
- `provider`;
- `web_search_options`;
- `stream_options.include_server_tool_events`.

It cannot reach inside `messages` or extend `tools`:
- An `extra_body["tools"]` would *replace* the SDK's function tools. So polza server tools (`polza:web_search`) can't be combined with SDK function tools that way, but `web_search_options` can.
- Reasoning: the SDK sends `ModelSettings.reasoning.effort` as top-level `reasoning_effort` (`SDK:...openai_chatcompletions.py:680-706`). polza **reads no top-level `reasoning_effort`**: the request succeeds and the field is ignored without an error. polza wants `reasoning.effort` or the `model@reasoning_effort=` suffix ([polza reasoning](https://polza.ai/docs/osobennosti/reasoning-tokens.md); chat reference, `ReasoningDto`).
  - **Fix:** leave `ModelSettings.reasoning` unset, so the SDK sends nothing, and pass `extra_body={"reasoning": {"effort": "low"}}`. *(probe: sent verbatim as top-level `reasoning`.)*
  - Or put `@reasoning_effort=low` in the model id kept in config.
  - The SDK warns about, and drops, only `reasoning.mode` / `reasoning.context` on this path (`openai_chatcompletions.py:102-128`), so the ignored `reasoning_effort` gets no warning from either side.
- Reasoning replies: polza's `message.reasoning` field is read into a reasoning item (`SDK:...chatcmpl_converter.py:141-160`).

**`cache_control`.** polza asks for `cache_control: {type: "ephemeral"}` on a **content part** of the system message, and only for Anthropic Claude. OpenAI, DeepSeek, Gemini and Grok cache automatically, OpenAI and Gemini from 1024 tokens ([polza caching](https://polza.ai/docs/osobennosti/caching.md)).

Can the SDK express a cacheable prefix?
- **Automatic-caching models:** yes, implicitly. Keep the frozen prefix at the start of `instructions`.
- **Claude:** no, not through any SDK API. Yes with the HTTP-layer rewrite below.

The reason, via the SDK:
- `instructions` is a plain string (`SDK:src/agents/agent.py:332-345`), sent as string content.
- If the system prompt goes in as input items with content parts instead, the converter rebuilds each text part as `{"type": "text", "text": ...}`. It copies only OpenAI's `prompt_cache_breakpoint` (`SDK:...chatcmpl_converter.py:424-446`), so `cache_control` is dropped *(probe: sent as `[{"type":"text","text":"LONG PREFIX"},{"type":"text","text":"tail"}]`)*.

Fix *(probe: works)*: a transport that splits the first system message at a marker and marks the prefix ephemeral:

```python
CUT = "\n\n<<volatile>>\n\n"

class CacheMarkTransport(httpx2.AsyncBaseTransport):
    def __init__(self, inner): self._inner = inner
    async def handle_async_request(self, request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(await request.aread())
            msg = (body.get("messages") or [None])[0]
            if msg and msg["role"] == "system" and isinstance(msg["content"], str) and CUT in msg["content"]:
                prefix, tail = msg["content"].split(CUT, 1)
                msg["content"] = [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                                  {"type": "text", "text": tail}]
                headers = [(k, v) for k, v in request.headers.items() if k.lower() != "content-length"]
                request = httpx2.Request(request.method, request.url, headers=headers,
                                         content=json.dumps(body).encode())
        return await self._inner.handle_async_request(request)

client = AsyncOpenAI(..., http_client=DefaultAsyncHttpx2Client(transport=CacheMarkTransport(httpx2.AsyncHTTPTransport())))
```

(`openai` 3.x uses `httpx2`. A custom `http_client` must be an `httpx2` client: `docs/release.md` 0.21.0.) Only strip the marker for models that don't need `cache_control`; it costs nothing.

## 2. Tracing and other telemetry

What is on by default:
- Tracing is on by default. The default processor batches spans to `https://api.openai.com/v1/traces/ingest` (`SDK:src/agents/tracing/processors.py:46`). Spans include LLM inputs and outputs unless `trace_include_sensitive_data=False` (`docs/tracing.md`, "Sensitive data").
- The exporter uses `OPENAI_API_KEY` from the environment, and skips with a warning if it is unset (`processors.py:107-116,143-146`).
- `set_default_openai_client(client)` defaults to `use_for_tracing=True`, which calls `set_tracing_export_api_key(client.api_key)` (`SDK:src/agents/__init__.py:295`, `SDK:src/agents/_config.py:20-24`). That would export traces to OpenAI with the polza key. **Don't call it, or pass `use_for_tracing=False`.**

How to turn it off:
- `set_tracing_disabled(True)` sets a manual flag that overrides the env (`SDK:src/agents/tracing/__init__.py:108-112`, `SDK:src/agents/tracing/provider.py:332-357`). Every `create_trace` / `create_span` then returns a no-op (`provider.py:380-386, 420-426`), so nothing reaches a processor.
- It does build the default provider, processor and exporter object (an `httpx2.Client`), because it calls `get_trace_provider()` (`SDK:src/agents/tracing/setup.py:39-66`). But the export thread only starts when a span is queued (`processors.py:735-755`).
- *(probe)* After tracing was disabled and six runs completed, the only threads were `MainThread` and the asyncio executor, and `_worker_thread` was `None`.
- Other switches: env `OPENAI_AGENTS_DISABLE_TRACING=1`, and `RunConfig(tracing_disabled=True)` for one run (`docs/tracing.md`).

To make it airtight (handoff §14, "No telemetry"):
- `set_tracing_disabled(True)` at startup.
- `set_trace_processors([])`, which removes the OpenAI exporter (`docs/tracing.md`, "Custom tracing processors").
- `OPENAI_AGENTS_DISABLE_TRACING=1` in the service environment.
- A test that asserts no processor receives a span.
- Optionally, a local processor that writes spans to our JSON-lines log.

Other outbound traffic, from a grep of non-sandbox `src/agents` for URLs:
- The tracing endpoint is the only network destination in the core.
- Requests carry `User-Agent: Agents/Python 0.23.1` (`SDK:src/agents/models/chatcmpl_helpers.py:34-35`), plus `openai`'s usual `X-Stainless-*` platform headers, to polza only.
- LLM inputs and outputs aren't logged unless `OPENAI_AGENTS_DONT_LOG_MODEL_DATA=0` (`SDK:src/agents/_debug.py`).

## 3. History over the `turn` table (the `Session` protocol)

**The protocol.** It needs `session_id`, `session_settings` and four async methods: `get_items(limit)`, `add_items(items)`, `pop_item()` and `clear_session()` (`SDK:src/agents/memory/session.py:52-93`). Any structural implementation works. If all four methods declare a keyword `wrapper`, the SDK passes the run's `RunContextWrapper` (`session.py:192-233`; `docs/sessions/index.md`, "Accessing run context from a custom session").

**What the Runner does with it:**
- **Before a run**, it calls `get_items` once and prepends the result to the new input (`SDK:src/agents/run_internal/session_persistence.py:395-470`). The optional `RunConfig.session_input_callback` reshapes that merge (`SDK:src/agents/run_config.py:441`).
- **During a streamed run**, the user input is saved right before the first model call (`SDK:src/agents/run_internal/run_loop.py:2243`), then each step's items are added as the step finishes (`run_loop.py:415-440`).
- **Within a run**, tool items travel in memory, not through the History.
- **`pop_item` is only used** to roll back server-managed conversations (`run_loop.py:2667-2676` calls `rewind_session_items` only when `server_conversation_tracker` is set; `session_persistence.py:997-1010`). Chat completions has no server-managed state (`SDK:...openai_chatcompletions.py:543-573`), so an append-only History can raise in `pop_item` and `clear_session`.

**What `add_items` receives** *(probe, one tool-using turn)*: `message:user`, `function_call`, `function_call_output`, `message:assistant`.

Mapping onto `turn` (append-only: `person_id, channel, mode, role, text, lang, ts, interrupted_heard`):

```python
class TurnHistory:                      # one per run: cheap; holds person/channel/mode
    session_settings = None
    def __init__(self, db, person_id, channel, mode, correlation_id): ...
    session_id = property(lambda self: f"person:{self.person_id}")   # one History per person, all channels

    async def get_items(self, limit=None):           # last N turns, any channel, oldest first
        rows = self.db.last_turns(self.person_id, limit)
        return [{"role": "user" if r.role == "person" else "assistant", "content": r.text} for r in rows]

    async def add_items(self, items):
        for it in items:
            if it.get("type", "message") == "message" and it.get("role") in ("user", "assistant"):
                self.db.append_turn(self.person_id, self.channel, self.mode,
                                    "person" if it["role"] == "user" else "aivita", _text(it["content"]),
                                    correlation_id=self.correlation_id)
            # function_call / function_call_output / reasoning: not History; tools write action_log

    async def pop_item(self): raise NotImplementedError("History is append-only")
    async def clear_session(self): raise NotImplementedError("History is append-only")
```

*(probe)* The probe ran this shape for a tool turn and a streamed turn. The table got exactly `person`/`aivita` text rows, and the next run's request replayed them as `system, user, assistant, user`.

Consequences:
- **Later turns see what was said, not tool results.** That fits snippet-then-read (handoff §7): an opened memory isn't replayed forever.
- **Attachments need their own column.** User content can be a list of parts (images); `_text` keeps the text and the rest needs somewhere to go.
- **`limit` caps the history.** It comes from `RunConfig(session_settings=SessionSettings(limit=N))` (`docs/sessions/index.md`, "Limiting retrieved history"). Summaries of older turns are a prompt-builder concern.
- **The built-in `SQLiteSession` stores its own JSON blobs and uses `asyncio.to_thread`** (`SDK:src/agents/memory/sqlite_session.py:358,464`). Don't use it. It is what `VoiceAgent` falls back to, in memory, keyed by the Hub Session id.

## 4. Dynamic instructions: frozen prefix + volatile tail

`Agent.instructions` may be `Callable[[RunContextWrapper[TContext], Agent], str | Awaitable[str]]`, called on every model call (`SDK:src/agents/agent.py:332-345,1129-1150`).

*(probe)* One shared Agent rendered `PREFIX\n---\nPERSON: p1; MODE: text` and `...p2; MODE: voice` for two concurrent runs.

**Layout A (simplest): one system message, prefix then tail.**
- Automatic prefix caching covers the frozen prefix. With the `CacheMarkTransport` above, Claude's `cache_control` covers it too.
- The History after the tail is never cached.

**Layout B: frozen `instructions`, tail injected late with `RunConfig.call_model_input_filter`.**
- The filter receives `ModelInputData(input, instructions)` right before each model call and returns a replacement (`SDK:src/agents/run_config.py:60-76,448`).
- *(probe)* A filter that inserted `{"role": "system", "content": "VOLATILE TAIL"}` before the newest user message produced `system(prefix), user, assistant, system(tail), user`. The tail was **not** persisted.
- The cacheable prefix then includes the whole History.
- Cost: in multi-step tool runs, the filter must insert before *this run's* user message, not the last item.
- How polza or each upstream treats a mid-conversation system message, especially Anthropic, is unverified. It might hoist or reject it. The alternative is a tail text part prepended to the user message inside the filter.

Start with A. Measure `cached_tokens` (§6) before trying B.

## 5. Concurrency: two people at once

**Runs are independent.** `Runner.run` / `run_streamed` keep per-run state in the `RunContextWrapper` / `RunState`. A single `Agent`, model object and `AsyncOpenAI` client can be shared. The SDK's only stated caveat is to keep `agent.tools` unchanged while it is shared across concurrent runs (`SDK:src/agents/lifecycle.py:37-40`). Tool availability per run can be gated with `is_enabled=callable(ctx, agent)` (`SDK:src/agents/tool.py:485`), for example image tools only in text mode.

*(probe)* `asyncio.gather` of a slow run for p1 and a fast one for p2 returned the right replies, each request carrying its own person and mode tail.

**Not handled for us:**
- **Same person on two Channels at once** (voice and chat). Each run reads the History at its start and appends as it goes, so the items interleave. Serialize with a per-person `asyncio.Lock` held across `Runner.run`. Background mind work yields to it (handoff §6.1).
- **Concurrent tool calls inside one run.** These run in parallel by default; `RunConfig(tool_execution=...max_function_tool_concurrency=N)` caps them (`docs/running_agents.md`).
- **Max turns.** `max_turns` defaults to 10 (`SDK:src/agents/run_config.py:45`).

## 6. Usage and cost per call

**Normalised usage.** `Usage` has requests, tokens, `cached_tokens`, `cache_write_tokens`, reasoning tokens and per-request entries. It has **no cost field**, so `cost_rub` is **dropped** from `result.context_wrapper.usage` and from `request_usage_entries` (`SDK:src/agents/usage.py:196-230`; `docs/usage.md`). The token counts and `cached_tokens` survive normalisation *(probe: `cached 14` summed over two calls)*.

**polza's usage object.** It carries `cost_rub` (and `cost`, an alias for it) plus `prompt_tokens_details.cached_tokens` / `cache_write_tokens`. When streaming, it arrives in the last chunk before `[DONE]` ([polza usage](https://polza.ai/docs/osobennosti/usage.md); the chat reference documents `stream_options.include_usage`).

Getting `cost_rub` through the SDK:
- `ModelSettings(preserve_raw_usage=True)` keeps the provider's usage dict on each `ModelResponse.raw_usage` (`SDK:src/agents/items.py:723`; `SDK:...openai_chatcompletions.py:385-389`; `SDK:...chatcmpl_stream_handler.py:656-660,1352-1354`). `openai` models keep unknown fields (`extra="allow"`, `openai/_models.py:121-129`).
- *(probe)* `raw_usage` was `{'prompt_tokens': 30, ..., 'cost_rub': 0.03, 'cost': 0.03}` for each call of a two-call tool turn, and for the streamed call.
- **Streaming needs `ModelSettings(include_usage=True)`.** For non-OpenAI base URLs the SDK doesn't send `stream_options` (`chatcmpl_helpers.py:53-67`). *(probe: `{'include_usage': True}` was sent.)*
- **Read it per call** in `RunHooks.on_llm_end(context, agent, response: ModelResponse)`. Time latency from `on_llm_start` (`SDK:src/agents/lifecycle.py:18-35`). `Agent.hooks` (`AgentHooks`) get the same callbacks (`lifecycle.py:209-225`), which is the only way under `VoiceAgent`. `response.request_id` is also there.
- After a run, `result.raw_responses[i].raw_usage` has the same data.
- **Gap:** a stream cancelled with `cancel("immediate")` (a barge-in) before its usage chunk produces no usage. polza bills the part already generated when the client disconnects ([polza API intro](https://polza.ai/docs/api-reference/introduction.md), "Повторы запросов"). So `llm_call.cost_rub` must be nullable, and the daily budget can reconcile against `GET /api/v2/balance` (polza usage doc). A mid-stream polza error is not billed.

## 7. Version, cadence, dependencies, licence

- **Current version:** 0.23.1, released 2026-10-02 on PyPI and GitHub. `requires-python >=3.10`, classifiers up to 3.14. Installed and ran on 3.14 *(probe)*. tinyaisense locks 0.22.3 (`tinyaisense/uv.lock`) and its `[agents]` extra asks for `openai-agents>=0.22`.
- **Versioning:** `0.Y.Z`, where **Y bumps may break public non-beta interfaces** and Z is for fixes and features (`docs/release.md`). 123 releases since 0.1.0 (2025-06-27). In 2026, minors went 0.7.0 (Jan 23) → 0.23.0 (Oct 2): about one every 2-3 weeks, often several patch releases a week.
- **Recent breaking changes that matter here:**
  - 0.21 moved to `openai>=3` and `httpx2`, which matters for custom `http_client`s.
  - 0.20 changed the default model.
  - Pin `~=0.23.1` and upgrade deliberately, together with tinyaisense.
- **Dependencies of a clean 0.23.1 install:** 38 packages, 49 MB. Required deps include `openai` 3.x, `pydantic`, `mcp` (pulls `starlette`, `uvicorn`, `sse-starlette`, `jsonschema`, `pyjwt`, `cryptography`), `requests`, `websockets`, `griffelib` and `httpx2` (`pyproject.toml` `dependencies`).
- **Licences:** `openai-agents` is **MIT** (`LICENSE`; PyPI `license_expression`). Every dependency is MIT, BSD, Apache-2.0, ISC or PSF, except **`certifi` (MPL-2.0)**. It comes in via `requests`, and `trafilatura` (already in handoff §11) requires it too. We use it unmodified, so it puts no obligations on Aivita's code. *(Checked from installed metadata.)*
- **Test fakes:** `agents.testing.ScriptedModel` with `assistant_message()` / `function_call()` scripts runs and streams with no provider (`docs/testing.md`). That covers the "deterministic fake LLM" of handoff §13 for the talk tier.

## 8. How tinyaisense's `VoiceAgent` uses the SDK

From `tinyaisense/packages/sdk/src/tinyaisense/openai_agents.py` at `442045a`:

**How a turn runs:**
- **One turn at a time.** Each push-to-talk Utterance is a turn: `Runner.run_streamed(self._instructed(), text, session=self._history)`. **No `context`, `run_config` or `hooks`** are passed.
- **Speech.** It speaks `ResponseTextDeltaEvent` deltas with `say.open/append`, and closes the `say` on `ResponseCompletedEvent`. Both events are emitted on the chat-completions path (§1).
- **Interrupt.** A button press calls `result.cancel("immediate")`. What the human heard is then written back with `session.add_items([{"role": "assistant", "content": heard}])`, and the next user input is prefixed with `CUT_OFF = "you were cut off; the human heard: '{heard}'"`.
- **Instructions.** `_instructed()` clones the Agent with callable instructions = `await agent.get_system_prompt(ctx)` followed by the hub MCP server's instructions. So our callable instructions survive, with the static hub guide appended *after* our volatile tail.
- **History default.** `SQLiteSession(hub.id)` in memory unless `session=` is given.

**What that means for a shared talk core:**
- **The person is fixed per `VoiceAgent`.** Bind the person into the Agent itself, through a closure or `agent.clone(instructions=...)`, not via `RunContextWrapper.context`, because context is `None` here. Pass `session=TurnHistory(...)`. The History is fixed per `VoiceAgent` instance too, which is fine for "assume the desk owner" (handoff §4.1) and not fine once speaker ID arrives.
- **Cost logging** must live on `Agent.hooks`, and tracing must be off globally.
- **The per-person lock is bypassed,** so a voice turn and a chat turn for the same person can interleave.
- **`turn.interrupted_heard`:**
  - The History sees an assistant item with the heard text, then a user item that starts with `CUT_OFF`.
  - `TurnHistory.add_items` can recognise the prefix (`tinyaisense.openai_agents.CUT_OFF` is exported), strip it, and record it.
  - It cannot UPDATE the earlier append-only row, so the heard text goes on its own `aivita` row.
  - Alternatively, use `VoiceAgent(on_turn=...)`, whose `Turn` carries `interrupted` and each `say`'s `heard_text`.
- **Fallback.** These are all M3 issues. They match the fallback in handoff §4.2: a thin adapter on `say.open/append/close` that copies the interrupt handling. Small upstream changes in tinyaisense would also fix them: pass `context=`, `run_config=` and `hooks=` through, and take a per-turn History factory.

## 9. What a hand-rolled loop would take

| Piece | Hand-rolled (plain `openai` 3.x) | With the SDK |
|---|---|---|
| Tool schema + dispatch | `openai.pydantic_function_tool(Model)` + a name→coroutine map, ~40 lines | `@function_tool` from signatures and docstrings |
| Step loop | `client.chat.completions.stream(...)` accumulates tool-call deltas (`ChatCompletionStreamState`, `openai/lib/streaming/chat/_completions.py:292`); run tools with `asyncio.gather`, append `tool` messages, repeat ≤ N; ~120 lines | `Runner.run_streamed` |
| History | read and write `turn` directly, ~60 lines | `TurnHistory` adapter, ~60 lines (§3) |
| Prompt layout + `cache_control` | build `messages` with content parts directly, ~20 lines | callable instructions + `CacheMarkTransport`, ~30 lines |
| Cost per call | `completion.usage.model_extra["cost_rub"]` | `preserve_raw_usage` + `on_llm_end` |
| Cancellation | cancel the task; persist the heard text, ~30 lines | `result.cancel("immediate")` |
| Test fake | mock transport or a small `FakeLLM`, ~50 lines | `agents.testing.ScriptedModel` |
| MCP tools (hub) | `mcp` client by hand, or call the tinyaisense SDK directly | `MCPServerStreamableHttp` / `HubMcpServer` |
| Voice turn loop | write the plan-B adapter (~370-line reference in `VoiceAgent`) | reuse `VoiceAgent`, with the §8 caveats |

The hand-rolled loop totals about 300-400 lines plus tests, and drops roughly 37 packages of dependency weight (`openai` stays). Unless the voice channel also drops `VoiceAgent` and `HubMcpServer`, the SDK comes back through `tinyaisense[agents]` anyway.

## Open points to verify live (polza smoke run, #7)

- Tool-call round trip through the SDK on the chosen talk model (handoff §4.3 already asks for this).
- Streaming with `include_usage=True` returns `cost_rub` in the last chunk.
- Claude via polza with `cache_control` on the system prefix: `cached_tokens` / `cache_write_tokens` on the second call.
- `extra_body={"reasoning": {"effort": ...}}` from the SDK actually changes `reasoning_tokens`. The top-level `reasoning_effort` that polza documents as ignored should not.
- How a mid-conversation `system` message behaves (layout B) on the chosen models.

## Sources

- openai-agents-python at v0.23.1: https://github.com/openai/openai-agents-python/tree/v0.23.1 (source paths as cited; docs under `docs/`, rendered at https://openai.github.io/openai-agents-python/)
- Releases: https://github.com/openai/openai-agents-python/releases · PyPI: https://pypi.org/project/openai-agents/
- polza.ai: chat completions https://polza.ai/docs/api-reference/chat/completions.md · caching https://polza.ai/docs/osobennosti/caching.md · usage https://polza.ai/docs/osobennosti/usage.md · reasoning https://polza.ai/docs/osobennosti/reasoning-tokens.md · API intro (stream errors, retries) https://polza.ai/docs/api-reference/introduction.md
- Companion research: [polza.ai API facts](https://github.com/unkier/aivita/blob/research/polza-api/docs/research/polza-api.md) (#2)
- `openai` 3.24.0 (installed package source, paths as cited)
- tinyaisense SDK at `442045a`: `packages/sdk/src/tinyaisense/openai_agents.py`, `packages/sdk/pyproject.toml`, `README.md` ("Agents in Python"), `uv.lock`
