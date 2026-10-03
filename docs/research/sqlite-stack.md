# SQLite stack: FTS5, sqlite-vec, licences

Research for [#6](https://github.com/unkier/aivita/issues/6), 2026-10-03. It checks [handoff](../handoff.md) §5 (`memory_fts`, `memory_vec`, the privacy wall in recall) and the §11 dependency list against the §2 licence posture.

Every FTS5 and sqlite-vec claim below was run, not just read. The throwaway scripts were a uv project in `/tmp`, run on **both** interpreters on this Arch box:

| Interpreter | Python | SQLite inside `sqlite3` | How it is linked | `enable_load_extension` |
|---|---|---|---|---|
| uv-managed (python-build-standalone, uv 0.10.0) | 3.14.3 | **3.50.4** | built into the interpreter | **available, works** |
| Arch system `/usr/bin/python3` | 3.14.7 | **3.53.4** | `lib-dynload/_sqlite3…so` → system `libsqlite3` | **available, works** |

Both builds report `ENABLE_FTS5`, `ENABLE_FTS4`, `ENABLE_RTREE`, `ENABLE_MATH_FUNCTIONS`, `THREADSAFE=1`. Every script printed identical results on both; only the version lines and timings differed. Versions tested: **sqlite-vec 0.1.9** (`vec_version()` → `v0.1.9`, the latest stable; 0.1.10 is alpha), **PyStemmer 3.1.0**.

## Short answer

- The stack works on Python 3.14, with uv-managed CPython and with Arch's system CPython. Both include FTS5 and both allow loading extensions. sqlite-vec ships `py3-none` wheels (a loadable `.so`, not tied to the Python ABI), so 3.14 needs no special wheel.
- **The trigram tokenizer does not make «собака» match «собаки».** It matches substrings, not word forms. It does fold Cyrillic case. It matches nothing for terms under 3 characters. It does not fold «ё» to «е».
- **Snowball stemming on both sides, over `unicode61`, is the better FTS.** It got 14 of 16 test queries exactly right; trigram got 4 of 16. **Recommendation: stemming only, no trigram.**
- sqlite-vec metadata filters are applied *during* KNN: you get k rows back, all of them past the filter. `=`, `!=`, range operators and (undocumented) `IN` are pushed down. **`OR` across two columns is not pushed down.** SQLite then filters the k rows after the search, so results go missing silently (0 of 10 rows in one test). The privacy wall therefore has to be one `IN` on one column, or a UNION of KNN queries that are each pushed down.
- Licences: every core dependency is MIT, BSD or Apache, with **one exception: the tinyaisense SDK (and `tinyaisense-wire`) has no licence at all.** trafilatura is Apache-2.0 since v1.8.0 and was GPLv3+ before. There is one tri-licensed transitive dependency, `tld` (MPL-1.1 / GPL-2.0 / LGPL-2.1), which we take under MPL-1.1. Don't install `trafilatura[all]` or `fastapi[standard]`.

## Claims checked

| # | Claim (source) | Verdict | Evidence |
|---|---|---|---|
| 1 | FTS5 is available in stdlib `sqlite3` on 3.14 | **Confirmed** on both interpreters | `pragma compile_options` lists `ENABLE_FTS5` |
| 2 | `trigram` tokenizer exists (FTS5 docs; added in SQLite 3.34.0) | **Confirmed** | tables created on 3.50.4 and 3.53.4 |
| 3 | Trigram folds case for Cyrillic (`case_sensitive 0` is the default) | **Confirmed** | `собака` / `СОБАКА` / `Собака` → row 1 |
| 4 | Trigram fixes «собака» vs «собаки» (handoff §5 implies it) | **Wrong** | `MATCH 'собака'` → [1], `MATCH 'собаки'` → [2]. Only the shared substring `собак` finds all three forms |
| 5 | Terms under 3 characters match nothing (FTS5 docs) | **Confirmed**, and worse than it sounds | `MATCH 'да'` → []. `"собак" AND "да"` → [] (one short term empties the whole AND) |
| 6 | Trigram indexes LIKE and GLOB (FTS5 docs) | **Confirmed, with a trap** | the plan shows `INDEX 0:L0` / `0:G0`. But LIKE keeps SQLite's ASCII-only case folding: `LIKE '%собак%'` misses «Собака», and `LIKE '%СОБАК%'` → [] |
| 7 | LIKE is not indexed with `case_sensitive 1`, `remove_diacritics 1`, or an `ESCAPE` clause (FTS5 docs) | **Confirmed** | the plan drops to `INDEX 0:` in all three cases |
| 8 | `remove_diacritics` folds «ё»→«е» | **Wrong** (the docs say Latin script only) | `елку` misses `Ёлку` under trigram `remove_diacritics 1` and under `unicode61 remove_diacritics 2`. Fold it in Python |
| 9 | Plain `unicode61` won't match «собака» to «собаки» (handoff §5) | **Confirmed** | `plain` column in script (b) |
| 10 | Snowball-stemming both sides fixes inflection (handoff §5) | **Confirmed** | `собакой`, `СОБАКИ`, `Анной`, `ёлки`, `happiness` all hit. Fails only on suppletion (`пёс`/`псами`) and on derivation across parts of speech (`работа`/`работает`) |
| 11 | sqlite-vec has wheels for 3.14 | **Confirmed** | `sqlite_vec-0.1.9-py3-none-manylinux…x86_64.whl` (also aarch64, macOS, win_amd64; no musllinux) |
| 12 | Extensions load from stdlib `sqlite3` | **Confirmed** on both | `enable_load_extension(True)`; `sqlite_vec.load(db)`; `vec_version()` → `v0.1.9` |
| 13 | vec0 metadata filters run during KNN, not after (sqlite-vec docs) | **Confirmed** | a filter that keeps 50 of 5,000 vectors still returned 10 rows for `k = 10` |
| 14 | Operators pushed into KNN: `= != > >= < <=` (docs) | **Confirmed, plus `IN`** (not in the docs) | `told_by in (?, ?)` shows up in the plan as `&Bg_`. In `c2`, `audience in (9, -1)` returns exactly the brute-force top-10 over the visible rows |
| 15 | OR inside a KNN filter | **Not pushed down: rows silently lost** | `(told_by = 9 or shareable = 1)` → **0 rows** where 10 exist. SQLite rewrites `(a = x or a = y)` on *one* column to `IN`, and that one works |
| 16 | Partition key filters | **Only `=` is pushed down** (docs). `IN` runs one KNN per value | `audience in (9, -1)` with `k = 10` → 20 rows, so wrap the query in `order by distance limit k` |
| 17 | vec0 writes are transactional with ordinary tables | **Confirmed** | a rollback removed both the `memory` row and the `memory_vec` row |
| 18 | Upsert on vec0 | **Not supported** | `INSERT OR REPLACE` → `UNIQUE constraint failed on memory_vec primary key`. Use `UPDATE` (metadata and vectors) or `DELETE` + `INSERT` |
| 19 | Dimensions are enforced | **Confirmed** | `Dimension mismatch … Expected 8 dimensions but received 9` |
| 20 | All core dependencies are permissive (handoff §2) | **Mostly. tinyaisense is the exception** | see [Licences](#licences) |

## Script outputs

### (a) FTS5 trigram, Russian + English (`a_trigram.py`)

The rows were 1 «Собака Дмитрия любит гулять в парке», 2 «У сестры Ани две собаки и кот», 3 «…о собаке соседа», 4 «Ёлку поставили…», 5 "The dog barked…", 6 "Dogs are friendly; DOGGY day care", 7 «Пёс убежал, псы лаяли…», 8 «Он сказал да и ушёл», 9 "Café crème brûlée".

```
python 3.14.3 | sqlite 3.50.4
ENABLE_FTS5 compiled in: True

-- MATCH on trigram (case_sensitive 0) --
MATCH 'собака'     -> [1]
MATCH 'СОБАКА'     -> [1]
MATCH 'собаки'     -> [2]
MATCH 'собак'      -> [1, 2, 3]
MATCH 'собаке'     -> [3]
MATCH 'ёлку'       -> [4]
MATCH 'елку'       -> []
MATCH 'dogs'       -> [6]
MATCH 'да'         -> []
MATCH 'cafe'       -> []

-- remove_diacritics 1 (does ё fold to е? does é fold to e?) --
t_rd MATCH 'елку'   -> []
t_rd MATCH 'cafe'   -> [9]

-- LIKE / GLOB (results + whether index is used) --
t     text LIKE '%собак%'               -> [2, 3]   plan=['SCAN t VIRTUAL TABLE INDEX 0:L0']
t     text LIKE '%СОБАК%'               -> []       plan=['SCAN t VIRTUAL TABLE INDEX 0:L0']
t     text LIKE '%DOG%'                 -> [5, 6]   plan=['SCAN t VIRTUAL TABLE INDEX 0:L0']
t     text LIKE '%да%'                  -> [3, 8]   plan=['SCAN t VIRTUAL TABLE INDEX 0:L0']
t     text GLOB '*Собака*'              -> [1]      plan=['SCAN t VIRTUAL TABLE INDEX 0:G0']
t     text LIKE '%собак%' ESCAPE '\'    -> [2, 3]   plan=['SCAN t VIRTUAL TABLE INDEX 0:']
t_cs  text LIKE '%собак%'               -> [2, 3]   plan=['SCAN t_cs VIRTUAL TABLE INDEX 0:']
t_rd  text LIKE '%собак%'               -> [2, 3]   plan=['SCAN t_rd VIRTUAL TABLE INDEX 0:']

-- Mixed query with a <3-char term: the short term zeroes an AND --
MATCH "собак" AND "да"     -> []
MATCH "собак" OR "да"      -> [1, 2, 3]

-- ё/е: normalise in Python on both sides (index a folded copy) --
t_norm MATCH norm('елку') -> [4]
t_norm MATCH norm('Ёлку') -> [4]

-- Index size on a 5,000-row synthetic RU/EN corpus --
big_tri: index  1009784 bytes  (raw text 562259 bytes, ratio 1.80)
big_u61: index   164928 bytes  (raw text 562259 bytes, ratio 0.29)
```

The FTS5 docs say a LIKE pattern with fewer than 3 non-wildcard characters falls back to a linear scan of the table. The plan string reads the same either way. A trigram index is about **6× larger** than a `unicode61` index over the same text.

Fuzzy trick (also in `a_trigram.py`): OR together the query's trigrams and rank by `bm25`. This recalls every form, with the exact form ranked first (`собаки` → rows 2, 3, 1). It gets noisy for longer queries and is not needed if stemming is used.

Raw user text must never go into `MATCH` unquoted (`a2_escape.py`). `Аня-сестра` raises `no such column: сестра`, `маме)` raises `fts5: syntax error`, and `OR not` is also a syntax error. Wrap every term in double quotes and double any `"` inside it.

### (b) PyStemmer Snowball over `unicode61` (`b_stemming.py`)

```
собака -> собак   собаки -> собак   собаке -> собак   собакой -> собак
Собачка -> собачк   пёс -> пес   псы -> псы   ёлку -> елк   елка -> елк
друг -> друг   друзья -> друз   люди -> люд   человек -> человек
dogs -> dog   running -> run   ran -> ran   mice -> mice
Аня -> ан   Ани -> ан   Анной -> ан

query        plain      plain prefix*  stemmed
собака       [1]        [1, 2, 3]      [1, 2, 3]
собаки       [2]        [1, 2, 3]      [1, 2, 3]
СОБАКЕ       [3]        [1, 2, 3]      [1, 2, 3]
собакой      []         []             [1, 2, 3]
dogs         [6]        [5, 6]         [5, 6]
елку         []         []             [4]
Анне         []         []             [2, 10]
переезд      []         []             []
да           [8]        -              [8]
```

`stem_text` lowercases with `casefold()`, folds «ё» to «е», and picks the Russian or English stemmer per token by script (Cyrillic or not). The Snowball Russian stemmer already folds «ё» itself (`stemWord('пёс')` → `пес`), so the explicit fold only keeps the input consistent.

Precision caveat: short words collapse to very short stems (`Аня` → `ан`). `ИИ` → `и`, which collides with the conjunction «и», so that query would match nearly every Russian memory. For stems under 2 to 3 characters, either drop the term (when other terms are present) or match the unstemmed word.

### (d) Head-to-head on 16 queries (`d_compare.py`)

| Strategy | Exact hits |
|---|---|
| trigram, query as typed (lowercased, ё→е) | **4 / 16** |
| Snowball stem both sides, `unicode61` | **14 / 16** (misses `работа`→«работает», `псами`→«псы») |
| trigram over the folded text, query = raw OR its stem | 11 / 16 (fails whenever the stem is under 3 characters: `Ане`→`ан`, `да`; English stems such as `happi` are not substrings of "happy") |

### (c) sqlite-vec: loading, vec0, filtered KNN (`c_vec.py`, `c2_in_or.py`)

```
python 3.14.3 /tmp/aivita-sqlite-research/.venv/bin/python3
sqlite 3.50.4
has enable_load_extension: True
vec_version(): v0.1.9

== Wall for viewer ANYA, single equality: told_by = ANYA ==
[told_by=] plan=['SCAN memory_vec VIRTUAL TABLE INDEX 0:3{___}___&Ba_&Df_', ...]
     (2, 0.0017, 2, 0, 'Anya is secretly afraid of big dogs')
     (4, 1.3036, 2, 0, "Anya's medical test on Friday")

== Wall as OR: (told_by = ANYA or shareable = 1) ==
[OR] plan=['SCAN memory_vec VIRTUAL TABLE INDEX 0:3{___}___&Df_', ...]   <- told_by/shareable NOT in the plan
     (1, 0.001, 1, 1, "Dmitrii's dog Bim loves the park")
     (2, 0.0017, 2, 0, 'Anya is secretly afraid of big dogs')
     (5, 0.0034, 3, 1, 'Oleg walks dogs as a volunteer')            <- row 4 silently missing

== Pre-filter, not post-filter: k rows come back even when the filter is selective ==
told_by=9 owns 50 of 5000 vectors; KNN k=10 with filter returned 10 rows
same filter written with OR returned 0 rows

-- c2: one denormalised column `audience` (= told_by, or -1 when shareable) --
m audience in (9, -1)              -> 10 rows, all visible=True  plan=[... &Ag_&Ba_]
m (audience = 9 or audience = -1)  -> 10 rows, all visible=True  plan=[... &Ba_&Ag_]   (SQLite rewrote OR to IN)
p audience in (9, -1)  [partition key] -> 20 rows (k per value)  plan=[... ]Aa_&Aa_]
IN result equals brute-force top-10 over visible rows: True

== Transactions: vec0 rows roll back with the memory row ==
after rollback: memory rows 0 | memory_vec rows 0
== Update / upsert ==
metadata UPDATE ok; shareable now: 1
INSERT OR REPLACE -> UNIQUE constraint failed on memory_vec primary key

== Brute-force KNN timing (float32, cosine, 20k vectors, k=20) ==
dim=1024 n=20000 no filter   : 20.9 ms/query
dim=1024 n=20000 told_by = 3 : 8.8 ms/query
dim=2560 n=20000 no filter   : 54.0 ms/query
dim=2560 n=20000 told_by = 3 : 25.1 ms/query
```

Vector types: `float[N]` (float32), `int8[N]` and `bit[N]`, built with `vec_f32()`, `vec_int8()` and `vec_quantize_binary()`. `sqlite_vec.serialize_float32(list)` packs a Python list into a blob. The metric is chosen per column, e.g. `distance_metric=cosine` (the default is L2). vec0 in 0.1.9 is **brute force**: an exact KNN over every vector that passes the filter. ANN indexes (DiskANN, IVF, rescore) are only in the 0.1.10 alphas. A 2560-dim float32 vector (e.g. `qwen3-embedding-4b`) costs 10 KB, so 100k memories take about 1 GB and about 0.27 s per unfiltered query by linear extrapolation. That is fine for one home. It is worth revisiting dims or `int8` once [#2](https://github.com/unkier/aivita/issues/2) settles the embedding model.

## Recommendation

### Full-text: Snowball stemming on both sides, no trigram

```sql
-- contentless_delete needs SQLite >= 3.43 (we have 3.50.4 / 3.53.4); rowid = memory.id
create virtual table memory_fts using fts5(
  stems, tokenize = 'unicode61', content = '', contentless_delete = 1
);
```

```python
RU, EN = Stemmer.Stemmer("russian"), Stemmer.Stemmer("english")
CYR, TOKEN = re.compile(r"[а-яё]", re.I), re.compile(r"\w+")

def stem_text(s: str) -> str:            # used on insert AND on every query
    toks = TOKEN.findall(s.casefold().replace("ё", "е"))
    return " ".join(RU.stemWord(t) if CYR.search(t) else EN.stemWord(t) for t in toks)

def fts_query(s: str) -> str:            # OR of quoted stems; never raw user text
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(stem_text(s).split()))
```

Why:

- It handles Russian inflection, which is the actual problem. Trigram does not.
- Two-letter words (`да`) and short names still work. Watch out for one-letter stems (see the caveat above).
- The index is about 6× smaller.
- No custom tokenizer is needed. That matters because stdlib `sqlite3` cannot register an FTS5 tokenizer written in Python, so stemming has to happen in Python on both sides anyway.

The contentless table keeps only the index. Snippets and highlights come from `memory.text`, never from FTS. `bm25()` still works.

Accepted misses: suppletion (`пёс`/`псы`, `человек`/`люди`) and derivation across parts of speech (`работа`/`работает`). Vector search covers these, and cross-language matches too, through the RRF merge. Add a second, trigram, table only if substring or partial-name lookups turn out to matter in practice. Do not add it up front.

### sqlite-vec: filtered KNN shape for the privacy wall

The final rule belongs to [#11](https://github.com/unkier/aivita/issues/11). Whatever it is, it must reach the vec0 query as `=`/`IN`/range constraints on **one** metadata column per condition, never as `OR` across columns. With today's §5 rule ("told by the current person, or shareable"), denormalise it into one column:

```sql
create virtual table memory_vec using vec0(
  memory_id integer primary key,           -- = memory.id
  embedding float[2560] distance_metric=cosine,
  audience integer,                         -- told_by, or -1 when shareable (UPDATE it when shareable flips)
  state text                                -- 'active' | 'fading' | 'lost'
);

select memory_id, distance
from memory_vec
where embedding match :q and k = :k
  and audience in (:viewer, -1)             -- pushed down: exact top-k among visible rows
  and state != 'lost';
```

If the rule ends up needing two independent columns, run one pushed-down KNN per branch and merge them:

```sql
with mine   as (select memory_id, distance from memory_vec where embedding match :q and k = :k and told_by = :viewer),
     shared as (select memory_id, distance from memory_vec where embedding match :q and k = :k and shareable = 1)
select memory_id, min(distance) as distance
from (select * from mine union all select * from shared)
group by memory_id order by distance limit :k;
```

On the FTS side, the wall is a plain join to `memory`. FTS5 returns *every* match, not a top-k, so a `WHERE` on the joined row is exact. `f_recall.py` ran the whole recall end to end: stemmed FTS + vec0 behind the wall, fused by RRF (`1/(60 + rank)`), then the wall checked again on the `memory` rows. Anya querying «собаки» never saw Dmitrii's surprise-puppy memory; Dmitrii did.

Other vec0 facts the schema has to live with:

- The dimension is fixed when the table is created. Changing the embedding model means a new table and re-embedding everything, so store the model id (§4.3), e.g. as a metadata column or in `memory`.
- Limits: at most 16 metadata columns and 4 partition keys.
- Boolean metadata supports only `=` and `!=`.
- Text metadata longer than 12 characters is slightly slower. 0.1.9 also fixed a DELETE bug on such columns, so **require `sqlite-vec>=0.1.9`**.
- No upsert. Writes share the surrounding transaction, so insert into `memory`, `memory_fts` and `memory_vec` in one transaction.
- Keep `enable_load_extension(False)` after `sqlite_vec.load(db)` so nothing else can be loaded.
- Do not use a partition key for the wall. Only `=` is pushed down, `IN` multiplies k, and the docs warn against partitions with fewer than "100's of vectors" each.

## Licences

Resolved by `uv sync` on Python 3.14 on 2026-10-03. Every package installed from a cp314 or pure-Python wheel except tinyaisense, which was built locally from a copy of the SDK. Licence data comes from each wheel's `License-Expression` / `License` metadata and licence files, cross-checked against the GitHub repo licence.

| Package | Version | Licence | Notes |
|---|---|---|---|
| openai | 3.24.0 | Apache-2.0 | repo `openai/openai-python` Apache-2.0. Uses `httpx2` (BSD-3), not `httpx` |
| openai-agents | 0.23.1 | MIT | repo MIT. Hard deps include `mcp` (MIT), `requests` (Apache-2.0), `griffelib` (ISC) |
| pydantic | 2.13.5 | MIT | `pydantic-core` MIT |
| sqlite-vec | 0.1.9 | MIT OR Apache-2.0 | dual-licensed (repo `LICENSE-MIT` + `LICENSE-APACHE`). The wheel ships no licence file |
| fastapi | 0.142.2 | MIT | `starlette` BSD-3. **Hard-depends on `opentelemetry-api`** (Apache-2.0, a no-op without an SDK) |
| uvicorn | 0.54.0 | BSD-3-Clause | `[standard]` extras are all permissive: uvloop, httptools, watchfiles, python-dotenv, pyyaml, websockets |
| httpx | 0.28.1 | BSD-3-Clause | `httpcore` BSD-3, `h11` MIT, `certifi` **MPL-2.0** (see below) |
| trafilatura | 2.3.0 | **Apache-2.0 since v1.8.0** (released 2024-03-20) | **GPLv3+ before v1.8.0** (README: "Versions prior to v1.8.0 are under GPLv3+ license"; the v1.8.0 notes say "License changed to Apache 2.0"). Its dependencies changed the same way: `htmldate` Apache-2.0 since 1.8.0 (GPLv3+ before), `courlan` Apache-2.0 since v1 (GPLv3+ before). 2.3.0 pins `courlan>=1.4.0` and `htmldate>=1.11.0`, so the resolver cannot pick the GPL versions. **Pin `trafilatura>=2.3`.** `justext` BSD-2, `lxml` BSD-3, `dateparser` BSD-3, `babel` BSD-3 |
| PyStemmer | 3.1.0 | MIT (wrapper) + BSD-3-Clause (bundled Snowball `libstemmer_c`) | both texts are in the wheel's `LICENSE`. GitHub shows NOASSERTION because one file holds two licences |
| Snowball algorithms / data | (inside PyStemmer) | BSD-3-Clause | "copyright (c) 2001-2006, Dr Martin Porter and Richard Boulton, … licensed under the BSD license". Repo `snowballstem/snowball` is BSD-3-Clause |
| pytest | 9.1.1 | MIT | `pluggy` MIT, `iniconfig` MIT, `packaging` Apache-2.0 OR BSD-2, `pygments` BSD-2 |
| pytest-asyncio | 1.4.0 | Apache-2.0 | |
| time-machine | 3.5.1 | MIT | works on 3.14 (travel smoke test passed) |
| **tinyaisense SDK** (`packages/sdk`) and **tinyaisense-wire** | 0.1.0 | **None** | **No `LICENSE` file in the repo (HEAD `442045a`), no `license` field in either `pyproject.toml`, GitHub API `license: null`.** A public repo without a licence is "all rights reserved". Its own dependencies are fine: `websockets` BSD-3; extras `mcp` MIT, `openai-agents` MIT |

### Transitive and optional risks

| Package | Pulled in by | Licence | Risk |
|---|---|---|---|
| `tld` 0.13.2 | `courlan` ← trafilatura (hard dep) | **MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later** | The only GPL in the core tree, and it is one option of a tri-licence. Take it under **MPL-1.1**: a file-level copyleft that only bites if we modify `tld` itself. Fine as an unmodified dependency |
| `certifi` | httpx, requests, trafilatura | MPL-2.0 | File-level weak copyleft, unmodified use. Standard everywhere; no action |
| `regex` | dateparser ← htmldate | Apache-2.0 AND CNRI-Python | permissive |
| `typing-extensions` | most | PSF-2.0 | permissive |
| `pycurl` | **`trafilatura[all]` only** | LGPL-2.1-only OR MIT | take it under MIT, or just don't install `[all]` |
| `faust-cchardet` | **`trafilatura[all]` only** | MPL-1.1 OR GPL-2.0-or-later OR LGPL-2.1-or-later | don't install `[all]` |
| `sentry-sdk`, `opentelemetry-sdk`, OTLP exporter | **`fastapi[standard]`** (through `fastapi-cloud-cli`) | MIT / Apache-2.0 | The licences are fine, but this is telemetry tooling, against §14 "No telemetry". Depend on plain `fastapi` |

Not a Python dependency of Aivita, but relevant to §2: the tinyaisense hub's Russian TTS voice (Silero v5) is CC BY-NC 4.0, non-commercial, per the tinyaisense README. It runs in the hub process, not in Aivita, so this repo's licence posture is unaffected.

Everything else in the resolved tree (67 packages) is MIT, BSD-2/3, Apache-2.0, ISC, 0BSD or MIT-0.

## Sources

- SQLite FTS5: https://sqlite.org/fts5.html (§4.3.1 Unicode61 Tokenizer, §4.3.4 The Trigram Tokenizer, §4.4.2 Contentless-Delete Tables, "as of version 3.43.0")
- SQLite release history: https://sqlite.org/changes.html (trigram added in 3.34.0; `remove_diacritics=2` in 3.27.0)
- sqlite-vec: https://github.com/asg017/sqlite-vec, `site/features/vec0.md` (metadata, partition and auxiliary columns, supported operators), `site/features/knn.md` (KNN shapes, `k =` vs `LIMIT`, `distance_metric`), release notes v0.1.7 to v0.1.10-alpha.4, PyPI `sqlite-vec` 0.1.9 wheels
- PyStemmer: PyPI wheel 3.1.0 `LICENSE`; https://github.com/snowballstem/snowball (BSD-3-Clause)
- trafilatura: https://github.com/adbar/trafilatura README "License" and the v1.8.0 release notes; https://github.com/adbar/courlan and https://github.com/adbar/htmldate READMEs
- Every other licence: the installed wheel metadata (`importlib.metadata`), plus the GitHub repo licence for openai-python, openai-agents-python, pydantic, fastapi, Kludex/uvicorn, encode/httpx, pytest, pytest-asyncio and time-machine
- tinyaisense: local checkout `/home/demon/devel/tinyaisense` at `442045a` and `gh api repos/unkier/tinyaisense`
- Scripts (throwaway, not committed): `/tmp/aivita-sqlite-research/{a_trigram,a2_escape,b_stemming,c_vec,c2_in_or,d_compare,e_contentless,f_recall}.py`, `/tmp/aivita-licences/{dump,smoke}.py`
