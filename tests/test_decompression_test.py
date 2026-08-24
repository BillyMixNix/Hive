from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

import kingdom.decompression_test as dt


ROOT = Path(__file__).resolve().parents[1]
CASE_PACK = ROOT / "benchmarks" / "decompression_test" / "CASE_PACK.json"


@pytest.fixture(scope="module")
def pack():
    return dt.load_case_pack(CASE_PACK)


def test_pack_is_twenty_balanced_cases_with_two_load_contrasts(pack):
    payload, cases = pack
    assert len(cases) == 20
    assert Counter(case.family for case in cases) == Counter(
        {
            "temporal_authority": 4,
            "containment": 4,
            "transformation": 4,
            "economics_obligations": 4,
            "intent_knowledge": 4,
        }
    )
    assert Counter(case.correct_choice for case in cases) == Counter(
        {"A": 5, "B": 5, "C": 5, "D": 5}
    )
    for family in {case.family for case in cases}:
        selected = {case.load: case for case in cases if case.family == family}
        assert selected["distractor_low"].support_depth == 3
        assert selected["distractor_high"].support_depth == 3
        assert selected["distractor_low"].event_count == 8
        assert selected["distractor_high"].event_count == 32
        assert selected["support_low"].event_count == 20
        assert selected["support_high"].event_count == 20
        assert selected["support_low"].support_depth == 2
        assert selected["support_high"].support_depth == 5
    assert len(payload["batches"]) == 6


def test_fixture_and_independent_replay_answers_agree_for_all_cases(pack):
    _, cases = pack
    for case in cases:
        assert dt._answer_from_replay(case) == case.options[case.correct_choice]


def test_compact_codec_is_query_blind_reversible_and_byte_smaller(pack):
    _, cases = pack
    for case in cases:
        compact = dt.compressed_packet(case)
        rendered = dt._canonical_json(compact)
        assert case.question not in rendered
        assert '"answer"' not in rendered
        assert '"gold"' not in rendered
        assert len(rendered.encode()) < len(
            dt._canonical_json(dt.raw_packet(case)).encode()
        )
        refs = {record[0] for record in compact["records"]}
        assert set(case.required_event_refs) <= refs
        decoded = tuple(
            dt._event_from_compact(record)
            for record in compact["records"]
        )
        assert dt.replay_events(decoded, through_time=case.query_time).state == (
            dt.replay_events(case.events, through_time=case.query_time).state
        )


def test_all_opaque_refs_resolve_to_exact_hashed_raw_events(pack):
    _, cases = pack
    for case in cases:
        stats = dt._representation_stats(case)
        assert set(stats["raw_source_index"]) == {
            event.event_id for event in case.events
        }
        assert all(
            len(digest) == 64
            and set(digest) <= set("0123456789abcdef")
            for digest in stats["raw_source_index"].values()
        )


def test_retrieval_is_deterministic_bounded_and_query_conditioned(pack):
    _, cases = pack
    for case in cases:
        first = dt.retrieval_packet(case)
        second = dt.retrieval_packet(case)
        assert first == second
        assert len(dt._canonical_json(first).encode()) <= min(
            len(dt._canonical_json(dt.raw_packet(case)).encode()),
            4 * len(dt._canonical_json(dt.compressed_packet(case)).encode()),
        )
        assert 1 <= len(first["chunks"]) < len(case.events)
        selected = {chunk["event_id"] for chunk in first["chunks"]}
        assert set(case.required_event_refs) | set(case.rejected_event_refs) <= selected


def test_six_batches_fully_counterbalance_position(pack):
    payload, _ = pack
    positions = {condition: Counter() for condition in dt.CONDITIONS}
    for batch in payload["batches"]:
        for position, condition in enumerate(batch["condition_order"]):
            positions[condition][position] += 1
    assert all(value == Counter({0: 2, 1: 2, 2: 2}) for value in positions.values())


def test_every_indispensable_ablation_changes_state_and_control_does_not(pack):
    payload, cases = pack
    by_case = {case.case_id: case for case in cases}
    for case_id in payload["ablation"]["essential_case_ids"]:
        case = by_case[case_id]
        original = dt.replay_events(case.events, through_time=case.query_time).state
        removed = dt.replay_events(
            dt._without_last_effect(case.events, case.ablation_event_id),
            through_time=case.query_time,
        ).state
        assert removed != original
        counterfactual = dt._answer_from_replay(
            replace(
                case,
                events=dt._without_last_effect(case.events, case.ablation_event_id),
            )
        )
        assert counterfactual != dt._answer_from_replay(case)
        assert counterfactual in case.options.values()
    for control_id in payload["ablation"]["control_case_ids"]:
        control = by_case[control_id]
        assert dt.replay_events(
            dt._without_last_effect(
                control.events, control.control_ablation_event_id
            ),
            through_time=control.query_time,
        ).state == dt.replay_events(
            control.events, through_time=control.query_time
        ).state


def _valid_response(cases):
    answers = []
    for case in cases:
        by_id = {event.event_id: event for event in case.events}
        refs = set(case.required_event_refs) | set(case.rejected_event_refs)
        ordered = sorted(
            refs,
            key=lambda ref: (
                by_id[ref].effective_time,
                by_id[ref].record_time,
                by_id[ref].event_id,
            ),
        )
        answers.append(
            {
                "case_id": case.case_id,
                "answer_choice": case.correct_choice,
                "ordered_event_refs": ordered,
                "rejected_event_refs": list(case.rejected_event_refs),
                "selected_current_claim_ids": list(case.current_claim_ids),
                "reasoning_code": case.reasoning_code,
            }
        )
    return json.dumps({"schema_version": 1, "answers": answers})


def test_strict_parser_accepts_exact_contract(pack):
    _, cases = pack
    selected = cases[:4]
    parsed = dt.parse_model_output(
        _valid_response(selected), [case.case_id for case in selected]
    )
    assert len(parsed) == 4
    assert parsed[0].case_id == selected[0].case_id


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        '{"schema_version":1,"answers":[]} trailing',
        '{"schema_version":1,"schema_version":1,"answers":[]}',
        '{"schema_version":1,"answers":[],"unknown":true}',
        "{",
    ],
)
def test_malformed_duplicate_unknown_or_trailing_output_fails_closed(raw):
    with pytest.raises(dt.ModelOutputRejected):
        dt.parse_model_output(raw, [])


def test_unknown_answer_field_and_oversized_lists_fail_closed(pack):
    _, cases = pack
    payload = json.loads(_valid_response(cases[:1]))
    payload["answers"][0]["unknown"] = 1
    with pytest.raises(dt.ModelOutputRejected, match="unknown"):
        dt.parse_model_output(json.dumps(payload), [cases[0].case_id])
    payload = json.loads(_valid_response(cases[:1]))
    payload["answers"][0]["ordered_event_refs"] = [f"e{i}" for i in range(17)]
    with pytest.raises(dt.ModelOutputRejected, match="bounds"):
        dt.parse_model_output(json.dumps(payload), [cases[0].case_id])


def test_valid_answer_passes_conjunctive_grade(pack):
    _, cases = pack
    case = cases[0]
    answer = dt.parse_model_output(_valid_response([case]), [case.case_id])[0]
    score = dt.grade_answer(case, answer, condition="compressed")
    assert score.primary_pass
    assert score.illegal_state_promotions == 0
    assert score.required_ref_recall == 1.0


def test_planned_claim_promotion_fails_even_with_correct_option(pack):
    _, cases = pack
    case = cases[0]
    payload = json.loads(_valid_response([case]))
    illegal = next(claim for claim in case.claims if claim.truth_class == "planned")
    payload["answers"][0]["selected_current_claim_ids"] = [illegal.claim_id]
    answer = dt.parse_model_output(json.dumps(payload), [case.case_id])[0]
    score = dt.grade_answer(case, answer, condition="compressed")
    assert not score.primary_pass
    assert score.illegal_state_promotions == 1
    assert "illegal_state_promotion" in score.failure_reasons


def test_future_and_plan_events_never_enter_replayed_current_state(pack):
    _, cases = pack
    for case in cases:
        replayed = dt.replay_events(case.events, through_time=case.query_time)
        by_id = {event.event_id: event for event in case.events}
        assert all(
            by_id[event_id].authority == "canonical"
            and by_id[event_id].status == "completed"
            and by_id[event_id].effective_time <= case.query_time
            for event_id in replayed.applied_event_ids
        )


def test_batch_prompts_share_solver_contract_and_compressed_is_under_sixty_percent(pack):
    payload, cases = pack
    by_case = {case.case_id: case for case in cases}
    ratios = []
    for batch in payload["batches"]:
        selected = [by_case[case_id] for case_id in batch["case_ids"]]
        raw = dt.build_solver_prompt(selected, "raw")
        compressed = dt.build_solver_prompt(selected, "compressed")
        retrieval = dt.build_solver_prompt(selected, "retrieval")
        assert raw.startswith(dt.SOLVER_PROMPT_PREFIX)
        assert compressed.startswith(dt.SOLVER_PROMPT_PREFIX)
        assert retrieval.startswith(dt.SOLVER_PROMPT_PREFIX)
        ratios.append(len(compressed.encode()) / len(raw.encode()))
    assert max(ratios) < 0.60


def test_solver_prompt_fully_specifies_codes_refs_and_unknown_atom_semantics():
    for code in dt.REASONING_CODES:
        assert code in dt.SOLVER_PROMPT_PREFIX
    assert "every causal prerequisite ref" in dt.SOLVER_PROMPT_PREFIX
    assert "every relevant planned" in dt.SOLVER_PROMPT_PREFIX
    assert '["?",key,null]' in dt.SOLVER_PROMPT_PREFIX


def test_equal_effective_time_order_is_not_decided_by_record_arrival(pack):
    _, cases = pack
    case = next(case for case in cases if case.case_id == "DT-TA-DL")
    payload = json.loads(_valid_response([case]))
    refs = payload["answers"][0]["ordered_event_refs"]
    by_id = {event.event_id: event for event in case.events}
    pair = next(
        (left, right)
        for index, left in enumerate(refs)
        for right in refs[index + 1 :]
        if by_id[left].effective_time == by_id[right].effective_time
    )
    left_index, right_index = refs.index(pair[0]), refs.index(pair[1])
    refs[left_index], refs[right_index] = refs[right_index], refs[left_index]
    answer = dt.parse_model_output(json.dumps(payload), [case.case_id])[0]
    assert dt.grade_answer(case, answer, condition="raw").primary_pass


def test_blinded_ablation_calls_never_expose_counterpart_worlds(pack):
    payload, cases = pack
    by_case = {case.case_id: case for case in cases}
    observed_roles = Counter()
    all_aliases = set()
    for call_plan in payload["ablation"]["counterbalanced_calls"]:
        entries = [
            (by_case[item["case_id"]], item["role"])
            for item in call_plan
        ]
        prompt, blinded = dt.build_ablation_prompt(entries)
        input_payload = json.loads(prompt.split("\nINPUT:\n", 1)[1])
        assert "evidence_complete" not in prompt
        assert "withheld_record_count" not in prompt
        assert "opaque_padding" not in prompt
        assert all(item["case_id"].startswith("AB-") for item in input_payload["cases"])
        assert len({case.case_id for _, case, _ in blinded}) == len(blinded) == 5
        assert Counter(role for _, _, role in blinded) in (
            Counter({"essential": 3, "control": 2}),
            Counter({"essential": 2, "control": 3}),
        )
        for payload_case, (alias, case, role) in zip(input_payload["cases"], blinded):
            assert payload_case["case_id"] == alias
            all_aliases.add(alias)
            observed_roles[(case.case_id, role)] += 1
            unknowns = [
                effect
                for record in payload_case["representation"]["records"]
                for effect in record[7]
                if effect[0] == "?"
            ]
            assert len(unknowns) == 1
    assert len(all_aliases) == 10
    assert all(count == 1 for count in observed_roles.values())
    assert len(observed_roles) == 10


def test_preflight_records_strong_retrieval_adequacy_and_full_task_projection(pack, tmp_path):
    payload, cases = pack
    runner = _runner(tmp_path, pack, PerfectFakeAsk(cases, payload))
    preflight = runner._preflight()
    assert preflight["task_reversibility_passed"]
    assert preflight["compression_loss_count"] == 0
    assert all(
        item["retrieval_relevant_ref_recall"] == 1.0
        and item["compressed_task_replay_match"]
        and item["raw_source_hashes_recomputed"]
        for item in preflight["representation_stats"]
    )


class PerfectFakeAsk:
    def __init__(self, cases, payload, *, malformed_condition=None, fail_call=None):
        self.by_case = {case.case_id: case for case in cases}
        self.ablation_aliases = {
            dt._ablation_alias(case_id, role): (self.by_case[case_id], role)
            for case_id in payload["ablation"]["essential_case_ids"]
            for role in ("essential", "control")
        }
        self.malformed_condition = malformed_condition
        self.fail_call = fail_call
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        call_number = len(self.calls)
        metadata = kwargs["metadata"]
        metadata.update(
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": max(1, len(prompt) // 4),
                "eval_count": 200,
                "total_duration_ns": 1_000_000,
            }
        )
        if self.fail_call == call_number:
            metadata.update({"done": False, "done_reason": "transport_error"})
            raise TimeoutError("one preserved physical failure")
        marker = "\nINPUT:\n"
        input_payload = json.loads(prompt.split(marker, 1)[1])
        condition = input_payload["condition_representation"]
        if condition == self.malformed_condition:
            return "```json\ntruncated"
        selected = [
            self.by_case[item["case_id"]]
            for item in input_payload["cases"]
        ] if condition != "compressed_ablation" else []
        if condition != "compressed_ablation":
            return _valid_response(selected)
        answers = []
        for item in input_payload["cases"]:
            alias = item["case_id"]
            case, role = self.ablation_aliases[alias]
            if role == "essential":
                answers.append(
                    {
                        "case_id": alias,
                        "answer_choice": "INSUFFICIENT",
                        "ordered_event_refs": [],
                        "rejected_event_refs": [],
                        "selected_current_claim_ids": [],
                        "reasoning_code": "INSUFFICIENT_EVIDENCE",
                    }
                )
            else:
                normal = json.loads(_valid_response([case]))["answers"][0]
                normal["case_id"] = alias
                answers.append(normal)
        return json.dumps({"schema_version": 1, "answers": answers})


def _runner(tmp_path, pack, fake):
    payload, cases = pack
    return dt.DecompressionSmokeRunner(
        repo_root=ROOT,
        output_dir=tmp_path / "smoke",
        case_pack_payload=payload,
        cases=cases,
        source_revision="a" * 40,
        source_file_sha256={path: "b" * 64 for path in dt.CRITICAL_SOURCE_FILES},
        model_digest=dt.MODEL_DIGEST,
        ask_fn=fake,
    )


def test_full_fake_smoke_is_20_calls_valid_supported_and_immutable(tmp_path, pack):
    payload, cases = pack
    fake = PerfectFakeAsk(cases, payload)
    result = _runner(tmp_path, pack, fake).run()
    output = tmp_path / "smoke"
    assert result["validity"] == "VALID"
    assert result["hypothesis_result"] == "SUPPORTED"
    assert result["evidence_level"] == "SUPPORTED"
    assert len(fake.calls) == 20
    assert len(list((output / "evidence" / "calls").glob("call_*.json"))) == 20
    assert len(list((output / "decisions").glob("decision_*.json"))) == 20
    status = json.loads((output / "RUN_STATUS.json").read_text(encoding="utf-8"))
    assert status["validity"] == "VALID"
    assert status["call_count"] == 20
    assert result["condition_summaries"]["compressed"]["primary_passes"] == 20
    assert result["ablation"]["essential_detected"] == 5
    assert result["ablation"]["control_passes"] == 5
    assert all(result["criteria"].values())
    assert result["usage"]["median_compressed_to_retrieval_prompt_token_ratio"] <= 1.0
    assert result["evidence_qualification"][
        "all_runtime_prompt_response_journal_decision_links_verified"
    ]
    with pytest.raises(FileExistsError):
        _runner(tmp_path, pack, PerfectFakeAsk(cases, payload)).run()


def test_malformed_model_batch_is_preserved_fail_closed_but_smoke_remains_valid(
    tmp_path, pack
):
    payload, cases = pack
    fake = PerfectFakeAsk(cases, payload, malformed_condition="retrieval")
    result = _runner(tmp_path, pack, fake).run()
    assert result["validity"] == "VALID"
    assert result["condition_summaries"]["retrieval"]["primary_passes"] == 0
    assert result["hypothesis_result"] == "SUPPORTED"
    decisions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "smoke" / "decisions").glob("*.json"))
    ]
    assert sum(item["status"] == "model_output_rejected" for item in decisions) == 6


def test_negative_has_no_plausible_rescue_label(tmp_path, pack):
    payload, cases = pack
    result = _runner(
        tmp_path, pack, PerfectFakeAsk(cases, payload, malformed_condition="compressed")
    ).run()
    assert result["validity"] == "VALID"
    assert result["hypothesis_result"] == "NOT_SUPPORTED"
    assert result["evidence_level"] == "SPECULATIVE"
    assert result["condition_summaries"]["compressed"]["primary_passes"] == 0
    assert not all(result["criteria"].values())


def test_transport_failure_stops_and_marks_smoke_invalid_without_repair(tmp_path, pack):
    payload, cases = pack
    fake = PerfectFakeAsk(cases, payload, fail_call=2)
    with pytest.raises(TimeoutError, match="preserved"):
        _runner(tmp_path, pack, fake).run()
    assert len(fake.calls) == 2
    status = json.loads(
        (tmp_path / "smoke" / "RUN_STATUS.json").read_text(encoding="utf-8")
    )
    assert status["validity"] == "INVALID"
    assert status["call_count"] == 2
    result = json.loads(
        (tmp_path / "smoke" / "RESULT.json").read_text(encoding="utf-8")
    )
    assert result["hypothesis_result"] == "INCONCLUSIVE_INVALID_SMOKE"


def test_frozen_runtime_and_call_budget_are_exact(tmp_path, pack):
    payload, cases = pack
    fake = PerfectFakeAsk(cases, payload)
    _runner(tmp_path, pack, fake).run()
    assert len(fake.calls) == 20
    for call in fake.calls:
        assert call["model"] == dt.MODEL
        assert call["timeout"] == 900
        assert call["max_retries"] == 1
        assert call["options"] == {
            "num_ctx": 32768,
            "num_predict": 2048,
            "temperature": 0.0,
            "seed": 73021,
        }


def test_postflight_tamper_is_detected_and_terminal_is_invalid(tmp_path, pack):
    payload, cases = pack

    class TamperingRunner(dt.DecompressionSmokeRunner):
        def _verify_evidence(self, preflight):
            path = self.audit.calls_dir / "call_000001.json"
            path.write_bytes(path.read_bytes() + b" ")
            return super()._verify_evidence(preflight)

    fake = PerfectFakeAsk(cases, payload)
    runner = TamperingRunner(
        repo_root=ROOT,
        output_dir=tmp_path / "smoke",
        case_pack_payload=payload,
        cases=cases,
        source_revision="a" * 40,
        source_file_sha256={path: "b" * 64 for path in dt.CRITICAL_SOURCE_FILES},
        model_digest=dt.MODEL_DIGEST,
        ask_fn=fake,
    )
    with pytest.raises(RuntimeError, match="file hash mismatch"):
        runner.run()
    status = json.loads(
        (tmp_path / "smoke" / "RUN_STATUS.json").read_text(encoding="utf-8")
    )
    assert status["validity"] == "INVALID"


def test_preflight_failure_leaves_terminal_invalid_evidence(tmp_path, pack):
    payload, cases = pack
    broken = json.loads(json.dumps(payload))
    broken["batches"][0]["condition_order"] = ["raw", "raw", "compressed"]
    runner = dt.DecompressionSmokeRunner(
        repo_root=ROOT,
        output_dir=tmp_path / "smoke",
        case_pack_payload=broken,
        cases=cases,
        source_revision="a" * 40,
        source_file_sha256={path: "b" * 64 for path in dt.CRITICAL_SOURCE_FILES},
        model_digest=dt.MODEL_DIGEST,
        ask_fn=PerfectFakeAsk(cases, payload),
    )
    with pytest.raises(dt.CasePackError):
        runner.run()
    status = json.loads(
        (tmp_path / "smoke" / "RUN_STATUS.json").read_text(encoding="utf-8")
    )
    assert status["validity"] == "INVALID"
    assert status["call_count"] == 0


def test_git_source_binding_rejects_modified_critical_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    for relative in dt.CRITICAL_SOURCE_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"frozen {relative}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    revision, sources = dt._git_revision_and_sources(repo)
    assert len(revision) == 40
    assert set(sources) == set(dt.CRITICAL_SOURCE_FILES)
    changed = repo / dt.CRITICAL_SOURCE_FILES[0]
    changed.write_text("modified\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="tracked or staged"):
        dt._git_revision_and_sources(repo)


def test_documented_cli_wiring_is_fixed_and_requires_acknowledgement(monkeypatch, pack):
    with pytest.raises(SystemExit, match="acknowledge"):
        dt.main([])
    payload, cases = pack
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(dt, "_git_revision_and_sources", lambda root: ("a" * 40, {path: "b" * 64 for path in dt.CRITICAL_SOURCE_FILES}))
    monkeypatch.setattr(dt, "load_case_pack", lambda path: (payload, cases))
    monkeypatch.setattr(dt, "_ollama_model_digest", lambda *args, **kwargs: dt.MODEL_DIGEST)
    monkeypatch.setattr(dt, "DecompressionSmokeRunner", FakeRunner)
    assert dt.main(["--acknowledge-frozen-smoke"]) == 0
    assert captured["ran"]
    assert captured["model_digest"] == dt.MODEL_DIGEST
