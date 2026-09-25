# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- The desktop app speaks Arabic. Choose English, العربية or the system language in
  Settings; the whole window turns right to left, and the switch happens live without
  stopping books that are translating.
- Colours follow the system. The accent colour is your Windows accent (or the
  desktop's on Linux), in the shades Windows itself uses for buttons in light and
  dark mode; light/dark follows the system as it changes; and the Windows 11 Mica
  backdrop follows the "Transparency effects" switch. Changes apply while the app is
  open. "Kitab green" is available as a fixed alternative.

### Changed
- The desktop app is reorganised so nothing overlaps at any window size. Each option
  is one row with a sentence explaining it, and controls move under the text when the
  window is narrow. Options most books never need sit under "More options".
- Every book in "My translations" (formerly Jobs) has one clearly labelled button for
  what to do next -- Stop, Open book, Try again, Continue -- and the rest in a menu,
  instead of a row of unlabelled icons.
- On/off choices are switches, the page range is checked as you type, and the Start
  button explains why it is unavailable.
- Settings save as you change them; the Save button is gone. Each translation
  service opens to its key, model and address, and shows whether a key is saved.
- Plainer wording throughout, written for each language rather than translated
  word for word.

### Planned
- Previous-paragraph context in the translation prompt.
- A quality report that flags suspiciously short or long translations.
- `--sample N` for a cheap first look at a long book.
- Linked EPUB footnotes.

## [0.3.0] - 2026-09-25

### Added
- Reasoning effort for OpenAI and OpenAI-compatible reasoning models such as GPT-6
  Luna: `--reasoning none|minimal|low|medium|high|xhigh|max`, and a menu next to the
  model in the desktop app, remembered per engine. Unset means the model's default.
  A level the model refuses stops the book with a clear message instead of failing
  every segment.

### Fixed
- `temperature` is no longer sent to a model while it is reasoning. OpenAI rejects
  that combination, which made GPT-6 models unusable at their default effort.
- The packaged app failed on every digital PDF: PyMuPDF's layout models, which the
  fast extractor loads at run time, were missing from the bundle. The build now also
  checks for every data set loaded at run time and refuses to finish without them.

## [0.2.0] - 2026-09-25

### Added
- Desktop app for Windows and Linux (`kitab-gui`, or the packaged builds). Queue
  several books and they run side by side, each in its own process, with live progress
  by stage. Stop keeps the work done so far and Retry resumes from there.
- Settings page: theme, how many books run at once, requests in flight, PDF page size,
  and the key, model and endpoint for each engine. The last options used on the
  Translate page are remembered.
- API keys are stored in Windows Credential Manager or the Linux Secret Service
  (GNOME Keyring, KWallet). With no keyring, they fall back to a file readable only by
  the user, and the app says so.
- Packaged builds: a Windows installer (per-user, no administrator rights) and portable
  zip, and a Linux AppImage for Ubuntu 22.04+, Mint 21+ and Arch. Each ships the
  command line too (`kitab-cli.exe`, or `Kitab.AppImage --cli`).
- `python packaging/build.py` builds either one in a single command. Pushing a `v*` tag
  builds both in CI and attaches them to a release.
- Image-only PDFs. Pages are OCR'd, diagrams are separated from prose and cropped out
  as figures, and headings and paragraphs are rebuilt from the page geometry. This runs
  automatically on scanned PDFs when the `ocr` extra is installed.

### Changed
- PDF output falls back to an installed Edge, Chrome, Chromium or Brave when
  Playwright's own Chromium is missing.
- Stage files are written to a temporary file and renamed into place, so an
  interrupted run never leaves half a file behind.
- The `ocr` extra uses `rapidocr` + `onnxruntime`, which install on Python 3.13+.

### Fixed
- CI installed a `dev` extra that does not exist, so pytest was never installed and
  every test job failed.

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

[Unreleased]: https://github.com/mohamad-aljeiawi/kitab-translate/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mohamad-aljeiawi/kitab-translate/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mohamad-aljeiawi/kitab-translate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mohamad-aljeiawi/kitab-translate/releases/tag/v0.1.0
