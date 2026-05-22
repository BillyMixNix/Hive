"""
code_domain.py

Hive's code research substrate.

Mirrors math_domain.py architecture — same loop, different domain.

For math, the artifact is a conjecture / proof fragment.
For code, the artifact is a hypothesis / verification result.

Provides:
- CodeConjecture  — falsifiable hypothesis about code behavior
- CodeExplorer    — AST inspection, runtime profiling, call tracing
- CodeLessonRecorder — structured failure memory for code strategies
- CodeProgressTracker — 0-6 rubric: observation → verified property
- AdversarialTestAgent — generates tests designed to break hypotheses
"""

import ast
import json
import time
import timeit
import inspect
import importlib
import statistics
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Callable


# ---------------------------------------------------------------------------
# Code Conjecture Schema
# ---------------------------------------------------------------------------

HYPOTHESIS_STATUS = {"unverified", "supported", "falsified", "verified"}

HYPOTHESIS_TYPES = {
    "correctness",   # "f(x) always returns a positive integer"
    "performance",   # "route() is O(n²) in the worst case"
    "architecture",  # "the planner never calls the coder directly"
    "security",      # "no user input reaches eval() unsanitized"
    "invariant",     # "active_task_id is always None or a valid task id"
    "regression",    # "patch X did not change behavior of function Y"
}


@dataclass
class CodeConjecture:
    """
    A falsifiable hypothesis about code behavior.

    Every hypothesis must be:
    - Precisely stated (what function/module/property)
    - Typed (correctness / performance / architecture / invariant)
    - Grounded in evidence before elevation
    - Subjected to adversarial testing before claiming support
    """

    statement: str
    hypothesis_type: str = "correctness"
    target_file: Optional[str] = None
    target_symbol: Optional[str] = None
    status: str = "unverified"
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    falsification_attempts: list = field(default_factory=list)
    test_cases: list = field(default_factory=list)
    proof_sketch: Optional[str] = None
    formal_fragment: Optional[str] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def __post_init__(self):
        if self.hypothesis_type not in HYPOTHESIS_TYPES:
            raise ValueError(
                f"Invalid hypothesis_type '{self.hypothesis_type}'. "
                f"Must be one of {HYPOTHESIS_TYPES}"
            )

    def add_evidence(self, observation: str):
        self.evidence.append(observation)
        self._touch()

    def record_falsification_attempt(self, attempt: str, succeeded: bool, counterexample: Any = None):
        prefix = "[FALSIFIED]" if succeeded else "[SURVIVED]"
        entry = f"{prefix} {attempt}"
        if counterexample is not None:
            entry += f" | counterexample: {repr(counterexample)[:120]}"
        self.falsification_attempts.append(entry)
        if succeeded:
            self.status = "falsified"
        self._touch()

    def add_test_case(self, inputs: Any, expected: Any, actual: Any, passed: bool):
        self.test_cases.append({
            "inputs": repr(inputs)[:200],
            "expected": repr(expected)[:200],
            "actual": repr(actual)[:200],
            "passed": passed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        self._touch()

    def elevate(self, new_status: str, new_confidence: float):
        assert new_status in HYPOTHESIS_STATUS, f"Invalid status: {new_status}"
        self.status = new_status
        self.confidence = new_confidence
        self._touch()

    def _touch(self):
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "statement":           self.statement,
            "hypothesis_type":     self.hypothesis_type,
            "target_file":         self.target_file,
            "target_symbol":       self.target_symbol,
            "status":              self.status,
            "confidence":          self.confidence,
            "evidence":            self.evidence,
            "falsification_attempts": self.falsification_attempts,
            "test_cases":          self.test_cases,
            "proof_sketch":        self.proof_sketch,
            "formal_fragment":     self.formal_fragment,
            "created_at":          self.created_at,
            "updated_at":          self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CodeConjecture":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Code Explorer — AST + Runtime Analysis
# ---------------------------------------------------------------------------

class CodeExplorer:
    """
    Inspects code structure and behavior programmatically.

    Generates evidence for hypothesis formation and adversarial testing.
    Operates on both source files (static) and live callables (dynamic).
    """

    # --- Static Analysis ---

    def parse_file(self, filepath: str) -> Optional[ast.AST]:
        """Parse a Python file into an AST. Returns None on syntax error."""
        try:
            source = Path(filepath).read_text(encoding="utf-8")
            return ast.parse(source, filename=filepath)
        except (SyntaxError, FileNotFoundError, OSError) as e:
            return None

    def get_functions(self, filepath: str) -> list[dict]:
        """Return all function/method definitions in a file with line numbers and args."""
        tree = self.parse_file(filepath)
        if tree is None:
            return []
        results = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                results.append({
                    "name":       node.name,
                    "lineno":     node.lineno,
                    "args":       args,
                    "is_async":   isinstance(node, ast.AsyncFunctionDef),
                    "docstring":  ast.get_docstring(node) or "",
                    "body_lines": node.end_lineno - node.lineno + 1,
                })
        return results

    def get_classes(self, filepath: str) -> list[dict]:
        """Return all class definitions with their method names."""
        tree = self.parse_file(filepath)
        if tree is None:
            return []
        results = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                results.append({
                    "name":    node.name,
                    "lineno":  node.lineno,
                    "methods": methods,
                    "bases":   [ast.unparse(b) for b in node.bases],
                })
        return results

    def find_calls_to(self, filepath: str, target_function: str) -> list[dict]:
        """Find all call sites of a named function within a file."""
        tree = self.parse_file(filepath)
        if tree is None:
            return []
        results = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name == target_function:
                    results.append({
                        "lineno": node.lineno,
                        "caller": target_function,
                    })
        return results

    def count_complexity(self, filepath: str, function_name: str) -> dict:
        """
        Estimate cyclomatic complexity of a function.
        Counts branches: if, elif, for, while, try, except, with, assert.
        """
        tree = self.parse_file(filepath)
        if tree is None:
            return {"error": "parse failed"}

        BRANCH_NODES = (
            ast.If, ast.For, ast.While, ast.Try,
            ast.ExceptHandler, ast.With, ast.Assert,
        )

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == function_name:
                    branches = sum(
                        1 for child in ast.walk(node)
                        if isinstance(child, BRANCH_NODES)
                    )
                    return {
                        "function":   function_name,
                        "complexity": branches + 1,  # +1 for base path
                        "body_lines": node.end_lineno - node.lineno + 1,
                        "rating": (
                            "low"    if branches <= 4  else
                            "medium" if branches <= 9  else
                            "high"
                        ),
                    }
        return {"error": f"Function '{function_name}' not found"}

    def detect_nested_loops(self, filepath: str) -> list[dict]:
        """Find nested loop structures — common source of O(n²) complexity."""
        tree = self.parse_file(filepath)
        if tree is None:
            return []

        results = []
        LOOP_TYPES = (ast.For, ast.While)

        def _walk_loops(node, depth=0, parent_fn=None):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent_fn = node.name
            if isinstance(node, LOOP_TYPES):
                if depth > 0:
                    results.append({
                        "lineno":    node.lineno,
                        "depth":     depth,
                        "in_function": parent_fn,
                        "type":      type(node).__name__,
                    })
                for child in ast.iter_child_nodes(node):
                    _walk_loops(child, depth + 1, parent_fn)
            else:
                for child in ast.iter_child_nodes(node):
                    _walk_loops(child, depth, parent_fn)

        _walk_loops(tree)
        return results

    def find_eval_exec_calls(self, filepath: str) -> list[dict]:
        """Security probe: find all eval() / exec() / __import__() call sites."""
        tree = self.parse_file(filepath)
        if tree is None:
            return []
        targets = {"eval", "exec", "__import__", "compile", "execfile"}
        results = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in targets:
                    results.append({"name": name, "lineno": node.lineno})
        return results

    # --- Dynamic Analysis ---

    def benchmark(
        self,
        fn: Callable,
        args_list: list,
        repeat: int = 3,
        number: int = 1,
    ) -> dict:
        """
        Benchmark a callable across multiple input sizes.
        args_list: list of (args, kwargs) tuples, one per input size.
        Returns timing results and inferred complexity class.
        """
        results = []
        for args, kwargs in args_list:
            times = []
            for _ in range(repeat):
                t0 = time.perf_counter()
                for _ in range(number):
                    fn(*args, **kwargs)
                t1 = time.perf_counter()
                times.append((t1 - t0) / number)
            results.append({
                "args_repr": repr(args)[:80],
                "mean_s":    round(statistics.mean(times), 6),
                "min_s":     round(min(times), 6),
            })

        # Infer complexity from timing ratios
        complexity = "unknown"
        if len(results) >= 2:
            ratios = []
            for i in range(1, len(results)):
                prev = results[i-1]["mean_s"]
                curr = results[i]["mean_s"]
                if prev > 0:
                    ratios.append(curr / prev)
            avg_ratio = statistics.mean(ratios) if ratios else 0
            if avg_ratio < 1.5:
                complexity = "O(1) or O(log n)"
            elif avg_ratio < 2.5:
                complexity = "O(n)"
            elif avg_ratio < 5.0:
                complexity = "O(n log n)"
            elif avg_ratio < 9.0:
                complexity = "O(n²)"
            else:
                complexity = "O(n²) or worse"

        return {
            "function":          getattr(fn, "__name__", str(fn)),
            "timings":           results,
            "inferred_complexity": complexity,
            "repeat":            repeat,
        }

    def profile_calls(self, fn: Callable, *args, **kwargs) -> dict:
        """
        Run a function and return basic call statistics.
        Captures exceptions cleanly.
        """
        result = {}
        t0 = time.perf_counter()
        try:
            output = fn(*args, **kwargs)
            result["output"] = repr(output)[:300]
            result["raised"] = None
        except Exception as e:
            result["output"] = None
            result["raised"] = f"{type(e).__name__}: {e}"
            result["traceback"] = traceback.format_exc()
        result["elapsed_s"] = round(time.perf_counter() - t0, 6)
        result["function"]  = getattr(fn, "__name__", str(fn))
        return result

    def get_source_metrics(self, filepath: str) -> dict:
        """Return high-level metrics for a Python file."""
        try:
            source = Path(filepath).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return {"error": f"Cannot read {filepath}"}

        lines = source.splitlines()
        tree = self.parse_file(filepath)

        functions = self.get_functions(filepath) if tree else []
        classes   = self.get_classes(filepath)   if tree else []
        nested    = self.detect_nested_loops(filepath) if tree else []
        dangerous = self.find_eval_exec_calls(filepath) if tree else []

        return {
            "filepath":       filepath,
            "total_lines":    len(lines),
            "blank_lines":    sum(1 for l in lines if not l.strip()),
            "comment_lines":  sum(1 for l in lines if l.strip().startswith("#")),
            "functions":      len(functions),
            "classes":        len(classes),
            "nested_loops":   len(nested),
            "dangerous_calls": len(dangerous),
            "parse_ok":       tree is not None,
        }


# ---------------------------------------------------------------------------
# Code Lesson Recorder
# ---------------------------------------------------------------------------

class CodeLessonRecorder:
    """
    Structured memory for failed code strategies.

    Same schema as MathLessonRecorder — strategy, failure point, insight —
    but typed for code hypotheses. Injected into the reflector automatically
    when code-related output is detected.
    """

    def __init__(self, path: str = "code_lessons.jsonl"):
        self.path = path

    def record(
        self,
        hypothesis: str,
        strategy: str,
        failure_point: str,
        insight: str,
        agent: str = "unknown",
        target_file: Optional[str] = None,
        target_symbol: Optional[str] = None,
    ) -> dict:
        lesson = {
            "hypothesis":     hypothesis,
            "strategy":       strategy,
            "failure_point":  failure_point,
            "insight":        insight,
            "agent":          agent,
            "target_file":    target_file,
            "target_symbol":  target_symbol,
            "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(lesson) + "\n")
        return lesson

    def load_lessons(
        self,
        target_file: Optional[str] = None,
        limit: int = 8,
    ) -> list[dict]:
        """Load recent lessons, optionally filtering by target file."""
        lessons = []
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        lesson = json.loads(line)
                        if target_file is None or lesson.get("target_file") == target_file:
                            lessons.append(lesson)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return lessons[-limit:]

    def format_for_reflector(self, target_file: Optional[str] = None) -> str:
        """Return formatted lessons for injection into reflector prompt."""
        lessons = self.load_lessons(target_file=target_file)
        if not lessons:
            return ""
        parts = ["Prior code strategy failures (do not repeat these):"]
        for l in lessons:
            parts.append(
                f"  - [{l.get('agent','?')}] Strategy: {l.get('strategy','?')} | "
                f"Failed: {l.get('failure_point','?')} | "
                f"Insight: {l.get('insight','?')}"
            )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Code Progress Tracker
# ---------------------------------------------------------------------------

CODE_PROGRESS_LEVELS = {
    0: "raw_observation",       # "this seems slow" — no structure
    1: "stated_hypothesis",     # falsifiable claim about behavior
    2: "empirically_tested",    # ran it, got numbers or pass/fail
    3: "pattern_identified",    # complexity class, failure mode named
    4: "formal_preconditions",  # assumptions explicitly stated
    5: "proof_sketch",          # step-by-step argument with gap identified
    6: "verified_property",     # property-based tested or statically proved
}

CODE_NEXT_ACTIONS = {
    0: "State the hypothesis precisely — what function, what property, falsifiable.",
    1: "Run it. Profile it. Write a test. Generate empirical evidence.",
    2: "Name the pattern — is this O(n²)? A missing guard? A race condition?",
    3: "State all assumptions. What does this rely on being true?",
    4: "Build a step-by-step argument. Where exactly does it hold or break?",
    5: "Run property-based tests (Hypothesis) or static analysis to verify.",
    6: "Commit the verified property. Wire it as a regression test.",
}


class CodeProgressTracker:
    """
    Scores code hypotheses on a 0-6 research depth rubric.

    Gives the planner a goal model — tells it what the NEXT step
    should be rather than just whether the current step passed.
    """

    def score(self, hypothesis: "CodeConjecture") -> dict:
        level = 0
        reasons = []

        if not hypothesis.statement or len(hypothesis.statement) <= 10:
            return self._result(0, reasons, hypothesis)
        level = max(level, 1)

        if hypothesis.evidence or hypothesis.test_cases:
            level = max(level, 2)
            reasons.append(
                f"{len(hypothesis.evidence)} evidence item(s), "
                f"{len(hypothesis.test_cases)} test case(s)"
            )

        pattern_signals = (
            "O(n", "O(log", "O(1)", "complexity", "always", "never",
            "invariant", "monotone", "bounded", "race", "deadlock",
            "injection", "overflow", "underflow", "missing guard",
        )
        if any(s in hypothesis.statement for s in pattern_signals):
            level = max(level, 3)
            reasons.append("pattern named in hypothesis")

        if hypothesis.proof_sketch and any(
            k in hypothesis.proof_sketch for k in
            ("assume", "Assume", "Let ", "where ", "requires",
             "bounded by", "precondition", "invariant:")
        ):
            level = max(level, 4)
            reasons.append("preconditions in proof sketch")

        if hypothesis.proof_sketch and len(hypothesis.proof_sketch) > 80:
            level = max(level, 5)
            reasons.append("proof sketch present")

        if hypothesis.formal_fragment:
            level = max(level, 6)
            reasons.append("formal fragment / verified test present")

        return self._result(level, reasons, hypothesis)

    def _result(self, level: int, reasons: list, hypothesis: "CodeConjecture") -> dict:
        return {
            "score":       level,
            "level_name":  CODE_PROGRESS_LEVELS.get(level, "unknown"),
            "max_score":   6,
            "reasons":     reasons,
            "next_action": CODE_NEXT_ACTIONS.get(level, "Maximum depth reached."),
            "hypothesis":  hypothesis.statement[:80],
            "type":        hypothesis.hypothesis_type,
            "status":      hypothesis.status,
            "confidence":  hypothesis.confidence,
        }

    def score_all(self, hypotheses: list) -> list:
        results = [self.score(h) for h in hypotheses]
        return sorted(results, key=lambda r: r["score"], reverse=True)


# ---------------------------------------------------------------------------
# Adversarial Test Agent
# ---------------------------------------------------------------------------

class AdversarialTestAgent:
    """
    Generates tests designed to break a CodeConjecture.

    For correctness: edge cases, boundary values, type violations.
    For performance: worst-case inputs, scaling probes.
    For architecture: traces call graphs looking for forbidden paths.
    For security: injection inputs, boundary-crossing values.

    Uses Hypothesis for property-based testing when available.
    """

    def __init__(self):
        try:
            import hypothesis
            self._hypothesis_available = True
        except ImportError:
            self._hypothesis_available = False

    def boundary_probe(self, fn: Callable, type_hint: str = "int") -> dict:
        """
        Test a function at boundary values for the given type.
        Returns a dict of input → output/exception.
        """
        if type_hint == "int":
            candidates = [0, 1, -1, 2, -2, 100, -100,
                          2**31 - 1, -(2**31), 2**63 - 1, -(2**63)]
        elif type_hint == "str":
            candidates = ["", " ", "\n", "\t", "a" * 1000,
                          "'; DROP TABLE--", "<script>", "\x00", "🔥"]
        elif type_hint == "list":
            candidates = [[], [None], [0]*1000, list(range(1000)),
                          list(range(1000, 0, -1))]
        else:
            candidates = [None, 0, "", [], {}]

        results = {}
        for val in candidates:
            try:
                out = fn(val)
                results[repr(val)] = {"output": repr(out)[:100], "raised": None}
            except Exception as e:
                results[repr(val)] = {"output": None, "raised": f"{type(e).__name__}: {e}"}

        falsified = any(r["raised"] for r in results.values())
        return {
            "function":      getattr(fn, "__name__", str(fn)),
            "type_hint":     type_hint,
            "results":       results,
            "falsified":     falsified,
            "counterexample": next(
                (inp for inp, r in results.items() if r["raised"]), None
            ),
        }

    def scaling_probe(self, fn: Callable, size_fn: Callable, sizes: list) -> dict:
        """
        Measure runtime at increasing input sizes.
        size_fn: callable that generates input of a given size.
        Returns timings and inferred complexity.
        """
        explorer = CodeExplorer()
        args_list = [((size_fn(s),), {}) for s in sizes]
        result = explorer.benchmark(fn, args_list)
        result["sizes"] = sizes
        return result

    def architecture_trace(self, source_dir: str, forbidden_edge: tuple) -> dict:
        """
        Check whether module A calls module B directly (forbidden architectural dependency).
        forbidden_edge: (caller_module, callee_function) e.g. ('planner', 'ask_model')
        """
        caller_mod, callee_fn = forbidden_edge
        violations = []

        for py_file in Path(source_dir).glob("*.py"):
            if caller_mod not in py_file.stem:
                continue
            explorer = CodeExplorer()
            calls = explorer.find_calls_to(str(py_file), callee_fn)
            if calls:
                violations.extend([
                    {"file": py_file.name, "lineno": c["lineno"]}
                    for c in calls
                ])

        return {
            "forbidden_edge":   f"{caller_mod} → {callee_fn}",
            "violations":       violations,
            "falsified":        len(violations) > 0,
            "verdict":          "VIOLATION FOUND" if violations else "clean",
        }

    def run_hypothesis_test(
        self,
        fn: Callable,
        strategy_desc: str,
        test_fn: Callable,
    ) -> dict:
        """
        Run a Hypothesis property-based test.
        test_fn: a function that accepts a Hypothesis strategy and asserts properties.
        Returns result dict with pass/fail and any counterexample found.
        """
        if not self._hypothesis_available:
            return {
                "status":  "skipped",
                "reason":  "Hypothesis library not available",
                "verdict": "inconclusive",
            }
        try:
            test_fn()
            return {
                "function":   getattr(fn, "__name__", str(fn)),
                "strategy":   strategy_desc,
                "status":     "passed",
                "falsified":  False,
                "verdict":    "property holds for all tested inputs",
            }
        except Exception as e:
            return {
                "function":   getattr(fn, "__name__", str(fn)),
                "strategy":   strategy_desc,
                "status":     "failed",
                "falsified":  True,
                "counterexample": str(e)[:300],
                "verdict":    "FALSIFIED — counterexample found",
            }

    def run(
        self,
        hypothesis: "CodeConjecture",
        *,
        fn: Callable = None,
        source_dir: str = ".",
        size_fn: Callable = None,
        sizes: list = None,
        forbidden_edge: tuple = None,
        strategy_desc: str = None,
        test_fn: Callable = None,
    ) -> dict:
        """
        Dispatch to the appropriate test method based on hypothesis.hypothesis_type.
        Updates the hypothesis with the falsification attempt result and returns a
        unified result dict with keys: hypothesis_type, status, falsified, verdict,
        counterexample, detail.
        """
        h_type = hypothesis.hypothesis_type

        if h_type == "architecture":
            if forbidden_edge is None:
                return self._skipped("forbidden_edge required for architecture hypotheses")
            result = self.architecture_trace(source_dir, forbidden_edge)

        elif h_type == "performance":
            if fn is None or size_fn is None:
                return self._skipped("fn and size_fn required for performance hypotheses")
            result = self.scaling_probe(fn, size_fn, sizes or [10, 100, 1000])
            result.setdefault("falsified", False)

        elif h_type == "security":
            if fn is None:
                return self._skipped("fn required for security hypotheses")
            result = self.boundary_probe(fn, type_hint="str")

        else:
            # correctness, invariant, regression
            if test_fn is not None and strategy_desc is not None:
                result = self.run_hypothesis_test(fn or (lambda x: x), strategy_desc, test_fn)
            elif fn is not None:
                stmt = hypothesis.statement.lower()
                if "string" in stmt or "str" in stmt:
                    type_hint = "str"
                elif "list" in stmt or "array" in stmt:
                    type_hint = "list"
                else:
                    type_hint = "int"
                result = self.boundary_probe(fn, type_hint=type_hint)
            else:
                return self._skipped(f"fn required for {h_type} hypotheses")

        falsified = result.get("falsified", False)
        verdict = result.get("verdict", "FALSIFIED" if falsified else "survived all probes")
        counterexample = result.get("counterexample")

        hypothesis.record_falsification_attempt(
            f"{h_type} adversarial test", falsified, counterexample
        )

        return {
            "hypothesis_type": h_type,
            "status":          "falsified" if falsified else "survived",
            "falsified":       falsified,
            "verdict":         verdict,
            "counterexample":  counterexample,
            "detail":          result,
        }

    def _skipped(self, reason: str) -> dict:
        return {
            "hypothesis_type": None,
            "status":          "skipped",
            "falsified":       False,
            "verdict":         "inconclusive",
            "counterexample":  None,
            "detail":          {"reason": reason},
        }
