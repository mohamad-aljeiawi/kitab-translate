# Third-party notices

kitab is licensed under the GNU Affero General Public License v3.0 ([LICENSE](LICENSE)).

That is not a preference. Three separate facts each force it on their own:

1. **PyMuPDF**, the default PDF backend, is AGPL-3.0 (or a paid Artifex commercial licence).
2. **EbookLib**, the EPUB writer, is AGPL-3.0-or-later.
3. Parts of kitab are derived from
   [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate), which is AGPL-3.0.

The AGPL is a strong copyleft licence, so any work that links PyMuPDF or EbookLib and is
distributed at all has to be AGPL-3.0 itself. There is no permissive re-licensing
available here without dropping all three.

What that means if you are using kitab: run it, modify it, translate what you like. If
you distribute a modified version, or run one as a network service, section 13 of the
AGPL requires you to offer your users the corresponding source.

## Derived code

| Component | Origin | Licence |
|---|---|---|
| `kitab/config.py` | `pdf2zh.config` in [PDFMathTranslate](https://github.com/Byaidu/PDFMathTranslate) | AGPL-3.0 |
| `kitab/cache.py` | `pdf2zh.cache` in PDFMathTranslate | AGPL-3.0 |
| `kitab/translate/` (translator layer) | PDFMathTranslate translator interface | AGPL-3.0 |
| `kitab/md/mask.py` | placeholder concept from PDFMathTranslate, implementation new | AGPL-3.0 |

Everything else is original to this project: ingest, the Markdown document model,
figures, segmentation and rendering.

## Runtime dependencies

| Package | Licence | Copyleft? |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | AGPL-3.0 or Artifex Commercial | **Yes** |
| [EbookLib](https://github.com/aerkalov/ebooklib) | AGPL-3.0-or-later | **Yes** |
| [markdown-it-py](https://github.com/executablebooks/markdown-it-py) | MIT | No |
| [mdit-py-plugins](https://github.com/executablebooks/mdit-py-plugins) | MIT | No |
| [mdformat](https://github.com/hukkin/mdformat) and `mdformat-tables` | MIT | No |
| [markdownify](https://github.com/matthewwithanm/python-markdownify) | MIT | No |
| [Jinja2](https://palletsprojects.com/p/jinja/) | BSD-3-Clause | No |
| [openai](https://github.com/openai/openai-python) | Apache-2.0 | No |
| [requests](https://requests.readthedocs.io/) | Apache-2.0 | No |
| [tenacity](https://github.com/jd/tenacity) | Apache-2.0 | No |
| [peewee](https://github.com/coleifer/peewee) | MIT | No |
| [rich](https://github.com/Textualize/rich) | MIT | No |

### Optional extras

| Extra | Package | Licence |
|---|---|---|
| `marker` | [marker-pdf](https://github.com/VikParuchuri/marker) | GPL-3.0 |
| `fast` | [pymupdf4llm](https://github.com/pymupdf/RAG) | AGPL-3.0 |
| `ocr` | [rapidocr-onnxruntime](https://github.com/RapidAI/RapidOCR) | Apache-2.0 |
| `pdf` | [playwright](https://playwright.dev/python/) | Apache-2.0 |
| `japanese` | [manga-ocr](https://github.com/kha-white/manga-ocr) | Apache-2.0 |

Note that `marker` is GPL-3.0 and its upstream models carry their own terms. Review them
before using `--backend marker` in a commercial setting.

## Bundled assets

Noto Naskh Arabic, in `kitab/render/assets/fonts/`, is copyright the Noto Project Authors
and licensed under the [SIL Open Font License 1.1](kitab/render/assets/fonts/OFL.txt). The
OFL allows bundling and embedding, including inlining into generated EPUB and PDF output.

## A note on translated output

kitab claims no right in what it produces. Copyright in a translation belongs to the
rights holder of the original work, and the translation right is reserved to them in every
Berne Convention country. Use kitab on public-domain works, works you hold the rights to,
or works whose licence allows translation.
