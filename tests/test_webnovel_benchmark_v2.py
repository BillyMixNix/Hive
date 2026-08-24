import json
import re
import subprocess
from pathlib import Path

import pytest

import hive_llm
import kingdom.webnovel_benchmark_v2 as v2_module
from kingdom.adi_story_boundary import load_adi_story_boundary
from kingdom.webnovel_benchmark_v2 import (
    PROTOCOL_V2_CRITICAL_SOURCE_FILES,
    PROTOCOL_V2_EXPECTED_SMOKE_CALLS,
    PROTOCOL_V2_FROZEN_PROMPT_SHA256,
    PROTOCOL_V2_ID,
    PROTOCOL_V2_MODEL,
    PROTOCOL_V2_MODEL_DIGEST,
    PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS,
    PROTOCOL_V2_SMOKE_RELATIVE_OUTPUT,
    ProtocolV2Config,
    ProtocolV2Runner,
    _authority_prompt,
    _git_revision_and_clean,
    _require_canonical_cli_output,
    _story_map_frozen_core_sha256,
    canonical_story_map_interface,
)


BENCHMARK_DIR = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "adi_001_richest_man_breathing"
)
REPO_ROOT = Path(__file__).resolve().parents[1]


def benchmark_inputs():
    seed = (BENCHMARK_DIR / "SEED.md").read_text(encoding="utf-8")
    contract = (BENCHMARK_DIR / "CONTRACT.md").read_text(encoding="utf-8")
    protocol = (BENCHMARK_DIR / "PROTOCOL_V2.md").read_text(encoding="utf-8")
    boundary = load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=(BENCHMARK_DIR / "STORY_MAP.json").read_text(
            encoding="utf-8"
        ),
    )
    return seed, contract, protocol, boundary


def expanded_longitudinal_boundary():
    seed = (BENCHMARK_DIR / "SEED.md").read_text(encoding="utf-8")
    contract = (BENCHMARK_DIR / "CONTRACT.md").read_text(encoding="utf-8")
    raw = json.loads((BENCHMARK_DIR / "STORY_MAP.json").read_text(encoding="utf-8"))
    for chapter in range(3, 11):
        chapter_key = str(chapter)
        for field in (
            "chapter_frontiers",
            "locked_terms_by_chapter",
            "forbidden_patterns_by_chapter",
            "opening_requirements_by_chapter",
        ):
            raw[field][chapter_key] = json.loads(
                json.dumps(raw[field]["2"])
            )
    return load_adi_story_boundary(
        seed=seed,
        contract=contract,
        source_map_text=json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )


def state_delta(prompt: str, *, locked=False) -> str:
    chapter = int(
        re.search(
            r'The exact top-level schema is: \{"schema_version": 1, "chapter": (\d+)',
            prompt,
        ).group(1)
    )
    source_hash = re.search(
        r'source_sha256 must be "([0-9a-f]{64})"', prompt
    ).group(1)
    evidence = (
        "Ren recorded the grounded result."
        if chapter == 2
        else f"Ren recorded the grounded result in Chapter {chapter}."
    )
    statement = evidence
    if locked:
        statement = "Ren founded Sovereign Capital."
    claim = {
        "claim_id": f"ch{chapter}.fact.recorded",
        "statement": statement,
        "status": "current",
        "depends_on": [],
        "evidence": {
            "source_id": f"chapter:{chapter:04d}",
            "source_sha256": source_hash,
            "chapter": chapter,
            "quote": evidence,
        },
    }
    summary = {
        "claim_id": f"ch{chapter}.summary.recorded",
        "statement": evidence,
        "status": "current",
        "depends_on": [claim["claim_id"]],
        "evidence": dict(claim["evidence"]),
    }
    categories = {
        category: []
        for category in (
            "facts",
            "character_states",
            "knowledge",
            "financial_state",
            "cultivation_state",
            "assets",
            "obligations",
            "mysteries",
            "themes",
            "tone",
            "chapter_summaries",
        )
    }
    categories["facts"] = [claim]
    categories["chapter_summaries"] = [summary]
    return json.dumps(
        {"schema_version": 1, "chapter": chapter, "claims": categories}
    )


class V2FakeAsk:
    def __init__(
        self,
        *,
        reject_baseline_prose=False,
        reject_kingdom_prose=False,
        reject_kingdom_chapter=None,
        reject_state=False,
        invalid_state=False,
        fail_state_transport=False,
        invalid_judge=False,
    ):
        self.calls = []
        self.reject_baseline_prose = reject_baseline_prose
        self.reject_kingdom_prose = reject_kingdom_prose
        self.reject_kingdom_chapter = reject_kingdom_chapter
        self.reject_state = reject_state
        self.invalid_state = invalid_state
        self.fail_state_transport = fail_state_transport
        self.invalid_judge = invalid_judge

    def __call__(
        self,
        prompt,
        *,
        role="default",
        timeout=None,
        model=None,
        system=None,
        options=None,
        max_retries=None,
        metadata=None,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "role": role,
                "timeout": timeout,
                "model": model,
                "system": system,
                "options": options,
                "max_retries": max_retries,
            }
        )
        if "state DELTA PROPOSER" in prompt and self.fail_state_transport:
            if metadata is not None:
                metadata.update(
                    {
                        "physical_attempts": 1,
                        "done": False,
                        "done_reason": "transport_error",
                    }
                )
            raise TimeoutError("state transport failed exactly once")
        if metadata is not None:
            metadata.update(
                {
                    "physical_attempts": 1,
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 10,
                    "eval_count": 20,
                    "total_duration": 100,
                }
            )
        if "state DELTA PROPOSER" in prompt:
            if self.invalid_state:
                return "not-json-state-proposal"
            return state_delta(prompt, locked=self.reject_state)
        if "condition-blind causal-degradation judge" in prompt:
            if self.invalid_judge:
                return "not-json"
            chapter = int(
                re.search(r'"through_chapter":\s*(\d+)', prompt).group(1)
            ) + 1
            return json.dumps(
                {
                    "schema_version": 1,
                    "chapter": chapter,
                    "continuity_violations": 0,
                    "factual_continuity_violations": 0,
                    "causal_prerequisite_violations": 0,
                    "obligation_violations": 0,
                    "progression_economic_errors": 0,
                    "intent_drift_score": 0,
                    "repair_burden_score": 10,
                    "rationale": ["The admitted chapter remains at the current boundary."],
                    "evidence": ["Ren recorded the grounded result."],
                }
            )
        if "ordinary novelist's causal outline" in prompt:
            return "BASELINE_PLAN"
        if "dependency/obligation/intent plan" in prompt:
            return json.dumps(
                {
                    "chapter_goal": "KINGDOM_PLAN",
                    "causal_chain": ["recover", "record"],
                    "prerequisites": ["remain at published endpoint"],
                    "obligations": [],
                    "progression_checks": ["no unearned change"],
                    "forbidden_moves": ["future promotion"],
                    "setup_payoff_links": [],
                    "terminal_intent_checks": ["grounded opening"],
                }
            )
        if "one pre-registered ordinary holistic revision" in prompt:
            if self.reject_baseline_prose:
                return (
                    "# Chapter Two\n\nAt the Walmart parking lot, Ren steadied his "
                    "breath. He returned to his apartment."
                )
            chapter = int(
                re.search(r"ELIGIBLE CHAPTER (\d+) FRONTIER", prompt).group(1)
            )
            recorded = (
                "Ren recorded the grounded result."
                if chapter == 2
                else f"Ren recorded the grounded result in Chapter {chapter}."
            )
            return (
                f"# Chapter {chapter}\n\nAt the Walmart parking lot, Ren steadied "
                f"his breath. {recorded}"
            )
        if "one pre-registered terminal Critical-Path revision" in prompt:
            chapter = int(
                re.search(r"ELIGIBLE CHAPTER (\d+) FRONTIER", prompt).group(1)
            )
            if self.reject_kingdom_prose or self.reject_kingdom_chapter == chapter:
                return (
                    "# Chapter Two\n\nAt the Walmart parking lot, Ren steadied his "
                    "breath. He returned to his apartment."
                )
            recorded = (
                "Ren recorded the grounded result."
                if chapter == 2
                else f"Ren recorded the grounded result in Chapter {chapter}."
            )
            return (
                f"# Chapter {chapter}\n\nAt the Walmart parking lot, Ren steadied "
                f"his breath. {recorded}"
            )
        if re.search(r"Write Chapter \d+ as finished", prompt):
            return "# Draft\n\nRen recorded the grounded result."
        if re.search(r"Synthesize Chapter \d+ as finished", prompt):
            return "# Draft\n\nRen recorded the grounded result."
        raise AssertionError("unrecognized Protocol-v2 prompt")


def _sealed_v1_fixture(tmp_path):
    root = tmp_path / "sealed-v1"
    files = {
        "calls.jsonl": b"sealed calls\n",
        "manifest.json": b'{"sealed": true}\n',
        "rejected/baseline/chapter_0002.json": b'{"rejected": true}\n',
    }
    expected = {}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        expected[relative] = (
            len(content),
            __import__("hashlib").sha256(content).hexdigest(),
        )
    return root, expected


def make_runner(
    tmp_path,
    fake,
    *,
    chapters=2,
    output_name="run",
    smoke_qualification_file=None,
    boundary_override=None,
):
    seed, contract, protocol, boundary = benchmark_inputs()
    if boundary_override is not None:
        boundary = boundary_override
    sealed_v1, sealed_expected = _sealed_v1_fixture(tmp_path)
    runner = ProtocolV2Runner(
        seed=seed,
        contract=contract,
        protocol_document=protocol,
        story_boundary=boundary,
        output_dir=tmp_path / output_name,
        ask_fn=fake,
        model_name=PROTOCOL_V2_MODEL,
        model_digest=PROTOCOL_V2_MODEL_DIGEST,
        source_revision="b" * 40,
        source_file_sha256={
            path: "c" * 64 for path in PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS
        },
        frozen_v1_evidence_dir=sealed_v1,
        frozen_v1_expected_files=sealed_expected,
        config=ProtocolV2Config(chapters=chapters),
        smoke_qualification_file=smoke_qualification_file,
    )
    return runner, boundary


def read_calls(output_dir: Path):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((output_dir / "evidence" / "calls").glob("call_*.json"))
    ]


def test_both_arms_consume_byte_identical_canonical_story_map_interface():
    _, _, _, boundary = benchmark_inputs()
    left = canonical_story_map_interface(
        boundary,
        boundary.initial_state,
        chapter=2,
        prior_tail=boundary.chapter_one_tail,
    )
    right = canonical_story_map_interface(
        boundary,
        boundary.initial_state,
        chapter=2,
        prior_tail=boundary.chapter_one_tail,
    )

    assert left == right
    assert "CANONICAL STORY MAP" in left
    assert '"depends_on"' in left
    assert '"provenance"' in left
    assert "MULTIVERSAL MARKETPLACE" not in left


def test_symmetric_smoke_preserves_all_ten_calls_guards_states_and_judges(tmp_path):
    fake = V2FakeAsk()
    runner, boundary = make_runner(tmp_path, fake)

    outcome = runner.run()

    assert outcome.status == "symmetric_smoke_passed"
    assert outcome.exit_code == 0
    assert len(fake.calls) == PROTOCOL_V2_EXPECTED_SMOKE_CALLS == 10
    assert all(call["max_retries"] == 1 for call in fake.calls)
    assert {call["model"] for call in fake.calls} == {PROTOCOL_V2_MODEL}
    assert {call["timeout"] for call in fake.calls} == {900}
    assert {call["options"]["num_ctx"] for call in fake.calls} == {32768}
    assert {call["options"]["num_predict"] for call in fake.calls} == {2048}
    assert {call["options"]["temperature"] for call in fake.calls} == {0.2}
    assert {call["options"]["seed"] for call in fake.calls} == {42001}

    calls = read_calls(tmp_path / "run")
    assert len(calls) == 10
    assert all(call["status"] == "completed" for call in calls)
    assert all(call["request"]["prompt"] for call in calls)
    assert all(call["response"]["text"] for call in calls)
    assert [call["request"]["condition"] for call in calls] == [
        "baseline",
        "baseline",
        "baseline",
        "baseline",
        "kingdom",
        "kingdom",
        "kingdom",
        "kingdom",
        "baseline",
        "kingdom",
    ]

    shared = canonical_story_map_interface(
        boundary,
        boundary.initial_state,
        chapter=2,
        prior_tail=boundary.chapter_one_tail,
    )
    assert calls[0]["request"]["prompt"].startswith(shared)
    assert calls[4]["request"]["prompt"].startswith(shared)
    assert (tmp_path / "run" / "branches" / "baseline" / "chapter_0002" / "accepted_branch.json").is_file()
    assert (tmp_path / "run" / "branches" / "kingdom" / "chapter_0002" / "accepted_branch.json").is_file()
    for condition in ("baseline", "kingdom"):
        folder = tmp_path / "run" / "branches" / condition / "chapter_0002"
        assert json.loads((folder / "guard_prose_precheck.json").read_text())["accepted"] is True
        assert json.loads((folder / "guard_state_promotion.json").read_text())["accepted"] is True
        metric = json.loads(
            (tmp_path / "run" / "metrics" / condition / "chapter_0002.json").read_text()
        )
        assert metric["illegal_state_promotions"] == 0
        trajectory = json.loads(
            (tmp_path / "run" / "metrics" / condition / "trajectory.json").read_text()
        )
        assert trajectory["aggregate"]["degradation_slope"] is None
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["winner"] is None
    assert status["symmetric_smoke_passed"] is True
    assert status["longitudinal_run_authorized"] is False
    assert (tmp_path / "run" / "RESULT.md").is_file()


def test_prose_rejection_stops_after_three_calls_and_never_runs_kingdom(tmp_path):
    fake = V2FakeAsk(reject_baseline_prose=True)
    runner, _ = make_runner(tmp_path, fake)

    outcome = runner.run()

    assert outcome.status == "symmetric_smoke_rejected"
    assert outcome.condition == "baseline"
    assert len(fake.calls) == 3
    assert len(read_calls(tmp_path / "run")) == 3
    folder = tmp_path / "run" / "branches" / "baseline" / "chapter_0002"
    rejection = json.loads((folder / "rejected_branch.json").read_text())
    assert "his apartment" in rejection["generation"]["raw_final_response"]
    assert rejection["canonical_promotion_occurred"] is False
    assert json.loads((folder / "guard_prose_precheck.json").read_text())["accepted"] is False
    assert not (tmp_path / "run" / "branches" / "kingdom").exists()
    assert not (tmp_path / "run" / "RESULT.md").exists()
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["winner"] is None
    assert status["longitudinal_run_authorized"] is False
    assert status["rejection_metrics"]["illegal_state_promotions"] == 0


def test_rejected_state_proposal_and_both_guard_decisions_are_preserved(tmp_path):
    fake = V2FakeAsk(reject_state=True)
    runner, _ = make_runner(tmp_path, fake)

    outcome = runner.run()

    assert outcome.status == "symmetric_smoke_rejected"
    assert len(fake.calls) == 4
    calls = read_calls(tmp_path / "run")
    assert "Sovereign Capital" in calls[-1]["response"]["text"]
    folder = tmp_path / "run" / "branches" / "baseline" / "chapter_0002"
    assert json.loads((folder / "guard_prose_precheck.json").read_text())["accepted"] is True
    promotion = json.loads((folder / "guard_state_promotion.json").read_text())
    assert promotion["accepted"] is False
    assert "locked future canon" in promotion["error"]["message"]
    rejection = json.loads((folder / "rejected_branch.json").read_text())
    assert len(rejection["guard_decisions"]) == 2
    assert not (folder / "accepted_branch.json").exists()
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["rejection_metrics"]["illegal_state_promotions"] == 1


def test_invalid_state_candidate_is_branch_rejection_not_illegal_promotion(tmp_path):
    fake = V2FakeAsk(invalid_state=True)
    runner, _ = make_runner(tmp_path, fake)

    outcome = runner.run()

    assert outcome.status == "symmetric_smoke_rejected"
    assert len(fake.calls) == 4
    folder = tmp_path / "run" / "branches" / "baseline" / "chapter_0002"
    decision = json.loads((folder / "guard_state_promotion.json").read_text())
    assert decision["classification"] == "candidate_state_schema_rejected"
    assert decision["illegal_state_promotions"] == 0
    assert read_calls(tmp_path / "run")[-1]["response"]["text"] == (
        "not-json-state-proposal"
    )
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["rejection_metrics"]["illegal_state_promotions"] == 0


def test_state_transport_failure_is_apparatus_failure_and_preserved(tmp_path):
    fake = V2FakeAsk(fail_state_transport=True)
    runner, _ = make_runner(tmp_path, fake)

    with pytest.raises(TimeoutError, match="exactly once"):
        runner.run()

    assert len(fake.calls) == 4
    calls = read_calls(tmp_path / "run")
    assert calls[-1]["status"] == "transport_error"
    assert calls[-1]["transport"]["error"]["message"] == (
        "state transport failed exactly once"
    )
    folder = tmp_path / "run" / "branches" / "baseline" / "chapter_0002"
    assert (folder / "guard_prose_precheck.json").is_file()
    assert not (folder / "rejected_branch.json").exists()
    assert not (folder / "accepted_branch.json").exists()
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["status"] == "apparatus_failure"
    assert status["winner"] is None


def test_kingdom_rejection_preserves_baseline_and_stops_without_winner(tmp_path):
    fake = V2FakeAsk(reject_kingdom_prose=True)
    runner, _ = make_runner(tmp_path, fake)

    outcome = runner.run()

    assert outcome.status == "symmetric_smoke_rejected"
    assert outcome.condition == "kingdom"
    assert len(fake.calls) == 7
    assert (
        tmp_path
        / "run"
        / "branches"
        / "baseline"
        / "chapter_0002"
        / "accepted_branch.json"
    ).is_file()
    kingdom = tmp_path / "run" / "branches" / "kingdom" / "chapter_0002"
    assert (kingdom / "rejected_branch.json").is_file()
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["winner"] is None
    assert status["condition_terminal_status"]["kingdom"][
        "terminal_status"
    ] == "rejected"
    assert status["condition_terminal_status"]["baseline"][
        "terminal_status"
    ] == "right_censored_after_admission_due_symmetric_stop"
    assert status["completed_paired_admitted_chapters"] == []


def test_invalid_judge_output_is_preserved_as_apparatus_failure(tmp_path):
    fake = V2FakeAsk(invalid_judge=True)
    runner, _ = make_runner(tmp_path, fake)

    with pytest.raises(ValueError):
        runner.run()

    calls = read_calls(tmp_path / "run")
    assert len(calls) == 9
    assert calls[-1]["response"]["text"] == "not-json"
    status = json.loads((tmp_path / "run" / "RUN_STATUS.json").read_text())
    assert status["status"] == "apparatus_failure"
    assert status["winner"] is None
    assert not (tmp_path / "run" / "RESULT.md").exists()


def test_fresh_only_directory_refuses_overwrite_before_any_call(tmp_path):
    fake = V2FakeAsk()
    (tmp_path / "run").mkdir()
    runner, _ = make_runner(tmp_path, fake)

    with pytest.raises(FileExistsError, match="fresh run directory"):
        runner.run()

    assert fake.calls == []


def test_sealed_v1_mutation_and_descendant_output_fail_before_any_call(tmp_path):
    fake = V2FakeAsk()
    runner, _ = make_runner(tmp_path, fake)
    sealed_call_file = runner.frozen_v1_evidence_dir / "calls.jsonl"
    sealed_call_file.write_bytes(sealed_call_file.read_bytes() + b"changed")

    with pytest.raises(RuntimeError, match="sealed Protocol-v1 evidence changed"):
        runner.run()
    assert fake.calls == []
    assert not (tmp_path / "run").exists()

    clean_runner, _ = make_runner(
        tmp_path, V2FakeAsk(), output_name="unused"
    )
    clean_runner.output_dir = clean_runner.frozen_v1_evidence_dir / "v2-child"
    with pytest.raises(ValueError, match="inside the sealed Protocol-v1"):
        clean_runner.run()


def test_wrong_model_or_oversize_authority_fails_without_transport(tmp_path):
    fake = V2FakeAsk()
    runner, _ = make_runner(tmp_path, fake)
    runner.model_name = "different-model"
    with pytest.raises(ValueError, match="requires model"):
        runner.run()
    assert fake.calls == []

    with pytest.raises(RuntimeError, match="authority cannot be clipped"):
        _authority_prompt("x" * 60_001, 60_000)

    expected = tmp_path / PROTOCOL_V2_SMOKE_RELATIVE_OUTPUT
    assert _require_canonical_cli_output(
        tmp_path, expected, chapters=2
    ) == expected.resolve()
    with pytest.raises(ValueError, match="unregistered retry"):
        _require_canonical_cli_output(
            tmp_path, tmp_path / "different-smoke", chapters=2
        )


def test_git_source_binding_requires_clean_tracked_filter_equivalent_head(tmp_path):
    repo = tmp_path / "binding-repo"
    repo.mkdir()
    paths = {}
    for relative in PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"bound source: {relative}\n", encoding="utf-8")
        paths[relative] = path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Protocol V2 Test",
            "-c",
            "user.email=protocol-v2@example.invalid",
            "commit",
            "-qm",
            "bind fixture",
        ],
        cwd=repo,
        check=True,
    )

    revision, bindings = _git_revision_and_clean(repo, paths)

    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert set(bindings) == set(PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS)
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in bindings.values())

    changed = repo / PROTOCOL_V2_CRITICAL_SOURCE_FILES[0]
    changed.write_text("changed after commit\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="tracked or staged source changes"):
        _git_revision_and_clean(repo, paths)

    subprocess.run(
        ["git", "restore", "--worktree", "--", PROTOCOL_V2_CRITICAL_SOURCE_FILES[0]],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "rm", "--cached", "-q", "--", PROTOCOL_V2_CRITICAL_SOURCE_FILES[0]],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Protocol V2 Test",
            "-c",
            "user.email=protocol-v2@example.invalid",
            "commit",
            "-qm",
            "make critical source untracked",
        ],
        cwd=repo,
        check=True,
    )
    with pytest.raises(RuntimeError, match="not tracked by Git"):
        _git_revision_and_clean(repo, paths)


def test_story_map_frozen_core_allows_only_new_chapter_three_plus_coverage():
    raw = json.loads((BENCHMARK_DIR / "STORY_MAP.json").read_text(encoding="utf-8"))
    original = _story_map_frozen_core_sha256(raw)

    expanded = json.loads(json.dumps(raw))
    for field in (
        "chapter_frontiers",
        "locked_terms_by_chapter",
        "forbidden_patterns_by_chapter",
        "opening_requirements_by_chapter",
    ):
        expanded[field]["3"] = json.loads(json.dumps(expanded[field]["2"]))
    assert _story_map_frozen_core_sha256(expanded) == original

    changed_chapter_two = json.loads(json.dumps(raw))
    changed_chapter_two["chapter_frontiers"]["2"].append("post-hoc tuning")
    assert _story_map_frozen_core_sha256(changed_chapter_two) != original

    changed_initial_canon = json.loads(json.dumps(raw))
    changed_initial_canon["future_intent"].append("post-hoc future intent")
    assert _story_map_frozen_core_sha256(changed_initial_canon) != original


def test_longitudinal_launch_fails_preflight_until_frontiers_are_reviewed(tmp_path):
    fake = V2FakeAsk()
    runner, _ = make_runner(tmp_path, fake, chapters=10)

    with pytest.raises(ValueError, match="requires a verified passing"):
        runner.run()

    assert fake.calls == []
    assert not (tmp_path / "run").exists()

    smoke_runner, _ = make_runner(tmp_path, fake, output_name="smoke")
    assert smoke_runner.run().status == "symmetric_smoke_passed"
    qualified_runner, _ = make_runner(
        tmp_path,
        V2FakeAsk(),
        chapters=10,
        output_name="longitudinal",
        smoke_qualification_file=tmp_path / "smoke" / "RUN_STATUS.json",
    )
    with pytest.raises(ValueError, match="lacks reviewed Story Map coverage"):
        qualified_runner.run()
    assert not (tmp_path / "longitudinal").exists()

    long_fake = V2FakeAsk()
    complete_runner, _ = make_runner(
        tmp_path,
        long_fake,
        chapters=10,
        output_name="longitudinal-complete",
        smoke_qualification_file=tmp_path / "smoke" / "RUN_STATUS.json",
        boundary_override=expanded_longitudinal_boundary(),
    )
    outcome = complete_runner.run()
    assert outcome.status == "longitudinal_completed"
    assert len(long_fake.calls) == 90
    status = json.loads(
        (tmp_path / "longitudinal-complete" / "RUN_STATUS.json").read_text()
    )
    assert status["phase"] == "longitudinal"
    assert status["symmetric_smoke_passed"] is False
    assert status["longitudinal_run_authorized"] is True
    assert status["longitudinal_run_completed"] is True
    assert status["smoke_qualification_consumed"] is True
    assert status["completed_paired_admitted_chapters"] == list(range(2, 11))
    assert status["trajectories"]["baseline"]["aggregate"][
        "degradation_slope"
    ] == 0.0
    assert "Chapter-10 degradation index" in (
        tmp_path / "longitudinal-complete" / "RESULT.md"
    ).read_text()


def test_longitudinal_qualification_rehashes_smoke_call_artifacts(tmp_path):
    smoke_runner, _ = make_runner(tmp_path, V2FakeAsk(), output_name="smoke")
    assert smoke_runner.run().status == "symmetric_smoke_passed"
    first_call = tmp_path / "smoke" / "evidence" / "calls" / "call_000001.json"
    first_call.write_bytes(first_call.read_bytes() + b"tampered")
    candidate, _ = make_runner(
        tmp_path,
        V2FakeAsk(),
        chapters=3,
        output_name="longitudinal",
        smoke_qualification_file=tmp_path / "smoke" / "RUN_STATUS.json",
        boundary_override=expanded_longitudinal_boundary(),
    )

    with pytest.raises(RuntimeError, match="call evidence changed"):
        candidate.run()
    assert not (tmp_path / "longitudinal").exists()


def test_longitudinal_rejection_preserves_paired_survivor_trajectory(tmp_path):
    smoke_runner, _ = make_runner(tmp_path, V2FakeAsk(), output_name="smoke")
    assert smoke_runner.run().status == "symmetric_smoke_passed"
    fake = V2FakeAsk(reject_kingdom_chapter=3)
    runner, _ = make_runner(
        tmp_path,
        fake,
        chapters=3,
        output_name="longitudinal",
        smoke_qualification_file=tmp_path / "smoke" / "RUN_STATUS.json",
        boundary_override=expanded_longitudinal_boundary(),
    )

    outcome = runner.run()

    assert outcome.status == "longitudinal_branch_rejected"
    assert outcome.chapter == 3
    assert outcome.condition == "kingdom"
    assert len(fake.calls) == 17
    status = json.loads((tmp_path / "longitudinal" / "RUN_STATUS.json").read_text())
    assert status["phase"] == "longitudinal"
    assert status["longitudinal_run_authorized"] is True
    assert status["longitudinal_run_completed"] is False
    assert status["completed_paired_admitted_chapters"] == [2]
    assert status["condition_terminal_status"]["baseline"] == {
        "terminal_status": "right_censored_after_admission_due_symmetric_stop",
        "admitted_through_chapter": 3,
        "first_rejection_chapter": None,
    }
    assert status["condition_terminal_status"]["kingdom"] == {
        "terminal_status": "rejected",
        "admitted_through_chapter": 2,
        "first_rejection_chapter": 3,
    }
    assert status["paired_survivor_trajectories"]["baseline"]["aggregate"][
        "degradation_slope"
    ] is None
    assert not (tmp_path / "longitudinal" / "RESULT.md").exists()


def test_manifest_freezes_exact_protocol_configuration(tmp_path):
    fake = V2FakeAsk(reject_baseline_prose=True)
    runner, boundary = make_runner(tmp_path, fake)

    runner.run()

    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["protocol_id"] == PROTOCOL_V2_ID
    assert manifest["source_revision"] == "b" * 40
    assert manifest["story_map_sha256"] == boundary.source_map_sha256
    assert manifest["model"] == PROTOCOL_V2_MODEL
    assert manifest["model_digest"] == PROTOCOL_V2_MODEL_DIGEST
    assert set(manifest["source_file_sha256"]) == set(
        PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS
    )
    assert manifest["frozen_v1_evidence_verified"]
    assert manifest["condition_order"] == ["baseline", "kingdom"]
    assert manifest["generation_calls_per_chapter_per_condition"] == 3
    assert manifest["expected_chapter_two_smoke_physical_calls_if_admitted"] == 10
    assert manifest["pairwise_preference_calls"] == 0
    assert manifest["stop_on_first_branch_rejection"] is True
    assert manifest["guard_repair_calls"] == 0
    assert manifest["prompt_template_sha256"] == dict(
        PROTOCOL_V2_FROZEN_PROMPT_SHA256
    )
    unhashed = dict(manifest)
    stored = unhashed.pop("manifest_payload_sha256")
    canonical = json.dumps(
        unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert stored == __import__("hashlib").sha256(canonical.encode()).hexdigest()


def test_documented_cli_wires_exact_frozen_configuration_without_real_model(
    tmp_path, monkeypatch
):
    fake = V2FakeAsk()
    actual_output_argument = REPO_ROOT / PROTOCOL_V2_SMOKE_RELATIVE_OUTPUT
    isolated_output = tmp_path / "cli-smoke"

    def canonical_output(repo_root, output_dir, *, chapters):
        assert repo_root == REPO_ROOT
        assert output_dir.resolve() == actual_output_argument.resolve()
        assert chapters == 2
        return isolated_output

    monkeypatch.setattr(v2_module, "_require_canonical_cli_output", canonical_output)
    monkeypatch.setattr(
        v2_module,
        "_git_revision_and_clean",
        lambda root, paths: (
            "b" * 40,
            {
                relative: "c" * 64
                for relative in PROTOCOL_V2_REQUIRED_SOURCE_BINDINGS
            },
        ),
    )
    monkeypatch.setattr(
        v2_module,
        "verify_frozen_v1_evidence",
        lambda *args, **kwargs: {"sealed": {"bytes": 1, "sha256": "d" * 64}},
    )
    monkeypatch.setattr(
        v2_module,
        "_ollama_model_digest",
        lambda *args, **kwargs: PROTOCOL_V2_MODEL_DIGEST,
    )
    monkeypatch.setattr(hive_llm, "ask_hive", fake)

    exit_code = v2_module.main(
        [
            "--seed-file",
            str(BENCHMARK_DIR / "SEED.md"),
            "--benchmark-file",
            str(BENCHMARK_DIR / "CONTRACT.md"),
            "--story-map-file",
            str(BENCHMARK_DIR / "STORY_MAP.json"),
            "--protocol-file",
            str(BENCHMARK_DIR / "PROTOCOL_V2.md"),
            "--output-dir",
            str(actual_output_argument),
            "--chapters",
            "2",
            "--model",
            PROTOCOL_V2_MODEL,
        ]
    )

    assert exit_code == 0
    assert len(fake.calls) == 10
    assert (isolated_output / "RUN_STATUS.json").is_file()
    assert (isolated_output / "RESULT.md").is_file()
