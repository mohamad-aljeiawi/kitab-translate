"""Exception types. Every failure the pipeline can recover from is one of these."""


class KitabError(Exception):
    """Base class for all Kitab errors."""


class UnsupportedInput(KitabError):
    """The input file is not a format we ingest."""


class ExtractionError(KitabError):
    """Stage 2/3 could not produce a document model."""


class MissingDependency(KitabError):
    """An optional extra is required for the requested mode but is not installed."""

    def __init__(self, package: str, extra: str, purpose: str):
        super().__init__(
            f"{purpose} requires the '{package}' package. "
            f"Install it with:  pip install 'kitab[{extra}]'"
        )
        self.package = package
        self.extra = extra


class PlaceholderMismatch(KitabError):
    """A translated segment lost, duplicated or invented a protected placeholder."""

    def __init__(self, segment_id: str, missing, extra):
        super().__init__(
            f"segment {segment_id}: placeholders missing={sorted(missing)} "
            f"unexpected={sorted(extra)}"
        )
        self.segment_id = segment_id
        self.missing = missing
        self.extra = extra


class BatchShapeError(KitabError):
    """An LLM returned a different number of segments than it was given."""


class TranslationFailed(KitabError):
    """A segment could not be translated after every retry and fallback."""
