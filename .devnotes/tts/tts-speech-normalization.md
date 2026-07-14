# Plan — TTS speech fixes: ordering, splitting, and normalization

**Branch:** `deploy/server`
**Scope:** `server/` only. No frontend file is touched by this plan.
**Companion:** the markdown-rendering work on `deploy/frontend` (commit `36673b8`).

---

## 1. The four bugs

Three were reported; a fourth was found while reading the code. They are **independent**
— in particular #2 is a concurrency bug that no amount of text cleaning would fix.

| # | Symptom | Root cause |
|---|---|---|
| 1 | Markdown symbols (`##`, `**`) are spoken aloud | Nothing strips them. The only sanitization before TTS is `_TTS_STRIP_PATTERNS` (`pipeline.py:712`), which removes language-enforcement boilerplate and nothing else. |
| 2 | **Sentences spoken out of order / jumbled**, worse with longer answers | **`asyncio.create_task` fire-and-forget** at `pipeline.py:770`. See §2. |
| 3 | Long URLs → "individual characters spoken", symbols read out | `.` is a sentence terminator (`pipeline.py:634`), so a URL is **split mid-address** into non-words that the engine spells out. See §3. |
| 4 | Short replies occasionally not spoken at all | `_split_sentences` **silently discards** fragments < 3 chars (`kokoro_tts.py:310`). "OK." / "Yes." can vanish. |

---

## 2. Bug #2 — out-of-order audio (the concurrency bug)

`tts_worker` detects a sentence, then:

```python
task = asyncio.create_task(_synthesize_and_queue(tts_buffer, current_lang))  # :770
self._synthesis_tasks.add(task)
```

`create_task` **does not await**. The loop immediately goes back to collecting the next
sentence and spawns another task. So sentences 1..N synthesize **concurrently**, and each
pushes into `self.state.audio_output` (`:760`) *whenever it finishes*. **Nothing enforces
ordering** — whichever finishes first wins the slot. A short sentence overtakes a long one.

It is worse than a simple reorder. `_synthesize_and_queue` is an `async for` that pushes
**multiple** chunks (one per sub-sentence — `kokoro_tts.py:267-280`), `await`ing the
executor between each. Every `await` is a yield point where a *different* task can push
*its* chunk. So chunks from different sentences can **interleave mid-sentence**.

Note what is *already* serialized, because it confirms the diagnosis: all Kokoro inference
funnels through `_kokoro_executor`, a **`max_workers=1`** pool (`kokoro_tts.py:52`). The
inference is serial; only the **queue pushes** race. The concurrency was therefore never
buying throughput — it was buying a race condition.

### Decision: **sequential synthesis** (confirmed with the user)

`await` each sentence's synthesis before starting the next. Order is then correct by
construction, and barge-in stays simple to reason about. The pipelining "lost" is
illusory given the single-worker executor.

Must preserve: `handle_interrupt` (`pipeline.py:977+`) cancels in-flight synthesis tasks
and drains queues. The awaited call still has to be cancellable — keep it a task that is
tracked in `self._synthesis_tasks` and awaited, rather than a bare inline `await`, so
cancellation on barge-in continues to work exactly as it does now.

---

## 3. Bug #3 — URLs

`SENTENCE_ENDINGS = frozenset('.?!。？！…')` (`:634`) treats a bare `.` as a terminator.
A URL is full of dots:

```
https://example.com/some/long/path
        ^          ^
        cut        cut
```

Kokoro receives `https://example` and `com/some/long/path` as separate utterances.
Fragments that aren't words get spelled out — **that is the "individual characters"
symptom**. Stripping symbols alone would not fix it; the splitter must stop cutting
inside URLs.

### Decision: omit URLs from speech

**Deployment profile: desktop chat app, not a kiosk.** On `deploy/frontend`, links now
render as **ordinary clickable links** (`target="_blank" rel="noopener noreferrer"`). The
URL is visible and one click away on screen, so reading it aloud has no informational
value — it is pure noise. Speak *what the source is*, not its address.

Handle bare URLs (`https://…`, `www.…`) **and** markdown links `[text](url)` → speak
`text`, drop the URL. Both EN and JA.

---

## 4. Bug #4 — the second splitter

There are **two** splitters and they disagree:

1. `pipeline.py` splits the token stream on `SENTENCE_ENDINGS`.
2. `synthesize_stream` splits *again* — `_split_sentences` (`kokoro_tts.py:289`) for EN,
   `_split_sentences_ja` (`:317`) for JA.

The EN one ends with:

```python
return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 3]   # :310
```

which **drops** anything under 3 characters. "OK." survives (3 chars) but a stray short
fragment does not — content the model produced is silently never spoken. The JA splitter
does the right thing already: it **merges** short fragments into a neighbour (`:339-355`).

### Decision: merge, never drop (confirmed with the user)
Bring the EN splitter in line with the JA one. Text the model produced must always be
spoken.

### Bug #4b — naive `.` splitting
Independent of URLs, a bare `.` terminator splits on things that are not sentence ends:

- decimals — "3.5 meters" → "3" / "5 meters"
- abbreviations — "Dr. Smith", "e.g.", "approx.", "Mr."
- version numbers — "v1.2.3"; filenames — "index.html"

The boundary test must require that a `.` is followed by whitespace/end **and** not
preceded by a digit or a known abbreviation. (`,` is *not* in `SENTENCE_ENDINGS` and does
not split — verified — so no change needed there.)

---

## 5. The non-conflict contract (unchanged, still binding)

> **The `llm_text_chunk` events sent to the client (`pipeline.py:515`, `:533`) must keep
> carrying RAW, UNMODIFIED markdown.**

The frontend needs the `##` and `**` to render them as formatting. Normalize **only** the
text handed to the TTS engine, inside the TTS branch — never the text sent to the client,
and never `conversation_history` (`:579-584`), which should keep what the model actually
said.

- Server touches `server/**`; frontend touches `frontend/**`. No file overlap.
- A test pins this: assert `llm_text_chunk` payloads still contain raw markdown.

---

## 6. Design

New module **`server/tts/speech_normalizer.py`** — one public function
`normalize_for_speech(text: str, lang: str) -> str`. Pure, synchronous, unit-testable
without a GPU. A separate module rather than more inline regex, because `pipeline.py`'s
inline `_TTS_STRIP_PATTERNS` block is already the kind of thing this codebase should stop
growing.

Order matters — structure before inline emphasis:

| Element | Treatment |
|---|---|
| Fenced code blocks ` ``` ` | Drop entirely. Reading code aloud is never useful, and the frontend renders it properly on screen. |
| Headings `#`–`######` | Drop marker, keep text, ensure it terminates so it doesn't run into the next line |
| Bold / italic `**` `*` `__` `_` | Drop markers, keep text |
| Inline code `` ` `` | Drop backticks, keep text |
| List markers `-` `*` `+` `1.` | Drop marker, keep item text |
| Blockquote `>` | Drop marker |
| Markdown links `[text](url)` | Speak `text`, drop the URL |
| Bare URLs | Drop (§3) |
| Tables `\|` | Drop pipes and separator rows |
| Horizontal rule `---` | Drop |

**Empty-after-normalization guard:** if a buffer reduces to whitespace (it was *only* a
code fence, or *only* a URL), skip synthesis rather than sending `""` to Kokoro.
`pipeline.py` already has this shape at `:706` and `:726` — follow it.

**Ordering within the fix:** normalization must run **before** the sentence-boundary
test where possible, so URL dots are gone before they can split anything. Because tokens
arrive incrementally and a URL can straddle the moment a boundary is tested, the
URL-aware boundary check (§4b) is needed **in addition to** normalization, not instead
of it.

---

## 7. Optional, non-blocking

`prompt_builder.py` system prompts don't discourage markdown. A line asking for plain
prose would *reduce* (never eliminate) bug #1. Treat as nice-to-have, **not** a substitute
for normalization — and **do not** suppress markdown entirely, because the frontend now
*wants* it for the screen. `format_search_context` (`prompt_builder.py:302`) is where the
cited URLs originate; leave it — the URL should reach the screen, it just must not be read
aloud.

---

## 8. Verification

The server runs on a remote GPU, so end-to-end audio cannot be exercised locally. The
normalizer and the splitter are therefore designed to be **fully testable offline** —
that is the primary safety net.

- [ ] Unit tests for `normalize_for_speech`: headings, bold/italic, inline code, fenced
      blocks, lists, blockquotes, tables, markdown links, bare URLs, long URLs with
      paths/queries, mixed EN/JA, empty-after-normalization, and **plain text passes
      through unchanged**.
- [ ] Splitter tests: decimals ("3.5"), abbreviations ("Dr."), versions, filenames must
      **not** split; real sentence ends must split; short fragments are **merged, not
      dropped** (bug #4).
- [ ] Ordering test: assert audio chunks reach `audio_output` in sentence order for a
      multi-sentence response (bug #2) — the regression that motivated the whole fix.
- [ ] Contract test: `llm_text_chunk` payloads still contain raw markdown (§5).
- [ ] Barge-in still cancels in-flight synthesis after the sequential change.
- [ ] Existing `server/` tests pass.
- [ ] Manual listen on the GPU host: a heading-heavy answer, and a search answer with
      sources.

---

## 9. Task checklist

- [x] Create `server/tts/speech_normalizer.py` with `normalize_for_speech(text, lang)`
- [x] Markdown stripping (§6), order-sensitive: blocks → inline
- [x] URL handling (§3): bare + markdown links, EN and JA
- [x] **Fix bug #2:** synthesis is now sequential in `tts_worker` — the task is still
      created and tracked (so `handle_interrupt` can cancel it) but is now **awaited**
      before the next sentence starts. `task.cancelled()` distinguishes a barge-in
      cancel (continue with the next turn) from `tts_worker` itself being cancelled on
      shutdown (must propagate, or the worker spins on a dying pipeline).
- [x] **Fix bug #4:** `_split_sentences` merges short fragments instead of dropping them
- [x] **Fix bug #4b:** `_is_sentence_end()` ignores `.` in decimals, abbreviations,
      versions and URLs
- [x] Wire `normalize_for_speech` into `tts_worker` on the `tts_buffer` path only
- [x] Empty-after-normalization guard
- [x] Unit tests: normalizer (34), splitter (14), ordering + contract (7) = **55 new**
- [x] Run the `server/` test suite — **no regressions** (see below)
- [ ] Manual listen check on the GPU host
- [ ] Commit on `deploy/server`

### Test results

Baseline on unmodified HEAD vs. working tree, run identically:

| | HEAD (baseline) | With these changes |
|---|---|---|
| passed | 92 | **147** (+55) |
| failed | 9 | **9** (unchanged) |
| errors | 2 | **2** (unchanged) |

The 9 failures / 2 errors are **pre-existing** — trio-variant rate-limiter tests in
`server/test_validation.py`, and `tests/test_stt.py`, which needs a live server. None
are caused by this work.

**The ordering test was verified to actually catch bug #2**: with the `await` reverted to
the original fire-and-forget `create_task`,
`test_audio_reaches_the_output_queue_in_sentence_order` **fails**; with the fix it
passes. A green test that also passes against the bug would have been worthless — an
earlier draft of the fake did exactly that (synthesis finished before the next sentence
arrived, so concurrent and sequential behaved identically) and was recalibrated so
sentences genuinely overlap in flight.

### Environment notes

- The venv has a **broken PyQt6 / pytest-qt** plugin that crashes pytest at startup,
  unrelated to this work. Run with `-p no:pytest-qt`.
- The project does **not** depend on `pytest-asyncio`, so the async tests drive the real
  `tts_worker` through a plain `asyncio.run()` wrapper rather than adding a test
  dependency to a deployed server.
- Running **Windows** git/npm against the `\\wsl.localhost` UNC path rewrites line
  endings (LF→CRLF) on files it touches, which makes unrelated files appear modified.
  Content is unchanged (`git diff --ignore-cr-at-eol` is empty). Prefer running git and
  npm **inside WSL**.
