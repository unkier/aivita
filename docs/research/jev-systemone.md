# Jev `/systemone`: contract and availability

Research for [issue #3](https://github.com/unkier/aivita/issues/3). Checked against handoff §2 (Decisions row), §4.3 (Decider rows, Decider interface) and §15 item 5. Researched 2026-10-03 from documentation only: there is no API key, so **nothing here was confirmed by a live call**.

Source keys (cited as `[P1]` and so on):

| Key | Source |
|---|---|
| P1 | polza, "Jev: решения вместо текста": https://polza.ai/docs/gaidy/jev |
| P2 | polza, "Как задавать вопросы Jev": https://polza.ai/docs/gaidy/jev-questions |
| P3 | polza, "Jev: рецепты и ограничения": https://polza.ai/docs/gaidy/jev-recipes |
| P4 | polza, API reference `POST Systemone` (includes the OpenAPI schema): https://polza.ai/docs/api-reference/systemone/create |
| P5 | polza, model catalog page: https://polza.ai/models/typesafe/jev (also `.md`) |
| P6 | polza, Jev landing page (updated 2026-09-18): https://polza.ai/jev |
| P7 | polza, API introduction (errors, retries, 429 types): https://polza.ai/docs/api-reference/introduction |
| P8 | polza, docs index: https://polza.ai/docs/llms.txt |
| T1 | TypeSafe, launch post (dated **Sep 15, 2026**): https://typesafe.ai/blog/introducing-system-one-models-and-jev |
| T2 | TypeSafe, API reference: https://docs.typesafe.ai/api |
| T3 | TypeSafe, Models (limits, aliases, language support): https://docs.typesafe.ai/models |
| T4 | TypeSafe, "Jev 1.13 jaggedness" (last reviewed 2026-10-02): https://docs.typesafe.ai/model-jaggedness/jev-1.13 |
| T5 | TypeSafe, Confidence: https://docs.typesafe.ai/confidence |
| T6 | TypeSafe, Noul: https://docs.typesafe.ai/primitives/noul |
| T7 | TypeSafe, Quick start: https://docs.typesafe.ai/introduction/quickstart |
| T8 | TypeSafe, Python SDK changelog: https://docs.typesafe.ai/sdk/python/changelog |
| T9 | TypeSafe, Legal and DPA: https://docs.typesafe.ai/legal, https://typesafe.ai/legal/data-processing |
| S1 | Secondary: aifront-page, sign-up pause (2026-09-22), quoting @typesafeai https://x.com/typesafeai/status/2102281508950307159: https://aifront-page.com/typesafe-ai-pauses-jev-ai-model-signups-demand-surge/ |
| S2 | Secondary: aifront-page, sign-ups reopened (2026-09-28), quoting Diogo Almeida https://x.com/CompleteSkeptic/status/2104338649999626397: https://aifront-page.com/typesafe-ai-reopens-jev-sign-ups-free-credit-suspended/ |

The X posts themselves could not be fetched, so S1 and S2 are the weakest sources here.

## Summary: handoff claims vs sources

| # | Handoff claim | Verdict | Correction / note |
|---|---|---|---|
| 1 | Endpoint `POST https://polza.ai/api/v1/systemone`, model `typesafe/jev` (§2, §4.3) | **Confirmed** | Aliases `jev-latest`, `jev-preview` and the pinned `jev-1.13.0` are also accepted [P4]. `typesafe/jev` floats to the latest stable version [P3]. |
| 2 | Request `{"model", "state": <text or JSON>, "questions": {name: {"type", "instructions", "criteria"}}}` | **Confirmed** | `state` is string, object **or array** [P4][T2]. `instructions` may also be an object or array [T2]. Optional `provider` field [P4]. |
| 3 | `criteria` is `{...}` for both choice and score (interface: `dict[str, str]`) | **Wrong** | `choice`: object `{option: description or null}`, description may be structured. `score`: an **ordered array** of 2-10 level descriptions. `noul`: optional `{"true": ..., "false": ...}` [P4][T2]. |
| 4 | Response `answers[name]` with `noul` / `choice` / `score`, `confidence` and `probabilities` | **Partly wrong** | A `noul` answer is only `{type, noul}`: **no `confidence`, no `probabilities`** [P4][T2][T6]. A `score` answer also has `legend`. The top level also has `model`, the version that answered (e.g. `jev-1.13.0`) [P4]. |
| 5 | `A.value` for score is `0..1` (interface comment) | **Wrong** | `score` is the probability-weighted level index, from `0` to `levels − 1`. It can land between levels (e.g. 1.62 on a 3-level scale, 3.99 on a 5-level scale) [P2][P3][T2]. To get 0..1, divide by `levels − 1` [P3]. |
| 6 | `usage.cost_rub` on every response | **Mostly confirmed** | Present in the HTTP response [P1][P4], but the OpenAPI schema marks it `nullable` [P4]. The official TypeSafe Python SDK drops it [P1][P4]. |
| 7 | Only input tokens are billed | **Confirmed** | Output tokens are free [P1][P4][T1][T3]. |
| 8 | About 280 overhead tokens per request, so batch questions | **Confirmed (polza's claim)** | Stated by polza [P1][P4]. Consistent with TypeSafe's examples (296-318 input tokens for one tiny question [T2]). |
| 9 | Questions can be in Russian | **Confirmed, with a caveat the handoff misses** | Accepted [P1]. But "English is the primary training language and where accuracy is currently best. Other languages … are handled but not equally well" [T3][P5]. Russian text also costs more tokens [P1]. |
| 10 | Not chat-completions, so use a small httpx client, not the openai SDK | **Confirmed** | The official TypeSafe SDKs work against polza with base URL `https://polza.ai/api` (no `/v1`) [P1][P4]. The Python SDK drops `cost_rub`, so httpx is still the right choice. |
| 11 | Limits: no images | **Confirmed** | Text only [P2][T3]. |
| 12 | Limits: weak at arithmetic, date comparison, too-literal reading | **Confirmed** | [P3][T4] |
| 13 | Limits: susceptible to instructions hidden in the state | **Confirmed** | "State is data, and jev-1.13 does not treat it as hostile by default" [T4][P3]. |
| 14 | Limits list is complete | **Incomplete** | Missing: **choice option-order bias** (it "leans toward the option that comes first") [T4]; accuracy loss from a large, irrelevant `state` ("context rot") [T4][P3]; double negatives and multi-hop indirection [T4]; contradictions between `instructions` and `criteria` [T4]; numbers in numeric form (hex, RGB) [T4]; English-primary (row 9). |
| 15 | Max questions, state size, rate limits (not stated in handoff) | — | 1-256 questions; `state` ≤ 400,000 chars and `questions` ≤ 400,000 chars on polza; context 32k tokens for state plus the longest question, 64k for state plus all questions; choice ≤ 255 options; score 2-10 levels [P3][P4][T3]. Rate limits in the next section. |
| 16 | "TypeSafe paused direct sign-ups on 2026-09-22" (§15.5) | **Confirmed but stale** | The pause happened on 2026-09-22 [S1]. Sign-ups **reopened on 2026-09-27**, without the $5 free credit [S2]. Both are secondary sources. |
| 17 | "polza still serves it" (§15.5) | **Confirmed from docs; not live-tested** | The polza catalog lists `typesafe/jev` with provider `typesafe` at 17.56 ₽ per 1M input tokens [P5]. The docs index has the three Jev guides and the `/systemone` reference [P8]. No deprecation notice from polza or TypeSafe was found. |
| 18 | Jev is "new, proprietary" | **Confirmed** | Launched 2026-09-15 in early access [T1]. Only one weights version serves every account; there is no fine-tuning [T3]. |

## Request shape

`POST https://polza.ai/api/v1/systemone`, `Authorization: Bearer $POLZA_API_KEY`, `Content-Type: application/json` [P4].

| Field | Type | Required | Notes |
|---|---|---|---|
| `model` | string | yes | `typesafe/jev`, `jev-latest`, `jev-preview`, `jev-1.13.0` [P4] |
| `state` | string, object or array | yes | ≤ 400,000 chars. Text only [P4]. An object with named fields is recommended: questions can point at a field by putting its path in backticks, e.g. `` `ticket.messages[0].text` `` [P2]. |
| `questions` | object `{name: Question}` | yes | 1-256 questions. **The model never sees the key name**, so all meaning must be in `instructions` [P2][T2]. |
| `provider` | object | no | polza provider routing [P4]. Jev has only one provider (`typesafe`) [P5], so this gives no failover. |

Question object [P4][T2]:

| `type` | `instructions` | `criteria` |
|---|---|---|
| `noul` | string, object or array | optional `{"true": desc, "false": desc}` |
| `choice` | string, object or array | **required**: `{option_key: desc or null}`, ≤ 255 options. A desc may be an object (e.g. `what` / `not_for` / `examples`) |
| `score` | string, object or array | **required**: an ordered **array** of 2-10 level descriptions, lowest first |

Structured `instructions` are allowed: put the question in one field and the data it refers to in other fields, then reference them in backticks [T2].

Example. This is Aivita-shaped, built from the documented shapes and not executed:

```json
{
  "model": "typesafe/jev",
  "state": {
    "recent_turns": [
      {"from": "Anya", "text": "Сижу на созвоне, потом напишу"},
      {"from": "Aivita", "text": "Хорошо!"}
    ],
    "candidate_thought": "Спросить Аню, поправился ли её папа"
  },
  "questions": {
    "natural_now": {
      "type": "noul",
      "instructions": "Would saying `candidate_thought` to the person right now feel natural, given `recent_turns`?"
    },
    "absorbed": {
      "type": "score",
      "instructions": "How absorbed in something else is the person in `recent_turns`?",
      "criteria": [
        "Free and chatting",
        "Doing something but can talk briefly",
        "Busy with a call, meeting or focused work"
      ]
    },
    "reaction": {
      "type": "choice",
      "instructions": "How did the person react to Aivita's last message in `recent_turns`?",
      "criteria": {"loved": null, "liked": null, "neutral": null, "ignored": null, "annoyed": null}
    }
  }
}
```

## Response shape

From the polza reference [P4] and guide [P1]. TypeSafe's own shape is the same minus `cost_rub` [T2].

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_urgent": { "type": "noul", "noul": 0.98 },
    "department": {
      "type": "choice",
      "choice": "billing",
      "confidence": 0.62,
      "probabilities": { "billing": 0.74, "technical": 0.26, "sales": 0.0 }
    },
    "frustration": {
      "type": "score",
      "score": 0.9,
      "confidence": 0.84,
      "legend": { "0": "Спокоен, просто описывает ситуацию", "1": "Раздражён, но вежлив", "2": "Очень зол, резкие выражения" },
      "probabilities": { "0": 0.1, "1": 0.9, "2": 0.0 }
    }
  },
  "usage": { "input_tokens": 633, "output_tokens": 73, "cost_rub": 0.0133 }
}
```

- `model`: the version that answered. TypeSafe advises logging it, and pinning the versioned ID if confidence thresholds were tuned against it, because aliases move [T3][P3].
- `usage.input_tokens` (billed), `usage.output_tokens` (free), `usage.cost_rub` (nullable) [P4].
- Errors use polza's standard format: `error.code`, `error.message`, `trace_id`, plus a TypeSafe-shaped `detail: {error_type, message}`. Statuses: 400 (validation, including TypeSafe's 422, or context exceeded), 401, 402 (`insufficient_balance`), 429, 503 [P4]. polza does not charge for failed requests [P7]. polza does not store or log request or response texts [P4][P6].

## Question types and semantics

- **`noul`** returns P(yes), from 0 to 1. Values near 0.5 mean "can't decide", not "medium": it is not a scale [P2][T6]. There is **no separate confidence**. TypeSafe's equivalent is `|2p − 1|` [T5]. Phrase the question so that a high value means "yes". Don't swap the meaning of `true` and `false` [P2][T4].
- **`choice`** returns the winning key, `probabilities` over all options (summing to 1), and `confidence = (p_max − 1/n) / (1 − 1/n)`, where n is the number of options [T5][P2]. Add an `other` / "not stated" option whenever the list may not cover every case [P2][P3].
- **`score`** returns `score = Σ i·p_i`, the expected level index in `[0, levels−1]`; `probabilities` per level (keys `"0"`…); `legend`; and `confidence = max(0, 1 − Σ p_i·|i − peak| / MAD_uniform)` [T5][T2]. The same `score` can come from different distributions, so read it together with `confidence` [P2]. Each level is judged on its own: phrases like "worse than the previous level" don't work. Use the score for thresholds and sorting, not for interpolating exact magnitudes [P2][P3][T4].
- Questions in one request run **in parallel and independently**, so one answer never sees another [P2]. A second request is justified only when its questions depend on the first one's answers [P2].
- Recommended use of confidence: three bands (act / act carefully / don't act), with **different thresholds per action according to the cost of an error**, tuned on labelled data [P1][T5].

## Billing

- polza price: **17.56 ₽ per 1M input tokens**; output is free; context 64K [P5]. TypeSafe's direct price: **$0.042 per 1M input tokens**, output free [T1][T3].
- About 280 overhead input tokens per request [P1][P4]. Ten questions in one request cost much less than ten single-question requests [P1].
- The polza doc examples work out to about 21 ₽ per 1M (0.0133 ₽ / 633 tokens; 0.0115 ₽ / 548 tokens) [P1][P4]. So the price has moved since those examples were written. Treat the catalog page [P5] and per-call `cost_rub` as the truth.
- Order of magnitude for Aivita: a batched decision with about 1,500 input tokens costs about 0.03 ₽.

## Limits

| Limit | Value | Source |
|---|---|---|
| Questions per request | 1-256 | [P4][P3] |
| `state` size on polza | ≤ 400,000 chars (same for `questions`) | [P3][P4] |
| Context | 32k tokens for `state` plus the longest question; 64k for `state` plus all questions | [P3][T3] |
| Choice options | ≤ 255 | [P4][T2] |
| Score levels | 2-10 | [P4][T2] |
| Input | Text only (string, JSON object, array) | [P2][T3] |
| TypeSafe rate limits | 100K tokens/s and 80 requests/s per account, "adjusting dynamically … can change without notice" | [T3] |
| polza rate limits | Per-organisation, per-model requests per minute and per day. The numbers are not published. A polza 429 carries `Retry-After`; a provider 429 does not (back off 1, 2, 4, 8 s) | [P7] |
| polza request timeout | 600 s | [P7] |
| Latency | TypeSafe: "70ms-500ms" end to end, measured from the US West Coast [T1]. polza: "about a second, however many questions" [P1] | [T1][P1] |

## Language support

- English is the primary training language and has the best accuracy. Other languages are "handled but not equally well". TypeSafe says to test on your own content and watch confidence when routing [T3]. polza's catalog page repeats this [P5].
- polza says questions and criteria may be written in Russian [P1], and its examples are Russian (the urgency example scores 0.98) [P1][P6].
- Russian text costs more tokens than English text of the same length [P1].
- **Unverified:** whether English `instructions` and `criteria` over a Russian `state` beat all-Russian questions. Nothing published measures this.

## Known weaknesses

All are from TypeSafe's own list for jev-1.13 [T4], mirrored in polza's guide [P3]:

1. Literal reading: negations, scoping words and implied conditions are taken at face value.
2. Counting, arithmetic and number comparison. Numeric representations (hex, RGB) do worse than named ones.
3. Date and time comparison. Extract the parts with `choice`, then compare in code.
4. Double negatives and multi-hop "property of a property" questions.
5. Large `state` full of irrelevant detail ("Jev suffers from context rot").
6. Adversarial content in `state` can move the answer. Prompt injection is not neutralised by default.
7. Contradictions between `instructions` and `criteria`.
8. **Choice option order: leans toward the first option.** The advice is to reorder the options and check the answer stays the same.
9. No text generation.

Also: the answer's shape is guaranteed but its correctness is not ("it can pick the wrong option") [P6]. There is no textual rationale [P6]. The speed and cost comparisons are TypeSafe's own, with no independent reproduction as of 2026-09-18 [P6], and TypeSafe itself flags evaluation bias [T1].

## Availability and deprecation

- **2026-09-15**: TypeSafe launches Jev (`jev-1.13.0`) in early access with a waitlist [T1].
- **2026-09-14 to 09-26**: TypeSafe Python SDK releases 0.5.7 to 0.7.2, active development [T8].
- **2026-09-20**: waitlist removed and sign-ups opened with $5 credit [S1].
- **2026-09-22**: new direct sign-ups paused because of demand; existing accounts kept working [S1].
- **2026-09-27**: sign-ups reopened, without the free credit for new users [S2].
- **polza**: serves Jev with a polza key and no TypeSafe account, paid in rubles [P1][P6]. Requests are forwarded to TypeSafe, whose service runs in a single US West Coast region [P6]. The only provider is `typesafe`. "Данные в РФ" and 152-ФЗ are both marked "—" [P5].
- **Deprecation**: none found. TypeSafe's models page lists only Jev 1.13; `jev-preview` points at the same build and "there is no preview build available right now" [T3]. The jaggedness page (reviewed 2026-10-02) says several weaknesses "will be fixed in later versions" [T4]. Expect alias moves, not removal.
- **Data handling**: TypeSafe does not train on customer requests [T3]. Zero data retention is enterprise-only [T9]. The DPA only says personal data is kept "for as long as necessary" [T9]. polza does not log the texts [P4].

## Does the handoff's `Q` / `A` / `Decider` interface map cleanly?

Not quite. There are five mismatches:

1. `Q.criteria: dict[str, str] | None` can't express a score (an ordered list), a `null` option description, or a structured description.
2. `A.value` for score is documented as 0..1. Jev returns 0..levels−1. §6.4's `thought_evaluation` is "the mean of the Decider's factor scores", so mixing raw scores from scales of different lengths would be wrong. polza's recipe explicitly normalises them [P3].
3. `A.confidence: float` is required, but Jev returns none for `noul`. `A.probabilities` is also absent for `noul`.
4. `decide(state: str, …)`: Jev accepts and recommends a structured object, with backtick paths in questions [P2].
5. The `dict[str, A]` return loses the answering model version, token usage, `cost_rub` and which backend actually answered after a fallback. §5 stores `decider_backend` in the decision trace and `cost_rub` per call, so the caller needs them.

Proposed correction (`llm/decider.py`):

```python
class Q(BaseModel):
    kind: Literal["noul", "choice", "score"]
    instructions: str | dict | list            # structured instructions allowed
    criteria: dict[str, str | dict | None] | list[str | dict] | None = None
    # noul:   optional {"true": ..., "false": ...}
    # choice: required {option: description | None}, 1..255 options
    # score:  required ordered list of level descriptions, 2..10, lowest first

class A(BaseModel):
    kind: Literal["noul", "choice", "score"]
    value: float | str            # noul: P(yes) 0..1 · choice: option key · score: normalised 0..1 = raw / (levels-1)
    raw_score: float | None = None    # score only: 0..levels-1 as returned
    confidence: float             # choice/score: backend value; noul: derived |2p-1| (Jev returns none)
    probabilities: dict[str, float] | None = None  # choice: per option; score: per level "0".."n-1"; noul: None

class Decision(BaseModel):
    answers: dict[str, A]
    backend: Literal["jev", "llm", "fake"]
    model: str                    # e.g. "jev-1.13.0" from the response
    input_tokens: int
    cost_rub: float | None        # nullable on polza

class Decider(Protocol):
    async def decide(self, state: str | dict | list, questions: dict[str, Q], *,
                     purpose: str, correlation_id: str) -> Decision: ...
```

Consequences for the backends and the confidence policy:

- `JevDecider` validates the limits before sending: ≤ 256 questions, ≤ 255 options, 2-10 levels, `state` ≤ 400k chars. It normalises `score`, derives the `noul` confidence, and records `model` and `cost_rub`. Fall back on 429, 5xx and timeouts. A 400 is a bug in our request: fall back, but log it as an error. A 402 (no balance) would hit the polza-based `LLMDecider` too, so it should go to the budget logic, not to the fallback.
- `LLMDecider` must return the same shapes. It should compute `confidence` with TypeSafe's formulas [T5] from its own probabilities, so that the `hi` / `lo` policy means the same thing on both backends.
- Confidence policy: for `noul`, `confidence ≥ 0.8` means `p ≥ 0.9` or `p ≤ 0.1`. TypeSafe and polza both recommend **per-gate thresholds by cost of error**, not one global pair [P1][T5]. The global `hi = 0.8`, `lo = 0.5` is fine as a start, but should allow per-purpose overrides.
- Choice order bias [T4] matters for `told_by` (speaker order) and the `pending_memory` label. For safety-relevant choices, shuffle the options, or re-ask with reversed order when confidence is in the middle band.
- Pin `jev-1.13.0` in config once thresholds are tuned, rather than `typesafe/jev`, because the alias moves [T3][P3].
