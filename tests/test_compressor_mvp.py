import pytest

from hive_compressor.compressor import CompressionError, compress_records
from hive_compressor.metering import UsageMeter


def record(**extra):
    value = {
        "ref": "evt-1",
        "effective_t": 10,
        "record_t": 12,
        "kind": "fact",
        "authority": "observed",
        "status": "active",
        "requires": [],
        "effects": ["door=open"],
    }
    value.update(extra)
    return value


def test_c1_keeps_semantic_fields_and_drops_record_time():
    result = compress_records([record()], mode="c1")
    out = result["records"][0]
    assert "record_t" not in out
    assert out["effective_t"] == 10
    assert out["kind"] == "fact"
    assert out["authority"] == "observed"
    assert out["status"] == "active"
    assert out["requires"] == []
    assert out["effects"] == ["door=open"]
    assert result["omitted_fields"] == ["record_t"]
    assert result["stats"]["output_bytes"] < result["stats"]["input_bytes"]


def test_unknown_field_fails_closed():
    with pytest.raises(CompressionError, match="unknown fields"):
        compress_records([record(secret_new_semantic="must-preserve")])


def test_missing_control_field_fails_closed():
    item = record()
    del item["authority"]
    with pytest.raises(CompressionError, match="authority"):
        compress_records([item])


def test_raw_is_baseline_not_lossy_projection():
    result = compress_records([record()], mode="raw")
    assert result["records"][0]["record_t"] == 12
    assert result["stats"]["bytes_saved"] == 0


def test_metering_stores_counts(tmp_path):
    meter = UsageMeter(tmp_path / "usage.db")
    result = compress_records([record()])
    meter.record("req-1", "abc123", result, 3.5)
    summary = meter.summary("abc123")
    assert summary["requests"] == 1
    assert summary["input_bytes"] >= summary["output_bytes"]
    assert summary["average_latency_ms"] == 3.5
