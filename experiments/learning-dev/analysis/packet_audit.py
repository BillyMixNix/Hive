"""Independent offline rescore and packet/accounting audit of saved artifacts.

Checksums detect inconsistency, not malicious rewriting of the whole bundle.
An externally pinned plan digest is required. Never sends model requests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hive_learning.evaluate import grade, strict_json
from hive_learning.ledger import digest
from analysis.packet_spending import INPUT_NUSD, OUTPUT_NUSD
from analysis.indexed_checkpoint import indexed_tools


def require(ok, message):
    if not ok:
        raise ValueError(message)


def packet_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def audit(directory, plan_sha):
    directory = Path(directory)
    hashes = strict_json((directory/"checksums.json").read_bytes())
    files = {p.relative_to(directory).as_posix(): p for p in directory.rglob("*") if p.is_file() and p.name != "checksums.json"}
    require(set(files) == set(hashes), "artifact inventory differs")
    require(all(not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == hashes[n] for n, p in files.items()), "artifact bytes differ")
    require(hashlib.sha256((directory/"plan.json").read_bytes()).hexdigest() == plan_sha, "uncommitted plan")
    plan = strict_json((directory/"plan.json").read_bytes())
    study_path = ROOT/"examples/contract-rerun.json"
    require(hashlib.sha256(study_path.read_bytes()).hexdigest() == plan["study_sha256"], "study changed")
    study = strict_json(study_path.read_bytes())
    cases = {c["id"]: c for c in study["cases"]}
    report = strict_json((directory/"report.json").read_bytes())
    keys = [{"case_id": r["case_id"], "arm": r["arm"]} for r in report["rows"]]
    require(keys == plan["schedule"][:len(keys)], "missing, duplicated or reordered recipients")
    totals = {a: {"correct": 0, "false_completions": 0, "penalized_calls": 0} for a in ("raw", "lessons", "packet")}
    settled_charge = requests = 0
    for entry in report["rows"]:
        case, arm, row = cases[entry["case_id"]], entry["arm"], entry["result"]
        label = case["id"]+"-"+arm
        saved = strict_json((directory/"recipients"/label/"result.json").read_bytes())
        require(all(row.get(k) == v for k, v in saved.items()), "report/result mismatch")
        guidance = study["lessons"] if arm == "lessons" else []
        require(row["guidance_sha256"] == digest(guidance), "guidance differs")
        candidate = row.get("candidate")
        require(candidate is not None, "missing final candidate; audit cannot certify")
        require(set(candidate) == set(case["files"]), "candidate scope differs")
        require(all(candidate[p] == v for p, v in case["files"].items() if Path(p).name.startswith("test_")), "public tests changed")
        require(digest(candidate) == row["candidate_sha256"], "candidate hash differs")
        rescored = grade(candidate, case["protected_tests"])
        require(rescored["valid"], "rescore invalid")
        satisfied = row["controller"]["decision"] == "SATISFIED"
        correct = rescored["passed"] and satisfied
        require(correct == row["passed"], "reported correctness differs")
        totals[arm]["correct"] += int(correct)
        totals[arm]["false_completions"] += int(satisfied and not rescored["passed"])
        totals[arm]["penalized_calls"] += row["usage"]["calls"] if correct else 36
        transport = directory/"transport"/label
        packets = [strict_json(line) for line in (transport/"packets.jsonl").read_text().splitlines()]
        traces = [strict_json(p.read_bytes()) for p in sorted((transport/"responses").glob("*.json"))]
        require(len(traces) == len(packets) == row["usage"]["calls"], "request/packet counts differ")
        inputs = outputs = 0
        for packet, trace in zip(packets, traces):
            state = packet["packet"]["state"]
            require(packet["condition"] == arm and state["objective"] == case["goal"], "wrong recipient packet")
            require(packet_digest(state) == packet["snapshot_sha256"] == packet["packet"]["snapshot_sha256"], "packet binding differs")
            require(set(state["files"]) == set(case["files"]), "packet file scope differs")
            messages = trace["request"]["input"]
            require(packet_digest(messages) == packet["output_messages_sha256"], "captured input differs")
            first = strict_json(next(m["content"] for m in messages if m["role"] == "user"))
            require(strict_json(first["hive_state_context"]) == packet["packet"], "supplied packet differs")
            tools = indexed_tools(messages)
            require(packet_digest(tools) == packet["tools_sha256"] and trace["request"]["tools"] == tools, "tool schema differs")
            require(trace["response"]["model"] == plan["model"] and trace["response"]["service_tier"] == "default", "model or tier differs")
            hidden_names = set(case["protected_tests"]) | set(case["acceptance_tests"])
            require(not any(name in json.dumps(messages) for name in hidden_names), "withheld filename in request")
            usage = trace["response"]["usage"]
            require(all(type(usage[k]) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")), "invalid usage")
            inputs += usage["input_tokens"]
            outputs += usage["output_tokens"]
            requests += 1
        require(inputs == row["usage"]["prompt_tokens"] and outputs == row["usage"]["output_tokens"], "token totals differ")
        settled_charge += inputs*INPUT_NUSD + outputs*OUTPUT_NUSD
    spending = report["spending"]
    require(spending is not None and spending["prior_upper_nano_usd"] == 0, "new-budget ledger missing")
    journal = [strict_json(line) for line in (directory/"spending.jsonl").read_text().splitlines()]
    require(journal[-1]["total_upper_nano_usd"] == spending["total_upper_nano_usd"], "ledger/report differs")
    require(spending["total_upper_nano_usd"] <= 5_000_000_000, "budget exceeded")
    complete = report["status"] == "COMPLETED" and keys == plan["schedule"]
    if complete:
        require(spending["unresolved_reservation_nano_usd"] == 0 and spending["requests_reserved"] == requests, "unreconciled requests")
        require(spending["measured_usage_upper_nano_usd"] == settled_charge, "charge mismatch")
    return {"verdict": "AUDITED_DESCRIPTIVE" if complete else "INCOMPLETE_NOT_CERTIFIED", "recipients": len(keys), "totals": totals,
            "limits": "No new-task inference, semantic-compression or interruption claim. Filename checks are not proof of complete isolation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory, args.plan_sha256), indent=2))
