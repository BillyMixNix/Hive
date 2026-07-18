from pathlib import Path


path = Path("main.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "from failure_intelligence import interpret_failure\n",
    "from failure_intelligence import interpret_failure\n"
    "from validation.live_loop import (\n"
    "    deploy_approved_patch,\n"
    "    evaluate_patch_result,\n"
    "    rollback_approved_patch,\n"
    ")\n",
    "live loop imports",
)

replace_once(
    "                        result = router.coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)\n\n"
    "                        _store_code_task_result(\n",
    "                        result = router.coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)\n"
    "                        result = evaluate_patch_result(\n"
    "                            result,\n"
    "                            task_note=ready_child.get(\"description\") or task.get(\"note\") or \"\",\n"
    "                            repo_root=Path.cwd(),\n"
    "                            completion_cues=ready_child.get(\"completion_cues\") or [],\n"
    "                        )\n\n"
    "                        _store_code_task_result(\n",
    "code task empirical evaluation",
)

replace_once(
    "        meta = dict(meta)\n"
    "        meta[\"pilot_verdict\"] = \"accept\"\n",
    "        meta = dict(meta)\n"
    "        empirical = dict(meta.get(\"empirical_validation\") or {})\n"
    "        if empirical and empirical.get(\"decision\") != \"candidate\":\n"
    "            return f\"Patch {patch_id} did not pass empirical validation and cannot be accepted.\"\n"
    "        meta[\"pilot_verdict\"] = \"accept\"\n",
    "pilot candidate requirement",
)

replace_once(
    "            backup = router.executor.backup_file(target_file)\n"
    "            router.executor.apply_patch(patch_text, target_file, patch_reason=patch_reason, file_text=file_text)\n"
    "            memory.update_task_status(patch_id, \"applied\")\n",
    "            backup = router.executor.backup_file(target_file)\n"
    "            evaluation_id = meta.get(\"evaluation_id\") or (meta.get(\"empirical_validation\") or {}).get(\"evaluation_id\")\n"
    "            deployment = None\n"
    "            if evaluation_id:\n"
    "                deployment = deploy_approved_patch(meta, repo_root=Path.cwd())\n"
    "            else:\n"
    "                router.executor.apply_patch(patch_text, target_file, patch_reason=patch_reason, file_text=file_text)\n"
    "            memory.update_task_status(patch_id, \"applied\")\n",
    "gate deployment path",
)

replace_once(
    "                metadata={\"apply_id\": f\"apply-{patch_id}\", \"patch_id\": patch_id,\n"
    "                          \"task_id\": meta.get(\"task_id\"), \"plan_id\": meta.get(\"plan_id\"),\n"
    "                          \"target_file\": target_file, \"backup_path\": backup},\n",
    "                metadata={\"apply_id\": f\"apply-{patch_id}\", \"patch_id\": patch_id,\n"
    "                          \"task_id\": meta.get(\"task_id\"), \"plan_id\": meta.get(\"plan_id\"),\n"
    "                          \"target_file\": target_file, \"backup_path\": backup,\n"
    "                          \"evaluation_id\": evaluation_id,\n"
    "                          \"deployment_id\": (deployment or {}).get(\"deployment_id\")},\n",
    "deployment provenance storage",
)

replace_once(
    "            router.executor.restore_backup(backup_path, target_file)\n"
    "            memory.update_task_status(patch_id, \"rolled_back\")\n",
    "            evaluation_id = meta.get(\"evaluation_id\") or (meta.get(\"empirical_validation\") or {}).get(\"evaluation_id\")\n"
    "            if evaluation_id:\n"
    "                rollback_approved_patch(meta, repo_root=Path.cwd())\n"
    "            else:\n"
    "                router.executor.restore_backup(backup_path, target_file)\n"
    "            memory.update_task_status(patch_id, \"rolled_back\")\n",
    "gate rollback path",
)

path.write_text(text, encoding="utf-8")
