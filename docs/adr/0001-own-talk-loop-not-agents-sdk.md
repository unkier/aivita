# Own talk loop instead of the OpenAI Agents SDK

The talk core runs its own model-and-tool loop on the plain `openai` client, through the same `llm/` interface the cheap and deep Tiers and the LLMDecider use. It does not use the OpenAI Agents SDK, even though the handoff suggested it and [OpenAI Agents SDK fit](https://github.com/unkier/aivita/issues/5) found that it fits.

The SDK's two strongest reasons fell away:

- tinyaisense's `VoiceAgent` won't be reused (M3 gets a thin adapter on `say.open/append/close`).
- The talk LLM gets no hub MCP tools.

The plain `tinyaisense` package doesn't pull the SDK in; only its `[agents]` extra does.

The SDK would have cost:

- 38 packages.
- A breaking-capable minor release every 2–3 weeks.
- Four polza workarounds: reasoning via `extra_body`, a cache-marking transport, cost via `raw_usage`, and tracing turned off.
- Lost `cost_rub` when a run raises.

The own loop costs about 300–400 lines.

## Consequences

- Nothing outside `llm/` may import `openai-agents`. Re-adding it means reopening this ADR.
- Tests fake the LLM at the `llm/` interface (`FakeLLM`), not with the SDK's `ScriptedModel`.
- Tool schemas come from `openai.pydantic_function_tool`, not `@function_tool`.
