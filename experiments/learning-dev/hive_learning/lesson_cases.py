"""Prospective, authored transfer tasks. Reference repairs are evaluator-only.

Six Python defect families, with disjoint formation, development and confirmation
projects. Instances share a mechanism; conclusions are scoped to those families.
No case or expected answer is selected in response to a live model result.
"""
import hashlib
import json
from pathlib import Path
import re

from .ledger import digest


FAMILIES = ("current_input", "paired_sort", "versioned_cache", "snapshot_alias",
            "explicit_zero", "single_pass")


def make_case(family, variant, split):
    tag = f"{family}_{variant:02d}"
    module = "component_" + hashlib.sha256(tag.encode()).hexdigest()[:8]
    n = 11 + variant * 7
    if family == "current_input":
        if variant % 3 == 0:
            source = ("class Quote:\n"
                "    def __init__(self, opening_rate):\n        self.opening_rate = opening_rate\n\n"
                "    def amount(self, units, live_rate, fee):\n"
                "        subtotal = units * self.opening_rate\n"
                "        return subtotal + fee\n")
            old, new = "units * self.opening_rate", "units * live_rate"
            goal = "Quote.amount must charge units at the live_rate supplied on each call, plus fee. Opening rates are historical. Preserve tests and the API."
            def checks(v):
                return f"q = Quote({v})\nassert q.amount(3, {v+5}, 2) == 3 * {v+5} + 2\nassert q.amount(0, {v+7}, 6) == 6\nassert q.amount(2, {v+1}, 0) == 2 * {v+1}"
            imported = "Quote"
        elif variant % 3 == 1:
            source = ("class Allowance:\n"
                "    def __init__(self, opening_balance):\n        self.opening_balance = opening_balance\n\n"
                "    def remaining(self, requested, current_balance):\n"
                "        available = self.opening_balance - requested\n"
                "        return max(0, available)\n")
            old, new = "self.opening_balance - requested", "current_balance - requested"
            goal = "Allowance.remaining must return current_balance minus requested, floored at zero. The opening balance is historical. Preserve tests and the API."
            def checks(v):
                return f"a = Allowance({v})\nassert a.remaining(3, {v+9}) == {v+6}\nassert a.remaining({v+10}, 2) == 0\nassert a.remaining(0, {v+2}) == {v+2}"
            imported = "Allowance"
        else:
            source = ("class Converter:\n"
                "    def __init__(self, initial_width):\n        self.initial_width = initial_width\n\n"
                "    def buckets(self, volume, current_width):\n"
                "        complete = volume // self.initial_width\n"
                "        return complete\n")
            old, new = "volume // self.initial_width", "volume // current_width"
            goal = "Converter.buckets returns the number of complete current_width-sized buckets in volume. Widths are positive integers and may change each call. Preserve tests and the API."
            def checks(v):
                return f"c = Converter({v})\nassert c.buckets({v*9+2}, 3) == ({v*9+2} // 3)\nassert c.buckets(0, 5) == 0\nassert c.buckets({v*5}, {v+2}) == ({v*5} // {v+2})"
            imported = "Converter"
    elif family == "paired_sort":
        source = ("def arrange(labels, payloads):\n"
            "    if len(labels) != len(payloads):\n        raise ValueError('length mismatch')\n"
            "    paired = zip(sorted(labels), payloads)\n"
            "    return list(paired)\n")
        old, new = "zip(sorted(labels), payloads)", "sorted(zip(labels, payloads), key=lambda item: item[0])"
        goal = "arrange returns (label, payload) pairs sorted by label while preserving every original association. Equal labels preserve their input order. Unequal lengths raise ValueError. Preserve tests and the API."
        def checks(v):
            return f"assert arrange([{v+2}, {v}, {v+1}], ['b', 'z', 'a']) == [({v}, 'z'), ({v+1}, 'a'), ({v+2}, 'b')]\nassert arrange([{v}, {v}], ['z', 'a']) == [({v}, 'z'), ({v}, 'a')]\nassert arrange([], []) == []"
        imported = "arrange"
    elif family == "versioned_cache":
        source = ("class Memo:\n"
            "    def __init__(self):\n        self.entries = {}\n\n"
            "    def identity(self, item, revision):\n        return item\n\n"
            "    def calculate(self, item, revision, values):\n"
            "        key = self.identity(item, revision)\n"
            "        if key not in self.entries:\n            self.entries[key] = sum(values)\n"
            "        return self.entries[key]\n")
        old, new = "return item", "return (item, revision)"
        goal = "Memo.calculate caches the first sum independently for each (item, revision). A new revision recomputes; repeating the same item and revision returns its original cached sum even if values change. Preserve tests and the API."
        def checks(v):
            return f"m = Memo()\nassert m.calculate('record', {v}, [3, 5]) == 8\nassert m.calculate('record', {v+1}, [7, 9]) == 16\nassert m.calculate('record', {v}, [100]) == 8\nassert m.calculate('other', {v}, [2, 3]) == 5"
        imported = "Memo"
    elif family == "snapshot_alias":
        source = ("class Journal:\n"
            "    def __init__(self, values):\n"
            "        self.live = list(values)\n"
            "        self.checkpoint = self.live\n\n"
            "    def replace(self, index, value):\n        self.live[index] = value\n\n"
            "    def totals(self):\n        return (sum(self.live), sum(self.checkpoint))\n")
        old, new = "self.checkpoint = self.live", "self.checkpoint = self.live.copy()"
        goal = "Journal keeps live mutable values and an independent opening checkpoint. Replacing a live value changes only the live total. totals returns (live total, opening total). Values are numbers. Preserve tests and the API."
        def checks(v):
            return f"j = Journal([{v}, 3, 5])\nassert j.totals() == ({v+8}, {v+8})\nj.replace(1, 9)\nassert j.totals() == ({v+14}, {v+8})\nj.replace(0, 0)\nassert j.totals() == (14, {v+8})"
        imported = "Journal"
    elif family == "explicit_zero":
        source = ("def configure(defaults, overrides):\n"
            "    selected = {key: value for key, value in overrides.items() if value}\n"
            "    combined = defaults.copy()\n"
            "    combined.update(selected)\n"
            "    return combined\n")
        old, new = "overrides.items() if value}", "overrides.items() if value is not None}"
        goal = "configure overlays defaults without mutating either input. Only None means no override; explicit zero, False, empty strings and empty lists must override. Preserve tests and the API."
        def checks(v):
            return f"defaults = {{'quota': {v}, 'enabled': True, 'label': 'old', 'rows': [1], 'keep': 7}}\noverrides = {{'quota': 0, 'enabled': False, 'label': '', 'rows': [], 'keep': None}}\nassert configure(defaults, overrides) == {{'quota': 0, 'enabled': False, 'label': '', 'rows': [], 'keep': 7}}\nassert defaults['quota'] == {v}\nassert overrides['keep'] is None"
        imported = "configure"
    elif family == "single_pass":
        source = ("def summarize(stream):\n"
            "    observed = tuple(stream)\n"
            "    count = len(observed)\n"
            "    total = sum(stream)\n"
            "    return {'count': count, 'total': total}\n")
        old, new = "total = sum(stream)", "total = sum(observed)"
        goal = "summarize consumes a possibly single-use iterable and reports its item count and sum. It must work for generators, including empty and signed inputs. Preserve tests and the API."
        def checks(v):
            return f"assert summarize(iter([{v}, -2, 5])) == {{'count': 3, 'total': {v+3}}}\nassert summarize(iter([])) == {{'count': 0, 'total': 0}}\nassert summarize(x for x in [-{v}, {v}, 1]) == {{'count': 3, 'total': 1}}"
        imported = "summarize"
    else:
        raise ValueError("unknown family")

    # Confirmation includes structural variants absent from formation, not just
    # different numbers or filenames. A family-level lesson must generalize its
    # principle, including nested aliasing and multi-stage iterator use.
    if family == "paired_sort" and variant % 3 == 1:
        source = ("def arrange(records):\n"
                  "    ranks = sorted(row['rank'] for row in records)\n"
                  "    selected = [dict(row, rank=rank) for row, rank in zip(records, ranks)]\n"
                  "    return selected\n")
        old, new = "[dict(row, rank=rank) for row, rank in zip(records, ranks)]", "sorted(records, key=lambda row: row['rank'])"
        goal = "arrange orders record dictionaries by rank, preserving each rank/payload association and input order for equal ranks. Do not change input records. Preserve tests and the API."
        def checks(v):
            return f"rows = [{{'rank': {v+1}, 'value': 'b'}}, {{'rank': {v}, 'value': 'z'}}, {{'rank': {v}, 'value': 'a'}}]\nassert arrange(rows) == [rows[1], rows[2], rows[0]]\nassert rows[0]['rank'] == {v+1}\nassert arrange([]) == []"
    elif family == "paired_sort" and variant % 3 == 2:
        source = ("def arrange(records):\n"
                  "    keys = sorted((row[0], row[1]) for row in records)\n"
                  "    paired = zip(keys, [row[2] for row in records])\n"
                  "    return list(paired)\n")
        old, new = "zip(keys, [row[2] for row in records])", "sorted([((row[0], row[1]), row[2]) for row in records], key=lambda item: item[0])"
        goal = "arrange takes (group, rank, payload) rows and returns ((group, rank), payload) rows sorted by the composite key. Preserve associations and stable input order for equal keys. Preserve tests and the API."
        def checks(v):
            return f"rows = [('b', {v}, 'x'), ('a', {v+1}, 'z'), ('a', {v}, 'm'), ('a', {v}, 'a')]\nassert arrange(rows) == [(('a', {v}), 'm'), (('a', {v}), 'a'), (('a', {v+1}), 'z'), (('b', {v}), 'x')]\nassert arrange([]) == []"
    elif family == "versioned_cache" and variant % 3 == 1:
        source = ("class Memo:\n    def __init__(self):\n        self.entries = {}\n\n"
                  "    def identity(self, text, mode):\n        return text\n\n"
                  "    def render(self, text, mode):\n        key = self.identity(text, mode)\n"
                  "        if key not in self.entries:\n            self.entries[key] = text.lower() if mode == 'lower' else text.upper()\n"
                  "        return self.entries[key]\n")
        old, new = "return text", "return (text, mode)"
        goal = "Memo.render must cache independently for each text and mode. Modes are lower and upper; the same text must render correctly under either mode regardless of earlier calls. Preserve tests and the API."
        def checks(v):
            return f"m = Memo()\nassert m.render('AbC{v}', 'lower') == 'abc{v}'\nassert m.render('AbC{v}', 'upper') == 'ABC{v}'\nassert m.render('AbC{v}', 'lower') == 'abc{v}'\nassert len(m.entries) == 2"
    elif family == "versioned_cache" and variant % 3 == 2:
        source = ("class Memo:\n    def __init__(self):\n        self.entries = {}\n\n"
                  "    def identity(self, account, tenant):\n        return account\n\n"
                  "    def balance(self, account, tenant, entries):\n        key = self.identity(account, tenant)\n"
                  "        if key not in self.entries:\n            self.entries[key] = sum(entries)\n"
                  "        return self.entries[key]\n")
        old, new = "return account", "return (account, tenant)"
        goal = "Memo.balance caches the first entry sum separately for every tenant/account pair. Equal account names in distinct tenants must never share results. Repeating a pair retains its original sum. Preserve tests and the API."
        def checks(v):
            return f"m = Memo()\nassert m.balance('user', 'east', [{v}, 3]) == {v+3}\nassert m.balance('user', 'west', [{v+8}, 5]) == {v+13}\nassert m.balance('user', 'east', [9000]) == {v+3}\nassert len(m.entries) == 2"
    elif family == "snapshot_alias" and variant % 3 == 1:
        source = ("class Journal:\n    def __init__(self, settings):\n"
                  "        self.live = dict(settings)\n        self.checkpoint = self.live\n\n"
                  "    def put(self, key, value):\n        self.live[key] = value\n\n"
                  "    def value(self, key):\n        return (self.live[key], self.checkpoint[key])\n")
        old, new = "self.checkpoint = self.live", "self.checkpoint = self.live.copy()"
        goal = "Journal keeps an independent opening checkpoint of numeric settings. put changes live settings only; value returns (live value, opening value). Preserve tests and the API."
        def checks(v):
            return f"j = Journal({{'limit': {v}, 'rate': 3}})\nj.put('limit', 0)\nassert j.value('limit') == (0, {v})\nj.put('rate', {v+5})\nassert j.value('rate') == ({v+5}, 3)"
    elif family == "snapshot_alias" and variant % 3 == 2:
        source = ("class Journal:\n    def __init__(self, rows):\n"
                  "        self.live = [list(row) for row in rows]\n        self.checkpoint = self.live.copy()\n\n"
                  "    def replace(self, row, column, value):\n        self.live[row][column] = value\n\n"
                  "    def totals(self):\n        return (sum(map(sum, self.live)), sum(map(sum, self.checkpoint)))\n")
        old, new = "self.checkpoint = self.live.copy()", "self.checkpoint = [row.copy() for row in self.live]"
        goal = "Journal stores numeric rows with an independent opening checkpoint. Replacing a cell must not change the opening total. totals returns (live total, opening total). Preserve tests and the API."
        def checks(v):
            return f"j = Journal([[{v}, 3], [5, 7]])\nj.replace(0, 1, 0)\nassert j.totals() == ({v+12}, {v+15})\nj.replace(1, 0, 9)\nassert j.totals() == ({v+16}, {v+15})"
    elif family == "explicit_zero" and variant % 3 == 1:
        source = ("def configure(original, incoming):\n    value = incoming.get('limit')\n"
                  "    chosen = value or original\n    return chosen\n")
        old, new = "value or original", "original if value is None else value"
        goal = "configure chooses incoming['limit'] if supplied and non-None, otherwise original. Zero, False, and empty strings are real supplied values. Do not mutate incoming. Preserve tests and the API."
        def checks(v):
            return f"assert configure({v}, {{'limit': 0}}) == 0\nassert configure({v}, {{'limit': False}}) is False\nassert configure({v}, {{'limit': ''}}) == ''\nassert configure({v}, {{'limit': None}}) == {v}\nassert configure({v}, {{}}) == {v}"
    elif family == "explicit_zero" and variant % 3 == 2:
        source = ("def configure(defaults, layers):\n"
                  "    chosen = {key: value for layer in layers for key, value in layer.items() if value}\n"
                  "    output = defaults.copy()\n    output.update(chosen)\n    return output\n")
        old, new = "layer.items() if value}", "layer.items() if value is not None}"
        goal = "configure overlays layers in order. The last non-None value for each key wins, including explicit zero, False, and empty strings. None contributes no override. Preserve inputs, tests and the API."
        def checks(v):
            return f"base = {{'limit': {v}, 'flag': True}}\nlayers = [{{'limit': {v+1}, 'flag': False}}, {{'limit': 0}}, {{'limit': None}}]\nassert configure(base, layers) == {{'limit': 0, 'flag': False}}\nassert base['limit'] == {v}\nassert layers[1]['limit'] == 0"
    elif family == "single_pass" and variant % 3 == 1:
        source = ("def summarize(stream):\n    observed = list(stream)\n"
                  "    if any(value < 0 for value in observed):\n        raise ValueError('negative value')\n"
                  "    accepted = tuple(stream)\n    return accepted\n")
        old, new = "accepted = tuple(stream)", "accepted = tuple(observed)"
        goal = "summarize validates a possibly single-use iterable of nonnegative numbers and returns all its items as a tuple. Negative values raise ValueError. Preserve tests and the API."
        def checks(v):
            return f"assert summarize(iter([{v}, 0, 5])) == ({v}, 0, 5)\nassert summarize(iter([])) == ()\ntry:\n    summarize(iter([1, -1]))\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError('negative accepted')"
    elif family == "single_pass" and variant % 3 == 2:
        source = ("def summarize(stream):\n    records = tuple(stream)\n"
                  "    keys = [row[0] for row in stream]\n"
                  "    values = [row[1] for row in records]\n    return dict(zip(keys, values))\n")
        old, new = "keys = [row[0] for row in stream]", "keys = [row[0] for row in records]"
        goal = "summarize consumes a possibly single-use iterable of (key, value) rows into a dictionary. Later duplicate keys win. Preserve tests and the API."
        def checks(v):
            return f"assert summarize(iter([('a', {v}), ('b', 3), ('a', {v+2})])) == {{'a': {v+2}, 'b': 3}}\nassert summarize(iter([])) == {{}}"

    original_symbol = imported
    imported = original_symbol + "_" + str(variant)
    source = re.sub(r"\b" + original_symbol + r"\b", imported, source)
    goal = re.sub(r"\b" + original_symbol + r"\b", imported, goal)

    def test_file(values, name):
        lines = [f"from {module} import {imported}", "", f"def test_{name}():"]
        for value in values:
            lines.extend("    " + re.sub(r"\b" + original_symbol + r"\b", imported, line)
                         for line in checks(value).splitlines())
        return "\n".join(lines) + "\n"

    assert source.count(old) == 1
    files = {module + ".py": source, "test_visible.py": test_file([n], "visible")}
    repaired = dict(files, **{module + ".py": source.replace(old, new)})
    case = {"id": tag, "family": family, "split": split, "goal": goal, "files": files,
            "acceptance_tests": {"test_acceptance.py": test_file([n+1000, n+2000], "acceptance")},
            "protected_tests": {"test_protected.py": test_file([n+101, n+211, n+307, n+401], "protected")}}
    return case, repaired


def build_study():
    cases, references = [], {}
    for family in FAMILIES:
        for variant in range(15):
            split = "formation" if variant == 0 else "screen1" if variant == 1 else "screen2" if variant == 2 else "confirmation"
            case, fixed = make_case(family, variant, split)
            cases.append(case)
            references[case["id"]] = fixed
    # Retention is an unrelated, previously demonstrated inclusive-boundary skill,
    # expressed with distinct functions and independent public failing examples.
    for i, operator in enumerate(("<=", ">=")):
        name = f"retention_{i}"
        wrong = "<" if operator == "<=" else ">"
        source = f"def permitted(value, threshold):\n    return value {wrong} threshold\n"
        def test(numbers, label):
            return (f"from {name} import permitted\n\ndef test_{label}():\n"
                    f"    for threshold in {numbers!r}:\n        for delta in (-1, 0, 1):\n"
                    f"            value = threshold + delta\n            assert permitted(value, threshold) == (value {operator} threshold)\n")
        files = {name+'.py': source, 'test_visible.py': test([31+i], 'visible')}
        cases.append({"id": name, "family": "retention", "split": "retention",
                      "goal": f"permitted must return whether value is {'at most' if i == 0 else 'at least'} threshold, including equality. Preserve tests.",
                      "files": files, "acceptance_tests": {"test_acceptance.py": test([71, 79], 'acceptance')},
                      "protected_tests": {"test_protected.py": test([-20, 0, 18, 112], 'protected')}})
        references[name] = dict(files, **{name+'.py': source.replace(f" {wrong} ",f" {operator} ")})
    study = {"schema": "hive.lesson-transfer.v2", "study_id": "lesson-transfer-20260908-v2",
             "model": "gpt-5.6-luna", "calls_per_recipient": 36, "seed": 1709,
             "families": list(FAMILIES), "cases": cases,
             "policy": {"formation_lessons": "one model-derived lesson per family's actual public debugging record",
                        "development_rounds": 2,
                        "selection": "accuracy signal first; otherwise at least 15 percent model-call reduction with all three arms correct; ties by family ID",
                        "confirmation": "12 never-presented projects from the selected family, plus both retention tasks",
                        "alpha_one_sided": 0.025,
                        "accuracy_minimum_gain": 1/6,
                        "efficiency_minimum_reduction": 0.15,
                        "both_controls_required": True,
                        "formation_costs_reported_separately": True,
                        "confirmation_attempts": 1,
                        "no_confirmation_feedback_to_proposer": True},
             "references_sha256": digest(references)}
    return study, references


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "examples"
    study, references = build_study()
    for name, value in (("lesson-study-v2.json", study), ("lesson-study-v2-references.json", references)):
        path = root / name
        path.write_text(json.dumps(value, indent=2) + "\n")
        print(name, hashlib.sha256(path.read_bytes()).hexdigest())
