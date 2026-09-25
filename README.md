<div align="center">

# kitab · كتاب

**Translate English and Japanese books into Arabic.**
PDF or EPUB goes in, a readable right-to-left Arabic EPUB comes out.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/mohamad-aljeiawi/kitab-translate/actions/workflows/ci.yml/badge.svg)](https://github.com/mohamad-aljeiawi/kitab-translate/actions/workflows/ci.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

</div>

```bash
pip install -e .

kitab book.pdf                          # -> out/book.ar.epub   (free, no API key)
kitab novel.epub --service deepseek     # better quality, cents per book
kitab manual.pdf --pdf --bilingual      # EPUB + PDF, original kept for review
kitab book.pdf --inspect                # what is this file, and what will it need?
```

One direction, on purpose. There is no `--to` flag, no language matrix and no
fixed-layout PDF rewriting. A book goes in, an Arabic book comes out.

<!-- Drop a before/after screenshot at docs/images/preview.png and uncomment:
<div align="center"><img src="docs/images/preview.png" alt="English source page beside the translated Arabic EPUB" width="820"></div>
-->

## Why kitab

**A 108-page book in 4 minutes 48 seconds.** That is 2,286 segments on the free Google
engine with no key, zero failures and no rate-limit backoff. The limiter adapts as it
runs, so the defaults sit near what the endpoint will actually take instead of far below
it.

**Formulas and code survive byte for byte.** Maths, code spans, links, section numbers
and identifiers are swapped for placeholders before translation and checked afterwards.
If a placeholder goes missing or turns up twice, that segment keeps its English source
and gets logged. A paragraph still in English is a much smaller problem than a paragraph
with the formula quietly gone.

**Code is found by typeface, not by guesswork.** A listing set in a monospaced face
becomes a fenced code block that the translator never sees. Skip that step and
`if (number1 > number2) {` comes back as `إذا (رقم > 1؛ رقم2) {`, which is syntactically
dead and wrong in a way you will not notice until someone tries to run it.

**Arabic PDFs stay searchable.** Noto Naskh Arabic ships with the package and is inlined
into the CSS, so the text layer survives. A 108-page book lands at 286 A5 pages and
1.2 MB with search working.

**Free by default.** The Google engine needs no key and no account. Add
`--service deepseek` or `openai` when you want better quality.

**Every stage is a file on disk.** A run can be resumed and inspected, and you can fix
the Markdown by hand between any two stages. Re-running skips whatever is already done.

**Diagrams get Arabic legends.** Labels inside figures are read by OCR, translated and
placed beneath the image, keyed by position. The artwork itself is never touched.

**Books that are entirely pictures still work.** A scanned or screenshot PDF has no text
layer at all, so kitab measures one: it reads each page, tells drawing apart from prose,
crops every diagram out as a figure, and rebuilds headings and paragraphs from the
geometry. Install `kitab[ocr]` and it happens automatically — the chart labels end up as
Arabic legends rather than spliced into the middle of your sentences.

**Nothing optional is required.** A missing extra makes the output worse and says so out
loud. It never fails the run.

## Why not kitab

Worth knowing before you install.

It does not preserve page layout and is not trying to. Line breaks move, page counts
change, multi-column becomes single column, and figures land wherever the reflow puts
them.

Scientific papers, forms, legal documents and sheet music all need page fidelity. That is
a different product. Use [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate)
for those.

Arabic is the only output language. If you need a language matrix, this is the wrong
tool.

Text inside images is not redrawn. Legends go underneath the figure, and inpainting is
not planned. See [Known limitations](#known-limitations).

The decision underneath all of it is **adaptability over visual conformity**. Arabic is a
different language with different rules. Its text expands and contracts against any box
you draw for English, and it runs the other way. The job is to carry the information
across correctly, in a form that adapts to whatever it gets read on.

## How it works

```
source (PDF / EPUB / HTML / Markdown)
   |  classify         what is this? does it need OCR?
   |  extract          structure, images, headings          -> Markdown
   |                   image-only pages: OCR, then measure
   |                   drawing vs prose                     -> Markdown + figure crops
   |  figures          OCR labels on diagrams               -> Arabic legend beneath
   |  segment          one unit per inline node             -> placeholders protect
   |                   formulas, code, links, numbers
   |  translate        batched, cached, glossary-consistent -> Arabic
   |  verify           every placeholder round-tripped?     -> or keep the source
   |  render           dir="rtl" HTML                       -> EPUB (+ PDF)
```

Because the output is HTML, the rendering engine runs the bidirectional algorithm and
text shaping correctly, for free. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) has the
full specification.

## Install

Needs Python 3.11 or newer.

```bash
git clone https://github.com/mohamad-aljeiawi/kitab-translate.git
cd kitab-translate

python -m venv .venv
.venv\Scripts\activate            # Windows
source .venv/bin/activate         # macOS / Linux

pip install -e .
```

That is enough to translate PDF, EPUB, HTML and Markdown with the free Google engine.

Optional extras, each independent:

| Extra | Install | What it adds |
|---|---|---|
| `fast` | `pip install -e '.[fast]'` | `pymupdf4llm`, better PDF structure, CPU only |
| `marker` | `pip install -e '.[marker]'` | Best PDF structure. Heavy (torch), needs Python 3.11/3.12 |
| `ocr` | `pip install -e '.[ocr]'` | Image-only PDFs, and Tier-1 figure legends |
| `pdf` | `pip install -e '.[pdf]'` then `playwright install chromium` | PDF output (~200 MB Chromium) |
| `japanese` | `pip install -e '.[japanese]'` | Vertical Japanese OCR for figures |
| `gui` | `pip install -e '.[gui]'` then `kitab-gui` | The desktop app, run from source |

## Desktop app

A window for everything the command line does, in English or Arabic (right to left).
You can queue several books and they run side by side with live progress. The Stop button keeps the work done so far, so
the book resumes from that point next time. API keys are kept in the system keyring,
not in a file.

**Download:** the [releases page](https://github.com/mohamad-aljeiawi/kitab-translate/releases)
has a Windows installer (`Kitab-<version>-windows-x64-setup.exe`, no administrator
rights needed), a portable Windows zip, and a Linux AppImage that runs on Ubuntu 22.04+,
Mint 21+ and Arch:

```bash
chmod +x Kitab-*-x86_64.AppImage
./Kitab-*-x86_64.AppImage                  # the window
./Kitab-*-x86_64.AppImage --cli book.pdf   # the same build as a command line
```

The Windows build ships `kitab-cli.exe` next to `kitab.exe` for the same purpose.

The builds include OCR and the lightweight PDF extractor. They leave out `marker` and
`japanese`, which need torch (2 GB+); use those from a source install. PDF output
prints through a browser that is already installed: Edge (on every Windows 11),
Chrome, Chromium or Brave.

**Where things live**

| | Windows | Linux |
|---|---|---|
| Settings | `%APPDATA%\kitab\gui.json` | `~/.config/kitab/gui.json` |
| API keys | Windows Credential Manager | GNOME Keyring / KWallet (Secret Service) |
| Work files | `%LOCALAPPDATA%\kitab\Cache\work` | `~/.cache/kitab/work` |

With no keyring running (a bare window manager on Arch, for instance), keys go to
`secrets.json` in the settings folder, readable only by you, and the Settings page
says so.

**Building it yourself** takes one command on the platform you are building for:

```bash
python packaging/build.py
```

The script creates its own Python 3.12 environment in `.venv-build`, using
[uv](https://docs.astral.sh/uv/) if it is installed, and leaves your development
environment alone. It then runs PyInstaller and wraps the result: an installer via
[Inno Setup](https://jrsoftware.org/isinfo.php) on Windows (skipped if Inno Setup is
missing), or an AppImage on Linux. PyInstaller cannot cross-compile, so build the
Linux version on Linux. Build it on the oldest distro you want to support, because
the AppImage needs a glibc at least as new as the one it was built on. Pushing a `v*`
tag makes CI build both and attach them to a draft release.

## Engines

| Engine | Key | Notes |
|---|---|---|
| `google` | none | Free web endpoint. Fine for samples and short works, rate-limited and unofficial. **Default.** |
| `openai` | `OPENAI_API_KEY` | Best quality. Batched, glossary-aware. |
| `deepseek` | `DEEPSEEK_API_KEY` | Same protocol, much cheaper per book. |
| `openailiked` | none | Any OpenAI-compatible endpoint: Ollama, vLLM, a gateway. |

```bash
export DEEPSEEK_API_KEY=sk-...
kitab book.pdf --service deepseek
```

Keys come from the environment or `~/.config/kitab/config.json`, never from the
repository. `kitab --engines` lists what each one wants.

### Reasoning models

For a reasoning model such as GPT-6 Luna, `--reasoning` sets how long it thinks
before answering: `none`, `minimal`, `low`, `medium`, `high`, `xhigh` or `max`.
The desktop app has the same choice next to the model name.

```bash
kitab book.pdf --service openai --model gpt-6-luna --reasoning low
```

- **Leave it unset** to use the model's own default (`medium` for Luna).
- **`none`** is the fastest and cheapest, and plenty for most prose.
- **Higher levels** cost more output tokens and help most with dense technical text.

Each model accepts its own set of levels; GPT-6 Astra, for example, rejects `none`.
If a model refuses the level you picked, the book stops with that message instead of
failing every paragraph. `temperature` is sent only when the model is not reasoning,
as OpenAI requires. The setting applies to `openai` and `openailiked`; DeepSeek picks
reasoning by model name instead (`deepseek-reasoner`).

### Speed and rate limits

Two independent knobs. `--workers` sets requests in flight, `--qps` sets requests started
per second across all workers. Both default per engine.

The limiter adapts. A 429, or a 403 or 503, or an empty 200 (which is how the free Google
endpoint says slow down) halves the rate for every worker, and sustained success walks it
back up. If you get blocked anyway, drop to `--qps 3 --workers 3`.

## What survives translation

These are protected byte for byte and never sent to an engine as translatable text:

- code spans and fenced code blocks
- inline and display maths (`$...$`, `$$...$$`, `\(...\)`)
- image references and link destinations
- section and figure numbers (`3.2.1`), URLs, email addresses
- `snake_case` identifiers
- glossary terms, when `--protect-terms` is given

Each one becomes a placeholder before translation and is verified after. A segment that
fails verification keeps its source text and gets listed in `report.json`.

Digits stay Western (0-9). Arabic-Indic numerals would break every cross-reference to a
figure that has not been translated.

## Code in technical books

Code is detected by typeface. A listing is set in a monospaced face and prose is not.
Listings become fenced code blocks, which the segmenter never sends to a translation
engine, and a monospaced word inside a sentence becomes inline code. In a programming
book this matters more than anything else. Hand `cin` to a translator and it comes back
as `سين`.

Indentation is not reconstructed. A PDF stores no leading spaces, so it would have to
come from geometry, and measured against a real book the geometry contradicts the
nesting. Listings keep their line numbers and no invented shape.

## PDF output

PDF is opt-in. `kitab book.pdf --pdf` prints the same HTML the EPUB is built from,
through headless Chromium.

> [!WARNING]
> Do not swap the bundled font for a Google Fonts link. Google serves WOFF2, Chromium
> cannot embed WOFF2 in a PDF, and it silently rasterises every glyph to Type 3. The page
> still looks right, but the text layer comes out scrambled and unsearchable.

## Figures

Two tiers, and only two.

**Tier 0** passes the image through untouched.

**Tier 1** reads its labels with OCR, translates them, and puts an Arabic legend beneath
the image, keyed by position. The artwork is never modified.

Someone reading a translated technical book needs to know what the labels on a diagram
say. They do not need the diagram redrawn.

## Page furniture and chapter breaks

Running heads, running feet and page numbers are dropped by repetition, so a chapter
title printed on every page is not translated 300 times and does not land as a stray
paragraph on each one.

A chapter opens on a new page, and the break covers the whole opening, a label plus the
title beneath it, so a label never ends up stranded on an empty page. No title page is
generated, because the book already has its own. Pass `--title-page` if you want one.

## Work directory

Every stage writes a file, and a stage whose output already exists is skipped unless you
pass `--force`:

```
out/.kitab/<book>/
  01_extract/document.md      extracted Markdown + images/
  02_document.json            segments and figure tiers
  03_translated.json          translations, before restore
  04_translated.md            translated Markdown  <- edit this by hand
  05_book.html                the RTL page the EPUB and PDF are built from
  glossary.json               the termbase  <- edit this before a long run
out/
  <book>.ar.epub
  <book>.ar.report.json
```

`glossary.json` and `04_translated.md` are the two files worth opening. Fixing twenty
terms in the glossary before the main run fixes them everywhere in the book.

## Try it

`samples/abstraction.md` is a short original document that exercises headings, maths, a
table, a blockquote and a code block:

```bash
kitab samples/abstraction.md -o samples/out
```

Books used for local development are copyrighted and cannot be redistributed, so no real
book ships with this repository. To try kitab on something full-length, use a work in the
public domain. [Project Gutenberg](https://www.gutenberg.org/) publishes EPUBs directly.

## Known limitations

Open problems, stated plainly. Help on any of these is welcome.

| # | Limitation | Workaround |
|---|---|---|
| 1 | Multi-column PDFs confuse the `builtin` backend | use `--backend fast` or `marker` |
| 2 | Heading detection is the weakest link in every tool in this category | check `04_translated.md` before rendering |
| 3 | `marker` and `pymupdf4llm` need Python 3.11/3.12 and may not install on newer runtimes | `builtin` covers the gap deliberately |
| 4 | Vector figures are not extracted, only embedded rasters. A figure drawn with PDF path operators is lost by `builtin` | use `--backend marker` |
| 5 | Footnotes are carried as text, not as linked EPUB footnotes | none yet |
| 6 | The free Google engine is unofficial. It rate-limits and can stop working | use `--service deepseek` for anything long |
| 7 | Tier-1 legends need a real diagram corpus; on image-only books the heading signal is measured height, which is weaker than a font size | none yet |
| 8 | No page-faithful mode, by design | use PDFMathTranslate |

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the details.
The test suite runs against a fake engine, so it needs no key and no network:

```bash
pip install -e '.[dev]'
pytest
```

## Licence

[AGPL-3.0](LICENSE), and not by preference. kitab links PyMuPDF and EbookLib, both
AGPL-3.0, and carries code from
[PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate), which is also AGPL-3.0.
Any one of those three would compel it on its own. If you run a modified kitab as a
network service, the AGPL requires you to offer users its source.

[NOTICE.md](NOTICE.md) has the full third-party breakdown.

### Credits

The translator layer, the persistent cache and the configuration store are carried over
from [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate) and keep their shape.
The rendering path is not. PDFMathTranslate rewrites the original PDF in place and so has
to implement the bidi algorithm and text shaping by hand. kitab emits HTML and lets the
rendering engine do that, correctly, for free.

Noto Naskh Arabic is bundled under the
[SIL Open Font License 1.1](kitab/render/assets/fonts/OFL.txt).

### Translating books you do not own

kitab is a tool, not a licence. Translation is a right reserved to the copyright holder in
every Berne Convention country. Use it on works in the public domain, works you hold the
rights to, or works whose licence allows translation, and keep the output of anything else
to yourself.
