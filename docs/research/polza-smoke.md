# polza.ai + Jev smoke run

Task ticket [#7](https://github.com/unkier/aivita/issues/7) (handoff §17 step 2). Run on 2026-10-03 from Dmitrii's home machine with real, billed calls. Script: [`scripts/polza_smoke.py`](../../scripts/polza_smoke.py) (`uv run --script`). Raw results: [`polza-smoke.json`](polza-smoke.json) (main run), [`polza-smoke-rerun.json`](polza-smoke-rerun.json) (fixed checks), [`polza-smoke-images.json`](polza-smoke-images.json).

It checks the claims marked **verify** in [polza.ai API facts](https://github.com/unkier/aivita/blob/research/polza-api/docs/research/polza-api.md) (§14), [OpenAI Agents SDK fit](https://github.com/unkier/aivita/blob/research/openai-agents-sdk/docs/research/openai-agents-sdk.md) and [Jev /systemone contract](https://github.com/unkier/aivita/blob/research/jev-systemone/docs/research/jev-systemone.md).

**Spend: 17.6 ₽ in total** (balance 803.41 → 785.79 ₽), under the 100 ₽ cap. That covers a trial run, the main run (12.3 ₽), reruns and two images.

Every latency below is **one sample**. Providers vary a lot from call to call: the same `gpt-5.6-luna` call took 1.2 s to first token on OpenAI and 11.2 s on Azure.

## Verdicts

| Claim | Verdict | Detail |
|---|---|---|
| Chat in RU and EN on talk and cheap candidates | **Works** | All 6 models answered. Latency is in the table below. |
| "Reply in the person's language" via the prompt | **Not reliable** | With a Russian system prompt, **Sonnet 5 and DeepSeek V4 Flash answered an English message in Russian**. Luna, Gemini 3.8 Flash, GPT-5 nano and Gemini 3.5 Flash-Lite answered in English. |
| Strict `json_schema` | **Works everywhere tested** | Valid on DeepSeek V4 Flash, GPT-5 nano, Gemini 3.5 Flash-Lite, Claude Haiku 4.5 (`anthropic`) and Sonnet 5. **Claude honours `response_format`**, against polza's RAG guide. No code fences. |
| §14.3 default provider `drouter` lacks tools | **Not a problem in practice** | Haiku 4.5 with `tools` or `json_schema` on the default route worked, with or without `provider.require_parameters`. The streamed response said it was served by **Amazon Bedrock**, not drouter, at the same price either way. |
| §14.1 tool round trip, raw | **Works** | Luna, Sonnet 5 and Gemini 3.8 Flash, streamed and not. `finish_reason: "tool_calls"`. Streamed `delta.tool_calls` is OpenAI-shaped: the first delta has `id`, `type` and `function.name`, and later deltas append `function.arguments`. Gemini sends the arguments in one delta. |
| `usage.cost_rub` on every response | **Confirmed** | A float on every chat, embedding, Jev and image response. It was **never null** in the ~100 billed calls. |
| §14.4 `cost_rub` in the stream | **Always sent** | It arrives **even without `stream_options.include_usage`**. The usage chunk has **one choice, not `choices: []`** as the docs say, so don't detect it by empty choices. |
| §14.5 reasoning switches | **Confirmed** | On GPT-5 nano, `reasoning.effort=minimal` and the `@reasoning_effort=minimal` suffix gave **0** reasoning tokens. A top-level `reasoning_effort=minimal` gave 448, the same as the default (384 to 2304), so **it is ignored**. DeepSeek V4 Flash used 75-147 reasoning tokens whatever effort was asked. |
| §14.6 caching | **Mostly confirmed** | Automatic caching on a 7.9k-token prefix: **GPT-5 nano** (7808 cached) and **DeepSeek V4 Flash** (7680 cached). **Gemini 3.5 Flash-Lite cached nothing** on a 9.1k prefix (two calls, 2 s apart). **Claude caches only with `cache_control`**: Haiku without it had 0 cached; with it the first call wrote 9410 tokens (1.38 ₽) and the next read them (0.12 ₽ instead of 1.11 ₽). |
| §14.7 embeddings | **Confirmed** | `qwen3-embedding-8b` returns 4096 dims and `-4b` returns 2560. **`dimensions=1024` works on both**: the result is the full vector's first 1024 dims renormalised (cosine 0.9999, norm 1.0). RU↔EN pair cosine: 8b 0.82 (0.85 at 1024), 4b 0.88; unrelated 0.13-0.23. `bge-m3`: 1024 dims, but unrelated texts score 0.38-0.40. Cost is about 1 µ₽ per token. |
| §14.8 server tools | **Blocked for this account** | Every `polza:*` tool gets 400 "Серверные инструменты (polza:*) недоступны для организации" (server tools are not available for the organisation). That is an account switch. `plugins: [{id: "web"}]` works through OpenAI native search, with a `url_citation`, but cost **1.42 ₽** for one question (8.8k prompt tokens injected). **`web_search_options` is silently ignored**: the model answered from memory with stale data. Web research is M5, so it is out of scope here. |
| §14.9 `client.images.generate` | **Works, but it is async** | The answer is **HTTP 201 `{"requestId"}` at once**, not a synchronous result for up to 120 s. The openai SDK returns an empty `ImagesResponse` with `requestId` in `model_extra`. Poll `GET /v1/media/{id}`: done in 10-12 s, `data[0].url` on `s3.polza.ai`, `cost_rub` 1.4. `tongyi-mai/z-image` wants **`size: "1:1"`** (an aspect ratio); `1024x1024`, a top-level `aspect_ratio` or `input.aspect_ratio` all get 400. Images are M5. |
| Mid-stream error with HTTP 200 | **Not triggered** | No live sample. The handling in the Agents SDK research still applies. |

### Agents SDK through polza

| Check | Verdict | Detail |
|---|---|---|
| Tool round trip via `Runner.run_streamed` | **Works** on Luna, Gemini 3.8 Flash and Sonnet 5 | Events were `tool_called → tool_output → message_output_created`. |
| Streamed cost with `include_usage` + `preserve_raw_usage` | **Works** | `on_llm_end` gets `raw_usage.cost_rub` for each model call (2 per tool turn). |
| Claude `cache_control` via the transport rewrite | **Works** | Sonnet 5: the first call wrote 12,309 tokens (3.61 ₽), the second read 12,309 (0.30 ₽). The cache is **shared across clients**: the SDK's Haiku call hit the prefix that an earlier raw call had written. |
| `extra_body` reasoning changes `reasoning_tokens` | **Yes** | GPT-5 nano: `minimal` gave 0 tokens and 1.1 s; `high` gave 7680 tokens and 53 s. `ModelSettings.reasoning` (sent as top-level `reasoning_effort`) **is ignored**: 320-896 tokens, the default. |
| A `system` message mid-Conversation (layout B) | **Works** on Luna, Gemini 3.8 Flash, Sonnet 5, DeepSeek V4 Flash and Haiku 4.5 | The roles sent were `system, user, assistant, system, user`. No errors, and every model obeyed the injected rule. |
| A failed run loses its cost | **New gap** | GPT-5 nano at `high` effort with `max_tokens=4000` spent everything on reasoning. The SDK raised `ModelBehaviorError` (`finish_reason='length'`, no text) **before `on_llm_end`**, so `cost_rub` was lost. polza billed about 0.19 ₽ anyway. |

### Jev (`/systemone`)

| Question | Answer |
|---|---|
| Does `noul` return confidence or probabilities? | **No.** Only `{type, noul}`. |
| Score range, and is there a `legend`? | **0..levels−1** (e.g. 1.93 on 3 levels), plus `confidence`, `probabilities` keyed `"0"…` and a **`legend`**. |
| Can `cost_rub` be null? | Not seen: a float on all 5 billed calls. A 400 is not billed and carries no usage. Price confirmed: **17.56 ₽ per 1M input tokens** (1015 tokens = 0.0178 ₽). |
| Top-level `model` | `"jev-1.13.0"`, both for `typesafe/jev` and when pinned as `jev-1.13.0`. |
| EN vs RU question over a Russian `state` | **Same answers**: busy 0.96 vs 0.95, "natural now" 0.31 vs 0.31, absorbed 1.98 vs 1.93, reaction `neutral` (confidence 0.92 vs 0.91). |
| Choice order bias | Not visible on a clear case: reversed options also gave `neutral` (0.93). |
| Latency | **0.3-0.7 s** for a 9-question batch, from here. |
| Validation | **A score with 1 level is accepted and billed** (score 0, confidence 1). A `choice` without `criteria` gets 400 `BAD_REQUEST` with a zod-style `metadata.raw` and `detail: {error_type, message}`. `JevDecider` must validate before sending. |
| `state` as a JSON string vs an object | Both are accepted. |

## Chat latency and cost (streamed, `reasoning.effort=low`, ~60-tokens in)

| Model | Tier tried | First token RU / EN (s) | Total RU / EN (s) | ₽ per reply | Served by |
|---|---|---|---|---|---|
| `openai/gpt-5.6-luna` | talk | 1.2 / 1.0 | 1.8 / 1.5 | 0.007-0.009 | OpenAI (Azure on one call: 11 s) |
| `google/gemini-3.8-flash` | talk | 2.8 / 4.0 | 3.2 / 4.4 | 0.021-0.026 | Google |
| `anthropic/claude-sonnet-5` | talk | 1.5 / 1.8 | 2.6 / 2.6 | 0.087-0.089 | Claude Platform on AWS |
| `deepseek/deepseek-v4-flash` | cheap | 3.1 / 3.2 | 3.5 / 4.1 | 0.0014 | StreamLake, Venice |
| `openai/gpt-5-nano` | cheap | 2.8 / 12.7 | 3.2 / 13.0 | 0.011-0.015 | OpenAI |
| `google/gemini-3.5-flash-lite` | cheap | 1.4 / 1.6 | 1.8 / 1.8 | 0.011-0.016 | Google |

Notes:
- Luna with `provider.only: ["openai"]` was the same: 1.4 s to first token.
- A reasoning model at `low` effort still thinks before its first token: GPT-5 nano used 128-313 reasoning tokens and DeepSeek 127-139.
- Strict-JSON extraction latency, non-streamed: Gemini Flash-Lite 3.3 s, Sonnet 5 3.6 s, GPT-5 nano 4.4 s, DeepSeek Flash 6.6 s, Haiku (`anthropic`) 19.8 s on one call (1.7-3.7 s on other routes).
- Non-streamed responses carry **no `provider` field**; streamed chunks do.

## Consequences for later tickets

- **Reply language** (map fog): a prompt rule is not enough on Sonnet 5 and DeepSeek. `turn.lang` must be explicit, and the language instruction must be stated per Turn (volatile tail or a late system message, which every tested model obeyed).
- **Model per tier** (#8): use the latency, cost and caching numbers above. Claude without `cache_control` pays the full prefix on every Turn: 1.1 ₽ per Haiku call at 9.4k tokens. Gemini 3.5 Flash-Lite showed no caching.
- **Cost logging and budget** (map fog):
  - The key's `usage` field **does not include image spend**; the balance does. Reconcile against `GET /v2/balance`.
  - A run that raises can lose its `cost_rub`. `GET /v1/history/generations/{id}` returns `clientCost` for a generation.
  - Set `max_tokens` with room for reasoning.
- **Decider interface** (#19): Jev's shapes confirmed as researched. Validate score levels (≥ 2) before sending. RU and EN questions agree, so the question language can follow whatever is easiest to maintain.
- **Talk core** (#9): the SDK workarounds all hold live (reasoning via `extra_body`, transport `cache_control`, cost via `raw_usage`), and layout B is safe on every candidate. Wrap runs so that a `ModelBehaviorError` still records an unknown-cost call.
- **M5 (out of scope)**: `polza:*` server tools must be switched on for the organisation before Aivita can use them. Until then, `plugins: web` works at about 1.4 ₽ per search, and `web_search_options` does nothing. Image generation is async (`requestId` → poll).
