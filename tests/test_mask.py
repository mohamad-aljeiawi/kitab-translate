"""Masking is the load-bearing part of the design: if a placeholder is lost, a formula
or a code identifier is lost with it. These tests pin down the round-trip and, just as
importantly, the failure reporting."""

from kitab.md.mask import CURLY, SQUARE, find_ids, mask_text, restore_text


def test_roundtrip_is_lossless():
    text = "Use `foo_bar()` in [the docs](http://x.io/a) per section 3.2.1."
    masked, literals = mask_text(text, CURLY)
    restored, missing, unexpected = restore_text(masked, literals, CURLY)
    assert restored == text
    assert not missing and not unexpected


def test_code_and_math_are_protected():
    text = "The bound $O(n \\log n)$ holds; see `queue_size`."
    masked, literals = mask_text(text, CURLY)
    assert "$O(n" not in masked
    assert "queue_size" not in masked
    assert "$O(n \\log n)$" in literals
    assert "`queue_size`" in literals


def test_currency_is_not_treated_as_maths():
    masked, literals = mask_text("It costs $5 and $10 together.", CURLY)
    assert masked == "It costs $5 and $10 together."
    assert literals == []


def test_plain_integers_are_left_alone():
    """A bare number is prose. Only dotted section numbers are protected."""
    masked, _ = mask_text("There were 3 chapters and 12 figures.", CURLY)
    assert "3" in masked and "12" in masked


def test_link_text_stays_translatable():
    masked, literals = mask_text("See [the manual](http://x.io) now.", CURLY)
    assert "the manual" in masked  # translatable
    assert "](http://x.io)" in literals  # destination protected


def test_reordering_is_allowed():
    """Arabic word order moves placeholders. That must not be an error."""
    masked, literals = mask_text("Run `init()` before `start()`.", CURLY)
    swapped = (
        masked.replace("{{v0}}", "TMP")
        .replace("{{v1}}", "{{v0}}")
        .replace("TMP", "{{v1}}")
    )
    _restored, missing, unexpected = restore_text(swapped, literals, CURLY)
    assert not missing and not unexpected


def test_dropped_placeholder_is_reported():
    masked, literals = mask_text("Call `sync_now()` twice.", CURLY)
    _restored, missing, unexpected = restore_text(
        masked.replace("{{v0}}", ""), literals, CURLY
    )
    assert missing == {0}
    assert not unexpected


def test_duplicated_placeholder_is_reported():
    masked, literals = mask_text("Call `sync_now()` twice.", CURLY)
    _restored, missing, unexpected = restore_text(masked + " {{v0}}", literals, CURLY)
    assert not missing
    assert unexpected == {0}


def test_invented_placeholder_is_reported_and_left_visible():
    masked, literals = mask_text("Call `sync_now()`.", CURLY)
    restored, missing, unexpected = restore_text(masked + " {{v9}}", literals, CURLY)
    assert unexpected == {9}
    assert "{{v9}}" in restored  # never guessed at


def test_engine_whitespace_is_tolerated():
    """Engines insert spaces inside a token. That is not a failure."""
    masked, literals = mask_text("Call `sync_now()`.", CURLY)
    mangled = masked.replace("{{v0}}", "{{ v0 }}")
    restored, missing, unexpected = restore_text(mangled, literals, CURLY)
    assert not missing and not unexpected
    assert "`sync_now()`" in restored


def test_square_style_for_statistical_engines():
    masked, literals = mask_text("See `x_y` now.", SQUARE)
    assert "[[0]]" in masked
    assert find_ids(masked, SQUARE) == [0]
    restored, missing, unexpected = restore_text(masked, literals, SQUARE)
    assert restored == "See `x_y` now."
    assert not missing and not unexpected


def test_glossary_terms_can_be_protected():
    masked, literals = mask_text(
        "The Kalman Filter converges.", CURLY, protected_terms=["Kalman Filter"]
    )
    assert "Kalman Filter" not in masked
    assert literals == ["Kalman Filter"]


def test_start_index_offsets_ids():
    masked, literals = mask_text("Use `a_b`.", CURLY, start_index=7)
    assert "{{v7}}" in masked
    assert len(literals) == 1


def test_complexity_notation_is_protected():
    """Engines translate "O(n)" into Arabic prose if you let them."""
    masked, literals = mask_text("Lookup is O(1) but sorting is O(n log n).", CURLY)
    assert "O(1)" not in masked
    assert "O(n log n)" not in masked
    assert literals == ["O(1)", "O(n log n)"]


def test_notation_rule_does_not_eat_ordinary_prose():
    masked, literals = mask_text("See Figure (a) and the note (below).", CURLY)
    assert masked == "See Figure (a) and the note (below)."
    assert literals == []


def test_lettered_section_numbers_are_protected():
    """ "D.1" unprotected becomes "د.1", which UAX #9 then renders as "1.د"."""
    masked, literals = mask_text("See D.1 and A.2.3 for details.", CURLY)
    assert "D.1" not in masked
    assert literals == ["D.1", "A.2.3"]
