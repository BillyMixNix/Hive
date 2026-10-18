"""Independent full-key checks; candidate-independent and never model feedback."""
from pathlib import Path
from textwrap import indent


def cache_audit_tests(case):
    if case["family"] != "versioned_cache":
        return {}
    source = next(p for p in case["files"] if not Path(p).name.startswith("test_"))
    module = Path(source).stem
    kind = case["id"].removeprefix("checkpoint_")
    if kind not in {"normalized_locale", "epoch_cache", "factor_cache", "operation_cache", "ambient_policy", "shared_namespace"}:
        raise ValueError("unsupported cache audit case")
    shared = kind == "shared_namespace"
    signature = "name, revision" if shared else "name"
    key_return = "(alias, revision)" if shared else "alias"
    dimensions = {"normalized_locale": "['en', 'fr', 'de']", "epoch_cache": "[-1, 0, 2]",
        "factor_cache": "[-2, 0, 3]", "operation_cache": "['sum', 'count']",
        "ambient_policy": "[-3, 0, 4]", "shared_namespace": "[-1, 0, 2]"}[kind]
    compute = "sum(values)"
    if kind == "factor_cache": compute = "sum(values) * dimension"
    if kind == "operation_cache": compute = "sum(values) if dimension == 'sum' else len(values)"
    if kind == "ambient_policy": compute = "sum(values) + dimension"
    call = "memo.fetch(name, values)" if kind == "ambient_policy" else "memo.fetch(name, dimension, values)"
    hook_call = "memo.identity(name, dimension)" if shared else "memo.identity(name)"
    # A nontrivial tuple-valued override gives pairs of distinct spellings the
    # same identity. Both equivalence and non-equivalence must survive the repair.
    body = f"""class AliasMemo(Memo):
    def identity(self, {signature}):
        alias = ('alias-domain', {{'a-one': 11, 'a-two': 11, 'b-one': 23, 'b-two': 23}}[name])
        return {key_return}

for memo_type, names in [(Memo, ['Alpha', 'Beta']), (AliasMemo, ['a-one', 'b-one', 'a-two', 'b-two'])]:
    entries = {{}}
    clients = {{ns: memo_type(entries, ns) for ns in ['east', 'west']}}
    expected = {{}}
    serial = 0
    for repetition in range(3):
        for namespace in ['east', 'west']:
            memo = clients[namespace]
            for name in names:
                for dimension in {dimensions}:
                    serial += 1
                    values = [serial * 7, -3, 5, repetition]
                    memo.policy = dimension if {kind!r} == 'ambient_policy' else 0
                    identity = {hook_call}
                    expected_key = (namespace, identity) if {shared!r} else (identity, dimension)
                    if expected_key not in expected:
                        expected[expected_key] = {compute}
                    assert {call} == expected[expected_key], (namespace, name, dimension, repetition)
                    assert values == [serial * 7, -3, 5, repetition]
    assert len(entries) == len(expected)
"""
    return {"test_cache_full_contract.py": f"from {module} import Memo\n\ndef test_full_cache_identity():\n" + indent(body, "    ")}
