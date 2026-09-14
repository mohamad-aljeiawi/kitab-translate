"""Stage 1-3: turn a source file into Markdown plus an images directory."""

from .classify import SourceKind, classify
from .extract import extract

__all__ = ["classify", "SourceKind", "extract"]
