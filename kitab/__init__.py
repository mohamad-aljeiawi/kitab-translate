"""Kitab -- one-direction book translator (English/Japanese -> Arabic).

The pipeline is a chain of file-on-disk stages; see ``kitab.pipeline``.
"""

__version__ = "0.2.0"

LANG_OUT = "ar"
SUPPORTED_LANG_IN = ("en", "ja", "auto")
