"""Strict, read-only resolver for user-authored Hive feature catalog entries."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


FEATURE_ID_RE = re.compile(r"NW-F\d{3}\Z", re.IGNORECASE)
FEATURE_HEADING_RE = re.compile(r"^###\s+(NW-F\d{3})\s+[—-]\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^\s*-\s+\*\*(?P<name>[^*]+?)\*\*:?\s*(?P<value>.*)$")
LIST_ITEM_RE = re.compile(r"^\s+(?:\d+[.)]|[-*])\s+(.+?)\s*$")
MAX_CATALOG_BYTES = 512 * 1024
MAX_FEATURE_SECTION_BYTES = 16 * 1024


class FeatureCatalogError(ValueError):
    """The catalog cannot be parsed safely."""


class FeatureNotFoundError(LookupError):
    """The requested feature ID is absent from the catalog."""


def _field_name(value: str) -> str | None:
    key = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    aliases = {
        "status": "status",
        "objective": "objective",
        "behavior": "objective",
        "scope": "scope",
        "dependencies": "dependencies",
        "acceptance criteria": "acceptance_criteria",
        "acceptance if behavior is changed later": "acceptance_criteria",
        "constraints": "constraints",
        "constraint": "constraints",
        "origin": "evidence",
        "evidence": "evidence",
    }
    return aliases.get(key)


def _parse_section(lines: list[str], raw: str) -> dict:
    heading = FEATURE_HEADING_RE.fullmatch(lines[0])
    if not heading:
        raise FeatureCatalogError("Malformed feature heading")

    values: dict[str, list[str]] = {}
    active: str | None = None
    for line in lines[1:]:
        if re.match(r"^#{2,3}\s+", line):
            break
        field = FIELD_RE.match(line)
        if field:
            active = _field_name(field.group("name").rstrip(":"))
            if active is None:
                continue
            values.setdefault(active, [])
            value = field.group("value").strip()
            if value:
                values[active].append(value)
            continue
        if not line.strip() or active is None:
            continue
        item = LIST_ITEM_RE.match(line)
        if item:
            values.setdefault(active, []).append(item.group(1).strip())
        elif line[:1].isspace() and values.get(active):
            values[active][-1] = f"{values[active][-1]} {line.strip()}".strip()
        else:
            active = None

    def scalar(key: str) -> str:
        return " ".join(values.get(key, [])).strip()

    return {
        "id": heading.group(1).upper(),
        "title": heading.group(2).strip(),
        "status": scalar("status"),
        "objective": scalar("objective"),
        "scope": values.get("scope", []),
        "dependencies": scalar("dependencies"),
        "acceptance_criteria": values.get("acceptance_criteria", []),
        "constraints": values.get("constraints", []),
        "evidence": values.get("evidence", []),
        "spec_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def load_features(catalog_path: Path) -> dict[str, dict]:
    try:
        with catalog_path.open("rb") as catalog_file:
            raw_bytes = catalog_file.read(MAX_CATALOG_BYTES + 1)
        if len(raw_bytes) > MAX_CATALOG_BYTES:
            raise FeatureCatalogError("Feature catalog exceeds the 512 KiB size limit")
        text = raw_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FeatureCatalogError(f"Feature catalog is unavailable: {exc}") from exc

    lines = text.splitlines()
    starts: list[int] = []
    for index, line in enumerate(lines):
        if line.startswith("### NW-F"):
            if not FEATURE_HEADING_RE.fullmatch(line):
                raise FeatureCatalogError(f"Malformed feature heading on line {index + 1}")
            starts.append(index)

    features: dict[str, dict] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        for next_heading in range(start + 1, end):
            if re.match(r"^##\s+", lines[next_heading]):
                end = next_heading
                break
        block = lines[start:end]
        raw = "\n".join(block).rstrip() + "\n"
        if len(raw.encode("utf-8")) > MAX_FEATURE_SECTION_BYTES:
            raise FeatureCatalogError(f"{block[0]} exceeds the 16 KiB specification limit")
        feature = _parse_section(block, raw)
        if not feature["status"]:
            raise FeatureCatalogError(f"{feature['id']} is missing a Status field")
        if feature["id"] in features:
            raise FeatureCatalogError(f"Duplicate feature ID: {feature['id']}")
        features[feature["id"]] = feature
    return features


def resolve_feature(catalog_path: Path, feature_id: str) -> dict:
    if not isinstance(feature_id, str) or not FEATURE_ID_RE.fullmatch(feature_id.strip()):
        raise FeatureNotFoundError("Feature ID must use the form NW-F001")
    normalized = feature_id.strip().upper()
    features = load_features(catalog_path)
    if normalized not in features:
        raise FeatureNotFoundError(f"Feature {normalized} was not found")
    return features[normalized]


def buildability(feature: dict) -> tuple[bool, str | None]:
    if not feature.get("status", "").strip().lower().startswith("planned"):
        return False, f"Feature status is '{feature.get('status', 'unknown')}', not Planned."
    missing = [
        name for name, value in (
            ("Objective", feature.get("objective")),
            ("Scope", feature.get("scope")),
            ("Acceptance criteria", feature.get("acceptance_criteria")),
            ("Constraints", feature.get("constraints")),
        ) if not value
    ]
    if missing:
        return False, "Feature specification is incomplete: " + ", ".join(missing) + "."
    return True, None


def render_build_request(feature: dict) -> str:
    """Serialize the approved catalog entry as the complete bounded user request."""
    payload = {
        key: feature[key]
        for key in (
            "id", "title", "objective", "scope", "dependencies",
            "acceptance_criteria", "constraints", "evidence",
        )
    }
    return (
        "Implement the selected Nix Workshop feature catalog entry below. "
        "This is the complete user-approved feature request. Treat its scope, "
        "acceptance criteria, and constraints as authoritative; do not add unrelated work.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
