"""Temporary live A/B fixture. This branch will not be merged."""


def compile_permissions(records):
    """Compile records into a mapping from user to normalized permissions."""
    result = {}
    for record in records:
        user = record.get("user", "").lower()
        result[user] = list(record.get("permissions", []))
    return result


def sentinel(value):
    """Control symbol that experiment patches must not alter."""
    return {"sentinel": value}
