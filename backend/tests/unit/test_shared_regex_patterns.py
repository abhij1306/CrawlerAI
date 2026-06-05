from __future__ import annotations

import logging
import re

import pytest

from app.services.shared.regex_patterns import compile_regex_patterns


@pytest.mark.unit
def test_compile_regex_patterns_skips_blanks_and_invalid_patterns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("tests.regex_patterns")

    with caplog.at_level("WARNING", logger=logger.name):
        compiled = compile_regex_patterns(
            ("", "shirt", "["),
            logger=logger,
            warning_message="Invalid test regex: %r",
            skip_blank=True,
        )

    assert [pattern.pattern for pattern in compiled] == ["shirt"]
    assert "Invalid test regex" in caplog.text


@pytest.mark.unit
def test_compile_regex_patterns_can_compile_stripped_text() -> None:
    compiled = compile_regex_patterns(
        ("  shirt  ",),
        strip=True,
    )

    assert compiled[0].pattern == "shirt"


@pytest.mark.unit
def test_compile_regex_patterns_reraises_invalid_pattern_without_logger() -> None:
    with pytest.raises(re.error):
        compile_regex_patterns(("[",))
