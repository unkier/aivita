# Aivita: implementation handoff

You are starting a new codebase. This file is everything you need; you will not have access to the conversations it came from. Read it fully before writing code. Where it says **verify**, check the real API before relying on it.

Owner: Dmitrii. Written 2026-10-03.

---

## 1. What we are building

**Aivita**, a companion: a digital life form that lives on Dmitrii's home machine, **remembers her people, dreams at night, and grows into herself over time**. Her heart is **intrinsic motivation**: she has drives and wishes of her own and acts proactively (asks someone a question, shows a picture, researches a topic she got curious about), not only when spoken to.

She is not a chatbot with memory bolted on. The test of every feature: does it make Aivita feel like a single, continuous being with an inner life?

## 2. Decisions already made (do not re-litigate)

| Topic | Decision |
|---|---|
| Name | The project, repo, Python package and the companion herself are all **aivita** (written "Aivita" in prose). Aivita is **female**: in Russian she always speaks of herself in feminine forms («я подумала», «я рада»), and her persona prompt and any self-references in code or docs use she/her. |
| Language | **Python** (3.11+; match tinyaisense's version if practical). |
| Repo | Aivita's **mind lives in its own repo, `aivita`**, separate from tinyaisense. It depends on the tinyaisense SDK. |
| Body | Dmitrii's existing hub project **[tinyaisense](https://github.com/unkier/tinyaisense)** is the body and senses: devices, firmware, audio, VAD, end-of-turn, RU/EN STT and TTS, an agent API (WebSocket), MCP tools, a Python SDK and a Simulator. **The hub has no LLM by design.** Aivita connects to it as its Agent. |
| Camera, screen, more devices | Dmitrii adds these to tinyaisense himself. **Do not design device contracts or firmware.** Consume whatever Kinds tinyaisense ships; until camera exists, treat "presence" as "someone spoke or pressed the button". |
| Interaction modes | **Voice** (through tinyaisense) **and a generic text chat**. Both are required. One mind behind both. |
| Languages | **Russian and English.** Reply in the language the person used. |
| LLM | **[polza.ai](https://polza.ai/)**, OpenAI-compatible. Base URL `https://polza.ai/api/v1`, key in env `POLZA_API_KEY`. Remote LLM is fine; local inference is not required. |
| Decisions | Closed-set choices (labels, scores, yes/no gates) go through a `Decider` interface. Default backend: **Jev** (TypeSafe AI) via polza.ai `POST /api/v1/systemone`, model `typesafe/jev`. Fallback backend: the cheap chat model with a strict JSON schema. Switchable in config. Jev is proprietary and new, so nothing outside `llm/decider*.py` may depend on it. Words (replies, thoughts, notes, dreams) stay on chat LLMs; the Python formulas in section 6.4 stay the final judge, and Jev only supplies their inputs. |
| Data | All state and memory live **locally** (SQLite + files on the home machine). Only text, events and deliberately chosen images go to the LLM. |
| People | **One Aivita, many people.** No limit. Each person is a separate entity in her mind with their own relationship, history and privacy wall. |
| Licence posture | Personal **open-source** project. Core dependencies must be permissive (MIT/Apache/BSD). GPL or non-commercial models only as optional plug-ins. Pick a licence (MIT or Apache-2.0) for the repo at the start. |
| First hardware | One **desk device facing the user** (camera, mic, speaker, display, once tinyaisense supports them). The hub can be the desk PC. |

## 3. Design principles

1. **Thinking is separate from speaking.** Thoughts are cheap and constant; acting on one is a separate, gated decision. Decisions are typed and probabilistic: every gate gets a probability and a confidence, and those numbers go into the decision trace.
2. **State math runs without an LLM.** Decay, drift, thresholds, scheduling are plain arithmetic in asyncio. The LLM is called only when someone talks or a threshold fires.
3. **Raw conversation is the source of truth.** Turns are append-only; summaries and vectors are indexes back to them.
4. **A subsystem is real only when it writes back.** Every action's outcome must flow back into memory and drives (research satisfies curiosity, an unanswered question keeps a concern open).
5. **Every person gets their own relationship.** What one person says is not repeated to another unless shareable.
6. **Imagined stays marked as imagined.** Dreams, inferences and guesses about people never silently become facts.
7. **Physiology runs itself.** Rest, dreaming and growth have no user knobs.
8. **Growth needs evidence.** Personality changes only after repeated independent observations, in small steps; human corrections win.
9. **Never claim an action you didn't take.** Check claimed actions ("I saved it", "I sent it") against the tool log.
10. **Keep it small.** No torch, no fine-tuning, no heavy frameworks in core.

## 4. Architecture

```
 tinyaisense hub (body)                     aivita (this repo: the mind)   
 ┌───────────────────────┐   agent API    ┌──────────────────────────────────────────┐
 │ devices, VAD, STT/TTS │◀──WebSocket──▶ │ body/      SDK session: events → triggers │
 │ speaker ID (later)    │   + MCP        │ channels/  voice adapter, web chat, CLI   │
 │ camera/screen (later) │                │ talk/      one conversation core           │
 └───────────────────────┘                │ mind/      drives, wishes, heartbeat,     │
                                          │            action scoring, gates          │
   browser ─── WebSocket ───────────────▶ │ memory/    SQLite + FTS5 + sqlite-vec     │
                                          │ people/    person nodes, privacy          │
                                          │ actions/   ask, research, show, note      │
                                          │ night/     consolidation, dreams          │
                                          │ llm/       polza client, tiers, decider,  │
                                          │            budget                         │
                                          └─────────────────┬────────────────────────┘
                                                            ▼
                                                  polza.ai (OpenAI-compatible)
```

### 4.1 Channels and the talk core

```
 tinyaisense utterance ─┐                                   ┌─▶ say.open/append/close on a device
 web chat message ──────┼─▶ channel adapter ─▶ talk core ─▶ ┼─▶ chat message (markdown, images)
 CLI line ──────────────┘   {person, channel,   (Agent,     └─▶ (Telegram later)
                             mode, text,         memory,
                             attachments}        drives)
```

- **One Agent, one memory, one persona** behind every channel. Something said by voice in the morning is known in chat at night.
- **One conversation history per person across channels.** Long-term memory is Aivita's own store.
- **Mode changes style, not mind.** Voice: short, speakable, no markdown or links. Text: may be longer, with links and images. Mode goes into the per-turn prompt.
- **Identity:** a text channel is signed in, so she knows the person for sure. Voice needs speaker ID later; until then, assume the desk owner or ask.
- **Proactive outreach picks a channel:** speak if the person is at a device, else write in chat, within the same contact budget.
- Text channels, in order: **local web chat** (FastAPI + WebSocket, with an "inner life" side panel), **CLI/REPL** for development, **Telegram** (aiogram 3) later.

### 4.2 Using tinyaisense (verify everything here against the repo)

Read in tinyaisense first: `README.md`, `CONTEXT.md`, `docs/adr/0001-0005`, `docs/protocol/agent.md`, and the SDK package. What the prior research found (at commit `442045a`, 2026-10-02):

- SDK entry point `tinyaisense.connect(...)`; the agent API is a WebSocket. **Only one agent Session at a time**, and Aivita holds it. `HubMcpServer` joins the same Session, so tools and voice share it.
- `say{address, text, then_listen}` speaks on a device and can open the mic right after: this is the proactive "ask a question" action. `say.open / append / close` streams LLM text with clause-level chunking.
- The hub picks the TTS voice from the text's script (Cyrillic → Russian). Utterances carry a language.
- Barge-in is handled on the device. The SDK's `VoiceAgent` adapter (built on the **OpenAI Agents SDK**) feeds "you were cut off; the human heard: …" back into the conversation; keep that behaviour.
- Button gestures, utterances, and device online/offline arrive as notifications. They become mind triggers.
- `[debug] record_dir` keeps per-Session WAVs and a `trace.jsonl`.
- **Simulator + fake speech plugin**: run integration tests with no hardware and no API calls.
- Device Kinds today: mic, speaker, button, LED. Camera and screen are coming.

Voice adapter plan: start with `VoiceAgent`, passing the shared Agent and a shared per-person `session=`. If its turn loop fights the shared core, write a thin adapter on `say.open/append/close` + utterance events and copy its interrupt handling.

### 4.3 LLM through polza.ai

| Need | How |
|---|---|
| Client | `AsyncOpenAI(base_url="https://polza.ai/api/v1", api_key=os.environ["POLZA_API_KEY"])` |
| Agents SDK | `OpenAIChatCompletionsModel(model=..., openai_client=client)` and **`set_tracing_disabled(True)`** (its default exporter sends traces to OpenAI). Verify tool-call round-trips work on the chosen model. |
| Model ids | `provider/model` form (e.g. `anthropic/...`, `openai/...`, `google/...`, `deepseek/...`, `qwen/...`). Use the models list endpoint. Keep ids in config, never hard-coded. |
| Tiers | **decide** (Jev: labels, scores, yes/no gates), **cheap** (short text jobs: System 1 reflexes, summaries, extraction, and the Decider fallback), **talk** (live conversation, low reasoning effort), **deep** (dreams, reflection, higher reasoning effort). |
| Decider (Jev) | `POST https://polza.ai/api/v1/systemone` with `{"model": "typesafe/jev", "state": <text or JSON>, "questions": {name: {"type": "noul"\|"choice"\|"score", "instructions": ..., "criteria": {...}}}}`. The response has `answers[name]` with `noul` / `choice` / `score`, `confidence` and `probabilities`, plus `usage.cost_rub`. Only input tokens are billed (plus ~280 overhead tokens per request), so batch several questions about the same state into one call. Questions can be in Russian. It is not the chat-completions endpoint, so use a small httpx client, not the openai SDK. **Verify** the request shape against https://polza.ai/docs/gaidy/jev with the smoke script (section 17). |
| Decider limits | No images; weak at arithmetic, date comparison and reading text too literally; susceptible to instructions hidden inside the state. So time, budgets and counting stay in Python, and web content in the state is never trusted to open a gate on its own. |
| Structured output | `response_format` `json_schema` strict, mapped to pydantic models (`Thought`, `Wish`, `MemoryItem`, `ActionChoice`). Strictness depends on the model; validate and retry once. |
| Caching | `cache_control: {type: "ephemeral"}` on the long system prefix (persona + person model). |
| Cost | Every response has `usage.cost_rub`. Log it per call and feed a **daily ruble budget** the mind manages itself. |
| Web research | Server-side `polza:web_search` tool or `web_search_options`. Fetch full pages with httpx + trafilatura when needed. |
| Embeddings | A multilingual model (e.g. `qwen/qwen3-embedding-4b`) so a Russian memory is found by an English query. Store the model id with each vector. |
| Images | `images/generations` for "show a picture" and dream illustrations. Vision input in chat for "look". |
| Fallbacks | Model alias syntax with fallbacks exists; verify in polza docs: https://polza.ai/docs/llms.txt |

**Decider interface** (`llm/decider.py`):

```python
class Q(BaseModel):            # one question
    kind: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, str] | None = None   # choice options or score levels

class A(BaseModel):            # one answer
    value: float | str         # probability (noul), option (choice), 0..1 (score)
    confidence: float
    probabilities: dict[str, float] | None = None

class Decider(Protocol):
    async def decide(self, state: str, questions: dict[str, Q], *, purpose: str,
                     correlation_id: str) -> dict[str, A]: ...

# JevDecider (polza /systemone), LLMDecider (cheap tier + json_schema), FakeDecider (tests)
```

**Confidence policy** (in `mind/`, not in the backends): confidence ≥ `hi` → use the answer; between `lo` and `hi` → also ask the LLMDecider and log both; below `lo` → choose the safe default (stay silent, keep the memory in quarantine, not shareable). Thresholds live in config; start with `hi = 0.8`, `lo = 0.5` and tune them from the trace. If Jev errors or is unreachable, fall back to `LLMDecider` automatically and log the fallback.

## 5. Data model (SQLite)

One database file in a data dir (`~/.aivita/` or configurable, `0700`). WAL mode. Atomic writes for any side files. Migrations from day one (plain numbered SQL files are enough). Every row that results from processing carries a **correlation id** linking it to the trigger that caused it.

Suggested tables (adjust, but keep the ideas):

- `person` id, display_name, aliases, kind (`met` | `heard_of`), relationship_stage, closeness, contact_budget (json), quiet_hours, language_pref, created_at.
- `person_edge` (a, b, relation, source_turn) e.g. "Anya is Dmitrii's sister".
- `channel_identity` (person_id, channel, external_id) maps a chat account / device / voice id to a person.
- `turn` append-only: id, person_id, channel, mode, role (`person` | `aivita`), text, lang, ts, interrupted_heard (nullable).
- `memory` id, person_id (about/with whom), text, kind (`fact` | `event` | `feeling` | `inferred` | `dream` | `research`), emotions (json name→0..10), importance, heat, recall_count, state (`active` | `fading` | `lost`), locked, **told_by**, **shareable** (default false), source_turn_ids, valid_from / superseded_by, created_at.
- `memory_fts` FTS5 over memory text with the **`trigram` tokenizer** (or Snowball-stem both sides; plain `unicode61` won't match «собака» to «собаки»).
- `memory_vec` sqlite-vec table, keyed by memory id.
- `memory_edge` Hebbian co-recall links with capped, decaying weights.
- `pending_memory` quarantine for self-generated items (thoughts, dreams, inferences) awaiting a label from one Decider `choice` question: `duplicate | merge | distinct | correction | continuation | new`, with the confidence stored next to it.
- `drive` (name, scope: global | person_id | topic, value, updated_at).
- `wish` id, content, kind (`curiosity | connection | care | expression | growth`), about (person/topic), sources (json ids), strength, expires_at, done_when, status (`wanted → in_progress → waiting → completed | abandoned`), history (json). A **concern** is a wish with kind `care` about someone's outcome; asking does not close it, only learning the outcome does.
- `thought` reservoir of unspoken thoughts: text, system (1|2), stimuli ids, saliency, last_accessed, ts.
- `decision` the decision trace: trigger, candidates with scores, chosen action (or "stay silent"), reason, gates hit, `answers` (json: question → value, confidence, probabilities) and `decider_backend`. Powers "why did / didn't you say anything?" with real probabilities.
- `action_log` every tool/action actually executed with result. Used to verify claimed actions.
- `dream` id, motif, text, seed memory ids, residue, ts.
- `cadence` persisted wall-clock schedule: name, next_at, last_at.
- `llm_call` model, tier (`decide | cheap | talk | deep`), purpose, tokens, cost_rub, latency, correlation id. Decider calls are logged like any other call.

Recall = FTS5 + vector search merged by **reciprocal rank fusion**, then re-weighted by importance, heat and recency, filtered by the **privacy wall** (only memories told by the current person, about shared context, or marked shareable).

## 6. The mind loop

```
every tick (60 s, no LLM): decay drives & emotions · cool memory heat · advance cadences
on trigger:                retrieve salient memories/thoughts → form thoughts (System 1/2)
                           → create/merge wishes → score candidate actions → gates
                           → act now | schedule | keep | do privately | drop
                           → write outcome back to memory, drives, decision trace
after a conversation:      extract per-person memories → pending queue → classify → store
at night:                  consolidate → blur/fade → dream → waking residue
weekly:                    test self-hypotheses · propose persona edits for approval
```

**Who decides what.** Words come from chat LLMs: System 2 thoughts, replies, research notes, dreams. Typed judgements come from the Decider: thought evaluation factors, "say it now or keep it?", wish merge vs new, presence and busyness cues from recent turns, and per-gate yes/no checks. The formula in section 6.4 combines these numbers with the drive state. The Decider never picks the action by itself.

### 6.1 Triggers
A message or utterance; a heartbeat (Aivita **chooses her own next check-in**, 10 min to 1 day); silence past a threshold; a date; a finished dream; finished research; a person appearing (button press or speech for now, camera later). Background work **yields to live conversation**. The thought loop **backs off** exponentially when nothing happens.

### 6.2 Thoughts (adapted from thoughtful-agents, https://github.com/xybruceliu/thoughtful-agents)
- System 1: a quick reflex (<15 words, no memory). System 2: a few deliberate thoughts shaped by salient memories, each citing its stimuli. If a topic doesn't touch her interests, she says so; don't force interest.
- Evaluation from factors: relevance to memory, her own information gap, filling someone's gap, expected impact, urgency, coherence with the last utterance, originality. These are **one Decider call** with a `score` per factor plus a `noul` "would saying this now feel natural?". System 1 reflexes stay on the cheap chat tier because they are text.
- Silence pressure: `score × 1.01^(turns since she last spoke)`.
- Unspoken thoughts stay in the reservoir and can resurface.
- Difference from TA: TA only thinks when someone speaks. Ours also thinks on time-driven triggers.

### 6.3 Drives

| Drive | Scope | Builds with | Satisfied by |
|---|---|---|---|
| Curiosity | per topic | recurring topics, dreams, unanswered questions | research, asking, a good answer |
| Connection | per person | time apart, warm last talk, open shared arc | any real exchange with that person |
| Care | per person + item | someone mentions a worry or an event | learning the outcome |
| Expression | global | strong emotion, vivid dream, finished research | making and sharing something |
| Growth | global | a mistake she noticed, a missing skill | practice, a confirmed hypothesis |
| Rest | global | activity, late hours | night cycle, quiet |

The last message sets the drift rate ("good night" slows connection need; an abrupt end speeds it). Example thresholds for connection: ≥0.20 private observation, ≥0.35 consider reaching out, ≥0.50 reach out. Emotions have half-lives (joy 3 days, anger 1, shame 14, grief 60; love and belonging don't decay) and every change needs an event as evidence. Mood is derived from recent emotion-tagged memories, not a stored number.

### 6.4 Action scoring

```
motivation = wish.strength × drive_pressure × thought_evaluation
           × relationship_closeness(person) × silence_factor
cost       = interruption_cost(presence, time of day, ignore streak) + resource_cost(rubles, time)
act if motivation − cost > threshold(action_rung)
```

`thought_evaluation` = the mean of the Decider's factor scores. `interruption_cost` adds a Decider `score` "how absorbed is this person right now?" read from their recent turns (the camera can feed this later).

### 6.5 Action ladder

| Rung | Actions | Gate |
|---|---|---|
| 0 Private | think, journal, recall, **research a topic**, make something | free (budget only) |
| 1 Ambient | **show something** (chat image now, device screen later), leave a note, "glance" cue that she has something to say | free if the person is present |
| 2 Social | **ask a question**, share a finding, invite to do something together | contact budget, quiet hours, coherence |
| 3 Interrupting | unprompted speech, push notification | strict gates and urgency |
| 4 World | reminders, files, messaging someone else | explicit, revocable permission per action type |

Rung 2-3 gates add Decider `noul` checks: "is this coherent with what they're doing now?" and "is it urgent enough to interrupt?". Quiet hours, contact budget and the 4 h spacing stay pure Python.

### 6.6 Guardrails (build with the first proactive action, not later)
- **Contact budget per person**, set by that person. Default: at most 3 interrupting messages a day, at least 4 h apart, quiet hours 23:00-07:00, do-not-disturb settable in conversation.
- **Ignore-streak backoff**: unanswered outreach raises thresholds. Silence never turns into guilt-tripping.
- **Private content is never spoken aloud** when someone else may be present; hold it or send it in that person's chat. A Decider `noul` "could someone else be present?" reads recent turns, defaulting to *yes* when unsure.
- **Decision trace** for every choice, including choosing silence.
- **Resource budget**: a daily ruble allowance she manages herself.

### 6.7 The three first proactive loops
- **Research**: curiosity wish past threshold on a quiet heartbeat → bounded session (a few searches and reads) → notes saved as `research` memories + a first-person reaction → curiosity partly satisfied → a **share candidate** linked to people likely to care → shared later when it fits the conversation. A rumination gate stops repeat research on the same thing. Decider uses: a `noul` per search result ("relevant to this curiosity wish?") to rerank before fetching pages, and a `noul` "is this the same question as research note X?" for the rumination gate.
- **Asking**: a high information-gap thought ("I don't know if Anya's dad got better") → ask now if the person is present and it's coherent, else schedule → concern stays open until answered (a Decider `noul` "does this reply answer the open concern?" closes or keeps it) → the answer updates the person model.
- **Showing**: expression drive builds → show an image (generated or found) to a present person, or turn it into a note → their reaction, classified by a Decider `choice` (`loved | liked | neutral | ignored | annoyed`), feeds back into how much she shows.

## 7. Memory behaviour

- **Extraction after conversations**: cursor-based over new turns only, with **speaker discipline** (never credit someone merely mentioned with what the speaker did). Record `told_by` and `shareable`.
- **Contradictions supersede** old facts (new job, new city) instead of coexisting.
- **Decider pass after extraction.** Extraction stays on a chat LLM because it writes text. Then, per item, one batched Decider call asks: emotions (`score` per emotion) and importance (`score`); `shareable` (`noul` "did they tell this in confidence?", safe default *not* shareable); `told_by` (`choice` among the speakers in the turn window, which enforces speaker discipline); and contradiction (`noul` per top recalled candidate "does the new item supersede this memory?").
- **Snippet-then-read**: recall injects short snippets with ids; the model opens a full memory via a tool. Never say "I don't remember" without searching; distinguish "never knew" from "forgot".
- **Heat**: memories cool over time and warm when actually used in a reply (searching alone doesn't count). Hot = full text, warm = summary, cold = not injected.
- **Locked memories** never fade.
- **Lossless before lossy**: old turns are summarized only after extraction; the raw turns stay.
- **People she has only heard of** ("my sister Anya") become lightweight `heard_of` nodes that can be upgraded.

## 8. Night cycle

Runs once per night on a persisted cadence (catch up lazily if the machine slept):
1. **Consolidate**: dedupe (a Decider `choice` `same | merge | distinct` per candidate pair), merge fragments into scenes, infer things never said outright (stored as `inferred`).
2. **Blur and fade**: aging memories lose detail but keep key facts; recalled ones get more time; fading ones may become `lost` (Aivita can notice the loss).
3. **Dream**: pick seed memories (emotionally congruent with the dominant mood, by importance, penalising recent seeds), spread activation 2 hops, write a first-person dream with the deep tier. Dreams never reinforce fading memories. Reject empty or template-sounding dreams using a Decider `score` "how vivid and specific is this dream?" plus a `noul` "template-sounding?" before saving.
4. **Waking residue**: a motif title and residue; dreams from the last ~18 h go into the prompt so she may mention one in the morning. Dreams can spawn wishes.

## 9. Growth (later milestone)
- **Hypothesis ledger**: she predicts something about herself, tests it against later events, and changes a trait only after 3+ independent observations, by a small step.
- **Identity moments**: permanent, append-only moments with why they matter; top recent ones go into every prompt.
- **Persona edit proposals**: at most daily, backed by 3+ concrete observations, each approved by the human.

## 10. Prompt layout
- Frozen prefix (cacheable): persona (Aivita, female, speaks Russian and English), values, tool list generated from the tool registry.
- Volatile tail: the person model, recalled memory snippets, current mood, open wishes/concerns about this person, dream residue, channel mode and language.
- Don't send history as JSON (the model starts imitating fields).
- Values first: no flattery or addictive design; she can disagree, keeps promises, owns mistakes.

## 11. Suggested repo layout

```
aivita/
├── pyproject.toml          # uv; ruff; pytest; mypy or pyright
├── LICENSE
├── README.md
├── CLAUDE.md               # conventions for future agents (write one)
├── config.example.toml     # model ids per tier, budgets, quiet hours, data dir
├── src/aivita/   
│   ├── app.py              # asyncio entry point: starts tick, channels, body
│   ├── config.py
│   ├── llm/                # polza client, tiers, structured output, cost accounting,
│   │                       #   decider.py (JevDecider, LLMDecider, FakeDecider)
│   ├── memory/             # db, migrations, store, recall (RRF), extraction, pending
│   ├── people/             # person nodes, identity mapping, privacy filter
│   ├── talk/               # Agent definition, prompt builder, tools exposed to the model
│   ├── channels/           # web (FastAPI+WS), cli, voice (tinyaisense)
│   ├── body/               # tinyaisense session, events → triggers, say/listen
│   ├── mind/               # tick, drives, emotions, thoughts, wishes, scoring, gates, trace
│   ├── actions/            # ask, research, show, note
│   └── night/              # consolidation, blur, dreams
└── tests/                  # unit (pure math), integration (Simulator, fake LLM)
```

Dependencies to start with: `openai`, `openai-agents`, `tinyaisense` SDK (from Dmitrii's repo), `pydantic`, `sqlite-vec`, `fastapi` + `uvicorn`, `httpx`, `trafilatura`, `PyStemmer` (if not using trigram), `pytest`, `pytest-asyncio`, `time-machine`. Check each licence is permissive.

## 12. Milestones

Build in vertical slices; each ends runnable and tested. Text chat comes first so nothing waits on hardware.

**M0 Skeleton.** Repo, licence, config, `CLAUDE.md`, SQLite with migrations, polza client with tiers and cost logging, CLI chat with a persona prompt. Add `llm/decider.py` with `JevDecider`, `LLMDecider` and `FakeDecider`, plus the config switch. *Done when* you can chat in Russian and English from the terminal, every turn and LLM call is in the DB with `cost_rub`, and one batched Jev call returns typed answers and is logged with `cost_rub`.

**M1 Memory and people.** Person table and identity mapping, post-conversation extraction, pending queue, hybrid recall (FTS5 trigram + sqlite-vec + polza embeddings, RRF), privacy filter, snippet-then-read tool. *Done when* a fact told in one session is recalled in a later one (cross-language too), and a fact told by person A is not revealed to person B unless shareable (test it). `pending_memory` labels, emotions/importance, `shareable`, `told_by` and supersede checks go through the Decider, and the privacy test still passes when the Decider is unsure (unsure defaults to not shareable).

**M2 Web chat.** FastAPI + WebSocket chat with streaming and sign-in per person; a read-only **inner-life panel** (mood, drives, open wishes/concerns, recent decisions including "stayed silent", each with its Decider probabilities and confidence). *Done when* two people can chat in separate browser sessions with separate relationships.

**M3 Voice through tinyaisense.** Hold the hub Session, voice channel adapter sharing the talk core and per-person history, streaming `say.open/append/close`, interrupt handling. *Done when* an integration test against the tinyaisense Simulator passes, and something said by voice is known in web chat.

**M4 Mind loop.** 60 s tick with persisted cadences, drives and emotion decay (pure, unit-tested with time-machine), thoughts and reservoir, wishes/concerns, action scoring, gates, decision trace, self-chosen heartbeat. Thought evaluation, the "say it now?" check and the soft gates go through the Decider with the confidence policy. Add a small **decider eval**: ~50 hand-labelled cases (Russian and English) run against both backends, reporting agreement, latency and rubles. *Done when* simulated time passing raises connection need for an absent person and produces a logged decision, gates block outreach in quiet hours, and the eval runs with the chosen default backend written in the README with its numbers.

**M5 First proactive actions.** Ask a question (voice `say{then_listen}` if at a device, else chat), research a topic (`polza:web_search`, notes as memories, share candidate), show a picture (image generation into chat). Each writes back to memory and drives. Daily ruble budget enforced. Decider uses: research relevance rerank, rumination gate, "concern answered?", reaction classification. *Done when* each loop runs end to end in tests with a fake LLM, and once for real.

**M6 Night cycle.** Consolidation (with Decider dedupe), blur/fade, dream generation with the Decider quality check, waking residue, lazy catch-up. *Done when* a nightly run produces a dream from real memories and the next morning's prompt includes the residue.

**M7 Growth.** Hypothesis ledger, identity moments, persona edit proposals with approval.

**Later (needs tinyaisense camera/screen):** presence-triggered greetings and held questions, waiting for a natural pause before speaking, `show` on the device screen, the glance cue, expressions on the display, speaker ID and face ID with consent. Jev is text only, so feed it a text description of the scene, not images, or skip it for vision.

## 13. Engineering conventions
- asyncio throughout; no task queue, no threads except where a library needs them.
- Pure functions for all state math so it can be unit-tested without an LLM or a clock.
- An LLM interface that tests can replace with a deterministic fake. Never call polza in unit tests. Tests use `FakeDecider` (scripted answers); the decider eval is the only place that calls Jev for real, and it is opt-in.
- A correlation id on every log row and every DB row produced by a trigger.
- Structured logs (JSON lines). Every LLM call logged with tier, purpose, cost.
- Fail-soft code paths need end-to-end tests; silent dead branches are the classic bug here.
- A test harness with a throwaway data dir and a simulated human; assert real data is untouched.
- Secrets only in env vars (`POLZA_API_KEY`); never commit them; `.env` in `.gitignore`.
- Don't max-pool mood across all memories as the store grows; use a recent window.

## 14. Privacy (non-negotiable)
- Data dir `0700`, local only. No telemetry. Agents SDK tracing disabled.
- Per-person privacy walls on recall (section 5).
- Raw audio and video are never stored by default; tinyaisense recording is a debug option only.
- Aivita "looks" (sends an image to the LLM) only when she decides to, and that is logged.
- Explain on request: "what did you see today?", "why did you speak up?" answered from the decision trace and action log.

## 15. Open questions (pick a reasonable default, note it in the README, and move on)
1. Desktop app vs phone vs both for the text channel beyond web chat. Default: web chat on the LAN, Telegram later.
2. How visible forgetting and grief should be. Default: visible in the inner-life panel, gentle in conversation.
3. Generate images herself vs only find existing ones at first. Default: generate via polza.
4. Physical moving head later (Stack-chan form factor)? Not this repo's concern now.
5. Jev availability (new, proprietary; TypeSafe paused direct sign-ups on 2026-09-22, polza still serves it). Default: Jev when reachable, falling back to `LLMDecider` automatically on errors, with the fallback logged.

## 16. References
- tinyaisense (body/hub): https://github.com/unkier/tinyaisense
- polza.ai docs: https://polza.ai/docs/llms.txt · chat: https://polza.ai/docs/api-reference/chat/completions.md · embeddings: https://polza.ai/docs/api-reference/embeddings/create.md
- companion-emergence (closest prior art; one user per persona, shells out to the Claude CLI; borrow ideas, not code structure): https://github.com/hanamorix/companion-emergence
- thoughtful-agents (inner-thoughts engine): https://github.com/xybruceliu/thoughtful-agents (`thoughtful_agents/utils/thinking_engine.py`, `saliency.py`)
- awesome-ai-companion (prior art list: Kin Mind, jiwen, kiwi-mem, dreams): https://github.com/DasterProkio/awesome-ai-companion
- sqlite-vec: https://github.com/asg017/sqlite-vec
- OpenAI Agents SDK (Python): https://github.com/openai/openai-agents-python
- Jev on polza.ai: https://polza.ai/docs/gaidy/jev
- TypeSafe AI, Jev announcement: https://typesafe.ai/blog/introducing-system-one-models-and-jev

## 17. How to start
1. Read tinyaisense's `README.md`, `CONTEXT.md`, `docs/adr/`, `docs/protocol/agent.md` and its SDK; note anything in section 4.2 that differs.
2. Confirm the polza.ai details in section 4.3 with one tiny script (chat, structured output, embeddings, `cost_rub`) and one batched Jev `/systemone` call with a `noul`, a `choice` and a `score` question in Russian.
3. Write `CLAUDE.md` and the README with the decisions in section 2.
4. Build M0, then proceed milestone by milestone. Show Dmitrii each milestone's "done when" result before starting the next.
