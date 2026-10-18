"""Fresh authored tasks for the prospective context/checkpoint revision.

Reference edits are used only in offline fixture verification. Every transfer
project has a distinct transformation; this remains a small synthetic distribution.
"""
import hashlib
from textwrap import dedent, indent

from hive_learning.lesson_cases import make_case


def build_cases():
    cases, references = [], {}

    def add(family, name, source, old, new, goal, public, hidden):
        case_id = "checkpoint_" + name
        module = "unit_" + hashlib.sha256(case_id.encode()).hexdigest()[:10]
        source = dedent(source).lstrip()
        assert source.count(old) == 1, case_id
        def test(body, label):
            return f"from {module} import *\n\ndef test_{label}():\n" + indent(dedent(body).strip(), "    ") + "\n"
        files = {module+".py": source, "test_visible.py": test(public, "public")}
        case = {"id": case_id, "family": family, "split": "confirmation", "goal": goal + " Preserve the public API, inputs and tests.",
                "files": files, "acceptance_tests": {"test_acceptance.py": test(public, "acceptance")},
                "protected_tests": {"test_independent.py": test(hidden, "independent")}}
        cases.append(case)
        references[case_id] = {**files, module+".py": source.replace(old, new)}

    sort_specs = [
        ("descending_pairs", "def process(keys, values):\n    result = list(zip(sorted(keys, reverse=True), values))\n    return result\n",
         "list(zip(sorted(keys, reverse=True), values))", "sorted(zip(keys, values), key=lambda row: row[0], reverse=True)",
         "process receives equal-length key and payload lists and returns pairs ordered by descending key. Keep original associations and preserve input order for equal keys.",
         "assert process([2, 5, 3], ['a', 'b', 'c']) == [(5, 'b'), (3, 'c'), (2, 'a')]",
         "sorted(zip(keys, values), key=lambda row: row[0], reverse=True)", "process(keys, values)"),
        ("masked_pairs", "def process(keys, values, flags):\n    selected = [key for key, keep in zip(keys, flags) if keep]\n    result = list(zip(selected, values))\n    return result\n",
         "list(zip(selected, values))", "[(key, value) for key, value, keep in zip(keys, values, flags) if keep]",
         "process receives three equal-length lists. Return key/payload pairs for true flags, keeping each selected original association and input order.",
         "assert process([4, 8, 2], ['x', 'y', 'z'], [False, True, True]) == [(8, 'y'), (2, 'z')]",
         "[(key, value) for key, value, keep in zip(keys, values, flags) if keep]", "process(keys, values, flags)"),
        ("permuted_columns", "def process(keys, values, order):\n    result = [(keys[index], values[position]) for position, index in enumerate(order)]\n    return result\n",
         "[(keys[index], values[position]) for position, index in enumerate(order)]", "[(keys[index], values[index]) for index in order]",
         "process receives equally long key/payload lists and a list of valid indices which may repeat or omit indices. Return original pairs in exactly that index order.",
         "assert process([4, 8, 2], ['x', 'y', 'z'], [2, 0, 2]) == [(2, 'z'), (4, 'x'), (2, 'z')]",
         "[(keys[index], values[index]) for index in order]", "process(keys, values, order)"),
        ("absolute_priority", "def process(keys, values):\n    ordered = sorted(keys, key=abs)\n    result = list(zip(ordered, values))\n    return result\n",
         "list(zip(ordered, values))", "sorted(zip(keys, values), key=lambda row: abs(row[0]))",
         "process receives equally long numeric key and payload lists. Return original pairs sorted by increasing absolute key. Equal absolute keys retain input order; retain each original signed key.",
         "assert process([-5, 2, -2], ['x', 'y', 'z']) == [(2, 'y'), (-2, 'z'), (-5, 'x')]",
         "sorted(zip(keys, values), key=lambda row: abs(row[0]))", "process(keys, values)"),
        ("stable_partition", "def process(keys, values, flags):\n    first = sorted(flags, reverse=True)\n    result = [(key, value, flag) for key, value, flag in zip(keys, values, first)]\n    return result\n",
         "[(key, value, flag) for key, value, flag in zip(keys, values, first)]", "sorted(zip(keys, values, flags), key=lambda row: not row[2])",
         "process receives equally long key, payload and Boolean flag lists. Return the original triples with true-flag records first, preserving input order within each flag group.",
         "assert process([1, 2, 3], ['a', 'b', 'c'], [False, True, False]) == [(2, 'b', True), (1, 'a', False), (3, 'c', False)]",
         "sorted(zip(keys, values, flags), key=lambda row: not row[2])", "process(keys, values, flags)"),
        ("top_k_pairs", "def process(keys, values, limit):\n    selected = sorted(keys, reverse=True)[:limit]\n    result = list(zip(selected, values[:limit]))\n    return result\n",
         "list(zip(selected, values[:limit]))", "sorted(zip(keys, values), key=lambda row: row[0], reverse=True)[:limit]",
         "process receives equally long key/payload lists and a nonnegative limit. Return up to limit original pairs with greatest keys first, preserving input order for equal keys.",
         "assert process([2, 8, 5], ['a', 'b', 'c'], 2) == [(8, 'b'), (5, 'c')]",
         "sorted(zip(keys, values), key=lambda row: row[0], reverse=True)[:limit]", "process(keys, values, limit)"),
    ]
    for name, source, old, new, goal, public, oracle, call in sort_specs:
        hidden = f"""import random
import copy
rng = random.Random(190871)
for size in range(9):
    for repeat in range(8):
        keys = [rng.randrange(-5, 6) for _ in range(size)]
        values = [{{'position': i, 'payload': [repeat, i]}} for i in range(size)]
        flags = [bool(rng.randrange(2)) for _ in range(size)]
        order = [rng.randrange(size) for _ in range(size+2)] if size else []
        limit = repeat
        before = copy.deepcopy((keys, values, flags, order))
        expected = {oracle}
        actual = {call}
        assert actual == expected
        assert (keys, values, flags, order) == before
        assert isinstance(actual, list)
"""
        add("paired_sort", name, source, old, new, goal, public, hidden)

    iterator_specs = [
        ("product_and_count", "import math\n\ndef process(stream):\n    saved = tuple(stream)\n    count = len(saved)\n    product = math.prod(stream)\n    return count, product\n",
         "math.prod(stream)", "math.prod(saved)",
         "process accepts any finite iterable of numbers, including a single-use iterator, and returns (item count, product). The empty product is one.",
         "assert process(iter([2, 3, 4])) == (3, 24)", "(len(values), math.prod(values))", "[rng.randrange(-3, 5) for _ in range(size)]"),
        ("mean_after_snapshot", "def process(stream):\n    saved = list(stream)\n    count = len(saved)\n    average = sum(stream) / count if count else 0\n    return count, average\n",
         "sum(stream) / count if count else 0", "sum(saved) / count if count else 0",
         "process accepts any finite numeric iterable, including single-use iterators, and returns (count, arithmetic mean). Empty input returns (0, 0).",
         "assert process(iter([2, 4, 9])) == (3, 5)", "(len(values), sum(values) / len(values) if values else 0)", "[rng.randrange(-8, 9) for _ in range(size)]"),
        ("head_and_tail", "def process(stream):\n    saved = tuple(stream)\n    first = saved[0] if saved else None\n    tail = tuple(stream)\n    return first, tail\n",
         "tail = tuple(stream)", "tail = saved[1:]",
         "process accepts any finite iterable, including single-use iterators, and returns (first item, tuple of remaining items). Empty input returns (None, ()).",
         "assert process(iter([8, 2, 5])) == (8, (2, 5))", "(values[0] if values else None, tuple(values[1:]))", "[rng.randrange(-4, 5) for _ in range(size)]"),
        ("ordered_unique", "def process(stream):\n    saved = tuple(stream)\n    count = len(saved)\n    unique = tuple(dict.fromkeys(stream))\n    return count, unique\n",
         "tuple(dict.fromkeys(stream))", "tuple(dict.fromkeys(saved))",
         "process accepts any finite iterable of hashable items, including single-use iterators. Return the original count and a tuple containing each distinct item once in order of first occurrence.",
         "assert process(iter([3, 1, 3, 2])) == (4, (3, 1, 2))", "(len(values), tuple(dict.fromkeys(values)))", "[rng.randrange(-2, 3) for _ in range(size)]"),
        ("enumerated_rows", "def process(stream, start):\n    saved = tuple(stream)\n    count = len(saved)\n    rows = list(enumerate(stream, start))\n    return count, rows\n",
         "list(enumerate(stream, start))", "list(enumerate(saved, start))",
         "process accepts any finite iterable, including single-use iterators, and an integer start. Return (item count, list of (index, item) pairs), assigning consecutive indices from start.",
         "assert process(iter(['x', 'y', 'z']), 7) == (3, [(7, 'x'), (8, 'y'), (9, 'z')])", "(len(values), list(enumerate(values, -7)))", "[str(rng.randrange(-4, 5)) for _ in range(size)]"),
        ("validate_then_reverse", "def process(stream):\n    saved = list(stream)\n    if any(value is None for value in saved):\n        raise ValueError('missing item')\n    result = tuple(reversed(list(stream)))\n    return result\n",
         "tuple(reversed(list(stream)))", "tuple(reversed(saved))",
         "process accepts any finite iterable, including single-use iterators. Reject any None item with ValueError, otherwise return all items in reverse order as a tuple. Empty input returns ().",
         "assert process(iter([3, 0, 5])) == (5, 0, 3)", "tuple(reversed(values))", "[rng.randrange(-4, 5) for _ in range(size)]"),
    ]
    for name, source, old, new, goal, public, oracle, values_expr in iterator_specs:
        call = "process(item, -7)" if name == "enumerated_rows" else "process(item)"
        hidden = f"""import random
import math
class Opaque:
    def __init__(self, items):
        self.cursor = iter(items)
    def __iter__(self):
        return self
    def __next__(self):
        return next(self.cursor)
    def __reduce__(self):
        raise TypeError('not serializable')
rng = random.Random(310917)
for size in range(10):
    values = {values_expr}
    expected = {oracle}
    advanced = iter(['discarded'] + values)
    next(advanced)
    for item in [list(values), iter(values), (x for x in values), Opaque(values), advanced]:
        assert {call} == expected
"""
        if name == "validate_then_reverse":
            hidden += "for item in [iter([2, None, 1]), Opaque([None]), (x for x in [0, None])]:\n    try:\n        process(item)\n    except ValueError:\n        pass\n    else:\n        raise AssertionError('None accepted')\n"
        add("single_pass", name, source, old, new, goal, public, hidden)

    cache_specs = [
        ("normalized_locale", "def identity(self, name):\n    return name.casefold()\n\ndef fetch(self, name, locale, values):\n    key = self.identity(name)\n    if key not in self.entries:\n        self.entries[key] = sum(values)\n    return self.entries[key]\n",
         "key = self.identity(name)", "key = (self.identity(name), locale)",
         "Memo.fetch caches the first sum separately for (identity(name), locale). identity is an overridable normalization hook and must remain authoritative; equivalent names share a result only within the same locale.",
         "m = Memo()\nassert m.fetch('Ada', 'en', [3, 4]) == 7\nassert m.fetch('Ada', 'fr', [8, 9]) == 17\nassert m.fetch('ADA', 'en', [99]) == 7",
         "name", "name.casefold()", "name.strip().casefold()", "fetch(' Alpha ', 'x', [v, 2])", "fetch('alpha', 'y', [v+4, 3])", "fetch('ALPHA', 'x', [999])"),
        ("epoch_cache", "def identity(self, name):\n    return name\n\ndef fetch(self, name, epoch, values):\n    key = self.identity(name)\n    if key not in self.entries:\n        self.entries[key] = sum(values)\n    return self.entries[key]\n",
         "key = self.identity(name)", "key = (self.identity(name), epoch)",
         "Memo.fetch caches the first sum for each (identity(name), epoch). A different epoch gets its own value; returning to an older epoch reuses its original value. Preserve the overridable identity hook.",
         "m = Memo()\nassert m.fetch('row', 0, [2, 3]) == 5\nassert m.fetch('row', 1, [4, 8]) == 12\nassert m.fetch('row', 0, [99]) == 5",
         "name", "name", "name.casefold()", "fetch('ALPHA', 0, [v, 2])", "fetch('alpha', -1, [v+4, 3])", "fetch('alpha', 0, [999])"),
        ("factor_cache", "def identity(self, name):\n    return name\n\ndef fetch(self, name, factor, values):\n    key = self.identity(name)\n    if key not in self.entries:\n        self.entries[key] = sum(values) * factor\n    return self.entries[key]\n",
         "key = self.identity(name)", "key = (self.identity(name), factor)",
         "Memo.fetch caches the first sum(values) * factor separately for each (identity(name), factor), including zero and negative factors. Preserve reuse on an identical key and the overridable identity hook.",
         "m = Memo()\nassert m.fetch('row', 2, [2, 3]) == 10\nassert m.fetch('row', 3, [4, 8]) == 36\nassert m.fetch('row', 2, [99]) == 10",
         "name", "name", "name.casefold()", "fetch('ALPHA', 0, [v, 2])", "fetch('alpha', -2, [v+4, 3])", "fetch('alpha', 0, [999])"),
        ("operation_cache", "def identity(self, name):\n    return name\n\ndef fetch(self, name, mode, values):\n    key = self.identity(name)\n    if key not in self.entries:\n        self.entries[key] = sum(values) if mode == 'sum' else len(values)\n    return self.entries[key]\n",
         "key = self.identity(name)", "key = (self.identity(name), mode)",
         "Memo.fetch supports sum and count modes. Cache the first result independently for (identity(name), mode), even when the same name was previously requested with another mode. Preserve the overridable identity hook.",
         "m = Memo()\nassert m.fetch('row', 'sum', [2, 3]) == 5\nassert m.fetch('row', 'count', [1, 2, 3]) == 3\nassert m.fetch('row', 'sum', [99]) == 5",
         "name", "name", "name.casefold()", "fetch('ALPHA', 'sum', [v, 2])", "fetch('alpha', 'count', [v+4, 3])", "fetch('alpha', 'sum', [999])"),
        ("ambient_policy", "def identity(self, name):\n    return name\n\ndef fetch(self, name, values):\n    key = self.identity(name)\n    if key not in self.entries:\n        self.entries[key] = sum(values) + self.policy\n    return self.entries[key]\n",
         "key = self.identity(name)", "key = (self.identity(name), self.policy)",
         "Memo.policy is a mutable numeric adjustment. fetch caches the first sum(values) + policy for each (identity(name), policy). Changing policy must select a separate entry; restoring policy must reuse its earlier entry. Preserve the overridable identity hook.",
         "m = Memo()\nm.policy = 2\nassert m.fetch('row', [2, 3]) == 7\nm.policy = 5\nassert m.fetch('row', [4, 8]) == 17\nm.policy = 2\nassert m.fetch('row', [99]) == 7",
         "name", "name", "name.casefold()", "fetch('ALPHA', [v, 2])", "fetch('alpha', [v+4, 3])", "fetch('alpha', [999])"),
        ("shared_namespace", "def identity(self, name, revision):\n    return (name, revision)\n\ndef fetch(self, name, revision, values):\n    key = self.identity(name, revision)\n    if key not in self.entries:\n        self.entries[key] = sum(values)\n    return self.entries[key]\n",
         "key = self.identity(name, revision)", "key = (self.namespace, self.identity(name, revision))",
         "Memo instances may share the supplied entries dictionary. fetch caches the first sum for (namespace, identity(name, revision)); namespaces must be isolated. The overridable identity hook controls identity within a namespace. Do not discard a supplied empty entries dictionary.",
         "shared = {}\na = Memo(shared, 'a')\nb = Memo(shared, 'b')\nassert a.fetch('row', 0, [2, 3]) == 5\nassert b.fetch('row', 0, [4, 8]) == 12\nassert a.fetch('row', 0, [99]) == 5",
         "name, revision", "(name, revision)", "(name.casefold(), revision)", "fetch('ALPHA', 0, [v, 2])", "fetch('alpha', 1, [v+4, 3])", "fetch('alpha', 0, [999])"),
    ]
    for name, methods, old, new, goal, public, args, default, hook, first, second, third in cache_specs:
        init = "def __init__(self, entries=None, namespace='default'):\n    self.entries = {} if entries is None else entries\n    self.namespace = namespace\n    self.policy = 0\n\n"
        source = "class Memo:\n" + indent(init + methods, "    ")
        expected1, expected2 = "v+2", "v+7"
        if name == "factor_cache": expected1, expected2 = "0", "-2 * (v+7)"
        if name == "operation_cache": expected2 = "2"
        if name == "ambient_policy": expected1, expected2 = "v+4", "v+12"
        pre1 = "m.policy = 2\n    " if name == "ambient_policy" else ""
        pre2 = "m.policy = 5\n    " if name == "ambient_policy" else ""
        hidden = f"""class Custom(Memo):
    def identity(self, {args}):
        return {hook}
for v in [-17, 0, 2, 39]:
    m = Custom()
    {pre1}assert m.{first} == {expected1}
    {pre2}assert m.{second} == {expected2}
    {pre1}assert m.{third} == {expected1}
    assert len(m.entries) == 2
"""
        if name == "shared_namespace":
            hidden += "shared = {}\na = Custom(shared, 'east')\nb = Custom(shared, 'west')\nc = Custom(shared, 'east')\nassert a.fetch('ALPHA', 0, [2, 7]) == 9\nassert b.fetch('alpha', 0, [3, 8]) == 11\nassert c.fetch('alpha', 0, [999]) == 9\nassert a.fetch('alpha', 1, [3]) == 3\nassert len(shared) == 3\n"
        add("versioned_cache", name, source, old, new, goal, public, hidden)

    # Disjoint unrelated mechanisms assess whether advice disrupts ordinary work.
    for family, variant in [("explicit_zero", 63), ("snapshot_alias", 64), ("current_input", 65)]:
        case, fixed = make_case(family, variant, "retention")
        case["id"] = "checkpoint_" + case["id"]
        cases.append(case)
        references[case["id"]] = fixed
    # Each transfer phase includes all three families; retention is a final phase.
    for index, case in enumerate(cases):
        case["phase"] = index % 6 // 2 + 1 if case["split"] == "confirmation" else 4
    return cases, references
