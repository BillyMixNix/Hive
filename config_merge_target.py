"""Temporary live A/B fixture. This branch is not intended to merge."""


def merge_settings(defaults, overrides):
    """Return settings with top-level overrides applied."""
    if not isinstance(defaults, dict) or not isinstance(overrides, dict):
        return {}
    result = dict(defaults)
    result.update(overrides)
    return result


def sentinel(value):
    """Control symbol that the patch must not alter."""
    return {"sentinel": value}
