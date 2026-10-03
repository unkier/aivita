# polza.ai API facts (vs handoff §4.3)

Research for [#2](https://github.com/unkier/aivita/issues/2). Checked 2026-10-03 against polza's own docs (starting at <https://polza.ai/docs/llms.txt>), its OpenAPI spec, and its public catalog endpoints.

**How this was checked.** No API key was used and no billed call was made. Model data comes from `GET /api/v1/models`, which polza documents as public with no auth ([models-ref]). Server tools come from `GET /api/v1/server-tools`, plugins from `GET /api/v2/plugins` (both public in [openapi]). Everything marked **verify** below goes into the smoke run (#7).

Polza's docs sometimes disagree with each other (the guides and the API reference). When they do, this file cites both and treats the OpenAPI spec and the live catalog as newer.

## Summary: handoff §4.3, row by row

| §4.3 claim | Verdict | Correction / detail |
|---|---|---|
| Client: `AsyncOpenAI(base_url="https://polza.ai/api/v1", api_key=...)` | **Confirmed** | Bearer key in `Authorization`. Full OpenAI-SDK compatibility is stated ([intro]). |
| Agents SDK via `OpenAIChatCompletionsModel` | **Confirmed on polza's side** (the SDK side belongs to #5) | Chat Completions supports streaming and tools ([chat-ref]). Polza also has a **Responses API, but it is beta and stateless**: no `previous_response_id`, no `store`. Internally it is converted to Chat Completions ([responses]). So Chat Completions is the right path. |
| Model ids in `provider/model` form; models list endpoint; ids in config | **Confirmed**, with caveats | `GET /api/v1/models` is **public (no key)** and returns ids, RUB prices, context, `supported_parameters` per provider ([models-ref], [models-guide]). On 2026-10-03 it listed 317 chat models. A few ids break the pattern: `GigaChat/GigaChat-3-Pro`, and image ids such as `seedream/5-pro-text-to-image`. The embeddings reference examples use the bare id `text-embedding-3-large`, but the catalog id is `openai/text-embedding-3-large` ([emb-ref], [catalog-emb]). |
| Tiers: talk = low reasoning effort, deep = higher | **Needs correction** | Set effort with the `reasoning: {effort: ...}` object or the model suffix `model@reasoning_effort=low`. **A top-level `reasoning_effort` field (OpenAI style) is silently ignored** ([reasoning]). Claude Opus 4.7+ uses `reasoning: {type: "adaptive", effort_level: ...}` instead ([reasoning]). |
| Decider (Jev) via `POST /api/v1/systemone` | **Out of scope (#3)** | The catalog lists `typesafe/jev`: type `classification`, endpoint `/api/v1/systemone`, 64k context, **17.56 ₽ per 1M input tokens** ([catalog-cls]). |
| Structured output: `json_schema` strict; strictness depends on model; validate + retry | **Confirmed; the support rules are stricter than the handoff assumes** | `response_format` accepts `text`, `json_object`, `json_schema` (with `strict`) and `grammar` ([chat-ref], [structured]). Support is decided **per provider, not per model**: look for `structured_outputs` in a provider's `supported_parameters` ([catalog]). It is listed by the default provider of 223/317 chat models and by at least one provider of 261/317. One polza guide says "Claude via Polza ignores `response_format`" ([rag]), but the catalog lists it for Claude's direct providers: **verify**. A `response-healing` plugin repairs invalid JSON ([plugins]). Keep validate + retry once. |
| Caching: `cache_control: {type: "ephemeral"}` on the system prefix | **Partly right** | Explicit `cache_control` is needed **only for Anthropic Claude**: max 4 breakpoints, TTL 5 min or `"ttl": "1h"`, write 1.25×, read 0.1×. OpenAI, DeepSeek, Gemini and Grok **cache automatically** (prefix ≥ ~1024 tokens) ([caching]). `cache_control` only fits on a content **part**, so the system message must be an array of parts, not a string ([chat-ref]). Behaviour on other providers is undocumented. |
| Cost: every response has `usage.cost_rub` | **Confirmed**, with gaps | Present on chat (plus alias `usage.cost`), embeddings, images and Responses ([chat-guide], [emb-ref], [img-ref], [responses]). With streaming it comes in the **final chunk (`choices: []`) before `[DONE]`** ([usage], [chat-ref]). The schema marks it nullable. Failed requests are free, but if the client disconnects, the partial answer is billed and no usage arrives ([intro]). |
| Web research: `polza:web_search` server tool or `web_search_options` | **Confirmed, and there is more** | Three switches: the server tool `tools: [{type: "polza:web_search", parameters: {...}}]` (0.5 ₽/call, Yandex by default or Google), `web_search_options`, or `plugins: [{id: "web"}]`. The guides and the reference disagree about `web_search_options` (details below). There are also server tools **`polza:web_fetch` (free, page → main text, up to 100k chars)**, `polza:image_search` and `polza:datetime` ([server-tools], [openapi]). `polza:web_fetch` may replace httpx + trafilatura. |
| Embeddings: multilingual, e.g. `qwen/qwen3-embedding-4b` | **Confirmed, but a better option exists** | `qwen/qwen3-embedding-4b`: 2560 dims, 32k context, **2.34 ₽/M**. **`qwen/qwen3-embedding-8b` is cheaper (1.17 ₽/M)**, has 4096 dims, and polza recommends it for Russian ([catalog-emb], [langchain], [rag]). A `dimensions` parameter exists "if the model supports it" ([openapi]). |
| Images: `images/generations` for "show a picture"; vision input for "look" | **Confirmed, with corrections** | The OpenAI-compatible endpoint really lives at `/v2/images/generations`; per the docs, the SDK with the `/api/v1` base still reaches it. It is **synchronous for up to 120 s**, then returns `{"status": "pending", id}` to poll at `GET /v1/media/{id}` ([img-ref]). Polza recommends the async Media API `POST /v1/media` for new code ([img-ref], [media-ref]). Results are kept on polza's CDN for **7 days only** ([media-ref]). Doc example ids (`gpt-image-1`, `dall-e-3`) are not in the catalog. Vision: `image_url` parts with a URL or base64 data URI; 181/317 chat models accept images ([media-input], [catalog]). |
| Fallbacks: "Model alias syntax with fallbacks exists" | **Wrong in substance** | The alias syntax exists: `model@provider=X&reasoning_effort=Y&allow_fallbacks=true\|false` (plus `data_residency` in the OpenAPI spec) ([aliases], [openapi]). But `allow_fallbacks` means **another provider for the same model**, not another model. **There is no model-level fallback**: the `models` array is documented as "НЕ РЕАЛИЗОВАНО" (not implemented) and is ignored ([openapi], [responses]). Aivita has to run her own fallback chain of model ids. |

Things the handoff does not mention but that matter:

- **The default provider can be a stripped-down one.** For example, the default ("top") provider of `anthropic/claude-haiku-4.5`, `claude-sonnet-4.6`, `claude-opus-4.5` and `claude-opus-4.6` is `drouter`. Its only supported parameter is `max_tokens`: no tools, no structured output. 26 models are like this ([catalog]). The docs do not say what happens to `tools` / `response_format` then. The reasoning page says unsupported reasoning blocks "may be dropped without an error" ([reasoning]). Use `provider: {require_parameters: true}` (defined in [openapi]) or `provider.only`. **Verify**.
- **Errors in the middle of a stream arrive with HTTP 200**, as a chunk with an `error` field and `finish_reason: "error"`. Check every chunk ([intro]).
- **A key-level spend limit (daily, weekly or monthly) exists.** `GET /api/v1/key` returns `usage_daily` and `limit_remaining`, and an exhausted key gets `402` ([key]). That is a hard backstop under Aivita's own ruble budget.
- **Parallel calls reserve money**: input cost plus `max_tokens` (2048 if unset). With a low balance, concurrent calls get `402` ([balance]).
- **Privacy:** by default polza stores no prompts or responses; per-key logging is opt-in and kept 30 days. Upstream providers keep data for 0 to 30 days, and polza flags DeepSeek (its own API) as "may train on data" ([privacy], [faq]). `provider.data_residency: "ru"` restricts a request to Russia-hosted providers; few models have one ([openapi], [catalog]).

---

## 1. Endpoints and client

- Base URL `https://polza.ai/api`; the OpenAI SDK uses `base_url="https://polza.ai/api/v1"` ([intro]).
- Endpoints relevant to Aivita ([openapi]):
  - chat: `POST /v1/chat/completions`
  - responses (beta): `POST /v1/responses`
  - Anthropic-native: `POST /v1/messages`
  - embeddings: `POST /v1/embeddings`
  - Jev: `POST /v1/systemone`
  - catalog: `GET /v1/models`, `/v1/models/catalog`, `/v1/models/{id}`
  - images: `POST /v2/images/generations`
  - media: `POST /v1/media`, `GET /v1/media/{id}`
  - storage: `POST /v1/storage/upload`
  - money: `GET /v2/balance`, `GET /v1/key`
  - history: `GET /v1/history/generations[/{id}]`
  - discovery: `GET /v1/server-tools`, `GET /v2/plugins`
- Limits ([intro]): request timeout 600 s, file size 50 MB.
- Error body: `{error: {code, message, trace_id, metadata: {provider_name, raw}}}` ([intro]).

When to retry ([intro]):

| Status | Retry? |
|---|---|
| 408, 502 | Yes, after a pause |
| 503 | Yes; respect `Retry-After` if present |
| 429 (polza's per-model, per-org minute/day limit) | Yes, not before `Retry-After` |
| 429 (provider's limit) | Yes, with backoff 1, 2, 4, 8 s, or switch model |
| 402 | Only when caused by concurrency |
| 400, 401, 403, 404, 413 | No |

There is no idempotency key. Polza already switches providers internally before it surfaces a provider 429.

## 2. Chat completions: streaming and tools

- Request fields ([openapi] `ChatCompletionRequestDto`):
  - standard: `model`, `messages` (or `prompt`), `max_tokens`/`max_completion_tokens`, `temperature`, `top_p`, `stop`, `seed`, `n`, `stream`, `logprobs`, `parallel_tool_calls`, `modalities`
  - tools: `tools`, `tool_choice` (`none`/`auto`/`required`/named), `max_tool_calls`
  - structured output: `response_format`
  - polza extras: `reasoning`, `provider`, `plugins`, `web_search_options`, `stop_server_tools_when`, `stream_options`
- Roles: `system`, `developer`, `user`, `assistant`, `tool` (`tool_call_id` required) ([chat-guide]).
- Tool round trip: standard OpenAI shape (assistant `tool_calls` → `role: tool` messages → final answer). Parallel tool calls are documented ([tools]). Function definitions accept `strict` ([openapi] `ToolFunctionDto`).
- Streaming is SSE with `chat.completion.chunk` deltas ([chat-ref]). The docs do not show a **streamed** tool-call example: **verify** that `delta.tool_calls` arrives in OpenAI form.
- `stream_options` ([openapi] `ChatStreamOptionsDto`):
  - `include_usage`: usage in the final chunk, "OpenAI compatibility"
  - `include_server_tool_events`: server-tool loop events in a `polza` field
  - `hide_intermediate_text`
- The response names the provider that served it (`"provider": "openai-direct"`) ([chat-guide]).
- `finish_reason` values: `stop`, `length`, `tool_calls`, `content_filter`, `error` ([openapi]).
- Tool support per model: in [catalog], `tools` is listed by the default provider of 231/317 chat models and by at least one provider of 257/317. Sber and Yandex models list no tools ([catalog]).

## 3. Structured output

- `response_format: {type: "json_schema", json_schema: {name, strict: true, schema}}`. Polza recommends `strict: true`, `additionalProperties: false` and an object at the top level (not a bare array) ([structured]).
- Per the docs, with `strict: true` "the model will return schema-valid JSON or an error" ([structured]). But support varies per model and per provider. The catalog signals it with `structured_outputs` (true JSON-schema enforcement) and `response_format` in `supported_parameters` ([catalog], [reasoning]).
- Contradiction: the RAG guide says Claude ignores `response_format` and that Gemini wraps JSON in code fences ([rag]). The catalog lists `structured_outputs` for Claude on the `anthropic`, Bedrock, Vertex and Azure providers ([catalog]). **Verify** with one Claude call.
- The guide advises against combining web search with `json_schema`: citations get lost ([websearch]).
- Plugin `response-healing` repairs invalid JSON ([plugins]). It does not appear in the live `GET /v2/plugins` list, which shows only `polza-pdf-parser` and `web` ([plugins-live]). The Responses reference lists it as a plugin ([responses]).

## 4. Prompt caching

Provider table ([caching]):

| Provider | Write | Read | Min tokens | Mode |
|---|---|---|---|---|
| OpenAI | free | 0.25–0.5× | 1024 | automatic |
| Anthropic Claude | 1.25× | 0.1× | — | manual (`cache_control`) |
| DeepSeek | standard | 0.1× | — | automatic |
| Google Gemini | free | 0.25× | 1024–2048 | automatic |
| Grok | free | 0.25× | — | automatic |

The catalog shows non-zero cache **write** prices for Gemini and some Qwen and OpenAI models ([catalog]), which contradicts "free" in this table. Budget from the catalog prices, not from the table.

- Chat Completions form: put `cache_control` on a content part of the system message, e.g. `{"role": "system", "content": [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]}` ([chat-ref], [caching]).
- 1-hour TTL: `"cache_control": {"type": "ephemeral", "ttl": "1h"}`; no beta header needed ([caching]).
- On the Anthropic-native `/v1/messages` endpoint, `cache_control` works on system, user text/image, assistant text, `tool_result` and tool definitions. Prefix order is tools → system → messages ([caching]).
- Usage reports `prompt_tokens_details.cached_tokens` and `cache_write_tokens`; `prompt_tokens` is the whole input ([caching]).
- Aivita's frozen prefix (persona, values, tool list) fits automatic caching on OpenAI, Gemini and DeepSeek as-is. On Claude it needs the array form and a `cache_control` marker.

## 5. Cost, usage, budget

- `usage` = `{prompt_tokens, completion_tokens, total_tokens, cost_rub, cost, prompt_tokens_details{cached_tokens, cache_write_tokens, audio_tokens, video_tokens}, completion_tokens_details{reasoning_tokens, ...}}` ([usage], [openapi] `UsagePresenter`).
- `cost_rub` is "the amount debited". It is typed as a nullable object in the schema ([openapi]), so handle `None`.
- Streaming: the final SSE event before `[DONE]` carries `choices: []` plus `usage` with `cost_rub` ([usage], [chat-ref]). The usage guide implies it always comes. The schema offers `stream_options.include_usage` "for OpenAI compatibility". Sending `include_usage: true` is the safe choice.
- Server-tool requests add `cost_details: {inference_cost_rub, server_tools_cost_rub}` and `server_tool_use` counts ([openapi]).
- The OpenAI Python SDK keeps unknown fields, and polza's own example reads `response.usage.cost_rub` ([chat-ref]).
- Billing rules ([intro]):
  - errors are not billed, including errors mid-stream
  - a client-side disconnect bills the generated part, and no usage is received
  - reconcile through `GET /v1/history/generations/{id}` or `GET /v1/key` ([openapi], [key])
- Key limits ([key]):
  - fields: `limit`, `limit_remaining`, `limit_reset` (`daily`/`weekly`/`monthly`/`never`), `usage_daily`/`usage_weekly`/`usage_monthly` in ₽
  - periods start at 01:00 Moscow time
  - an exhausted key gets `402`
- Reserve: each call reserves input cost plus `max_tokens` (2048 if unset). Set `max_tokens` tight to allow more concurrency ([balance]).
- Reasoning tokens are billed as output tokens ([reasoning]). The RAG guide warns that DeepSeek reasoning can eat the whole `max_tokens` and return an empty `content` ([rag]).

## 6. Models list

- `GET /api/v1/models?type=chat|image|embedding|audio|video|tts|stt|classification&include_providers=true`. Public, no key ([models-guide], [models-ref]). OpenAPI marks an `accept-language` header as required.
- Fields per model: `id`, `name`, `type`, `context_length`, `max_completion_tokens`, `architecture.input_modalities`/`output_modalities`, `top_provider{...}`, `providers[]`, `endpoints`, `stores_data_in_russia`, `is_fz152_compliant` ([catalog]).
- Fields per provider: `pricing`, `supported_parameters`, `supports_native_web_search`, `context_length` ([catalog]).
- Pricing keys ([models-guide], [catalog]):
  - `prompt_per_million`, `completion_per_million` (RUB per 1M tokens)
  - `input_cache_read_per_million`, `input_cache_write_per_million`, `internal_reasoning_per_million`
  - `web_search_per_thousand`, `image_input_per_million`, `per_request`
  - `currency: "RUB"`
- Snapshot of 2026-10-03: 317 chat, 26 embedding and 25 image models, plus 1 classification model (Jev) ([catalog]).
- A shortlist is in Appendix A and the full chat list in Appendix B. **Prices change; read them from the endpoint at startup instead of copying them.**

## 7. Routing, aliases, fallbacks

- The `provider` object ([provider], [openapi] `ProviderDto`):
  - `order`, `only`, `ignore`: provider slugs
  - `sort`: `price`, `latency` or `throughput`
  - `max_price`: RUB per 1M tokens, per image, per request
  - `allow_fallbacks`
  - `require_parameters`: "require the provider to support all passed parameters"
  - `data_residency: "ru"`
- If no provider is given, polza picks one by availability, speed and cost and fails over between providers on errors ([provider]).
- Alias syntax: `<model>@<key>=<value>&...`, keys `provider` (maps to `provider.only`), `reasoning_effort` (maps to `reasoning.effort`), `allow_fallbacks` (maps to `provider.allow_fallbacks`) ([aliases]). The OpenAPI spec adds `data_residency` ([openapi]).
- Alias rules ([aliases]):
  - works on `/v1/chat/completions`, `/v1/responses` and `/v1/messages`, not on embeddings, audio or media
  - setting the same thing in both the alias and the body returns `400`
  - responses echo the canonical model id without the suffix
- **No model-to-model fallback.** The `models` array is "НЕ РЕАЛИЗОВАНО. Массив fallback-моделей пока не поддерживается … и игнорируется" ("not implemented; the array of fallback models is not supported yet and is ignored") ([openapi], [responses]).
- **Practical consequence:** `llm/` keeps a per-tier list of model ids and moves to the next one on 5xx, 429 without `Retry-After`, or a timeout. Polza already handles failover between providers of the same model.

## 8. Reasoning

- `reasoning: {effort: none|minimal|low|medium|high|xhigh|max, max_tokens, enabled, exclude, summary}`. For Claude Opus 4.7+: `{type: "adaptive", effort_level: low|medium|high|max}` ([reasoning], [openapi] `ReasoningDto`).
- **A top-level `reasoning_effort` is ignored without an error.** Use `reasoning.effort` or the `@reasoning_effort=` suffix ([reasoning]).
  - If the OpenAI Agents SDK maps `ModelSettings.reasoning` to the top-level field on Chat Completions, put the effort in the model-id suffix instead (for #5 to confirm).
- Polza forwards no default effort and does not remap levels. If a provider does not list `reasoning`, the block may be dropped without an error ([reasoning]).

## 9. Web search and server tools

There are three ways to turn search on, and the docs disagree:

| Switch | What [websearch] (guide) says | What [openapi] / live lists say |
|---|---|---|
| `plugins: [{id: "web", max_results, search_prompt, engine}]` | "Recommended, any model". Engine `native` (OpenAI, Anthropic, xAI, Perplexity) or `exa`. | Live plugin `web`: Yandex Search API run **before** the model call, results injected; engines `yandex` (default), `native`, `exa`; `max_results` 1–20 ([plugins-live]). |
| `web_search_options` | "OpenAI-native, limited models, ignored elsewhere" | "Enables web search for **any** model: polza runs it (server tool `polza:web_search`; for models without tool calling, the search runs before the call)". `search_context_size` is accepted but has no effect. |
| `tools: [{type: "polza:web_search", parameters: {...}}]` | not mentioned | The model calls the tool and polza runs it inside the request. Parameters: `max_results` 1–10 (default 5), `max_uses` (default 3), `allowed_domains`/`excluded_domains` (≤50), `engine` `yandex` (default) or `google`. **0.5 ₽ per call** ([server-tools]). |

Other server tools ([server-tools]):

| Tool | Price | Notes |
|---|---|---|
| `polza:web_fetch` | **free** | URL → main content, `max_characters` 100–100000 (default 20000) |
| `polza:image_search` | 0.5 ₽ | image URL, title, source site, size; could serve "show a picture" with real images |
| `polza:datetime` | free | |
| `polza:wordstat`, `polza:search_suggestions`, `polza:find_party`, `polza:find_company_by_email`, `polza:clean_address` | various | Russian business lookups; not relevant to Aivita |

Server-tool loop controls ([openapi]):

- `max_tool_calls`: default 10, cap 30
- `stop_server_tools_when: [{type: "step_count", value}, {type: "spend_cap", value_rub}]`; the spend cap is soft, checked before each model step
- function tools (`type: function`, run by Aivita) and server tools (`type: polza:*`) share the one `tools` array

Results:

- Citations come back in `message.annotations[]` as `url_citation` ([websearch]).
- Native search reports `usage.server_tool_use.web_search_requests` ([websearch]).
- The catalog has a `web_search_per_thousand` price for native provider search; for GPT and Claude it is 1170.68 ₽ per 1000 searches, about 1.17 ₽ each ([catalog]).

**Verify** which switch the smoke run should use. The handoff's "server-side `polza:web_search` tool" is the clearest one: Yandex/Google, priced per call, the model decides when to search.

## 10. Embeddings

- `POST /v1/embeddings {model, input: str|[str], encoding_format: float|base64, dimensions?, provider?}`; `usage.cost_rub` returned ([emb-ref], [openapi]).
- Multimodal input (text + image) works only on `google/gemini-embedding-2-preview` ([emb-ref]).

Multilingual (RU↔EN) candidates. Prices and context are from [catalog-emb]; dims from [langchain] unless noted:

| id | dims | ctx | ₽ / 1M tokens | Note |
|---|---|---|---|---|
| `qwen/qwen3-embedding-8b` | 4096 | 32k | **1.17** | polza's pick for Russian ([rag]); providers deepinfra, nebius, siliconflow |
| `qwen/qwen3-embedding-4b` | 2560 | 32k | 2.34 | the handoff's example; deepinfra only |
| `intfloat/multilingual-e5-large` | 1024 | 512 | 1.17 | "cross-lingual search" ([rag]); short context |
| `baai/bge-m3` | not stated by polza | 8k | 1.17 | multilingual ([catalog-emb]) |
| `openai/text-embedding-3-small` | 1536 (shrinkable via `dimensions`) | 8k | 2.34 | |
| `openai/text-embedding-3-large` | 3072 | 8k | 15.22 | |
| `google/gemini-embedding-001` | 3072 | 20k | 17.56 | |
| `yandex/text-search-doc` / `-query` | not stated | — | 14.23 | separate doc and query models; hosted in Russia |

- Polza confirms `dimensions` only for OpenAI's `text-embedding-3-*` ([langchain]). The OpenAPI spec says "if the model supports it" ([openapi]). Whether Qwen3 truncation works through polza is unverified.
- At 4096 floats a vector is about 16 KB. That matters for sqlite-vec (#6) and makes 2560 or a truncated size attractive.

## 11. Vision input

- Content part `{"type": "image_url", "image_url": {"url": "https://…" | "data:image/jpeg;base64,…", "detail": "auto"|"low"|"high"}}`. PNG, JPEG, WebP and GIF (first frame only) are accepted; several images per message are allowed ([media-input]).
- Large files can go through `POST /v1/storage/upload` and be sent as a URL. Storage takes images, video and audio only ([media-input]).
- Check that the model's `architecture.input_modalities` contains `"image"`: true for 181/317 chat models ([catalog]). Gemini models also accept `media_resolution` ([openapi]).

## 12. Image generation

- **OpenAI-compatible:** `client.images.generate(model=..., prompt=..., size=..., quality=..., response_format="url"|"b64_json")`. The real path is `/v2/images/generations`; the docs say the SDK with `base_url=/api/v1` is routed correctly. Synchronous up to **120 s**, then it returns `{id, status: "pending"}` to poll at `GET /v1/media/{id}` every 3–5 s. The success body has `data[].url` (`cdn.polza.ai`) and `usage.cost_rub` ([img-ref]).
- **Media API (recommended for new code):** `POST /v1/media {model, input: {prompt, aspect_ratio, quality, images: [{type: "url"|"base64", data}]}, async: true}`, then poll `GET /v1/media/{id}` ([media-ref], [gpt-image]). The model guides use this form; the input fields vary per model ([gpt-image]).
- **Retention: generated files live on polza's CDN for 7 days**, then they are deleted ([media-ref], [privacy]). Aivita must download every image she wants to keep into her local store.
- The catalog lists 25 image models; all list both `/api/v1/media` and `/api/v1/images/generations` ([catalog-img]). Per-image prices, cheapest first ([catalog-img]):

| id | ₽ per image |
|---|---|
| `tongyi-mai/z-image` | 1.40 |
| `qwen/image` | 2.25–3 |
| `x-ai/grok-imagine-image` | 2.50 |
| `google/gemini-2.5-flash-image` | 2.90 |
| `google/gemini-3.1-flash-lite-image` | 2.90 |
| `yandex/yandex-art` | 2.91 |
| `openai/gpt-image-1.5` | 3 (medium) / 16.5 (high) |
| `qwen/image-2.1` | 3 (1K) / 6 (2K) |
| `bytedance/seedream-4` | 3 |
| `openai/gpt-5.4-image-2` | 4 (1K) to 11 (4K) |
| `google/gemini-3.1-flash-image-preview` | 4.80 (1K) |
| `black-forest-labs/flux.2-pro` | 5 (1K) |
| `google/gemini-3-pro-image-preview` | 13.50 |

## 13. Privacy and data residency

- Polza does not store request or response content by default, only metadata (time, model, tokens). Logging is an opt-in per API key and kept 30 days ([faq], [privacy]).
- How upstream providers treat data, per polza ([privacy]):

| Group | Providers |
|---|---|
| No storage | Azure, Groq, Bedrock, DeepInfra, Fireworks, Together, Cerebras, SambaNova, Featherless |
| Keep up to 30 days | OpenAI, Anthropic, Google Vertex, Mistral, xAI, … |
| "Potentially unsafe / may train" | DeepSeek, OpenInference |

- `provider.ignore` excludes chosen providers. `provider.data_residency: "ru"` keeps the request on Russia-hosted providers (it is rejected if the model has none). Only about 20 chat models have one: Sber GigaChat, YandexGPT, and some Qwen, DeepSeek-V3.2 and gpt-oss models served by Yandex ([openapi], [catalog]).

## 14. Verify in the smoke run (#7)

1. Tool-call round trip, streamed and non-streamed, on the chosen talk model: `delta.tool_calls` shape, `finish_reason: "tool_calls"`.
2. `json_schema` strict on the chosen cheap model **and** on one Claude model. Does Claude honour it or ignore it ([rag] vs [catalog])?
3. What happens when the default provider lacks `tools`/`structured_outputs` (e.g. `anthropic/claude-haiku-4.5`, default `drouter`), with and without `provider.require_parameters: true`.
4. `usage.cost_rub` in the final stream chunk, with and without `stream_options.include_usage`.
5. `reasoning.effort` vs `@reasoning_effort=` vs top-level `reasoning_effort` (the last should be ignored).
6. `cached_tokens` on a second call with the same ≥1024-token prefix, and Claude with `cache_control`.
7. `qwen/qwen3-embedding-8b` vs `-4b`: vector length, `dimensions` truncation.
8. `polza:web_search` and `polza:web_fetch` in `tools`, `annotations`, `cost_details`.
9. `client.images.generate` with base `/api/v1` and the sync/pending behaviour.

---

## Appendix A. Shortlist of chat models (full-feature provider prices)

Prices are in ₽ per 1M tokens, from the cheapest provider that supports tools (named when it is not the default provider) ([catalog], snapshot 2026-10-03). This is not a tier recommendation; #8 decides tiers.

Legend:

- tools / strict / reasoning: `Y` = that provider lists `tools` / `structured_outputs` / `reasoning`; `some` = only some providers do; `-` = none do.
- vision: image input accepted.
- RU: the model is hosted in Russia.

| id | ctx | in ₽/M | out ₽/M | cache read ₽/M (/ write) | tools | strict | vision | reasoning | RU |
|---|---|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-4.5` (via `anthropic`) | 200k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `anthropic/claude-opus-5.5` | 1000k | 468 | 2341 | 23.4 / w 585 | Y | some | Y | Y |  |
| `anthropic/claude-sonnet-4.6` (via `anthropic`) | 200k | 351 | 1756 | 35.1 / w 439 | Y | Y | Y | Y |  |
| `anthropic/claude-sonnet-5` | 1000k | 234 | 1171 | 23.4 / w 293 | Y | Y | Y | Y |  |
| `deepseek/deepseek-v4-flash` | 1024k | 3.3 | 6.6 | 0.66 | Y | Y | Y | Y |  |
| `deepseek/deepseek-v4-pro` | 1024k | 24.4 | 48.9 | 2.0 | Y | Y | - | Y |  |
| `deepseek/deepseek-v4.1-flash` | 1048k | 10.5 | 21.1 | 2.1 | Y | Y | Y | Y |  |
| `google/gemini-2.5-flash-lite` | 1048k | 5.9 | 23.4 | 0.59 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.1-flash-lite` | 1048k | 14.6 | 87.8 | 1.5 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.1-pro-preview` (via `google-vertex/global/flex`) | 1048k | 117 | 702 | 11.7 / w 22.0 | Y | Y | Y | Y |  |
| `google/gemini-3.5-flash-lite` | 1048k | 17.6 | 146 | 1.8 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.8-flash` | 1048k | 43.9 | 220 | 4.4 / w 2.4 | Y | Y | Y | Y |  |
| `minimax/minimax-m3` | 262k | 26.9 | 112 | 5.9 | Y | Y | Y | Y |  |
| `mistralai/mistral-small-2603` | 262k | 17.6 | 70.2 | 1.8 | Y | Y | Y | Y |  |
| `moonshotai/kimi-k2.6` | 262k | 54.4 | 287 | 11.4 | Y | Y | Y | Y |  |
| `openai/gpt-5-mini` | 400k | 14.6 | 117 | 1.5 | Y | Y | Y | Y |  |
| `openai/gpt-5-nano` | 400k | 2.9 | 23.4 | 0.29 | Y | Y | Y | Y |  |
| `openai/gpt-5.4-mini` | 400k | 43.9 | 263 | 4.4 | Y | Y | Y | Y |  |
| `openai/gpt-5.4-nano` | 400k | 11.7 | 73.2 | 1.2 | Y | Y | Y | Y |  |
| `openai/gpt-5.5` | 1050k | 293 | 1756 | 29.3 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-luna` | 1050k | 11.7 | 70.2 | 1.2 / w 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-sol` | 1050k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `qwen/qwen3.5-flash-02-23` | 1000k | 7.6 | 30.4 | - | Y | Y | Y | Y |  |
| `qwen/qwen3.6-35b-a3b` | 262k | 5.9 | 81.9 | 2.9 | Y | Y | Y | Y | Y |
| `qwen/qwen3.8-flash` | 1000k | 17.6 | 55.0 | 1.9 / w 23.4 | Y | Y | Y | Y |  |
| `qwen/qwen3.8-max` | 1000k | 234 | 702 | 29.3 / w 293 | Y | Y | Y | Y |  |
| `sber/gigachat-2` | 128k | 91.0 | 91.0 | - | - | - | - | - | Y |
| `x-ai/grok-4.3` | 1000k | 146 | 293 | 23.4 | Y | Y | Y | Y |  |
| `yandex/yandexgpt-5-lite` | 32k | 280 | 280 | - | - | - | - | - | Y |
| `z-ai/glm-4.7-flash` | 202k | 7.0 | 46.8 | 1.2 | Y | Y | Y | Y |  |
| `z-ai/glm-5.3-flash` | 1048k | 8.8 | 29.3 | 1.8 | Y | Y | Y | Y |  |

## Appendix B. Full chat catalog snapshot (2026-10-03)

Generated from [catalog] (`GET https://polza.ai/api/v1/models?type=chat&include_providers=true`, sent with an `accept-language: ru` header). Prices and flags are the **default ("top") provider's**. `some` = only some providers support it, so pin the provider. **†** = the default provider lacks `tools` although other providers have them; route around it.

| id | ctx | in ₽/M | out ₽/M | cache read ₽/M (/ write) | tools | strict | vision | reasoning | RU |
|---|---|---|---|---|---|---|---|---|---|
| `GigaChat/GigaChat-3-Pro` | 262k | 102 | 247 | - | Y | - | - | - |  |
| `aiesa/aiesa-mini` | - | 120 | 170 | - | - | - | - | - | Y |
| `aiesa/aiesa-pro` | - | 350 | 600 | - | - | - | - | - | Y |
| `aion-labs/aion-2.0` | 131k | 93.7 | 187 | 23.4 | Y | - | - | Y |  |
| `aion-labs/aion-3.0` | 131k | 351 | 702 | 87.8 | Y | - | - | Y |  |
| `aion-labs/aion-3.0-mini` | 131k | 81.9 | 164 | 21.1 | Y | - | - | Y |  |
| `aion-labs/aion-rp-llama-3.1-8b` | 32k | 93.7 | 187 | - | - | - | - | - |  |
| `amazon/nova-2-lite-v1` | 1000k | 35.1 | 293 | - | Y | - | Y | Y |  |
| `amazon/nova-lite-v1` | 300k | 7.0 | 28.1 | - | Y | - | Y | - |  |
| `amazon/nova-micro-v1` | 128k | 4.1 | 16.4 | - | Y | - | - | - |  |
| `amazon/nova-pro-v1` | 300k | 93.7 | 375 | - | Y | - | Y | - |  |
| `anthracite-org/magnum-v4-72b` | 32k | 293 | 585 | - | - | Y | - | - |  |
| `anthropic/claude-fable-5` | 1000k | 1171 | 5853 | 117 / w 1463 | Y | Y | Y | Y |  |
| `anthropic/claude-fable-5.1` | 1000k | 1171 | 5853 | 29.3 / w 1463 | Y | Y | Y | Y |  |
| `anthropic/claude-haiku-4.5` † | 200k | 50.2 | 50.2 | 50.2 / w 50.2 | some | some | Y | some |  |
| `anthropic/claude-opus-4.1` | 200k | 1756 | 8780 | 176 / w 2195 | Y | some | Y | Y |  |
| `anthropic/claude-opus-4.5` † | 200k | 324 | 1620 | 32.4 / w 405 | some | some | Y | some |  |
| `anthropic/claude-opus-4.6` † | 1000k | 151 | 151 | 151 / w 151 | some | some | Y | some |  |
| `anthropic/claude-opus-4.7` | 1000k | 585 | 2927 | 58.5 / w 732 | Y | Y | Y | Y |  |
| `anthropic/claude-opus-4.8` | 1000k | 585 | 2927 | 58.5 / w 732 | Y | Y | Y | Y |  |
| `anthropic/claude-opus-5` | 1000k | 585 | 2927 | 58.5 / w 732 | Y | some | Y | Y |  |
| `anthropic/claude-opus-5.5` | 1000k | 468 | 2341 | 23.4 / w 585 | Y | some | Y | Y |  |
| `anthropic/claude-sonnet-4` | 200k | 351 | 1756 | 35.1 / w 439 | Y | - | Y | Y |  |
| `anthropic/claude-sonnet-4.5` | 1000k | 351 | 1756 | 35.1 / w 439 | Y | Y | Y | Y |  |
| `anthropic/claude-sonnet-4.6` † | 200k | 75.3 | 75.3 | 75.3 / w 75.3 | some | some | Y | some |  |
| `anthropic/claude-sonnet-5` | 1000k | 234 | 1171 | 23.4 / w 293 | Y | Y | Y | Y |  |
| `anthropic/claude-sonnet-5.5` | 1000k | 234 | 1171 | 23.4 / w 293 | Y | some | Y | Y |  |
| `arcee-ai/trinity-large-thinking` | 262k | 29.3 | 93.7 | 7.0 | Y | some | - | Y |  |
| `baidu/ernie-4.5-vl-424b-a47b` | 123k | 49.2 | 146 | - | - | - | Y | Y |  |
| `bytedance-seed/seed-1.6` | 262k | 29.3 | 234 | - | Y | Y | Y | Y |  |
| `bytedance-seed/seed-1.6-flash` | 262k | 8.8 | 35.1 | - | Y | Y | Y | Y |  |
| `bytedance-seed/seed-2.0-lite` | 262k | 29.3 | 234 | - | Y | Y | Y | Y |  |
| `bytedance-seed/seed-2.0-mini` | 262k | 11.7 | 46.8 | - | Y | Y | Y | Y |  |
| `bytedance/ui-tars-1.5-7b` | 128k | 11.7 | 23.4 | 11.7 | - | Y | Y | - |  |
| `cohere/command-a` | 256k | 293 | 1171 | - | - | Y | - | - |  |
| `cohere/command-r-08-2024` | 128k | 17.6 | 70.2 | - | Y | Y | - | - |  |
| `cohere/command-r-plus-08-2024` | 128k | 293 | 1171 | - | Y | Y | - | - |  |
| `cohere/command-r7b-12-2024` | 128k | 4.4 | 17.6 | - | - | Y | - | - |  |
| `deepseek/deepseek-chat` | 163k | 37.5 | 104 | - | Y | Y | - | - |  |
| `deepseek/deepseek-chat-v3-0324` † | 163k | 25.8 | 93.7 | 17.6 | some | some | - | some |  |
| `deepseek/deepseek-chat-v3.1` † | 163k | 17.6 | 87.8 | 15.2 | some | some | - | Y |  |
| `deepseek/deepseek-r1` | 64k | 81.9 | 293 | - | Y | - | - | Y |  |
| `deepseek/deepseek-r1-0528` | 163k | 52.7 | 252 | 26.3 | Y | Y | - | Y |  |
| `deepseek/deepseek-v3.1-terminus` | 163k | 31.6 | 111 | 15.2 | Y | Y | - | Y |  |
| `deepseek/deepseek-v3.2` | 163k | 24.4 | 36.2 | 2.5 | Y | some | - | Y | Y |
| `deepseek/deepseek-v3.2-exp` | 163k | 15.7 | 23.6 | 7.9 | Y | Y | - | Y |  |
| `deepseek/deepseek-v4-flash` | 1024k | 3.3 | 6.6 | 0.66 | Y | Y | Y | Y |  |
| `deepseek/deepseek-v4-flash-0731` | 1024k | 5.2 | 15.5 | 0.16 | Y | some | - | Y |  |
| `deepseek/deepseek-v4-flash-vision-exp` | 1048k | 25.2 | 75.7 | 0.80 | Y | Y | Y | Y |  |
| `deepseek/deepseek-v4-pro` | 1024k | 24.4 | 48.9 | 2.0 | Y | Y | - | Y |  |
| `deepseek/deepseek-v4-pro-0813` | 1048k | 27.8 | 199 | 10.3 | Y | Y | - | Y |  |
| `deepseek/deepseek-v4.1-flash` | 1048k | 10.5 | 21.1 | 2.1 | Y | Y | Y | Y |  |
| `fireworks/ember-1` | 1048k | 351 | 1756 | 35.1 | Y | Y | Y | Y |  |
| `google/gemini-2.5-flash` | 1048k | 17.6 | 146 | 1.8 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-2.5-flash-lite` | 1048k | 5.9 | 23.4 | 0.59 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-2.5-pro` | 1048k | 73.2 | 585 | 7.3 / w 22.0 | Y | Y | Y | Y |  |
| `google/gemini-2.5-pro-preview` | 1048k | 73.2 | 585 | 7.3 / w 22.0 | Y | Y | Y | Y |  |
| `google/gemini-2.5-pro-preview-05-06` | 1048k | 73.2 | 585 | 7.3 / w 22.0 | Y | Y | Y | Y |  |
| `google/gemini-3-flash-preview` | 1048k | 29.3 | 176 | 2.9 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3-pro-preview` | 1048k | 125 | 878 | - | - | - | Y | - |  |
| `google/gemini-3.1-flash-lite` | 1048k | 14.6 | 87.8 | 1.5 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.1-flash-lite-preview` | 1048k | 14.6 | 87.8 | 1.5 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.1-pro-preview` † | 1048k | 113 | 790 | - | some | some | Y | some |  |
| `google/gemini-3.1-pro-preview-customtools` | 1048k | 234 | 1405 | 23.4 / w 43.9 | Y | Y | Y | Y |  |
| `google/gemini-3.5-flash` | 1048k | 87.8 | 527 | 8.8 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.5-flash-lite` | 1048k | 17.6 | 146 | 1.8 / w 4.9 | Y | Y | Y | Y |  |
| `google/gemini-3.6-flash` | 1048k | 43.9 | 220 | 4.4 / w 2.4 | Y | Y | Y | Y |  |
| `google/gemini-3.7-flash` | 1048k | 43.9 | 220 | 4.4 / w 2.4 | Y | Y | Y | Y |  |
| `google/gemini-3.8-flash` | 1048k | 43.9 | 220 | 4.4 / w 2.4 | Y | Y | Y | Y |  |
| `google/gemma-2-27b-it` | 8k | 76.1 | 76.1 | - | - | Y | - | - |  |
| `google/gemma-3-12b-it` † | 131k | 3.5 | 11.7 | 1.8 | some | some | Y | - |  |
| `google/gemma-3-27b-it` | 128k | 3.5 | 12.9 | 1.8 | Y | Y | Y | - | Y |
| `google/gemma-3-4b-it` | 96k | 2.0 | 8.0 | - | - | some | Y | - |  |
| `google/gemma-4-26b-a4b-it` † | 262k | 7.0 | 23.4 | 4.1 | some | Y | Y | Y |  |
| `google/gemma-4-31b-it` † | 262k | 9.4 | 35.1 | 5.9 | some | Y | Y | Y |  |
| `gryphe/mythomax-l2-13b` | 4k | 7.0 | 7.0 | - | - | Y | - | - |  |
| `ibm-granite/granite-4.0-h-micro` | 131k | 2.0 | 13.1 | - | - | - | - | - |  |
| `inception/mercury-2` | 128k | 29.3 | 87.8 | 2.9 | Y | Y | - | Y |  |
| `inference-net/schematron-v2-small` | 128k | 5.9 | 26.9 | 5.9 | - | Y | - | - |  |
| `mancer/weaver` | 8k | 46.8 | 87.8 | - | - | - | - | - |  |
| `meta-llama/llama-3.1-70b-instruct` | 131k | 46.8 | 46.8 | - | Y | Y | - | - |  |
| `meta-llama/llama-3.1-8b-instruct` † | 131k | 2.3 | 4.7 | - | some | some | - | - |  |
| `meta-llama/llama-3.2-1b-instruct` | 60k | 3.2 | 23.5 | - | - | - | - | - |  |
| `meta-llama/llama-3.2-3b-instruct` | 131k | 2.3 | 2.3 | - | - | some | - | - |  |
| `meta-llama/llama-3.3-70b-instruct` | 131k | 11.7 | 37.5 | - | Y | Y | - | - |  |
| `meta-llama/llama-4-maverick` | 131k | 23.4 | 70.2 | - | Y | some | Y | - |  |
| `meta-llama/llama-4-scout` † | 327k | 11.7 | 35.1 | - | some | Y | Y | - |  |
| `meta-llama/llama-guard-4-12b` | 163k | 21.1 | 21.1 | - | - | - | Y | - |  |
| `microsoft/phi-4` | 16k | 7.6 | 16.4 | - | - | Y | - | - |  |
| `microsoft/wizardlm-2-8x22b` | 65k | 56.2 | 56.2 | - | - | - | - | - |  |
| `minimax/minimax-01` | 1000k | 23.4 | 129 | - | - | - | Y | - |  |
| `minimax/minimax-m1` † | 1000k | 46.8 | 258 | - | some | - | - | Y |  |
| `minimax/minimax-m2` | 196k | 29.9 | 117 | 3.5 | Y | Y | - | Y |  |
| `minimax/minimax-m2-her` | 65k | 35.1 | 140 | 3.5 | - | - | - | - |  |
| `minimax/minimax-m2.1` | 196k | 31.6 | 111 | 3.4 | Y | some | Y | Y |  |
| `minimax/minimax-m2.5` | 196k | 25.8 | 69.1 | - | Y | Y | - | Y |  |
| `minimax/minimax-m2.7` | 196k | 24.6 | 98.3 | 4.9 | Y | some | - | Y |  |
| `minimax/minimax-m3` | 262k | 26.9 | 112 | 5.9 | Y | Y | Y | Y |  |
| `mistralai/codestral-2508` | 256k | 35.1 | 105 | 3.5 | Y | Y | - | - |  |
| `mistralai/devstral-2512` | 262k | 46.8 | 234 | 4.7 | Y | Y | - | - |  |
| `mistralai/ministral-14b-2512` | 262k | 23.4 | 23.4 | 2.3 | Y | Y | Y | - |  |
| `mistralai/ministral-3b-2512` | 131k | 11.7 | 11.7 | 1.2 | Y | Y | Y | - |  |
| `mistralai/ministral-8b-2512` | 262k | 17.6 | 17.6 | 1.8 | Y | Y | Y | - |  |
| `mistralai/mistral-large` | 128k | 234 | 702 | 23.4 | Y | Y | - | - |  |
| `mistralai/mistral-large-2407` | 131k | 234 | 702 | 23.4 | Y | Y | - | - |  |
| `mistralai/mistral-large-2512` | 262k | 58.5 | 176 | 5.9 | Y | Y | Y | - |  |
| `mistralai/mistral-medium-3` | 131k | 46.8 | 234 | 4.7 | Y | Y | Y | - |  |
| `mistralai/mistral-medium-3-5` | 262k | 176 | 878 | - | Y | Y | Y | Y |  |
| `mistralai/mistral-medium-3.1` | 131k | 46.8 | 234 | 4.7 | Y | Y | Y | - |  |
| `mistralai/mistral-nemo` † | 131k | 2.1 | 3.5 | - | some | Y | - | - |  |
| `mistralai/mistral-saba` | 32k | 23.4 | 70.2 | 2.3 | Y | Y | - | - |  |
| `mistralai/mistral-small-24b-instruct-2501` † | 32k | 5.9 | 9.4 | - | some | Y | - | - |  |
| `mistralai/mistral-small-2603` | 262k | 17.6 | 70.2 | 1.8 | Y | Y | Y | Y |  |
| `mistralai/mistral-small-3.1-24b-instruct` † | 131k | 3.5 | 12.9 | 1.8 | some | Y | Y | - |  |
| `mistralai/mistral-small-3.2-24b-instruct` | 131k | 7.0 | 21.1 | 3.5 | Y | Y | Y | - |  |
| `mistralai/mixtral-8x22b-instruct` | 65k | 234 | 702 | 23.4 | Y | Y | - | - |  |
| `mistralai/voxtral-small-24b-2507` | 32k | 11.7 | 35.1 | 1.2 | Y | Y | - | - |  |
| `moonshotai/kimi-k2` | 131k | 64.4 | 258 | - | Y | some | - | - |  |
| `moonshotai/kimi-k2-0905` | 262k | 45.7 | 222 | 22.8 | Y | Y | - | - |  |
| `moonshotai/kimi-k2-thinking` † | 262k | 93.7 | 140 | - | some | Y | - | Y |  |
| `moonshotai/kimi-k2.5` | 262k | 46.8 | 222 | 10.5 | Y | Y | Y | Y |  |
| `moonshotai/kimi-k2.6` | 262k | 54.4 | 287 | 11.4 | Y | Y | Y | Y |  |
| `moonshotai/kimi-k2.7-code` | 256k | 83.4 | 351 | 16.7 | Y | Y | Y | Y |  |
| `moonshotai/kimi-k3` | 1048k | 176 | 1330 | 33.9 | Y | Y | Y | Y |  |
| `morph/morph-v3-fast` | 81k | 93.7 | 140 | - | - | - | - | - |  |
| `morph/morph-v3-large` | 262k | 105 | 222 | - | - | Y | - | - |  |
| `nex-agi/nex-n2.5-mini` | 262k | 2.9 | 11.7 | 0.29 | - | Y | Y | Y |  |
| `nex-agi/nex-n2.5-pro` | 262k | 8.8 | 29.3 | 1.8 | Y | Y | Y | Y |  |
| `nousresearch/hermes-3-llama-3.1-405b` | 131k | 117 | 117 | - | - | Y | - | - |  |
| `nousresearch/hermes-3-llama-3.1-70b` | 65k | 35.1 | 35.1 | - | - | Y | - | - |  |
| `nousresearch/hermes-4-405b` | 131k | 117 | 351 | - | - | - | - | Y |  |
| `nvidia/nemotron-3-nano-30b-a3b` | 262k | 5.9 | 23.4 | 2.9 | Y | some | - | Y |  |
| `nvidia/nemotron-3-ultra-550b-a55b` | 262k | 58.5 | 258 | 11.7 | Y | Y | - | Y |  |
| `nvidia/nemotron-3.5-lightning` † | 262k | 4.6 | 21.1 | 2.3 | some | Y | - | Y |  |
| `openai/chatgpt-4o-latest` | 128k | 1375 | 4125 | - | Y | - | Y | - |  |
| `openai/gpt-3.5-turbo` | 16k | 58.5 | 176 | - | Y | Y | - | - |  |
| `openai/gpt-3.5-turbo-0613` | 4k | 117 | 234 | - | Y | Y | - | - |  |
| `openai/gpt-3.5-turbo-16k` | 16k | 351 | 468 | - | Y | Y | - | - |  |
| `openai/gpt-4` | 8k | 3512 | 7024 | - | Y | some | - | - |  |
| `openai/gpt-4-turbo` | 128k | 1171 | 3512 | - | Y | Y | Y | - |  |
| `openai/gpt-4.1` | 1047k | 234 | 937 | 58.5 | Y | Y | Y | - |  |
| `openai/gpt-4.1-mini` | 1047k | 46.8 | 187 | 11.7 | Y | Y | Y | - |  |
| `openai/gpt-4.1-nano` | 1047k | 11.7 | 46.8 | 3.5 | Y | Y | Y | - |  |
| `openai/gpt-4o` | 128k | 293 | 1171 | - | Y | Y | Y | - |  |
| `openai/gpt-4o-2024-05-13` | 128k | 585 | 1756 | - | Y | Y | Y | - |  |
| `openai/gpt-4o-2024-08-06` | 128k | 293 | 1171 | 146 | Y | Y | Y | - |  |
| `openai/gpt-4o-2024-11-20` | 128k | 293 | 1171 | 146 | Y | Y | Y | - |  |
| `openai/gpt-4o-mini` † | 128k | 17.6 | 70.2 | 8.8 | some | Y | Y | - |  |
| `openai/gpt-4o-mini-2024-07-18` | 128k | 17.6 | 70.2 | 8.8 | Y | Y | Y | - |  |
| `openai/gpt-5` | 400k | 146 | 1171 | 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5-mini` | 400k | 14.6 | 117 | 1.5 | Y | Y | Y | Y |  |
| `openai/gpt-5-nano` | 400k | 2.9 | 23.4 | 0.29 | Y | Y | Y | Y |  |
| `openai/gpt-5-pro` | 400k | 1756 | 14048 | - | Y | Y | Y | Y |  |
| `openai/gpt-5.1` | 400k | 73.2 | 585 | 7.3 | Y | Y | Y | Y |  |
| `openai/gpt-5.1-codex` | 400k | 146 | 1171 | 15.2 | Y | Y | Y | Y |  |
| `openai/gpt-5.1-codex-max` | 400k | 146 | 1171 | 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5.1-codex-mini` | 400k | 29.3 | 234 | 3.5 | Y | Y | Y | Y |  |
| `openai/gpt-5.2` † | 400k | 99.3 | 790 | - | some | some | Y | some |  |
| `openai/gpt-5.2-chat` | 400k | 102 | 819 | 10.2 | Y | Y | Y | Y |  |
| `openai/gpt-5.2-codex` | 400k | 205 | 1639 | 20.5 | Y | Y | Y | Y |  |
| `openai/gpt-5.2-pro` | 400k | 2458 | 19667 | - | Y | Y | Y | Y |  |
| `openai/gpt-5.3-chat` | 128k | 481 | 3850 | - | Y | - | Y | - |  |
| `openai/gpt-5.3-codex` | 400k | 205 | 1639 | 20.5 | Y | Y | Y | Y |  |
| `openai/gpt-5.4` | 1050k | 146 | 878 | 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5.4-mini` | 400k | 43.9 | 263 | 4.4 | Y | Y | Y | Y |  |
| `openai/gpt-5.4-nano` | 400k | 11.7 | 73.2 | 1.2 | Y | Y | Y | Y |  |
| `openai/gpt-5.4-pro` | 1050k | 1756 | 10536 | - | Y | Y | Y | Y |  |
| `openai/gpt-5.5` | 1050k | 293 | 1756 | 29.3 | Y | Y | Y | Y |  |
| `openai/gpt-5.5-pro` | 1050k | 1756 | 10536 | - | Y | Y | Y | Y |  |
| `openai/gpt-5.6-luna` | 1050k | 11.7 | 70.2 | 1.2 / w 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-luna-pro` | 1050k | 11.7 | 70.2 | 1.2 / w 14.6 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-sol` | 1050k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-sol-pro` | 1050k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-terra` | 1050k | 117 | 702 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-5.6-terra-pro` | 1050k | 117 | 702 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-6-astra` | 1050k | 585 | 2927 | 58.5 / w 732 | Y | Y | Y | Y |  |
| `openai/gpt-6-astra-pro` | 1050k | 585 | 2927 | 58.5 / w 732 | Y | Y | Y | Y |  |
| `openai/gpt-6-luna` | 1050k | 5.9 | 29.3 | 0.59 / w 7.3 | Y | Y | Y | Y |  |
| `openai/gpt-6-luna-pro` | 1050k | 5.9 | 29.3 | 0.59 / w 7.3 | Y | Y | Y | Y |  |
| `openai/gpt-6-sol` | 1050k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-6-sol-pro` | 1050k | 117 | 585 | 11.7 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-6.1-sol` | 1050k | 117 | 585 | 5.9 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-6.1-sol-pro` | 1050k | 117 | 585 | 5.9 / w 146 | Y | Y | Y | Y |  |
| `openai/gpt-oss-120b` | 131k | 4.7 | 16.4 | 4.7 | Y | Y | - | Y | Y |
| `openai/gpt-oss-20b` | 131k | 2.1 | 10.5 | 1.1 | Y | Y | - | Y | Y |
| `openai/gpt-oss-safeguard-20b` | 131k | 8.8 | 35.1 | 4.4 | Y | Y | - | Y |  |
| `openai/o1` | 200k | 1756 | 7024 | 878 | Y | Y | Y | Y |  |
| `openai/o1-pro` | 200k | 17560 | 70241 | - | - | Y | Y | Y |  |
| `openai/o3` | 200k | 234 | 937 | 58.5 | Y | Y | Y | Y |  |
| `openai/o3-mini` | 200k | 129 | 515 | 64.4 | Y | Y | - | Y |  |
| `openai/o3-mini-high` | 200k | 129 | 515 | 64.4 | Y | Y | - | Y |  |
| `openai/o3-pro` | 200k | 2341 | 9365 | - | Y | Y | Y | Y |  |
| `openai/o4-mini` | 200k | 129 | 515 | 32.2 | Y | Y | Y | Y |  |
| `openai/o4-mini-high` | 200k | 129 | 515 | 32.2 | Y | Y | Y | Y |  |
| `perceptron/perceptron-mk1` | 32k | 17.6 | 176 | - | - | Y | Y | Y |  |
| `perceptron/perceptron-mk1.5` | 36k | 17.6 | 176 | - | Y | Y | Y | Y |  |
| `perplexity/sonar` | 127k | 117 | 117 | - | - | - | Y | - |  |
| `perplexity/sonar-deep-research` | 128k | 234 | 937 | - | - | - | - | Y |  |
| `perplexity/sonar-pro` | 200k | 351 | 1756 | - | - | - | Y | - |  |
| `perplexity/sonar-pro-search` | 200k | 351 | 1756 | - | - | Y | Y | Y |  |
| `perplexity/sonar-reasoning-pro` | 128k | 234 | 937 | - | - | - | Y | Y |  |
| `poolside/laguna-s-2.1` | 1048k | 10.5 | 21.1 | 1.1 | Y | - | - | Y |  |
| `poolside/laguna-xs-2.1` | 262k | 7.0 | 14.0 | 3.5 | Y | - | - | Y |  |
| `qwen/qwen-2.5-72b-instruct` | 32k | 42.1 | 46.8 | - | Y | Y | - | - |  |
| `qwen/qwen-2.5-7b-instruct` | 32k | 4.7 | 11.7 | 4.7 | Y | some | - | - |  |
| `qwen/qwen-2.5-coder-32b-instruct` | 32k | 3.5 | 12.9 | 1.8 | - | Y | - | - |  |
| `qwen/qwen-plus` | 1000k | 30.4 | 91.3 | 6.1 / w 38.0 | Y | Y | - | - |  |
| `qwen/qwen-plus-2025-07-28` | 1000k | 30.4 | 91.3 | - | Y | Y | - | - |  |
| `qwen/qwen2.5-vl-72b-instruct` | 32k | 17.6 | 70.2 | 8.8 | - | Y | Y | - |  |
| `qwen/qwen3-14b` | 40k | 5.9 | 25.8 | 2.9 | Y | Y | - | Y |  |
| `qwen/qwen3-235b-a22b` † | 40k | 23.4 | 70.2 | - | some | some | - | Y | Y |
| `qwen/qwen3-235b-a22b-2507` | 262k | 11.7 | 11.7 | 11.7 | Y | Y | - | - |  |
| `qwen/qwen3-235b-a22b-thinking-2507` † | 262k | 11.7 | 11.7 | 11.7 | some | Y | - | Y |  |
| `qwen/qwen3-30b-a3b` | 40k | 7.0 | 25.8 | 3.5 | Y | Y | - | Y |  |
| `qwen/qwen3-30b-a3b-instruct-2507` | 128k | 5.6 | 22.6 | - | Y | Y | - | - |  |
| `qwen/qwen3-30b-a3b-thinking-2507` | 262k | 10.5 | 35.1 | - | Y | Y | - | Y |  |
| `qwen/qwen3-32b` | 131k | 8.2 | 23.4 | 5.3 | Y | Y | - | Y |  |
| `qwen/qwen3-8b` | 40k | 23.4 | 23.4 | 11.7 | Y | Y | - | Y |  |
| `qwen/qwen3-coder` | 262k | 25.8 | 111 | - | Y | Y | - | some |  |
| `qwen/qwen3-coder-30b-a3b-instruct` | 160k | 8.2 | 31.6 | - | Y | some | - | - |  |
| `qwen/qwen3-coder-flash` | 1000k | 22.8 | 114 | 4.6 / w 28.5 | Y | - | - | - |  |
| `qwen/qwen3-coder-next` | 262k | 14.0 | 87.8 | 7.0 | Y | Y | - | - |  |
| `qwen/qwen3-coder-plus` | 1000k | 76.1 | 380 | 15.2 / w 95.1 | Y | Y | - | - |  |
| `qwen/qwen3-max` | 262k | 91.3 | 457 | 18.3 / w 114 | Y | Y | - | - |  |
| `qwen/qwen3-max-thinking` | 262k | 91.3 | 457 | - | Y | Y | - | Y |  |
| `qwen/qwen3-next-80b-a3b-instruct` | 131k | 11.4 | 91.3 | - | Y | some | - | - |  |
| `qwen/qwen3-next-80b-a3b-thinking` | 262k | 35.1 | 35.1 | - | Y | some | - | Y |  |
| `qwen/qwen3-vl-235b-a22b-instruct` | 262k | 23.4 | 103 | 12.9 | Y | Y | Y | - |  |
| `qwen/qwen3-vl-235b-a22b-thinking` | 262k | 52.7 | 410 | - | Y | Y | Y | Y |  |
| `qwen/qwen3-vl-30b-a3b-instruct` | 131k | 10.5 | 46.8 | - | Y | Y | Y | - |  |
| `qwen/qwen3-vl-30b-a3b-thinking` | 131k | 23.4 | 117 | - | Y | Y | Y | Y |  |
| `qwen/qwen3-vl-32b-instruct` | 131k | 12.2 | 48.7 | - | Y | Y | Y | - |  |
| `qwen/qwen3-vl-8b-instruct` | 131k | 13.7 | 53.3 | - | Y | Y | Y | - |  |
| `qwen/qwen3-vl-8b-thinking` | 131k | 21.1 | 246 | - | Y | Y | Y | Y |  |
| `qwen/qwen3.5-122b-a10b` † | 262k | 30.4 | 244 | - | some | Y | Y | Y |  |
| `qwen/qwen3.5-27b` | 262k | 22.8 | 183 | - | Y | Y | Y | Y |  |
| `qwen/qwen3.5-35b-a3b` | 262k | 9.4 | 87.8 | 4.7 | Y | Y | Y | Y | Y |
| `qwen/qwen3.5-397b-a17b` | 262k | 45.7 | 274 | - | Y | some | Y | Y |  |
| `qwen/qwen3.5-9b` † | 32k | 1.7 | 5.0 | - | some | some | Y | some |  |
| `qwen/qwen3.5-flash-02-23` | 1000k | 7.6 | 30.4 | - | Y | Y | Y | Y |  |
| `qwen/qwen3.5-plus-02-15` | 1000k | 30.4 | 183 | - | Y | Y | Y | Y |  |
| `qwen/qwen3.5-plus-20260420` | 1000k | 35.1 | 211 | - / w 43.9 | Y | Y | Y | Y |  |
| `qwen/qwen3.6-27b` | 262k | 35.1 | 234 | 3.5 | Y | Y | Y | Y |  |
| `qwen/qwen3.6-35b-a3b` | 262k | 5.9 | 81.9 | 2.9 | Y | Y | Y | Y | Y |
| `qwen/qwen3.6-flash` | 1000k | 22.0 | 132 | - / w 27.4 | Y | Y | Y | Y |  |
| `qwen/qwen3.6-max-preview` | 262k | 120 | 721 | - / w 150 | Y | Y | - | Y |  |
| `qwen/qwen3.6-plus` | 1000k | 38.0 | 228 | - / w 47.6 | Y | Y | Y | Y |  |
| `qwen/qwen3.7-max` | 1000k | 173 | 518 | 34.5 / w 216 | Y | Y | - | Y |  |
| `qwen/qwen3.8-27b` | 262k | 10.5 | 220 | 10.0 | Y | Y | Y | Y |  |
| `qwen/qwen3.8-flash` | 1000k | 17.6 | 55.0 | 1.9 / w 23.4 | Y | Y | Y | Y |  |
| `qwen/qwen3.8-max` | 1000k | 234 | 702 | 29.3 / w 293 | Y | Y | Y | Y |  |
| `qwen/qwen3.8-max-prime` | 1000k | 468 | 1405 | 58.5 | Y | Y | Y | Y |  |
| `qwen/qwen3.8-omni-flash` | 1000k | 17.6 | 55.0 | 1.9 | Y | Y | Y | Y |  |
| `rekaai/reka-edge` | 16k | 11.7 | 11.7 | - | Y | Y | Y | - |  |
| `relace/relace-apply-3` | 256k | 99.5 | 146 | - | - | - | - | - |  |
| `relace/relace-search` | 256k | 117 | 351 | - | Y | - | - | - |  |
| `sakana/fugu-max` | 1000k | 234 | 702 | 29.3 | Y | Y | Y | Y |  |
| `sakana/fugu-ultra` | 1000k | 585 | 3512 | 58.5 | Y | Y | Y | Y |  |
| `sakana/fugu-ultra-v2` | 1000k | 585 | 3512 | 58.5 | Y | Y | Y | Y |  |
| `sao10k/l3-lunaris-8b` | 8k | 4.7 | 5.9 | - | - | some | - | - |  |
| `sao10k/l3.1-euryale-70b` † | 32k | 76.1 | 87.8 | - | some | Y | - | - |  |
| `sao10k/l3.3-euryale-70b` | 131k | 76.1 | 87.8 | - | - | Y | - | - |  |
| `sber/gigachat` | 32k | 91.0 | 91.0 | - | - | - | - | - | Y |
| `sber/gigachat-2` | 128k | 91.0 | 91.0 | - | - | - | - | - | Y |
| `sber/gigachat-2-max` | 131k | 797 | 797 | - | - | - | Y | - | Y |
| `sber/gigachat-2-pro` | 128k | 700 | 700 | - | - | - | Y | - | Y |
| `sber/gigachat-max` | 128k | 910 | 910 | - | - | - | Y | - | Y |
| `sber/gigachat-plus` | 32k | 280 | 280 | - | - | - | - | - | Y |
| `sber/gigachat-pro` | 32k | 700 | 700 | - | - | - | Y | - | Y |
| `stepfun/step-3.5-flash` | 262k | 10.5 | 35.1 | 2.3 | Y | - | - | Y |  |
| `stepfun/step-3.7-flash` | 262k | 18.7 | 108 | 3.7 | Y | some | Y | Y |  |
| `tencent/hunyuan-a13b-instruct` | 131k | 16.4 | 66.7 | - | - | Y | - | Y |  |
| `tencent/hy-mt2-1.8b` | 8k | 5.2 | 20.7 | - | - | - | - | - |  |
| `tencent/hy-mt2-30b-a3b` | 32k | 8.2 | 32.8 | 3.5 | - | Y | - | - |  |
| `tencent/hy-mt2-7b` | 8k | 8.7 | 34.5 | - | - | Y | - | - |  |
| `tencent/hy3` | 262k | 12.3 | 50.9 | 3.1 | Y | Y | - | Y |  |
| `tencent/hy4-preview` | 1048k | 87.4 | 263 | 4.2 | Y | Y | - | Y |  |
| `thedrummer/cydonia-24b-v4.1` | 131k | 35.1 | 58.5 | - | - | Y | - | - |  |
| `thedrummer/skyfall-36b-v2` | 32k | 64.4 | 93.7 | 29.3 | - | Y | - | - |  |
| `thedrummer/unslopnemo-12b` | 32k | 46.8 | 46.8 | - | Y | Y | - | - |  |
| `thinkingmachines/inkling` | 524k | 111 | 474 | 18.7 | Y | - | Y | Y |  |
| `undi95/remm-slerp-l2-13b` | 6k | 41.0 | 76.1 | - | - | Y | - | - |  |
| `upstage/solar-mini4` | 524k | 5.9 | 23.4 | 0.59 | Y | Y | - | Y |  |
| `upstage/solar-pro-3` | 131k | 17.6 | 70.2 | 1.8 | Y | Y | - | Y |  |
| `writer/palmyra-x5` | 1040k | 70.2 | 702 | - | - | - | - | - |  |
| `x-ai/grok-4.20` | 2000k | 146 | 293 | 23.4 | Y | Y | Y | Y |  |
| `x-ai/grok-4.20-multi-agent` | 2000k | 146 | 293 | 23.4 | - | Y | Y | Y |  |
| `x-ai/grok-4.3` | 1000k | 146 | 293 | 23.4 | Y | Y | Y | Y |  |
| `x-ai/grok-4.5` | 500k | 234 | 702 | 35.1 | Y | Y | Y | Y |  |
| `x-ai/grok-4.6` | 500k | 234 | 702 | 58.5 | Y | Y | Y | Y |  |
| `x-ai/grok-4.7` | 500k | 234 | 702 | 58.5 | Y | Y | Y | Y |  |
| `x-ai/grok-build-0.1` | 256k | 117 | 234 | 23.4 | Y | Y | Y | Y |  |
| `xiaomi/mimo-v2.5` | 1050k | 13.9 | 27.9 | 0.30 | Y | some | Y | Y |  |
| `xiaomi/mimo-v2.5-pro` † | 1050k | 35.6 | 71.3 | 0.33 | some | some | - | Y |  |
| `xiaomi/mimo-v2.6-flash` | 1048k | 12.9 | 32.8 | 10.5 | Y | Y | Y | Y |  |
| `xiaomi/mimo-v2.6-pro` | 1048k | 50.3 | 102 | 0.42 | Y | Y | Y | Y |  |
| `xiaomi/mimo-v2.6-pro-ultraspeed` | 1048k | 509 | 1018 | 4.2 | Y | Y | Y | Y |  |
| `yandex/aliceai-llm` | 32k | 700 | 1680 | - | - | - | - | - | Y |
| `yandex/yandexgpt-5-lite` | 32k | 280 | 280 | - | - | - | - | - | Y |
| `yandex/yandexgpt-5-pro` | 32k | 1680 | 1680 | - | - | - | - | - | Y |
| `yandex/yandexgpt-5.1-pro` | 32k | 1120 | 1120 | - | - | - | - | - | Y |
| `z-ai/glm-4.5` | 131k | 41.0 | 181 | 20.5 | Y | Y | - | Y |  |
| `z-ai/glm-4.5-air` | 131k | 17.6 | 70.2 | 8.8 | Y | Y | - | Y |  |
| `z-ai/glm-4.5v` | 65k | 70.2 | 211 | 12.9 | Y | - | Y | Y |  |
| `z-ai/glm-4.6` | 202k | 41.0 | 200 | - | Y | Y | - | Y |  |
| `z-ai/glm-4.6v` | 131k | 35.1 | 105 | 17.6 | Y | Y | Y | Y |  |
| `z-ai/glm-4.7` | 202k | 44.5 | 204 | - | Y | some | Y | Y |  |
| `z-ai/glm-4.7-flash` | 202k | 7.0 | 46.8 | 1.2 | Y | Y | Y | Y |  |
| `z-ai/glm-5` | 202k | 70.2 | 225 | 14.0 | Y | Y | - | Y |  |
| `z-ai/glm-5-turbo` | 202k | 140 | 468 | 28.1 | Y | - | - | Y |  |
| `z-ai/glm-5.1` | 200k | 113 | 355 | 21.0 | Y | Y | - | Y |  |
| `z-ai/glm-5.2` | 1000k | 10.0 | 258 | 8.8 | Y | Y | - | Y |  |
| `z-ai/glm-5.3` | 1048k | 49.2 | 155 | 9.1 | Y | some | - | Y |  |
| `z-ai/glm-5.3-flash` | 1048k | 8.8 | 29.3 | 1.8 | Y | Y | Y | Y |  |
| `z-ai/glm-5.3-flashx` | 1048k | 43.3 | 146 | 10.5 | Y | - | Y | Y |  |
| `z-ai/glm-5.3-prime` | 1000k | 328 | 1030 | 65.6 | Y | - | - | Y |  |
| `z-ai/glm-5v-turbo` | 202k | 140 | 468 | 28.1 | Y | - | Y | Y |  |

## Sources

[intro]: https://polza.ai/docs/api-reference/introduction.md
[chat-guide]: https://polza.ai/docs/gaidy/chat-completions.md
[chat-ref]: https://polza.ai/docs/api-reference/chat/completions.md
[openapi]: https://polza.ai/api/openapi.json
[tools]: https://polza.ai/docs/gaidy/tool-calling.md
[structured]: https://polza.ai/docs/gaidy/structured-output.md
[plugins]: https://polza.ai/docs/gaidy/plugins.md
[websearch]: https://polza.ai/docs/gaidy/web-search.md
[caching]: https://polza.ai/docs/osobennosti/caching.md
[usage]: https://polza.ai/docs/osobennosti/usage.md
[aliases]: https://polza.ai/docs/osobennosti/aliases.md
[provider]: https://polza.ai/docs/gaidy/provider-selection.md
[reasoning]: https://polza.ai/docs/osobennosti/reasoning-tokens.md
[models-guide]: https://polza.ai/docs/gaidy/models.md
[models-ref]: https://polza.ai/docs/api-reference/models/list.md
[catalog]: https://polza.ai/api/v1/models?type=chat&include_providers=true
[catalog-emb]: https://polza.ai/api/v1/models?type=embedding&include_providers=true
[catalog-img]: https://polza.ai/api/v1/models?type=image&include_providers=true
[catalog-cls]: https://polza.ai/api/v1/models?type=classification&include_providers=true
[server-tools]: https://polza.ai/api/v1/server-tools
[plugins-live]: https://polza.ai/api/v2/plugins
[emb-ref]: https://polza.ai/docs/api-reference/embeddings/create.md
[langchain]: https://polza.ai/docs/integracii/langchain.md
[rag]: https://polza.ai/docs/gaidy/rag.md
[media-input]: https://polza.ai/docs/gaidy/media-input.md
[img-ref]: https://polza.ai/docs/api-reference/images/generations.md
[media-ref]: https://polza.ai/docs/api-reference/media/create.md
[gpt-image]: https://polza.ai/docs/gaidy/gpt-image-1-5.md
[responses]: https://polza.ai/docs/api-reference/responses/create.md
[privacy]: https://polza.ai/docs/osobennosti/privacy.md
[faq]: https://polza.ai/docs/glavnoe/faq.md
[key]: https://polza.ai/docs/api-reference/other/key.md
[balance]: https://polza.ai/docs/api-reference/other/balance-v2.md

- `[intro]` API introduction: <https://polza.ai/docs/api-reference/introduction.md>
- `[chat-guide]` / `[chat-ref]` Chat Completions guide and reference: <https://polza.ai/docs/gaidy/chat-completions.md>, <https://polza.ai/docs/api-reference/chat/completions.md>
- `[openapi]` OpenAPI spec: <https://polza.ai/api/openapi.json>
- `[tools]` Tool calling: <https://polza.ai/docs/gaidy/tool-calling.md>
- `[structured]` Structured output: <https://polza.ai/docs/gaidy/structured-output.md>
- `[plugins]` / `[plugins-live]` Plugins guide and live list: <https://polza.ai/docs/gaidy/plugins.md>, <https://polza.ai/api/v2/plugins>
- `[websearch]` Web search: <https://polza.ai/docs/gaidy/web-search.md>
- `[server-tools]` Server tools (live): <https://polza.ai/api/v1/server-tools>
- `[caching]` Caching: <https://polza.ai/docs/osobennosti/caching.md>
- `[usage]` Usage accounting: <https://polza.ai/docs/osobennosti/usage.md>
- `[aliases]` / `[provider]` Aliases and provider selection: <https://polza.ai/docs/osobennosti/aliases.md>, <https://polza.ai/docs/gaidy/provider-selection.md>
- `[reasoning]` Reasoning tokens: <https://polza.ai/docs/osobennosti/reasoning-tokens.md>
- `[models-guide]` / `[models-ref]` Models guide and reference: <https://polza.ai/docs/gaidy/models.md>, <https://polza.ai/docs/api-reference/models/list.md>
- `[catalog]`, `[catalog-emb]`, `[catalog-img]`, `[catalog-cls]` Live catalog: `https://polza.ai/api/v1/models?type=chat|embedding|image|classification&include_providers=true`
- `[emb-ref]` Embeddings: <https://polza.ai/docs/api-reference/embeddings/create.md>
- `[langchain]` / `[rag]` LangChain and RAG guides (embedding dims, model advice): <https://polza.ai/docs/integracii/langchain.md>, <https://polza.ai/docs/gaidy/rag.md>
- `[media-input]` Media input (vision): <https://polza.ai/docs/gaidy/media-input.md>
- `[img-ref]` / `[media-ref]` / `[gpt-image]` Images, Media API, GPT Image 1.5: <https://polza.ai/docs/api-reference/images/generations.md>, <https://polza.ai/docs/api-reference/media/create.md>, <https://polza.ai/docs/gaidy/gpt-image-1-5.md>
- `[responses]` Responses API: <https://polza.ai/docs/api-reference/responses/create.md>
- `[privacy]` / `[faq]` Privacy and FAQ: <https://polza.ai/docs/osobennosti/privacy.md>, <https://polza.ai/docs/glavnoe/faq.md>
- `[key]` / `[balance]` Key limits and balance: <https://polza.ai/docs/api-reference/other/key.md>, <https://polza.ai/docs/api-reference/other/balance-v2.md>
