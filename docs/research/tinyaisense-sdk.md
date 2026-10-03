# tinyaisense SDK vs the handoff

Research for [#4](https://github.com/unkier/aivita/issues/4). Checked against tinyaisense at commit `442045a` (local checkout `~/devel/tinyaisense`, also public at https://github.com/unkier/tinyaisense/tree/442045a), 2026-10-03.

- Every `path:line` below is in the tinyaisense repo at `442045a` unless it says otherwise. Where the docs and the code disagree, the code wins. Here they agreed everywhere I looked.
- **Verified by running**: the uv git and path dependencies (uv 0.10.0); importing the SDK on Python 3.11.12; and four integration tests from a scratch outside project on Python 3.14.3: an in-process hub, the Simulator, fake speech, `VoiceAgent` and the Agents SDK's `ScriptedModel`. All four passed. The scratch project was thrown away. Its fixture is reproduced in §4.

## Summary: handoff §4.2 vs the code

| # | Handoff §4.2 claim | Verdict | Correction / detail |
|---|---|---|---|
| 1 | SDK entry point `tinyaisense.connect(...)`; the agent API is a WebSocket | **Confirmed** | `connect(url, token, *, takeover=False, utterances=None)`. You can `await` it or use it with `async with`. The URL is `ws://<hub>:8421/agent` (`packages/sdk/src/tinyaisense/session.py:422-431`, `docs/protocol/agent.md:9`). It **never reconnects by itself** (`session.py:63-68`). |
| 2 | Only one agent Session at a time, and Aivita holds it | **Confirmed** | A second `hello` gets `busy` with `holder` and `since`. `takeover=True` ends the other Session (`taken_over`). After `taken_over`, an agent must not reconnect by itself. There is no resume: a dropped link is a new Session. The hub ends the Session after 6 s with no frame from the agent (`agent.md:14,67,73-91`). While Aivita holds the hub, Claude Code's `tinyaisense mcp` shim can't use it unless it takes the hub over (`README.md:47`). |
| 3 | `HubMcpServer` joins the same Session, so tools and voice share it | **Confirmed** | It sends the `X-Hub-Session: <hub.id>` header (`openai_agents.py:82-93`). A joined link has no `wait_for_event` tool (`mcp_server.py:427-433`). A tool call that runs past 50 s returns `pending`, and its result then arrives as an `mcp.result` notification on the agent-API link (`agent.md:78`). `VoiceAgent` ignores `mcp.result`. |
| 4 | `say{address, text, then_listen}` speaks and then opens the mic: the proactive "ask" | **Partial** | `say` replies **when playback ends, not with the answer**. The answer arrives as `utterance.start{trigger:"then_listen"}` … `utterance.end{transcript, lang}` notifications, linked by the `utterance_id` in the say result. The mic opens only if the speaker *drained*: not if the say was cut, and not if another `say` is queued after it (`agent.md:248-253`). `VoiceAgent` **ignores** these answers (`openai_agents.py:179-185`; I verified this by test). Only the MCP `say` tool returns the answer inline (`mcp_server.py:527-553`). |
| 5 | `say.open/append/close` streams LLM text with clause-level chunking | **Confirmed** | Speech starts after the first clause. A tail of 4 or more words is spoken after a 500 ms pause in the text. A `say.open` **must be closed**, or every `say` queued after it never plays (`agent.md:257-267`, `session.py:224-230`). The hub strips markdown, URLs and emoji before TTS (`hub/.../speech/text.py:25-48`). `heard_text` is the *original* text (`agent.md:246`). |
| 6 | The hub picks the TTS voice from the text's script (Cyrillic → Russian) | **Partial** | The choice order is: an explicit `voice`, then `lang`, then the dominant script, then the hub default (`agent.md:250`). For a streamed say the script is judged **from the clauses it has when the first one is cut**, and a say has only one Voice (`hub/.../speech/layer.py:333-341`). So in a mixed RU/EN reply, the whole say is spoken in the voice of its first clause. `VoiceAgent` never passes `lang` or `voice`. |
| 7 | Utterances carry a language | **Partial** | `utterance.end.lang` is **optional**. It is present only when the Session opted in to transcripts and words were heard (none on a `click`). It is the language of the longest segment (`agent.md:274-275,304`). The local Parakeet STT sets it **by the transcript's script**: `ru` if mostly Cyrillic, else `en` (`hub/.../speech/local.py:106-134`). |
| 8 | Barge-in is handled on the device | **Confirmed** | The Reflex (ADR 0003). The hub arms it on every online device while a Session exists (`agent.md:79`), and the speaker is cut about 6 ms after the press (`docs/adr/0003…md:4`). |
| 9 | `VoiceAgent` (OpenAI Agents SDK) feeds "you were cut off; the human heard: …" back into the conversation | **Partial** | The exact text is `you were cut off; the human heard: '{heard}'` (`openai_agents.py:34`). It is **prefixed to the next push-to-talk user message**, with `\n\n` before the human's words. It is neither a separate message nor sent right away. A click interrupts but starts no turn, so the note waits for the next utterance (`openai_agents.py:197-198,213-223`). In addition, the heard part of a cancelled reply is written to the history as an assistant item through `session.add_items` (`openai_agents.py:206-210`). |
| 10 | Button gestures, utterances and device online/offline arrive as notifications | **Confirmed** | See §3. While a device is armed (the default), a press under 250 ms is a `click`, which means "stop talking", and there is **no `long_press`** (`docs/protocol/kinds/button.md:28`). `VoiceAgent` consumes **every** notification and passes none on (§2). |
| 11 | `[debug] record_dir` keeps per-Session WAVs and a `trace.jsonl` | **Confirmed** | This is hub config (`README.md:33`, `hub/.../config.py:182-186`). The agent can't set it. It records raw audio, so under handoff §14 it is for debugging only. |
| 12 | Simulator + fake speech plugin: integration tests with no hardware and no API calls | **Confirmed, with caveats** | The tests need **`tinyaisense-hub` and `tinyaisense-sim`, both Python ≥3.14**. The fake plugin lives in the hub package (`tinyaisense_hub.speech.fake`). The hub's `start_hub` fixture is **not exported**: only the `simulator` fixture is (`sim/.../pytest_plugin.py:49-60`). Fake speech under 200 ms is dropped as noise (`hub/.../speech/listening.py:33`), so each test phrase needs **20 or more characters**. See §4. |
| 13 | Device Kinds today: mic, speaker, button, LED; camera and screen are coming | **Confirmed** | `docs/adr/0001…md:3`. |
| 14 | Plan: start with `VoiceAgent`, passing the shared Agent and a shared **per-person** `session=` | **Wrong as stated** | `session=` is **one** Agents SDK `Session` per `VoiceAgent`, fixed when it is constructed (`openai_agents.py:122-133`). There is no per-utterance person routing. `VoiceAgent` is the sole consumer of notifications; it ignores `then_listen` answers and `mcp.result`; it passes no `context`, `lang` or run config; and its `on_turn` callback is synchronous. **Recommendation:** for M3, write the thin adapter on `say.open/append/close` and utterance events from the start, and copy `VoiceAgent`'s interrupt logic (§2). |

**Not in the handoff, but it matters:**

- **tinyaisense has no licence.** There is no `LICENSE` file, no `license` field in any `pyproject.toml`, and GitHub detects none (`gh api repos/unkier/tinyaisense` → `license: null`). Handoff §2 requires permissive core dependencies, and Aivita will be MIT.
- **Python:** the SDK and `tinyaisense-wire` need ≥3.11; the hub and the Simulator need ≥3.14 (`README.md:77-83`). tinyaisense itself develops on 3.14 (`.python-version`). The map's choice of Python 3.14 for Aivita is therefore *required* to run the Simulator in-process.
- **openai-agents version:** the SDK's `[agents]` extra asks for `openai-agents>=0.22` with no upper bound (`packages/sdk/pyproject.toml:15`). tinyaisense locks 0.22.3 (`uv.lock:809-810`). A fresh resolve in an outside project picked **0.23.1**, and `VoiceAgent` passed there.
- **Shared key:** the hub's optional polza.ai cloud speech engines read the same `POLZA_API_KEY` env var (`README.md:22`). The polza.ai costs that Aivita logs won't include the hub's STT and TTS.

## 1. The public API surface relevant to Aivita

### `tinyaisense` (core; dependencies: `tinyaisense-wire` and `websockets`)

It exports `connect`, `Session`, `Notification`, `ApiError` and `SessionEnded` (`packages/sdk/src/tinyaisense/__init__.py:3,7`).

| Call | Returns / notes | Source |
|---|---|---|
| `connect(url, token, *, takeover=False, utterances=None)` | A `Session`. Raises `ApiError("unauthorized"\|"busy")`. `utterances={transcript, audio, rate}` sets the default opt-in, which has transcripts on. | `session.py:422-431` |
| `Session.id`, `.url`, `.token`, `.ended`, `.disarmed` | `ended` is `taken_over`, `shutdown` or `closed`. `disarmed` is the set of device names whose Reflex is off. | `session.py:70-92` |
| `devices()` / `voices()` | `[{name, online, manifest}]` / `[{id, lang, name}]` | `session.py:127-133` |
| `say(address, text, *, voice, lang, replace, then_listen)` | Returns `{reason, played_ms, interrupted, heard_text, degraded?, utterance_id?}` once the speech has played or been cut | `session.py:188-213`, `agent.md:237-255` |
| `say_open(address, …) → handle`, `say_append(handle, text)`, `say_close(handle) → say result` | Streaming text. Appends after a cut are accepted and ignored. | `session.py:215-243`, `agent.md:257-267` |
| `listen(address, *, lang, utterances)` | The `utterance.end` params. Cancelling the call ends the listen with `stopped`. | `session.py:245-261` |
| `command(address, name, args)`, `led_release(device)`, `reflex_set(device, armed)` | LED and Reflex control. The first `led` command claims the LED away from the Status display. | `session.py:135-151`, `agent.md:127-142` |
| `stream_start/stop/drain`, `send_audio`, `audio(handle)` | Raw audio. Not needed for text-in/text-out voice. | `session.py:153-186,263-277` |
| `notifications()` | An async iterator over the Session's notifications. **Only one consumer gets each notification.** | `session.py:279-284` |
| `close()` | Leaves the hub; the Session ends. | `session.py:286-289` |
| Cancelling any `call()` | Sends a `cancel` for that request to the hub, e.g. cuts a `say` | `session.py:106-125`, `agent.md:144-150` |

Errors: branch on `ApiError.code`, which is one of `unauthorized`, `unsupported`, `invalid_args`, `unknown_address`, `busy`, `failed`, `timeout`, `disconnected` or `overflow` (`agent.md:33-43`). The SDK pings the hub every 2 s and so notices a dead hub within about 6 s (`session.py:26-28`).

### `tinyaisense.openai_agents` (the `[agents]` extra: `openai-agents>=0.22`, `mcp>=2.2,<3`)

Exports: `VoiceAgent`, `HubMcpServer`, `Turn`, `CUT_OFF`, `InterruptPolicy` and `interrupt_on_press` (`openai_agents.py:367`).

- `VoiceAgent(hub, agent, *, session=None, policy=interrupt_on_press, on_turn=None)`, and `await .run()` until the Session ends (`openai_agents.py:122-160`).
- `Turn(input, spoken, interrupted, result, error)`: `spoken` is the list of say results, one per model response (`openai_agents.py:49-63`).
- `InterruptPolicy = (Notification, armed) -> bool`. The default is `armed and method == "button.down"` (`openai_agents.py:37-46`).
- `HubMcpServer(hub, *, name="tinyaisense", client_session_timeout_seconds=60)` is an `MCPServerStreamableHttp` aimed at `http(s)://<hub>/mcp` (`openai_agents.py:66-111`). The hub tools it offers are `devices`, `voices`, `say`, `listen`, `command`, `led_release` and `set_reflex` (`mcp_server.py:244-361`). Its server instructions tell the model to "Speak plainly and briefly: no markdown, lists or code" (`mcp_server.py:39-44`).

## 2. How `VoiceAgent` drives a turn

`run()` starts two tasks, `_follow` and `_take_turns`, and returns when either ends (`openai_agents.py:147-160`).

1. **Follow (`_follow`, `:162-185`).** It iterates `hub.notifications()`, which makes it the only consumer.
   - On a device Event (anything with `data`) while a turn runs, if `policy(event, armed)` is true, it interrupts the turn. If the Reflex didn't cut that speaker (a different device, or a disarmed one), the adapter cuts the speech itself with `say(speaker, "", replace=True)` (`:167-173`, `:354-360`).
   - It collects each `say.ended` on the last turn's speaker into `heard` (`:174-176`).
   - `device.online` updates the manifest it keeps (`:177-178`).
   - Only utterances with **`trigger == "button"`** become turns, and only if the reason isn't `click` and the transcript isn't empty (`:179-185`). Utterances from `then_listen` and `listen` are dropped.
2. **Take turns (`_take_turns`, `:187-193`).** It takes one turn at a time from a queue of `(device, transcript)` pairs. After each turn it calls `on_turn(turn)` **synchronously**; the return value is ignored, so an `async def` callback would never run.
3. **One turn (`_take`, `:195-211`).**
   - If the human cut off the last turn, the input becomes `CUT_OFF.format(heard=…) + "\n\n" + transcript`. `heard` joins the `heard_text` of every say in the last turn, its tools' says included (`:213-223`).
   - It calls `Runner.run_streamed(self._instructed(), text, session=self._history)`, with no `context`, no `run_config` and no `max_turns` (`:199`).
   - `_instructed()` clones the agent with dynamic instructions: the agent's own system prompt, then the `HubMcpServer` instructions (`:225-240`).
4. **Streaming to speech (`_Turn.take`, `:270-287`; `_Speech`, `:299-360`).**
   - For each `RawResponsesStreamEvent`, a `ResponseTextDeltaEvent` becomes `say_append`; the say is opened lazily on the first delta with `say_open(speaker)`, without `lang` or `voice`.
   - A `ResponseCompletedEvent` closes that say without waiting for it to play. So there is **one `say` per model response**, and any `say` a tool makes afterwards queues behind it.
   - The speaker is the first `speaker` capability in the Manifest of the device the human spoke to (`:242-248`).
   - If a say fails (the device went offline, or the Session ended), the rest of the reply goes unspoken but the turn completes (`:326-327,350-352`).
   - These events come from the Agents SDK's chat-completions stream handler as well (`agents/models/chatcmpl_stream_handler.py` emits `ResponseTextDeltaEvent` and `ResponseCompletedEvent`), so `OpenAIChatCompletionsModel` on polza.ai works with `VoiceAgent`.
5. **Interrupt (`_Turn.interrupt`, `:289-296`).** It records the current step (`result.current_turn`) as `dropped` and calls `result.cancel("immediate")`. After the turn, if the dropped step had speech the human heard, `session.add_items([{"role":"assistant","content": heard}])` writes it to the history, because a cancelled run keeps none of its reply (`:206-210`). A reply that had finished streaming before the cut stays in the history whole, and only the next turn's note says where it was cut (test: `hub/tests/test_openai_agents.py:203-223`).
6. **History (`session=`).** This is any Agents SDK `Session` (`agents.memory.Session`, with `get_items`, `add_items`, `pop_item` and `clear_session`). The default is `SQLiteSession(hub.id)`, an in-memory store that dies with the Hub Session (`:133`). The user's text, the cut-off note included, is stored as the user item (test: `test_openai_agents.py:192-200`).

**What it does not do:** route turns to a person; give the mind any notification; start a turn from a `then_listen` answer; pass `lang`; pass the utterance's `lang` or `degraded` to the model; or await an async `on_turn`. Those gaps are why handoff §4.2's "per-person `session=`" plan doesn't fit as written.

## 3. Notifications and events

Every notification carries `t`, the hub's wall-clock time in ms since the epoch. For a device Event, `t` is when the Event happened on the device (`agent.md:23`). The full table is at `agent.md:152-170`.

| Method | Params (besides `t`) | Use in Aivita |
|---|---|---|
| `device.online` | `device`, `manifest` | Body state: which devices and capabilities exist. It is **not** presence. |
| `device.offline` | `device` | Body state. Proactive speech falls back to chat. |
| `button.down` / `button.up` | `address`, `data:{}` | Interrupt policy, and "someone is here" presence |
| `button.click` / `button.double_click` / `button.long_press` | `address`, `data:{}` | Mind triggers. While a device is armed, a click means "stop talking" and there is no `long_press` (`kinds/button.md:23-28`). |
| `utterance.start` | `utterance_id`, `address`, `trigger` (`button`, `then_listen` or `listen`), `handle?` | Presence; links an answer to the ask that opened its mic |
| `transcript.partial` | `utterance_id`, `text`, `lang` | Optional live text |
| `utterance.end` | `utterance_id`, `reason`, `transcript?`, `lang?`, `degraded?`, `stats` | **A person Turn** (voice channel). The reason is one of `end_of_turn`, `button`, `click`, `no_speech`, `max_duration`, `stopped` or `disconnected` (`agent.md:287-297`). |
| `say.ended` | `address`, `text`, plus the say result | What was actually heard (`heard_text`); write-back |
| `mcp.result` | `pending`, `tool`, and `result` or `error` | Only if the LLM is given the hub's MCP tools |
| `stream.started` / `stream.ended` | `handle`, … | Raw audio only; unused |
| `session.ended` | `reason` | Voice channel down; reconnect policy |

Ordering guarantees (`agent.md:172-184`):

- Events from one device arrive in that device's order.
- Cause comes before effect: `button.down`, then the cut say's result, then `utterance.start`.
- JSON messages never wait behind audio.
- From the press on the device to `button.down` on the agent socket takes ≤20 ms at p99.

The hub never interrupts a turn itself; an adapter next to the agent decides (`agent.md:183`). Unknown methods and fields must be ignored (`agent.md:22`).

## 4. Running the hub, Simulator and fake speech in Aivita's tests

**What to install** (dev group only; the hub and the Simulator need Python ≥3.14): `tinyaisense-hub`, `tinyaisense-sim[pytest]`, `pytest>=9`, `pytest-asyncio>=1.4`. Use the git sources from §5.

**Pieces:**

- `tinyaisense_hub.Hub(Config, state_dir=, runtime_dir=, auto_approve=, host=, mdns=)` runs a whole hub in-process. `Hub.agent_url` and `Hub.mcp_url` give its URLs (`hub/.../hub.py:28-96`).
- `tinyaisense_sim.Simulator(hub.device_address)` runs simulated devices, and `await sim.add("m5stack-atom-echo", name)` adds one (`sim/.../simulator.py:86-156`).
- `OwnerClient(hub.owner_socket).approve(device_id, name)` pairs a device.
- `SimDevice.talk(pcm)` is push-to-talk (`simulator.py:348-369`), `device.mic.feed(pcm)` gives the mic something to hear (for `then_listen` and `listen`), and `fake.decode(device.speaker.pcm()).text` reads back what was spoken (`hub/.../speech/fake.py:42-84`).
- The fake engines (`FakeTts`, `FakeStt`, `FakeVad`, `FakeTurn`) speak each character as a 10 ms tone and decode it back. The end of a turn is heard at `.`, `!`, `?` or `…` (`fake.py:1-7,91-153`).
- No-LLM agents: `agents.testing.ScriptedModel` and `assistant_message` ship upstream in openai-agents. tinyaisense's own tests use them (`hub/tests/test_openai_agents.py:11,127-144`).

Here is the fixture, which passed on Python 3.14.3 with stock asyncio (uvloop isn't required):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from tinyaisense_hub import Config, EngineConfig, Hub, OwnerClient, SpeechConfig, VoiceConfig

FAKE = "tinyaisense_hub.speech.fake:"
SPEECH = SpeechConfig(
    engines={n: EngineConfig(FAKE + c) for n, c in
             {"tts": "FakeTts", "stt": "FakeStt", "vad": "FakeVad", "turn": "FakeTurn"}.items()},
    tts={"en": "tts", "ru": "tts"}, stt={"en": "stt", "ru": "stt"}, vad="vad", turn="turn",
    voices=(VoiceConfig("alto", "en", "Alto"), VoiceConfig("masha", "ru", "Маша")),
)

@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):            # the MCP client (httpx) must not use a proxy
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, "*")

@pytest.fixture
async def hub(tmp_path):
    with TemporaryDirectory(prefix="tas-") as runtime:   # short: the owner socket path must fit sockaddr_un
        config = Config(agent_token="agent-token", device_port=0, http_port=0, speech=SPEECH)
        async with Hub(config, state_dir=tmp_path / "state", runtime_dir=Path(runtime),
                       host="127.0.0.1", mdns=None) as hub:
            yield hub

# in a test:
#   sim = Simulator(hub.device_address); desk = await sim.add("m5stack-atom-echo", "desk")
#   async with OwnerClient(hub.owner_socket) as owner: await owner.approve(desk.device_id, "desk")
#   await desk.wait_for(lambda: desk.state == "online")
#   async with tinyaisense.connect(hub.agent_url, "agent-token") as s: await desk.wait_for(lambda: desk.armed); ...
#   finally: await sim.close()
```

**Checked in the scratch project** (each test took about 2 s):

- (a) A Russian push-to-talk turn through `VoiceAgent` + `ScriptedModel`: the reply is spoken, and `heard_text` matches.
- (b) A `then_listen` answer arrives as `utterance.start{trigger:"then_listen"}` and `utterance.end{transcript, lang:"ru", reason:"end_of_turn"}`, with the `utterance_id` from the say result.
- (c) While `VoiceAgent` runs, a `then_listen` answer starts **no** turn, and the model is never called.
- (d) `listen` works.

**Gotchas:**

- Speech under 200 ms is noise (`MIN_SPEECH_MS`, `listening.py:33`), and a press under 250 ms is a `click` that is discarded (`config.py:62`). Fake-speech phrases therefore need **≥20 characters**. A 16-character phrase failed with `no_speech`.
- Leave `auto_approve` off and approve by name. `auto_approve` names a device `echo-xxxx` (`devices.py:759-762`).
- The hub's own `start_hub`, `paired` and `armed` helpers live in `packages/hub/tests/` and can't be imported. Copy their pattern instead (`hub/tests/conftest.py:72-116`).

## 5. How Aivita should depend on the SDK

**Git dependency, pinned (recommended).** I verified it with uv 0.10.0: uv resolves `tinyaisense-wire` *transitively* from the same commit and subdirectory, even though the SDK declares it as `{ workspace = true }`.

```toml
[project]
requires-python = ">=3.14"
dependencies = ["tinyaisense[agents]"]          # or plain "tinyaisense" if VoiceAgent/HubMcpServer aren't used

[dependency-groups]
dev = ["tinyaisense-hub", "tinyaisense-sim[pytest]", "pytest>=9", "pytest-asyncio>=1.4"]

[tool.uv.sources]
tinyaisense     = { git = "https://github.com/unkier/tinyaisense", rev = "442045a", subdirectory = "packages/sdk" }
tinyaisense-hub = { git = "https://github.com/unkier/tinyaisense", rev = "442045a", subdirectory = "packages/hub" }
tinyaisense-sim = { git = "https://github.com/unkier/tinyaisense", rev = "442045a", subdirectory = "packages/sim" }
```

**Path dependency** (`{ path = "../tinyaisense/packages/sdk", editable = true }`): also verified, and `wire` resolves as an editable path. The lockfile then records a relative path, so it works only with a sibling checkout. Use it for co-developing both repos, not in the committed lock.

**Python:** the SDK and wire support ≥3.11 (verified: importing `tinyaisense.openai_agents` on 3.11.12). The hub and the Simulator need ≥3.14 (`packages/hub/pyproject.toml:5`, `packages/sim/pyproject.toml:5`). With the dev group above, the project must be `>=3.14`, or uv can't resolve.

**Versions:** pin a tested `openai-agents` range, e.g. `>=0.22,<0.24`, because `VoiceAgent` relies on Agents SDK internals: `RunResultStreaming.current_turn`, `cancel(mode)` and `RawResponsesStreamEvent`.

**Licences:** the SDK's runtime dependencies are permissive: websockets is BSD-3; openai-agents and mcp are MIT. The hub and the Simulator pull in `soxr` and `zeroconf`, both **LGPL-2.1-or-later**, which is fine as dev-only dependencies. tinyaisense itself has **no licence** (see the summary).

## 6. Constraints the Aivita talk core must meet

These keep a voice channel pluggable in M3 without a rewrite. "Voice sink" means the M3 adapter that drives `say.open/append/close`.

1. **Stream by model response.** A turn yields text deltas as they arrive, in segments that each mark the end of one model response. The voice sink opens one `say` per response and closes it at the response's end, so that any tool-made speech queues behind it (`openai_agents.py:270-287`). Plain "one string per turn" output blocks this.
2. **Cancel immediately, at any point.** This includes before the first token and during a tool call. Cancelling must leave the History consistent: the person's Turn is kept, and the unsaid part of the reply is discarded (`result.cancel("immediate")`, `openai_agents.py:289-296`).
3. **Record what was heard, not what was generated.** After the channel reports its say results (`heard_text`, `interrupted`, `reason`, `played_ms`), Aivita's Turn stores `heard_text` and an `interrupted` flag. Text that was generated but never spoken must not count as said (handoff principle 9). Text channels report "heard = sent".
4. **The cut-off note goes in the prompt, not the raw Turn.** The next person Turn after an interruption must give the model what was heard (`you were cut off; the human heard: '…'`). The talk core puts this in the per-turn volatile tail. `VoiceAgent` instead prefixes it to the user's stored message, which would pollute the append-only History (handoff principle 3).
5. **Turn input is more than text.** It is `{person, channel, mode, text, lang?, source_ref}`, where `source_ref` is the `utterance_id`/device for voice and the message id for chat. The talk core builds the per-turn prompt (person model, recall, mode, language) from that input, because `VoiceAgent`'s `run_streamed(agent, text)` passes nothing else (`:199`).
6. **One running turn per person, with interrupt-then-replace.** A new input that interrupts a running turn must wait until the cancelled turn has finished its write-back (`VoiceAgent` awaits `spoken()` first, `:284-287`). Proactive outreach must check this lock and the device's speaker queue: says on one speaker play first in, first out, and a `replace` cuts the rest (`agent.md:227-229`).
7. **The talk core must not own the hub link.** `body/` is the only consumer of `Session.notifications()` (`session.py:279-284`). It fans notifications out to the voice channel (utterances, `say.ended`, interrupt events) and to the mind (`device.*`, gestures, presence). Nothing in `talk/` may import `tinyaisense`.
8. **Answers to pending asks.** A `then_listen` answer arrives as a separate utterance, linked by `utterance_id` (`agent.md:248-253`). The talk core must accept a Turn tagged "reply to ask X" (correlation id) and still treat it as a normal person Turn in the same History.
9. **The History is Aivita's store, not the Agents SDK `session=`.** If the talk core uses the Agents SDK, either it passes an explicit `input` each turn or it implements `agents.memory.Session` (`get_items`, `add_items`, `pop_item`, `clear_session`) over Aivita's own Turns. Either way it must accept assistant text added after the fact (the heard text, `:206-210`).
10. **Mode and language come with each turn.** Voice mode means short, plain, speakable text: the hub strips markdown, URLs and emoji anyway (`text.py:25-48`), but `heard_text` keeps the raw text. A say gets one Voice, chosen from its first clause, so the talk core should know the reply language and let the sink pass `lang`. Otherwise a reply that opens with a word in another script is spoken in the wrong voice (`layer.py:333-341`).
11. **Sink failure is not turn failure.** If the device drops mid-reply, the rest goes unspoken, the turn still completes, and the History records only what was heard. The next utterance gets a turn (`openai_agents.py:326-327,350-352`; test `test_openai_agents.py:375-401`).
12. **Never block the event loop.** The hub drops a Session after 6 s with no frame (`agent.md:14`), and an interrupt is worth about 20 ms. SQLite, embeddings and prompt building must be fast or run off the loop, and the turn hook must be async-safe (`VoiceAgent`'s `on_turn` is synchronous).
13. **The Hub Session comes and goes.** It can end at any time (`taken_over`, `shutdown`, `closed`, `session.py:77-79`). Voice then goes offline while text keeps working. `body/` reconnects with backoff, except after `taken_over` (`agent.md:76`).
14. **Identity lives outside the talk core.** A voice utterance names only a device address. The channel adapter maps device to person (in M3, the desk Owner by default); the talk core always receives a resolved person.

## Open questions this raises

- **tinyaisense licence.** Aivita (MIT, open source) would depend on an unlicensed SDK. The Owner should add MIT or Apache-2.0 to tinyaisense, at least to `packages/sdk` and `packages/wire`.
- **Hub MCP tools in the talk LLM?** Giving the model `HubMcpServer` lets it `say` and `listen` directly. That bypasses Aivita's action log (handoff principle 9) and couples `talk/` to the body. The default suggested here: don't expose them; `actions/` and `body/` call the SDK.
- **Reply language** (already on the map): the utterance `lang` is a script heuristic, and a say has one Voice, so the M3 sink should pass `lang` explicitly.
