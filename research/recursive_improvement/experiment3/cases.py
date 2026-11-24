"""Trusted case construction, independent of the subject extraction algorithm.

The generated JSON files, not a runtime random generator, are the frozen inputs.
Expectations are specified by construction. Families are related; distinct inputs
are not a claim of statistical independence or broad task coverage.
"""
import json


def build_cases():
    public = []
    heldout = []

    def add(group, text, expected=None, error=False):
        group.append({"id": f"exp3-{'pub' if group is public else 'held'}-{len(group)+1:03d}",
                      "input": text, **({"error": "ValueError"} if error else {"expected": expected})})

    examples = [
        ('Status: {"action":"repair","ready":true} done.', {"action": "repair", "ready": True}),
        ('{invalid-prefix} then {"item":37} then {"item":41}', {"item": 37}),
        (json.dumps({"text": 'quoted } and { and \\" inside'}), {"text": 'quoted } and { and \\" inside'}),
        ('{"first":{"second":[1,null,false]}} trailing }', {"first": {"second": [1, None, False]}}),
        ('```json\n{"wrapped":"yes"}\n``` extra {"ignore":1}', {"wrapped": "yes"}),
        ('[{"inside_array":3}]', {"inside_array": 3}),
        ('{} after {} after', {}),
        ('unclosed { preceding {"recovered":true}', {"recovered": True}),
        ('{"bad":NaN} then {"finite":12}', {"finite": 12}),
        ('{"bad":Infinity}', None),
        ('{"bad":-Infinity}', None),
        ('nothing structured here', None),
        ('{"unfinished":', None),
        ('} before {"unicode":"雪🌲"} after', {"unicode": "雪🌲"}),
    ]
    for text, expected in examples:
        add(public, text, expected, error=expected is None)

    for i in range(8):
        value = {"record": 907 + i, "flags": [True, None, False], "label": f"new-{i}"}
        encoded = json.dumps(value, ensure_ascii=False)
        add(heldout, f"Case #{i}: " + encoded + " commentary", value)
        add(heldout, encoded + ' {"later":' + str(1901+i) + '}', value)
        add(heldout, f"{{unquoted-{i}:oops}} " + encoded, value)
        add(heldout, f"broken-{i} {{ open " + encoded, value)
        quoted = {"record": 1207+i, "text": f'escaped \\" brace }} slash \\ newline\n opening {{ token {i}'}
        add(heldout, "quoted " + json.dumps(quoted, ensure_ascii=False) + " } end", quoted)
        nested = {"tree": {"branch": [{"leaf": 1703+i}, [None, False, "é雪"]]}}
        add(heldout, "```json\n" + json.dumps(nested, ensure_ascii=False) + "\n``` tail }", nested)
        add(heldout, '[null, "prefix", ' + encoded + ", true]", value)
        constant = ("NaN", "Infinity", "-Infinity")[i % 3]
        add(heldout, '{"bad":' + constant + '} retry ' + encoded, value)
        add(heldout, '{"nonfinite' + str(i) + '":' + constant + '}', error=True)
        add(heldout, '{"truncated' + str(i) + '":[false,', error=True)
        add(heldout, f"plain response {3301+i}; no braces at all", error=True)
        braces = {"a": '}{"x":1}{' + str(i), "b": '\\"{}\\', "n": 2801+i}
        add(heldout, json.dumps(braces) + ' after {"unused":9}', braces)

    # Frozen response-replay tasks exercise original Planner.plan_task, not just
    # its helper. This does not measure new model reasoning or code generation.
    plans = []
    for i in range(8):
        goal = f"Frozen planning replay {4501+i}: repair JSON extraction"
        plan = {"goal": goal, "task_type": "bugfix", "work_mode": "repair",
                "tasks": [{"title": "Repair extraction", "description": "Modify JSON extraction in planner.py.",
                           "target_file": "planner.py", "target_symbol": "_extract_json_object",
                           "change_intent": "modify_existing_logic", "expected_operation": "modify_logic"}],
                "dependencies": ["planner.py"], "risks": [],
                "next_action": "Modify _extract_json_object in planner.py.", "status": "planned"}
        if i == 6:
            plan["goal"] += ' with a quoted } and { and \\" token'
            goal = plan["goal"]
        text = json.dumps(plan)
        wrapped = [text, "Plan follows. " + text + " End.", text + ' {"unrelated":true}',
                   "```json\n" + text + "\n``` extra }", "{malformed-replay} " + text,
                   "open { junk " + text, text + " trailing }", "[" + text + "]"][i]
        plans.append({"id": f"exp3-plan-{i}", "input": wrapped, "expected_goal": goal})
    return public, heldout, plans


if __name__ == "__main__":
    from pathlib import Path
    for name, cases in zip(("public_cases.json", "heldout_cases.json", "plan_cases.json"), build_cases()):
        Path(__file__).with_name(name).write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
