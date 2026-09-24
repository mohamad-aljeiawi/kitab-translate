"""The data that flows between stages.

Everything here is JSON-serialisable on purpose: each stage writes its output to the
work directory, so a run can be inspected, hand-corrected and resumed at any boundary.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Where a segment came from. Used for prompting (a heading is translated differently
# from a code caption) and for reporting.
SEGMENT_KINDS = (
    "heading",
    "paragraph",
    "list_item",
    "table_cell",
    "blockquote",
    "caption",
    "figure_legend",
    "metadata",
)


@dataclass
class Segment:
    """One translatable unit: the text of a single Markdown inline node."""

    id: str
    kind: str
    source: str  # masked source text, exactly what the engine receives
    placeholders: list[str] = field(default_factory=list)  # index -> original literal
    translation: Optional[str] = None  # masked translation, before restore
    status: str = "pending"  # pending | translated | cached | failed | skipped
    note: str = ""  # why it failed, if it did

    @property
    def translated(self) -> bool:
        return self.status in ("translated", "cached")


@dataclass
class Figure:
    """An image extracted from the source document."""

    id: str
    path: str  # relative to the extract directory
    tier: int = 0  # 0 = pass through, 1 = OCR + Arabic legend beneath
    ocr_lines: list[dict[str, Any]] = field(default_factory=list)  # {text, box, pos}
    legend_segment_ids: list[str] = field(default_factory=list)


@dataclass
class Document:
    """The whole book between stages."""

    title: str
    lang_in: str
    markdown: str = ""
    segments: list[Segment] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def segment_by_id(self, sid: str) -> Optional[Segment]:
        for s in self.segments:
            if s.id == sid:
                return s
        return None

    # ---- persistence ---------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Document":
        raw = json.loads(text)
        return cls(
            title=raw["title"],
            lang_in=raw["lang_in"],
            markdown=raw.get("markdown", ""),
            segments=[Segment(**s) for s in raw.get("segments", [])],
            figures=[Figure(**f) for f in raw.get("figures", [])],
            meta=raw.get("meta", {}),
        )

    def save(self, path: Path) -> None:
        # Write-then-rename: a stage file is how a run resumes, so a process killed
        # mid-write must leave the previous file or none, never half of one.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Document":
        return cls.from_json(path.read_text(encoding="utf-8"))


@dataclass
class Report:
    """What actually happened, written next to the output as report.json."""

    input_path: str = ""
    service: str = ""
    model: str = ""
    lang_in: str = ""
    lang_out: str = "ar"
    stages: dict[str, Any] = field(default_factory=dict)
    segments_total: int = 0
    segments_translated: int = 0
    segments_cached: int = 0
    segments_failed: int = 0
    figures_tier0: int = 0
    figures_tier1: int = 0
    warnings: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
