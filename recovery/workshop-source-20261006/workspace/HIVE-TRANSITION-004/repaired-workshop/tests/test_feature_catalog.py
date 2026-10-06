import pytest

from workshop import feature_catalog


CATALOG = """# Feature backlog

## Planned

### NW-F010 — Example buildable feature
- **Status:** Planned
- **Objective:** Add a report card to Settings.
- **Scope:**
  - Read GET /api/health.
  - Render the report card in Settings.
- **Dependencies:** Existing health endpoint.
- **Acceptance criteria:**
  1. The card displays the health response.
  2. Tests cover the real endpoint contract.
- **Constraints:**
  - Do not change the health endpoint.
  - Do not apply automatically.
- **Evidence:** Prior run abc123.

### NW-F011 — Undefined queued feature
- **Status:** Queued / needs definition
- **Objective:** Add a future feature.
- **Scope:** To be defined.
- **Dependencies:** None.
- **Acceptance criteria:** To be defined.
- **Constraints:** Do not invent acceptance criteria.
"""


def _write_catalog(tmp_path, contents=CATALOG):
    path = tmp_path / "FEATURES.md"
    path.write_text(contents, encoding="utf-8")
    return path


def test_resolves_exact_structured_spec_and_section_hash(tmp_path):
    path = _write_catalog(tmp_path)

    feature = feature_catalog.resolve_feature(path, "nw-f010")
    buildable, reason = feature_catalog.buildability(feature)

    assert feature["id"] == "NW-F010"
    assert feature["title"] == "Example buildable feature"
    assert feature["objective"] == "Add a report card to Settings."
    assert feature["scope"] == [
        "Read GET /api/health.",
        "Render the report card in Settings.",
    ]
    assert feature["dependencies"] == "Existing health endpoint."
    assert feature["acceptance_criteria"] == [
        "The card displays the health response.",
        "Tests cover the real endpoint contract.",
    ]
    assert feature["constraints"] == [
        "Do not change the health endpoint.",
        "Do not apply automatically.",
    ]
    assert len(feature["spec_sha256"]) == 64
    assert buildable is True
    assert reason is None


def test_hash_changes_when_selected_feature_spec_changes(tmp_path):
    path = _write_catalog(tmp_path)
    before = feature_catalog.resolve_feature(path, "NW-F010")["spec_sha256"]
    path.write_text(CATALOG.replace("report card in Settings", "summary card in Settings"), encoding="utf-8")
    after = feature_catalog.resolve_feature(path, "NW-F010")["spec_sha256"]
    assert before != after


@pytest.mark.parametrize("feature_id", ["NW-F999", "../NW-F010", "NW-F010/../../app.py", ""])
def test_unknown_and_unsafe_ids_fail_closed(tmp_path, feature_id):
    with pytest.raises(feature_catalog.FeatureNotFoundError):
        feature_catalog.resolve_feature(_write_catalog(tmp_path), feature_id)


def test_nonplanned_or_incomplete_entries_are_not_buildable(tmp_path):
    features = feature_catalog.load_features(_write_catalog(tmp_path))

    assert feature_catalog.buildability(features["NW-F011"])[0] is False
    incomplete = dict(features["NW-F010"], scope=[])
    buildable, reason = feature_catalog.buildability(incomplete)
    assert buildable is False
    assert "Scope" in reason


def test_duplicate_or_malformed_catalog_ids_fail_closed(tmp_path):
    duplicate = CATALOG.replace("### NW-F011 — Undefined queued feature", "### NW-F010 — Undefined queued feature")
    with pytest.raises(feature_catalog.FeatureCatalogError, match="Duplicate feature ID"):
        feature_catalog.load_features(_write_catalog(tmp_path, duplicate))

    malformed = CATALOG.replace("### NW-F010 — Example buildable feature", "### NW-FXXX — Example buildable feature")
    with pytest.raises(feature_catalog.FeatureCatalogError, match="Malformed feature heading"):
        feature_catalog.load_features(_write_catalog(tmp_path, malformed))


def test_catalog_and_individual_specs_are_size_bounded(tmp_path):
    oversized_spec = CATALOG.replace(
        "Add a report card to Settings.",
        "x" * feature_catalog.MAX_FEATURE_SECTION_BYTES,
    )
    with pytest.raises(feature_catalog.FeatureCatalogError, match="16 KiB"):
        feature_catalog.load_features(_write_catalog(tmp_path, oversized_spec))

    oversized_catalog = "# backlog\n" + ("x" * feature_catalog.MAX_CATALOG_BYTES)
    with pytest.raises(feature_catalog.FeatureCatalogError, match="512 KiB"):
        feature_catalog.load_features(_write_catalog(tmp_path, oversized_catalog))


def test_rendered_request_contains_scope_dependencies_acceptance_and_constraints(tmp_path):
    feature = feature_catalog.resolve_feature(_write_catalog(tmp_path), "NW-F010")
    request = feature_catalog.render_build_request(feature)

    for required_text in (
        "NW-F010", "Read GET /api/health.", "Existing health endpoint.",
        "Tests cover the real endpoint contract.", "Do not apply automatically.",
    ):
        assert required_text in request
