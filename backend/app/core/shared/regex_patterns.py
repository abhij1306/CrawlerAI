from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
import re

__all__ = ("compile_regex_patterns",)

RegexWarningExtraFactory = Callable[[object, str, re.error], dict[str, object]]


def compile_regex_patterns(
    patterns: Iterable[object],
    *,
    flags: int = re.I,
    logger: logging.Logger | None = None,
    warning_message: str = "Skipping invalid regex pattern: %r",
    skip_blank: bool = True,
    strip: bool = False,
    preserve_compiled: bool = False,
    warning_pattern_arg: bool = True,
    warning_extra: RegexWarningExtraFactory | None = None,
) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if preserve_compiled and isinstance(pattern, re.Pattern):
            compiled.append(pattern)
            continue
        text = str(pattern)
        if skip_blank and not text.strip():
            continue
        compile_text = text.strip() if strip else text
        try:
            compiled.append(re.compile(compile_text, flags))
        except re.error as exc:
            if logger is None:
                raise
            extra = warning_extra(pattern, compile_text, exc) if warning_extra else None
            if warning_pattern_arg:
                logger.warning(warning_message, pattern, extra=extra)
            else:
                logger.warning(warning_message, extra=extra)
    return tuple(compiled)
