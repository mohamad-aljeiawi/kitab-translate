# kitab Architecture

> **Scope:** English and Japanese books → Arabic, one direction.
> This document is the design specification. For installation and usage, see the
> [README](../README.md); for how to contribute, see [CONTRIBUTING](../CONTRIBUTING.md).

---

## 0. The decision this rests on

**Adaptability over visual conformity.** The output does not reproduce the source page
and is not trying to. Arabic is a different language with its own rules; its text
expands and contracts against any box drawn for English, and it runs the other way. The
job is to carry the information across correctly, in a form that adapts to whatever it
is read on.

Everything below follows from that sentence. Accepting it buys three things:

1. **The bidi problem disappears.** Output is HTML; the rendering engine runs UAX #9 and
   HarfBuzz. No embedding levels, no level-run/font-run intersection, no direction-aware
   pen placement, no glyph IDs written into a content stream.
2. **Every stage becomes a file.** A run is resumable and inspectable, and a human can
   correct the document between any two stages.
3. **The scope closes.** Scientific papers, forms, sheet music and legal documents need
   page fidelity. kitab does not serve them, and saying so is what keeps it small.

What it costs: line breaks move, page counts change, multi-column layouts become single
column, and figures land where the reflow puts them.

---

## 1. Architecture

```
                                    kitab/
  ┌──────────────┐
  │   classify   │  ingest/classify.py    what is this file? does it need OCR?
  └──────┬───────┘
         │  SourceInfo
  ┌──────▼───────┐
  │   extract    │  ingest/{pdf,epub,ocr}.py      → Markdown + images/
  └──────┬───────┘
         │  Markdown
  ┌──────▼───────┐
  │   figures    │  figures.py            Tier 0 / Tier 1, legend injection
  └──────┬───────┘
         │  Markdown (annotated)
  ┌──────▼───────┐
  │   segment    │  md/ast.py + md/mask.py        → list[Segment]
  └──────┬───────┘
         │  masked source strings
  ┌──────▼───────┐
  │  translate   │  translate/*           batched, cached, glossary-aware
  └──────┬───────┘
         │  masked translations
  ┌──────▼───────┐
  │   verify     │  md/mask.restore_text  every placeholder, exactly once
  └──────┬───────┘
         │  Markdown (Arabic)
  ┌──────▼───────┐
  │    render    │  render/{html,epub_out,pdf_out}.py
  └──────────────┘
         │
     EPUB · PDF · HTML · report.json
```

### Module map

| Module | Responsibility | Carried over? |
|---|---|---|
| `kitab/config.py` | settings store, engine env resolution | from `pdf2zh.config` |
| `kitab/cache.py` | persistent translation cache (sqlite/peewee) | from `pdf2zh.cache` |
| `kitab/models.py` | `Segment`, `Figure`, `Document`, `Report` | new |
| `kitab/errors.py` | every recoverable failure has a type | new |
| `kitab/ingest/classify.py` | format + text-layer detection | new |
| `kitab/ingest/pdf.py` | 3 PDF→Markdown backends | new |
| `kitab/ingest/epub.py` | EPUB/HTML→Markdown, ruby stripping | new |
| `kitab/ingest/ocr.py` | RapidOCR wrapper, position labelling | new |
| `kitab/figures.py` | Tier 0/1 classification, legend injection | new |
| `kitab/md/mask.py` | placeholder protection + verification | concept from `pdf2zh` |
| `kitab/md/ast.py` | Markdown document model | new |
| `kitab/translate/base.py` | engine interface, batching, caching | from `pdf2zh.translator` |
| `kitab/translate/openai_like.py` | OpenAI, DeepSeek, compatible endpoints | from `pdf2zh.translator` |
| `kitab/translate/google.py` | free Google web endpoint | from `pdf2zh.translator` |
| `kitab/translate/glossary.py` | termbase extraction and reuse | new |
| `kitab/render/html.py` | Markdown → RTL HTML | new |
| `kitab/render/epub_out.py` | EPUB with RTL spine | new |
| `kitab/render/pdf_out.py` | Chromium / WeasyPrint | new |
| `kitab/pipeline.py` | stage orchestration, resume, reporting | new |
| `kitab/cli.py` | command line | new |

---

## 2. Stage contracts

Each stage writes a file. A stage whose output exists is skipped unless `--force`.

| # | Stage | Input | Output | Skippable |
|---|---|---|---|---|
| 1 | classify | source file | `SourceInfo` (in memory) | no |
| 2 | extract | source file | `01_extract/document.md`, `01_extract/images/` | via 02 |
| 3 | OCR | scanned pages / figures | text + boxes | via 02 |
| .. | figures | Markdown | annotated Markdown, `Figure[]` | via 02 |
| .. | segment | Markdown | `02_document.json` | yes |
| 4 | translate | `Segment.source[]` | `03_translated.json` | yes |
| 5 | rebuild | segments + tokens | `04_translated.md`, `05_book.html` | no (cheap) |
| 6 | emit | HTML | `<name>.ar.epub`, `<name>.ar.pdf` | no (cheap) |

### 2.1 Classify (`ingest/classify.py`)

Samples up to 12 pages spread across the document and measures extracted characters per
page. Below `SCANNED_THRESHOLD_CHARS = 120` the PDF is a picture of a book.

This single boolean decides the hardware budget for the run. Sampling is spread rather
than taken from the front, because front matter is image-heavy even in a digital book.

### 2.2 Extract (`ingest/pdf.py`, `ingest/epub.py`)

**EPUB and HTML** skip PDF extraction entirely. An EPUB already *is* a document model.
Japanese specifics handled here, because they are lossy if deferred:

- `<rt>`/`<rp>` furigana is dropped, `<ruby>`/`<rb>` unwrapped, because a phonetic gloss in the
  translation input only confuses the engine;
- `<br/>` inside a paragraph becomes a space, because vertical-writing EPUBs use it for
  line control, not meaning;
- spine order is used for reading order (`get_items()` order is not reading order).

**PDF** has three backends behind one interface:

| Backend | Basis | Requires | Use when |
|---|---|---|---|
| `marker` | Datalab Marker | `kitab[marker]`, torch, Py 3.11/3.12 | best structure; complex layouts |
| `fast` | `pymupdf4llm` | `kitab[fast]` | CPU-only, good enough for most books |
| `builtin` | PyMuPDF directly | nothing | always available; ordinary single-column books |

`auto` picks the best installed one.

The `builtin` backend is implemented here and does five things that a naive PyMuPDF
extractor gets wrong. Every one of them was found by looking at rendered output, not
by reasoning about the code:

1. **Restores inter-span spaces.** A PDF has no words. Text is drawn as positioned
   runs, and a run boundary very often falls between two words with no space character
   anywhere. Joining spans naively yields `Readoutofsuperconductingqubits`. A space is
   inserted where the horizontal gap between consecutive spans exceeds `0.2 × font size`.
2. **Breaks paragraphs.** A vertical gap over `0.55 × body size`, or a first-line indent
   over `0.9 × body size`, ends the paragraph. Without this, a page collapses into one
   4000-character block, which destroys the reading experience *and* the translation,
   because an engine given a whole page at once produces markedly worse Arabic than one
   given a paragraph.
3. **Merges runs sharing a baseline.** PyMuPDF returns each positioned run as its own
   "line". A contents entry is drawn as three runs at one y -- `1.15` at x=72, the
   title at x=101, `79` at x=418 -- so read top-to-bottom it shreds: the page number
   of one entry glues to the section number of the next (`42 1.2`) and every title is
   stranded alone. Runs on a baseline are merged left-to-right, and a merged row is
   marked `fielded` so it never joins the paragraph above or below it.
4. **Splits genuine columns, but not fields.** A vertical band no line crosses splits
   the page. A band is only a column if both sides are at least 20% of the page width
   -- otherwise it is a *field*, like a contents page's page-number strip, and
   splitting there would undo the baseline merge.
5. **Attaches orphan bullets.** PDFs draw the bullet glyph as a separate run, which
   otherwise becomes a paragraph containing nothing but `•`. It is merged into the
   item and emitted as a real Markdown list.
6. **Detects code by typeface.** The decisive fix for technical books. A listing is
   set in a monospaced face and prose is not, so every span is classified by font.
   PyMuPDF's monospace flag is unreliable -- this book sets its listings in
   `LucidaSans-Typewriter` with `flags=0` -- so the font *name* is matched too, and
   that is what actually works. Three outcomes:

   * a line that is mostly monospaced joins a **fenced code block**, which `md/ast.py`
     never segments, so no engine ever sees it;
   * a monospaced *span inside a prose line* is wrapped in backticks, becoming inline
     code -- the mixed case, and the common one: "uses six `if` statements";
   * a bare line number between two code lines keeps the fence open, because a blank
     line in a printed listing is just its number.

   A line is code when it is 60% monospaced, **or** when everything not monospaced is
   ornament -- digits, spaces, separators. Without that second clause `20 }` is one
   monospaced character in three and goes to the translator. Code is also excluded
   from the body-size statistic, or a page of listings makes the 8pt monospace face
   the "body" size and turns the surrounding prose into headings.

7. **Strips running heads, feet and page numbers.** By repetition, not position: a
   line in the top or bottom band whose text -- digits removed, so the page number
   does not make each instance unique -- recurs across a quarter of the pages. A real
   heading appears once and cannot be caught. Below three pages nothing is dropped.

8. **Takes a line's *dominant* size, not its largest.** A drop cap is one 30pt
   character on a 15pt line; the maximum turned every drop-capped paragraph into a
   heading, which then forced a page break and stranded it.

9. **Merges a title wrapped over two lines** into one heading. Display type is
   centred, so the second line starts further right and the paragraph indent rule
   reads it as a new block -- producing two `<h1>`s, a page break between them, and
   the first line alone on an empty page. Headings use a gap-only continuation test.

10. **Names chapters by text when the typography says nothing.** Some ebook PDFs are
    a single font at a single size with no bold anywhere -- every span in *Social
    Engineering* is ArialRegular 9pt, flags 0. The size heuristic correctly finds
    nothing and the book becomes one unnavigable chapter, so short lines matching
    `Chapter N` / `Part N` are promoted. Only when typography yielded almost nothing,
    and never for a line ending in a full stop, which is a sentence and not a title.

11. **Detects headings by relative size.** Body text is whichever font size occupies the
   most characters; sizes above it are ranked into heading levels. Lines over 120
   characters are never headings.

Heading detection is the weakest link in every tool in this category, not just this one.
`report.json` records which backend ran, and `04_translated.md` exists so a human can
fix the structure.

### 2.3 OCR (`ingest/ocr.py`)

RapidOCR on ONNX Runtime, CPU, ~seconds per page at 200 DPI. Used for scanned pages and
for Tier-1 figure labels, the same engine both times.

Scanned pages become **flat** Markdown with `## Page N` markers and no inferred
headings. Without a layout model there is no reliable heading signal in a scan, and
inventing one produces a wrong table of contents, which is worse than none.

Not installed → scanned input is refused with an explanation, and every figure is
Tier 0. An uninstalled extra degrades output; it never fails the run.

### 2.4 Figures (`figures.py`)

Two tiers, as scoped.

**Tier 0** passes the image through untouched.

**Tier 1** reads the labels with OCR, translates them and emits an Arabic legend *beneath* the image
keyed by a coarse 3×3 position (`أعلى اليسار`, `الوسط`, (...)). The artwork is never
modified.

Promotion to Tier 1 requires ≥ 2 recognised lines and ≥ 8 characters total. One stray
word is noise, not a label set.

The legend is injected into the Markdown **before** segmentation, so its text goes
through the ordinary translation path with the ordinary glossary and the ordinary
placeholder checks. There is no second translation route.

Tiers 2 and 3 (inpainting text back into the image) are not implemented and not planned
here. A reader of a translated technical book needs to know what the diagram's labels
say; they do not need the diagram redrawn.

### 2.5 Segment (`md/ast.py`)

The unit of translation is **one markdown-it `inline` token**, the inline content of a
paragraph, heading, list item, table cell or blockquote line.

Everything else in the token stream (fences, HTML blocks, table structure, list
markers, heading levels, image nodes) is never handed to an engine, so an engine cannot
damage it. Code fences are block tokens with no inline children, so they are skipped *by
construction* rather than by a rule someone could forget.

An inline token's `.content` is the raw Markdown source of that content. The round-trip:

```
source → tokens → [inline.content → mask → translate → restore] → tokens → Markdown
```

Restoration re-parses the translated string with `parseInline` to rebuild the token's
children, so an engine that legitimately moves emphasis or a link produces a correct
tree rather than broken syntax.

A node is skipped when it has no letters, or when masking consumed everything (a
standalone image, a numeric table cell). No request is spent on it.

**Segment ids are positional and out-of-band** (`s00042`). Nothing is ever numbered
inside the prose. This is the mechanism behind "translate without numbering it so as not
to mess up the formatting": the index lives in the data structure.

### 2.6 Mask and verify (`md/mask.py`)

Two rule sets, run as **one left-to-right alternation**, not sequentially, because a
later rule could otherwise match inside a placeholder an earlier rule emitted.

Markdown constructs (byte-exact):

| Rule | Protects |
|---|---|
| `code_span` | `` `foo_bar()` `` |
| `image` | `![alt](images/f1.png)` |
| `footnote_ref` | `[^1]` |
| `link_dest` | `](http://x.io)`, the *destination* only; `[text]` stays translatable |
| `ref_link`, `autolink`, `html_tag` | reference links, `<http://(...)>`, raw HTML |

Lexical constructs:

| Rule | Protects | Note |
|---|---|---|
| `math_display`, `math_bracket`, `math_paren` | `$$...$$`, `\[(...)\]`, `\(...\)` | |
| `math_inline` | `$E=mc^2$` | requires no space after `$`; `$5 and $10` is left alone |
| `url`, `email` | | |
| `section_no` | `3.2.1` | dotted only; a bare `12` is prose |
| `snake_case` | `queue_size` | code-like identifiers outside code spans |
| `glossary` | termbase entries | only with `--protect-terms` |

**Placeholder style is per engine.** LLMs follow an instruction about `{{v0}}` and leave
it intact; statistical MT mangles braces, so the Google engine gets `[[0]]`. Restoration
is tolerant of whitespace and case (`{{ V0 }}` restores) and of **reordering**. Arabic
word order moves placeholders, and that is not an error.

**Verification is strict.** An id that appears zero times, twice, or that was never
issued is a hard failure for that segment. On failure the segment **keeps its source
text** and is listed in `report.json`. Publishing a paragraph with its formula missing
is worse than publishing one still in English.

`restore_escaped_literals()` then repairs Markdown escaping introduced by the renderer
(`$O(n \log n)$` → `$O(n \\log n)$`). Valid Markdown, but the intermediate `.md` is meant
to be read and reused, and doubled backslashes in LaTeX survive into published books.

**Digits stay Western (0-9)** by default. Arabic-Indic numerals would break every
cross-reference to an untranslated figure.

### 2.7 Translate (`translate/`)

```python
class BaseTranslator:
    mask_style: MaskStyle       # which placeholder syntax this engine survives
    batch_size: int             # segments per request
    max_batch_chars: int        # soft cap regardless of batch_size
    supports_glossary: bool

    def translate_many(texts) -> list[str]   # primary entry point
    def do_translate(text) -> str            # engines must implement
    def do_translate_batch(texts) -> list[str]  # optional; defaults to a loop
```

| Engine | Key | Batch | Style | Notes |
|---|---|---|---|---|
| `google` | none | 1 | `[[n]]` | free web endpoint, 8 workers @ 8 qps, 5000 char cap |
| `openai` | `OPENAI_API_KEY` | 20 | `{{vn}}` | JSON array in/out |
| `deepseek` | `DEEPSEEK_API_KEY` | 20 | `{{vn}}` | same protocol, different base URL |
| `openailiked` | none | 8 | `{{vn}}` | Ollama, vLLM, gateways; smaller batch |

**Batch shape is checked, never assumed.** An LLM returns a JSON array; if the length
differs the whole batch is discarded and the segments are retried one at a time. A
silently misaligned batch shifts every translation onto the wrong paragraph, the worst
failure this pipeline can have, and the one that is hardest to notice in a language you
do not read.

**Concurrency and rate are separate knobs.** PDFMathTranslate conflates them: a
`ThreadPoolExecutor(max_workers=thread)` with `@retry(wait=wait_fixed(1))` on the
worker, and a GUI that passes the thread count as `qps`. Four threads is not four
requests per second; it is "as fast as four threads can go". With no `stop=` on that
retry, a permanently failing segment also retries forever and the book never finishes.

kitab splits them:

* `workers` sets requests in flight (`ThreadPoolExecutor` in `translate_many`).
* `qps` sets requests *started* per second, a token bucket in `translate/limiter.py`,
  shared by every worker.

and adds the part neither has: the rate responds to the server. A 429 (or a 403/503,
or an empty 200, all three being how the free Google endpoint says "slow down") halves
the rate for **every** worker; twenty consecutive successes step it back up toward the
ceiling. AIMD, the same control law as TCP congestion control.

Measured on a 108-page book, free Google endpoint, 2286 segments:

| Setting | Time | Failures |
|---|---|---|
| sequential, 0.4 s throttle (old) | ~19 min (extrapolated) | none |
| 4 workers, 2.5 qps | 1.3× faster | 0 |
| 8 workers, 8 qps (current default) | **4.8 min** | 0 |

The limiter never backed off during that run, which is the evidence the defaults are
not reckless. If an endpoint does start blocking, `--qps 3 --workers 3` is the cautious
setting, and the AIMD floor (10% of the configured rate) means even a wrong `--qps`
converges instead of failing.

Retries stay **bounded** at 6 attempts for OpenAI and 4 for Google, so no segment can hang
a run.

**Thread safety.** `requests.Session` is per-thread via `threading.local`; sqlite runs
in WAL mode with a busy timeout; each batch owns a disjoint set of result indices, and
results are placed **by index, never by completion order**. With a worker pool, that
distinction is the difference between a translated book and a shuffled one.

**Caching** is keyed by `(engine, engine parameters, source text)`. Any parameter that
changes output (model, temperature, prompt version, glossary revision) is registered
with `add_cache_impact_parameters` and becomes part of the key. Interrupting a 400-page
book and restarting costs nothing.

**The prompt** (`ARABIC_SYSTEM_PROMPT`) is one constant, so a change is a one-line diff
and automatically invalidates stale cache rows. Because the target is only ever Arabic,
it can be specific: MSA register, don't mirror source syntax, preserve `{{vN}}` exactly
once each but *may move them*, keep Markdown emphasis, keep Western digits, use the
glossary, output the translation only.

### 2.8 Glossary (`translate/glossary.py`)

One pass over the whole book collects capitalised terms appearing ≥ 4 times, translates
them once, and injects them into every later request. Written to `work/glossary.json`,
sorted, hand-editable.

This is the difference between a usable technical translation and an unusable one.
Chunk-by-chunk translation cannot produce consistency: the same term becomes three
different Arabic words in three chapters and the reader cannot tell they are the same
thing. Fixing twenty terms in `glossary.json` before the main run fixes them everywhere.

### 2.9 Render (`render/`)

**HTML** is `<html lang="ar" dir="rtl">` with `style_ar.css`. The rules that matter:

- Naskh font stack with Latin fallbacks (a technical book is full of Latin identifiers);
- `line-height: 1.9`, because Arabic has deep descenders and marks above the baseline; 1.4 is
  cramped;
- `code, kbd, samp, pre { direction: ltr; unicode-bidi: isolate; }`, where the isolation is
  the important half: it stops surrounding Arabic from reordering the code's punctuation,
  which is the classic way mixed-direction technical text goes wrong;
- logical properties throughout (`padding-inline-start`, `border-inline-start`), so
  nothing depends on physical left/right;
- `hyphens: none`, because Arabic is not hyphenated;
- tables are `direction: rtl` (first column on the right) inside an `overflow-x: auto`
  container, so a wide table never forces the page sideways.

**EPUB** is the primary artifact. Two settings decide whether an Arabic EPUB opens
correctly, and general-purpose tools routinely miss both:

- `page-progression-direction="rtl"` on the spine (`book.set_direction("rtl")`);
- `dir="rtl"` + `lang="ar"` on every XHTML document (`EpubHtml(direction="rtl", lang="ar")`).

Get either wrong and the book opens backwards. Split at `# ` headings by default: a
single 400-page XHTML makes a reader stutter and breaks progress tracking.

**Fonts are bundled, never linked.** `render/assets/fonts/` carries Noto Naskh Arabic
(OFL), inlined into the CSS as a `data:` URI. Linking Google Fonts is the obvious move
and is actively wrong: Google serves WOFF2, Chromium cannot embed WOFF2 into a PDF, so
it rasterises every glyph into a **Type 3** font. The page looks correct and the text
layer underneath is destroyed:

| Font source | Embedded as | Text extracted from the PDF |
|---|---|---|
| Google Fonts link | Type 3 | `عمدا ةفار غ تترك ةالص ف ح ه ذه` ✗ |
| Bundled TTF, data: URI | `NotoNaskhArabic-Regular` | `هذه الصفحة تركت فارغة عمدا` ✓ |

An unsearchable, uncopyable PDF that renders beautifully is the kind of defect nobody
notices until a reader complains. `--no-embed-fonts` falls back to installed fonts,
which on Windows means Segoe UI: correct, searchable, and the wrong typeface for a book.

**Bidi needs one nudge.** The renderer implements UAX #9 correctly, and correct is not
the same as right. An Arabic paragraph ending `... London EC1N 8TS.` has its full stop
as a *neutral* between an LTR run and the paragraph end, so the algorithm attaches it to
the Latin run and it renders on the wrong side: `.Saffron House, 6-10 Kirby Street`. So
`isolate_ltr_runs()` wraps every Latin run in `<bdi>`; the neutrals then take the
paragraph direction. Code, `pre`, `kbd` and `samp` are skipped -- the stylesheet already
isolates them. In a translated technical book, full of identifiers and product names,
this is on nearly every page.

Related, upstream: `D.1` must be masked or the letter is translated to `د`, and `د.1`
then renders as `1.د`. The `lettered_no` rule in `md/mask.py` covers it.

**PDF** is printed from the same HTML, never a separate pipeline.

| Backend | Size | Notes |
|---|---|---|
| `chromium` (Playwright) | ~500 MB | best-tested Arabic shaping; honours `@page` margin boxes |
| `weasyprint` | ~200 MB | Pango + HarfBuzz; honours the CSS Paged Media margin boxes Chromium ignores; awkward native deps on Windows |

Neither installed → the HTML is still written and that is said plainly. The EPUB does not
depend on this stage.

**Bilingual mode** keeps the original beneath each translated block in an LTR span. It is
the review surface, and it is hidden in `@media print`.

---

## 3. Data model

```python
Segment(id, kind, source, placeholders, translation, status, note)
#   kind:   heading|paragraph|list_item|table_cell|blockquote|caption|figure_legend
#   source: MASKED text, exactly what the engine receives
#   status: pending|translated|cached|failed|skipped

Figure(id, path, tier, ocr_lines, legend_segment_ids)

Document(title, lang_in, markdown, segments, figures, meta)

Report(input_path, service, model, stages, segments_*, figures_*, warnings, failures)
```

All JSON-serialisable, on purpose: every stage boundary is a file a human can open.

---

## 4. Invariants

These are what the test suite pins down. Breaking one is a bug regardless of what else
still works.

1. **No engine ever sees non-text structure.** Fences, tables, image nodes, heading
   levels and list markers do not appear in any request.
2. **Every placeholder round-trips exactly once**, or the segment keeps its source and is
   reported. Never partially restored, never guessed.
3. **Placeholder reordering is legal.** Arabic word order moves them.
4. **A batch returns exactly as many items as it was given**, or it is discarded and
   retried per segment. Order is never inferred.
5. **Results are placed by request index, never by completion order.**
6. **Digits stay Western** unless explicitly asked otherwise.
7. **An uninstalled optional extra degrades output and says so**; it never fails a run.
8. **A stage with existing output is skipped** unless `--force`.
9. **The EPUB declares RTL page progression and RTL/Arabic documents.**

---

## 5. Failure modes and what happens

| Failure | Detection | Response |
|---|---|---|
| Engine drops a placeholder | `restore_text` reports `missing` | segment keeps source; listed in `report.json` |
| Engine invents a placeholder id | `unexpected` | left visible in output; reported |
| LLM returns a short/long array | length check | batch discarded, retried per segment |
| Google endpoint blocked / changed | no result container | tenacity retry ×4, then segment fails |
| Rate limit | `openai.RateLimitError` | exponential backoff ×6 |
| Segment exceeds 5000 chars (Google) | length check | explicit error, never truncated silently |
| Corrupt cache | exception on read | treated as a miss; run continues |
| Corrupt config | JSON error | treated as empty; run continues |
| Marker/OCR/Playwright missing | `find_spec` | `MissingDependency` with the exact install command |
| Image referenced but missing | `Path.exists()` | warning; EPUB still written |
| Scanned PDF without `--ocr` | classify | loud warning before wasting a translation budget |
| PDF/EPUB write fails | exception | recorded in `report.warnings`, other outputs still produced |

---

## 6. Hardware

| Input | Machine | Throughput |
|---|---|---|
| EPUB / Markdown | any laptop, 4 GB | API-bound only |
| Digital PDF, `builtin` or `fast` | CPU, 8 GB | fast; no model beyond PyMuPDF |
| Digital PDF, `marker` | 5 GB VRAM peak | ~2.9 pages/s on a large GPU |
| Scanned PDF, RapidOCR | CPU, 8-16 GB | seconds per page |
| Scanned PDF, Surya on CPU | CPU | 1-5 min per page, avoid |

**Translation runs on someone else's hardware by default.** A 7-8B local model is a real
step down for literary and technical Arabic, and a 27B+ model contradicts the constraint.
The engine abstraction means a local model is a config change if that stops being true.

---

## 7. Testing

`pytest` runs 69 tests, no key, no network. Structure:

- `tests/test_mask.py` covers the load-bearing part: round-trip, currency vs maths, bare
  integers left alone, link text translatable, **reordering allowed**, dropped /
  duplicated / invented placeholders each reported, engine whitespace tolerated.
- `tests/test_ast.py` covers kinds labelled, fences never segmented, standalone images never
  segmented, structure preserved through a translation, failed segments keep their
  source, bilingual mode, RTL HTML output, table scroll container.
- `tests/test_pipeline.py` runs end to end with three fake engines: a well-behaved one, one
  that drops every placeholder, one that returns a short array. Covers EPUB RTL metadata,
  report completeness, resume, `--force`, chapter splitting, and batch order/count.

The fake engines are the point: these are contracts, not integrations.

---

## 8. Roadmap

**Phase 1, proof** *(done)*
Digital PDF and EPUB → Arabic EPUB, free engine, no key.

**Phase 2, quality** *(partly done)*
Glossary ✓, segment cache ✓, bilingual ✓, Chromium PDF ✓.
Remaining: previous-paragraph context in the prompt; a quality report that flags
suspiciously short or long translations; `--sample N` for a cheap first look at a book.

**Phase 3, coverage**
RapidOCR wiring is written but untested against real scans. Tier-1 legends need a real
diagram corpus. Japanese: EPUB path works; vertical PDF needs `manga-ocr`.

**Phase 4, optional, only if 1 to 3 are used**
Manga as a *sibling* module: `comic-text-detector` → `manga-ocr` → inpaint → Arabic in
bubbles. It shares only the translator layer and the glossary. Japanese manga reads
right-to-left, which happily matches Arabic. That is the one thing that gets easier.

---

## 9. Known limitations

1. **Multi-column PDFs** confuse the `builtin` backend; use `fast` or `marker`.
2. **Heading detection** is the weakest link in every tool in this category. Check
   `04_translated.md`.
3. **`marker` needs Python 3.11/3.12.** On newer interpreters `marker` and
   `pymupdf4llm` may not install at all. `builtin` covers that gap deliberately, so
   kitab still works everywhere without them.
4. **Vector figures are not extracted** as images, only embedded rasters. A figure drawn
   with PDF path operators is lost by the `builtin` backend.
5. **Footnotes** are carried as text, not as linked EPUB footnotes.
6. **The free Google engine is unofficial.** It rate-limits and can stop working.
7. **No page-faithful mode.** By design; see §0.
