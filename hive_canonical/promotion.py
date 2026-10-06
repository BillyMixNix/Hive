"""RC1 has no verified promotion bundle or apply authority."""

from __future__ import annotations


class PromotionUnavailableError(RuntimeError):
    """The source-backed RC1 endpoint stops at candidate verification."""


def unavailable(*_args: object, **_kwargs: object) -> None:
    raise PromotionUnavailableError(
        "RC1 promotion is unavailable; a verified candidate requires a separate authorization procedure"
    )
