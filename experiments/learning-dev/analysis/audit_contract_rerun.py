"""Independently audit a downloaded contract-rerun artifact; never call a model."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.contract_rerun import BANK_SHA256, PRIOR_NUSD, contracts, describe, read_plan, schedule, sources
from analysis.indexed_checkpoint import indexed_tools
from analysis.lesson_checkpoint import CHECK_INSTRUCTION
from analysis.lesson_bank_v4 import total_spending
from analysis.public_contracts import PublicContractGate
from analysis.typed_actions import typed_action
from hive_learning.evaluate import candidate_snapshot, grade, strict_json
from hive_learning.ledger import canonical, digest
from hive_learning.lesson_study import compact, neutral_lesson


def read(path):
    return strict_json(path.read_bytes())


def audit(archive, archive_sha, run_id, launch_commit, destination):
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha.removeprefix("sha256:")
    extraction = archive.with_suffix("")
    extraction.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert len(names) == len(set(names)) and z.testzip() is None
        for info in z.infolist():
            path = Path(info.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert not stat.S_ISLNK(info.external_attr >> 16)
        z.extractall(extraction)
    raw = extraction/"hive-contract-evidence"
    checks = read(raw/"checksums.json")
    for name, sha in checks.items():
        path = Path(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert hashlib.sha256((raw/path).read_bytes()).hexdigest() == sha, name
    actual_files = {p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file()}
    assert actual_files == set(checks) | {"checksums.json"}
    plan, study, prior = read_plan()
    manifest, report, state = [read(raw/p) for p in ("manifest.json", "report.json", "study-state.json")]
    assert manifest["plan"] == plan and str(manifest["run_id"]) == str(run_id)
    assert manifest["commit"] == launch_commit
    assert manifest["source_hashes"] == sources()
    assert report["episode_id"] == digest(manifest)
    assert report["study_sha256"] == plan["study_sha256"]
    assert report["source_sha256"] == plan["source_sha256"] == digest(sources())
    assert report["continued_after"] == prior["episode_id"]
    assert report["study_state_sha256"] == hashlib.sha256((raw/"study-state.json").read_bytes()).hexdigest()
    expected = [{"case_id": c["id"], "arm": a} for c, a in schedule(study)]
    assert state["schedule"] == expected
    assert state["bank_sha256"] == BANK_SHA256 == digest(study["lessons"])
    assert [(r["case_id"], r["arm"]) for r in state["trials"]] == [
        (r["case_id"], r["arm"]) for r in expected[:len(state["trials"])]]
    assert state["assessment"] == report["assessment"] == describe(state, study)
    cloud_preflight = read(extraction/"hive-rerun-preflight.json")
    local_preflight = read(ROOT/plan["preflight"])
    for key in ("verified", "study_sha256", "runtime_sha256", "new_model_requests",
                "saved_bad_patches_rejected", "reference_regression_accepted"):
        assert cloud_preflight[key] == local_preflight[key]
    assert len(cloud_preflight["cases"]) == len(local_preflight["cases"]) == 15
    for cloud, local in zip(cloud_preflight["cases"], local_preflight["cases"]):
        assert cloud["case_id"] == local["case_id"] and cloud["contract_policy"] == local["contract_policy"]
        assert cloud["initial"]["valid"] and not cloud["initial"]["passed"]
        assert cloud["reference"]["valid"] and cloud["reference"]["passed"]
        assert cloud["reference_contract"] is None or cloud["reference_contract"]["accepted"]
    withheld = {p for c in study["cases"] for kind in ("acceptance_tests", "protected_tests") for p in c[kind]}
    carry, requests, input_tokens, output_tokens = PRIOR_NUSD, 0, 0, 0
    recipient_rows, checkpoints_checked, handoffs_checked, candidate_count = [], 0, 0, 0
    rows_by = {(r["case_id"], r["arm"]): r for r in state["trials"]}
    for index, account in enumerate(report["transport_usage"]):
        item = expected[index]
        label = item["case_id"] + "-" + item["arm"]
        assert account["recipient"] == label
        case = next(c for c in study["cases"] if c["id"] == item["case_id"])
        guidance = [] if item["arm"] == "baseline" else study["lessons"] if item["arm"] == "lesson" else [neutral_lesson(x) for x in study["lessons"]]
        memory = [{"id": f"memory_{i+1}", **x} for i, x in enumerate(guidance)]
        traces = [read(p) for p in sorted((raw/"transport"/label/"responses").glob("*.json"))]
        observed_checks, recipient_in, recipient_out = [], 0, 0
        for trace in traces:
            request, response = trace["request"], trace["response"]
            body = canonical(request)
            assert request["model"] == response["model"] == "gpt-5.6-luna"
            assert request["service_tier"] == response["service_tier"] == "default"
            assert request["store"] is False and request["max_output_tokens"] == 4096
            assert all(name not in body for name in withheld)
            recipient_in += response["usage"]["input_tokens"]
            recipient_out += response["usage"]["output_tokens"]
            if "tools" not in request:
                continue
            assert request["tools"] == indexed_tools(request["input"])
            assert request["tool_choice"] == "required" and request["parallel_tool_calls"] is False
            assert request["input"][1] == {"role": "system", "content": CHECK_INSTRUCTION + canonical(memory)}
            packet = json.loads(next(m["content"] for m in request["input"] if m["role"] == "user"))
            if "repair_handoff" in packet:
                handoff = packet["repair_handoff"]
                assert handoff["public_objective"] == case["goal"]
                assert handoff["context_scope"].startswith("The complete selected callable")
                declarations = contracts(case)
                if declarations:
                    policy = PublicContractGate(case["files"], declarations).policy
                    assert handoff["public_input_contracts"] == policy["contracts"]
                else:
                    assert "public_input_contracts" not in handoff
                handoffs_checked += 1
            try:
                if response.get("status") != "completed" or response.get("error") is not None:
                    continue
                action = json.loads(typed_action(response["output"], request["tools"]))
                check = action["arguments"]["memory_check"]
                valid = (check["memory_id"] in {m["id"] for m in memory} | {"none"}
                    and (check["applicability"] != "applies" or check["memory_id"] != "none")
                    and check["public_evidence"].strip() and check["expected_effect"].strip())
                if valid:
                    observed_checks.append({"action": action["name"], **check})
            except (ValueError, KeyError):
                pass
        checkpoints = read(raw/"transport"/label/"checkpoints.json")
        assert observed_checks == [{k: v for k, v in c.items() if k != "call"} for c in checkpoints]
        checkpoints_checked += len(checkpoints)
        spending = account["spending"]
        assert spending["prior_upper_nano_usd"] == carry
        assert spending["measured_usage_upper_nano_usd"] == recipient_in*500 + recipient_out*1800
        metered_calls = sum(m["calls"] for m in account["meters"])
        if spending["unresolved_reservation_nano_usd"]:
            assert 0 <= metered_calls-len(traces) <= 1
        else:
            assert len(traces) == metered_calls
        assert recipient_in == sum(m["prompt_tokens"] for m in account["meters"])
        assert recipient_out == sum(m["output_tokens"] for m in account["meters"])
        if not spending["unresolved_reservation_nano_usd"]:
            assert len(traces) == spending["requests_reserved"]
        journal = [strict_json(line) for line in (raw/"transport"/label/"spending.jsonl").read_text().splitlines()]
        assert journal[0]["event"] == "opened"
        assert {k: v for k, v in journal[-1].items() if k != "event"} == spending
        for line in journal:
            assert line["prior_upper_nano_usd"] == carry and line["total_upper_nano_usd"] <= 5_000_000_000
        carry = spending["total_upper_nano_usd"]
        requests += spending["requests_reserved"]
        input_tokens += recipient_in; output_tokens += recipient_out
        folder = raw/"recipients"/label
        if not (folder/"result.json").exists():
            assert (item["case_id"], item["arm"]) not in rows_by
            continue
        result = read(folder/"result.json")
        assert result["guidance_sha256"] == digest(guidance)
        row = rows_by.get((item["case_id"], item["arm"]))
        if row is not None:
            assert all(row[k] == v for k, v in compact(result).items())
            assert row["checkpoint_count"] == len(checkpoints)
        final_check = None
        public_check = None
        if result.get("candidate_sha256"):
            candidate = read(folder/"candidate.json")
            assert digest(candidate) == result["candidate_sha256"]
            assert candidate == result["candidate"] == candidate_snapshot(folder/"workspace", case["files"])
            for path, content in case["files"].items():
                if Path(path).name.startswith("test_"):
                    assert candidate[path] == content
            final_check = grade(candidate, case["protected_tests"])
            assert final_check["valid"] and final_check["passed"] == result["score"]["passed"]
            declarations = contracts(case)
            if declarations:
                gate = PublicContractGate(case["files"], declarations)
                public_check = gate.evaluate(candidate)
                assert result["controller"]["public_contract_policy_sha256"] == gate.policy_sha256
                if result["passed"]:
                    assert public_check["valid"] and public_check["accepted"]
            assert result["passed"] == bool(final_check["passed"] and result["controller"]["decision"] == "SATISFIED")
            candidate_count += 1
        else:
            assert not result["passed"]
        recipient_rows.append({**item, "passed": result["passed"], "controller_decision": result.get("controller", {}).get("decision"),
            "calls": result["usage"]["calls"], "input_tokens": recipient_in, "output_tokens": recipient_out,
            "upper_charge_nano_usd": spending["measured_usage_upper_nano_usd"],
            "outcome": result.get("outcome", "controller_result"), "failure_codes": result.get("failure_codes", []),
            "candidate_sha256": result.get("candidate_sha256"), "independent_rescore": final_check,
            "independent_public_check": public_check})
    assert carry == report["spending"]["total_upper_nano_usd"] <= 5_000_000_000
    assert total_spending(PRIOR_NUSD, [a["spending"] for a in report["transport_usage"]]) == report["spending"]
    assert requests == report["spending"]["requests_reserved"]
    assert input_tokens*500 + output_tokens*1800 == report["spending"]["measured_usage_upper_nano_usd"]
    if report["status"] == "COMPLETED":
        assert len(recipient_rows) == 45 and not report["http_errors"]
        assert report["spending"]["unresolved_reservation_nano_usd"] == 0
        assert state["assessment"]["verdict"] == "DESCRIPTIVE_ONLY"
    audit_result = {"verified": True, "scope": "Artifact integrity, assignments, accounting, guidance and independent rescoring; no general learning claim.",
        "workflow_url": f"https://github.com/BillyMixNix/Hive/actions/runs/{run_id}", "launch_commit": launch_commit,
        "archive_sha256": archive_sha.removeprefix("sha256:"), "artifact_files_verified": len(checks),
        "report_status": report["status"], "provider_requests": requests, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "candidates_independently_rescored": candidate_count,
        "checkpoints_verified": checkpoints_checked, "repair_handoffs_verified": handoffs_checked,
        "guidance_assignment_verified": True, "withheld_test_names_absent_from_requests": True,
        "visible_tests_preserved": True, "bank_sha256": BANK_SHA256,
        "prior_upper_nano_usd": PRIOR_NUSD, "permanent_earlier_unknown_usage_reservation_nano_usd": 532372800,
        "spending": report["spending"], "assessment": report["assessment"], "recipients": recipient_rows,
        "limitations": ["Reused synthetic tasks; gate built after earlier observed failures.",
            "One attempt per case and arm, fixed provider alias rather than a pinned weight snapshot.",
            "Input preservation checks supported values on observed synchronous public calls only.",
            "Absence of withheld test names is a scoped exposure check, not proof of all possible information isolation."]}
    destination.mkdir(exist_ok=False)
    for name in ("manifest.json", "report.json", "study-state.json", "accounting.json", "checksums.json"):
        shutil.copyfile(raw/name, destination/name)
    (destination/"audit.json").write_text(json.dumps(audit_result, indent=2)+"\n")
    return audit_result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path); p.add_argument("--sha256", required=True)
    p.add_argument("--run-id", required=True); p.add_argument("--launch-commit", required=True)
    p.add_argument("--destination", required=True, type=Path)
    a = p.parse_args()
    result = audit(a.archive, a.sha256, a.run_id, a.launch_commit, a.destination)
    print(json.dumps({k: v for k, v in result.items() if k not in ("recipients", "limitations")}, indent=2))
