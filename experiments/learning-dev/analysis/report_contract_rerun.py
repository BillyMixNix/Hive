"""Summarize the independently audited repeat; no inferential learning verdict."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hive_learning.lesson_study import ARMS


def summarize(directory, raw):
    audit = json.loads((directory/"audit.json").read_text())
    study = json.loads((ROOT/"examples/contract-rerun.json").read_text())
    cases = {c["id"]: c for c in study["cases"]}
    rows = audit["recipients"]
    arms = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        transfer = [r for r in selected if cases[r["case_id"]]["split"] == "confirmation"]
        retention = [r for r in selected if cases[r["case_id"]]["split"] == "retention"]
        arms[arm] = {
            "transfer_correct": sum(r["passed"] for r in transfer), "transfer_completed": len(transfer),
            "retention_correct": sum(r["passed"] for r in retention), "retention_completed": len(retention),
            "transfer_calls": sum(r["calls"] for r in transfer),
            "transfer_penalized_calls": sum(r["calls"] if r["passed"] else 36 for r in transfer),
            "retention_calls": sum(r["calls"] for r in retention),
            "all_calls": sum(r["calls"] for r in selected),
            "input_tokens": sum(r["input_tokens"] for r in selected),
            "output_tokens": sum(r["output_tokens"] for r in selected),
            "charge_upper_nano_usd": sum(r["upper_charge_nano_usd"] for r in selected),
            "false_completions": sum(r["controller_decision"] == "SATISFIED" and not r["passed"] for r in selected)}
    gate_observations = []
    for row in rows:
        workspace = raw/"recipients"/(row["case_id"]+"-"+row["arm"])/"workspace"
        reports = []
        for path in workspace.rglob("trace.jsonl"):
            for line in path.read_text().splitlines():
                event = json.loads(line)
                if event.get("event") == "public_contract_checked":
                    reports.append(event)
        mutated = [r for r in reports if any(c["violations"] for c in r.get("checks", []))]
        if mutated:
            gate_observations.append({"case_id": row["case_id"], "arm": row["arm"],
                "recorded_mutation_checks": len(mutated),
                "distinct_mutating_candidate_hashes": sorted({r["candidate_sha256"] for r in mutated}),
                "controller_decision": row["controller_decision"], "final_passed": row["passed"]})
    previous = json.loads((ROOT/"results/checkpoint-retest-final/results.json").read_text())
    result = {"status": audit["report_status"], "assessment": audit["assessment"], "arms": arms,
        "provider_requests": audit["provider_requests"], "spending": audit["spending"],
        "recorded_input_mutation_observations": gate_observations,
        "previous_audited_followon": previous["followon_arms"],
        "workflow_url": audit["workflow_url"], "launch_commit": audit["launch_commit"],
        "bank_sha256": audit["bank_sha256"], "no_weight_training": True,
        "confirmatory_gain_claim_allowed": False}
    (directory/"results.json").write_text(json.dumps(result, indent=2)+"\n")
    with (directory/"task-results.csv").open("w", newline="") as f:
        fieldnames = ["case_id", "family", "split", "arm", "passed", "controller_decision", "calls",
                      "penalized_calls", "input_tokens", "output_tokens", "upper_charge_nano_usd",
                      "candidate_sha256", "outcome"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            case = cases[row["case_id"]]
            writer.writerow({**{k: row[k] for k in fieldnames if k in row},
                "family": case["family"], "split": case["split"],
                "penalized_calls": row["calls"] if row["passed"] else 36})
    spend = audit["spending"]
    text = ["# Hive input-contract rerun", "",
        f"Status: **{audit['report_status']}**. {len(rows)}/45 recipient results recorded; {audit['provider_requests']} provider requests.", "",
        "This reran the same 15 tasks and the same three retained model-generated lessons after the input-contract repair. The comparison is descriptive because the tasks were already evaluated and the repair used an observed failure.", "",
        "| Condition | Correct transfer repairs | Correct retention repairs | Transfer calls | Transfer calls with failure penalty | False completions | All calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    labels = {"baseline": "No lessons", "lesson": "Retained lessons", "neutral": "Neutral notes"}
    for arm, x in arms.items():
        text.append(f"| {labels[arm]} | {x['transfer_correct']}/{x['transfer_completed']} | {x['retention_correct']}/{x['retention_completed']} | {x['transfer_calls']} | {x['transfer_penalized_calls']} | {x['false_completions']} | {x['all_calls']} |")
    text += ["", "A false completion is a controller SATISFIED verdict that fails the independent final checks. Failed repairs receive a fixed 36-call effort penalty; finishing incorrectly or stopping early cannot earn an efficiency advantage.", ""]
    for control, x in audit["assessment"].get("comparisons", {}).items():
        text.append(f"Against {labels[control].lower()}, lessons used less penalized effort on {x['lesson_lower_effort']} transfer tasks, more on {x['lesson_higher_effort']}, and tied on {x['ties']}. The aggregate reduction was {100*x['relative_reduction']:.2f}% (negative means more effort).")
        text.append("")
    text += ["## Input check", "",
        "The controller used explicit argument-preservation declarations on eleven tasks, identically across conditions. Four tasks require consuming iterators and retained their original adapter. The public input checker does not inspect protected tests. All original acceptance tests remained in place; all cache tasks received the previously defined full-cache audit at final scoring only.", "",
        f"The saved controller traces recorded input mutations in {len(gate_observations)} recipients. These are reports from the checker on observed public-test calls, not a universal proof of input preservation.", ""]
    if gate_observations:
        text += ["| Task | Condition | Distinct mutation candidate hashes | Final decision | Final correct |",
                 "| --- | --- | ---: | --- | --- |"]
        for r in gate_observations:
            text.append(f"| {r['case_id'].removeprefix('checkpoint_')} | {labels[r['arm']]} | {len(r['distinct_mutating_candidate_hashes'])} | {r['controller_decision']} | {r['final_passed']} |")
        text.append("")
    text += ["## Spending", "",
        f"Prior cumulative bound: ${spend['prior_upper_nano_usd']/1e9:.7f}. Added measured-usage bound: ${spend['measured_usage_upper_nano_usd']/1e9:.7f}. New unresolved reservation: ${spend['unresolved_reservation_nano_usd']/1e9:.7f}. Cumulative bound: **${spend['total_upper_nano_usd']/1e9:.7f} of the original $5**.", "",
        "The cumulative bound retains the earlier $0.5323728 unknown-usage reservation. These are conservative token-charge bounds, not a provider invoice or the account's balance. The same full-context reservation was retained before every request; no retry or new authorization resets prior spending.", "",
        "| Condition | Input tokens | Output tokens | Added charge bound |",
        "| --- | ---: | ---: | ---: |"]
    for arm, x in arms.items():
        text.append(f"| {labels[arm]} | {x['input_tokens']} | {x['output_tokens']} | ${x['charge_upper_nano_usd']/1e9:.7f} |")
    text += ["", "Conservative rates remain 500 nanoUSD per input token and 1800 per output token, reverified on September 8 against [official OpenAI pricing](https://developers.openai.com/api/docs/pricing).", "",
        "## Evidence and limits", "",
        f"[Cloud run]({audit['workflow_url']}); launch commit `{audit['launch_commit']}`; retained-bank hash `{audit['bank_sha256']}`.", "",
        f"The independent audit verified {audit['artifact_files_verified']} artifact files, reconciled all charge records, checked the exact supplied guidance and tool schemas, and rescored {audit['candidates_independently_rescored']} saved final candidates. Original public tests remained unchanged. Original and supplemental private-test filenames were absent from captured requests; this is a scoped check, not a general proof of isolation.", "",
        "The same provider model alias was used once per task and condition. Model weights were not trained. There is no statistical confirmation, pooling with prior runs, task replacement, or evidence here of broad recursive self-improvement. The prior study remains unchanged and is reported separately.", ""]
    (directory/"RESULT.md").write_text("\n".join(text))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path); p.add_argument("--raw", required=True, type=Path)
    a = p.parse_args()
    result = summarize(a.directory, a.raw)
    print(json.dumps({k: v for k, v in result.items() if k not in ("previous_audited_followon",)}, indent=2))
