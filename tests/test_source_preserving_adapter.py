import copy

import pytest

from hive_compressor.adapter import build_adapter_packet, preserve_source, recover_source
from hive_compressor.compressor import CompressionError, compress_records


def canonical_record(ref="state-1", **updates):
    record = {
        "ref": ref,
        "effective_t": 1,
        "kind": "constraint",
        "authority": "user_instruction",
        "status": "active",
        "requires": [],
        "effects": ["do_not_modify_auth"],
    }
    record.update(updates)
    return record


def test_human_text_is_preserved_verbatim_and_recoverable():
    text = "Keep the old login system working for now. Don't touch auth in this patch."
    source = preserve_source("msg-1", text)
    packet = build_adapter_packet(
        [source],
        [{"record": canonical_record(), "source_refs": ["msg-1"]}],
    )

    assert packet["source_evidence"][0]["text"] == text
    assert recover_source(packet, "msg-1") == text
    assert "text" not in packet["compression_records"][0]


def test_compressor_only_receives_machine_state():
    source = preserve_source("msg-1", "Start OAuth work now.")
    packet = build_adapter_packet(
        [source],
        [{"record": canonical_record(effects=["current_task=migrate_oauth"]), "source_refs": ["msg-1"]}],
    )

    result = compress_records(packet["compression_records"], mode="c1")
    assert result["records"][0]["effects"] == ["current_task=migrate_oauth"]
    assert "Start OAuth work now." not in repr(result["records"])


def test_derived_state_must_have_source_lineage():
    source = preserve_source("msg-1", "Maybe OAuth someday.")
    with pytest.raises(CompressionError, match="at least one source_ref"):
        build_adapter_packet([source], [{"record": canonical_record(), "source_refs": []}])


def test_unknown_source_reference_fails_closed():
    source = preserve_source("msg-1", "Maybe OAuth someday.")
    with pytest.raises(CompressionError, match="unknown source"):
        build_adapter_packet(
            [source],
            [{"record": canonical_record(), "source_refs": ["msg-404"]}],
        )


def test_human_text_fields_are_rejected_from_machine_state():
    source = preserve_source("msg-1", "Do not touch auth.")
    record = canonical_record()
    record["human_text"] = "Do not touch auth."
    with pytest.raises(CompressionError, match="must not embed preserved human text"):
        build_adapter_packet(
            [source],
            [{"record": record, "source_refs": ["msg-1"]}],
        )


def test_source_integrity_failure_is_detected():
    source = preserve_source("msg-1", "Exact wording matters.")
    packet = build_adapter_packet(
        [source],
        [{"record": canonical_record(), "source_refs": ["msg-1"]}],
    )
    tampered = copy.deepcopy(packet)
    tampered["source_evidence"][0]["text"] = "Changed wording."

    with pytest.raises(CompressionError, match="integrity"):
        recover_source(tampered, "msg-1")
