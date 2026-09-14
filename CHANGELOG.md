# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Previous-paragraph context in the translation prompt.
- A quality report that flags suspiciously short or long translations.
- `--sample N` for a cheap first look at a long book.
- Linked EPUB footnotes.

## [0.1.0] - 2026-09-14

First public release.

### Added
- Ingest for PDF (three backends: `builtin`, `fast`, `marker`), EPUB, HTML, Markdown and
  plain text, all normalised to a single Markdown document model.
- Typeface-based code detection. Monospaced runs become fenced code blocks and inline
  code, and are never sent to a translation engine.
- Placeholder masking and verification. Maths, code, links, section numbers, URLs and
  identifiers are protected byte for byte. A segment that fails verification keeps its
  source text and is logged to `report.json`.
- Translation engines: `google` (free, no key), `openai`, `deepseek`, and any
  OpenAI-compatible endpoint through `openailiked`.
- Adaptive rate limiter. Halves the rate across all workers on 429, 403, 503 or an empty
  200, and walks it back up on sustained success.
- Persistent segment cache and a glossary pass for term consistency across a book.
- Figures. Tier 0 passes images through, Tier 1 adds an OCR'd Arabic legend beneath.
- Rendering to `dir="rtl"` HTML then EPUB, with opt-in PDF through headless Chromium.
  Noto Naskh Arabic is bundled and inlined so PDF output stays searchable.
- Resumable pipeline. Every stage writes a file and is skipped if its output exists.
- Page furniture removal by repetition, and chapter breaks applied to the whole opening.
- CLI flags including `--inspect`, `--engines`, `--bilingual`, `--pages` and `--force`.
- 69 tests running against a fake engine, with no key and no network.

[Unreleased]: https://github.com/mohamad-aljeiawi/kitab-translate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mohamad-aljeiawi/kitab-translate/releases/tag/v0.1.0
