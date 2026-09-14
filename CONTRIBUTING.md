# Contributing to kitab

Thanks for considering it. kitab is deliberately small, about 4,500 lines, and the goal
is to keep it readable.

## Getting set up

```bash
git clone https://github.com/mohamad-aljeiawi/kitab-translate.git
cd kitab-translate

python -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -e '.[dev]'

pytest
```

The suite runs against a fake translation engine, so it needs no API key and no network.
If a test you add needs either, put it behind a marker and make sure it skips cleanly
without them.

## Before you open a pull request

```bash
black kitab tests      # formatting
flake8 kitab tests     # linting
pytest                 # 69 tests, about 4 seconds
```

## What is most useful

The [Known limitations](README.md#known-limitations) table is the live list. These have
the most leverage right now:

- Heading detection (limitation 2), the weakest link in every tool in this category.
- Vector figure extraction (limitation 4). Figures drawn with PDF path operators are
  currently lost by the `builtin` backend.
- OCR against real scans (limitation 7). The RapidOCR path is written but has never been
  exercised against a real corpus of scanned pages.
- Linked EPUB footnotes (limitation 5).

## Things that will be declined

Listed here so you do not spend an evening on them.

**A `--to` flag or a language matrix.** One direction is the design, not an oversight. It
is what keeps the segmenter, the glossary and the RTL rendering path simple enough to get
right.

**Page-faithful or fixed-layout output.** That is
[PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate)'s job and it does it well.
See section 0 of [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Inpainting translated text back into figures.** Tier 0 and Tier 1 are the whole design.

**Reconstructing code indentation from PDF geometry.** This was measured against a real
book and the geometry contradicts the nesting.

**Replacing the bundled font with a Google Fonts link.** Chromium cannot embed WOFF2 into
a PDF and silently rasterises every glyph, which destroys the text layer.

## Ground rules

Never commit a copyrighted book, or anything extracted from one. `samples/` is for
original or public-domain content only. `.gitignore` is set up to help, but check anyway.

Never commit an API key. Keys belong in the environment or in
`~/.config/kitab/config.json`.

A stage that cannot do its job should degrade and say so, not raise. An uninstalled extra
must never fail a run.

If a translated segment fails placeholder verification it keeps its source text. Please
preserve that.

## Licence

kitab is AGPL-3.0 and, as [NOTICE.md](NOTICE.md) explains, cannot be anything else while
it links PyMuPDF and EbookLib. By contributing you agree your work is licensed the same
way.
