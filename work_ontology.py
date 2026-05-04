WORK_MODES = {
    "observe",
    "research",
    "repair",
    "modify",
    "create",
    "integrate",
    "refactor",
    "validate",
    "document",
    "configure",
}

DOMAINS = {
    "code",
    "math",
    "business",
    "writing",
    "science",
    "personal",
    "general",
}

TASK_TYPE_MODE_DEFAULTS = {
    "bugfix": "repair",
    "feature": "create",
    "refactor": "refactor",
    "validation": "validate",
    "docs": "document",
    "architecture": "modify",
    "state": "modify",
    "routing": "modify",
    "math_exploration": "research",
    "math_conjecture": "research",
    "math_symbolic": "research",
    "math_adversarial": "research",
    "math_formal": "research",
    "math_strategic": "research",
    "code_hypothesis": "research",
    "code_adversarial": "validate",
    "code_benchmark": "validate",
    "code_formal": "validate",
    "code_invariant": "validate",
    "code_regression": "validate",
}

FILE_LEVEL_WORK_MODES = {
    "observe",
    "research",
    "create",
    "validate",
    "document",
    "configure",
}

MODE_DEFINITIONS = {
    "observe": "look without changing",
    "research": "reduce uncertainty before acting",
    "repair": "fix broken behavior or artifacts",
    "modify": "change existing behavior or artifacts",
    "create": "add a new artifact or capability",
    "integrate": "connect existing pieces",
    "refactor": "preserve outcome while improving structure",
    "validate": "test, prove, or check claims",
    "document": "preserve understanding",
    "configure": "tune settings, defaults, or environment",
}


def normalize_work_mode(mode=None, task_type=None, text=""):
    value = str(mode or "").strip().lower()
    if not value:
        value = TASK_TYPE_MODE_DEFAULTS.get(str(task_type or "").strip(), "")
    if not value:
        value = infer_work_mode(text)
    if value not in WORK_MODES:
        raise ValueError(f"Unsupported work_mode: {value}")
    return value


def infer_work_mode(text):
    lowered = (text or "").lower()
    if any(token in lowered for token in ("observe", "look at", "inspect", "show ", "status")):
        return "observe"
    if any(token in lowered for token in ("research", "investigate", "uncertain", "figure out", "explore")):
        return "research"
    if any(token in lowered for token in ("fix", "bug", "broken", "failing", "regression", "repair")):
        return "repair"
    if any(token in lowered for token in ("create", "add ", "new ", "introduce", "draft", "build")):
        return "create"
    if any(token in lowered for token in ("integrate", "wire ", "connect", "hook up")):
        return "integrate"
    if "refactor" in lowered or "restructure" in lowered:
        return "refactor"
    if any(token in lowered for token in ("validate", "verify", "prove", "test ", "check whether")):
        return "validate"
    if any(token in lowered for token in ("document", "explain", "write docs", "preserve knowledge")):
        return "document"
    if any(token in lowered for token in ("configure", "setting", "default", "environment", "parameter")):
        return "configure"
    if any(token in lowered for token in ("change", "modify", "update", "revise")):
        return "modify"
    return "modify"


def infer_domain(text, target_file=None, task_type=None):
    lowered = (text or "").lower()
    type_text = str(task_type or "")
    if (
        target_file
        or type_text.startswith("code_")
        or ".py" in lowered
        or "code" in lowered
        or any(token in lowered for token in ("hive", "task backlog", "older tasks", "completed tasks"))
    ):
        return "code"
    if type_text.startswith("math_") or any(token in lowered for token in ("math", "proof", "prove", "conjecture", "theorem", "lemma")):
        return "math"
    if any(token in lowered for token in ("market", "offer", "customer", "business", "demand")):
        return "business"
    if any(token in lowered for token in ("draft", "essay", "article", "copy", "writing")):
        return "writing"
    if any(token in lowered for token in ("experiment", "hypothesis", "science", "measurement")):
        return "science"
    if any(token in lowered for token in ("habit", "schedule", "personal", "plan my")):
        return "personal"
    return "general"


def infer_artifact(text, domain=None):
    lowered = (text or "").lower()
    if any(token in lowered for token in ("task", "backlog", "completed", "older work", "old work")):
        return "task backlog"
    if any(token in lowered for token in ("gui", "ui", "window", "button", "switch", "toggle", "theme")):
        return "GUI capability"
    if domain == "math":
        return "mathematical claim"
    if domain == "business":
        return "business artifact"
    if domain == "writing":
        return "written artifact"
    return ""


def infer_operation(text, mode=None, artifact=None):
    lowered = (text or "").lower()
    if artifact == "task backlog" and any(token in lowered for token in ("clear", "archive", "remove", "prune")):
        return "clear stale task records"
    if mode == "create":
        return "add capability"
    if mode == "repair":
        return "fix broken behavior"
    if mode == "validate":
        return "check claim"
    return ""


def infer_validation(text, domain=None, artifact=None):
    if domain == "code":
        if artifact == "task backlog":
            return "route smoke test plus memory status check"
        return "AST parse plus focused smoke test"
    if domain == "math":
        return "proof, counterexample search, or formal check"
    return ""


def build_work_profile(task=None, plan=None, child=None):
    task = task or {}
    plan = plan or {}
    child = child or {}
    metadata = task.get("metadata") or {}
    target_file = child.get("target_file") or task.get("target_file") or metadata.get("target_file")
    task_type = child.get("task_type") or plan.get("task_type") or task.get("task_type") or metadata.get("task_type")
    text = " ".join(
        str(value or "")
        for value in (
            task.get("note"),
            plan.get("goal"),
            plan.get("next_action"),
            child.get("title"),
            child.get("description"),
        )
    )
    mode = normalize_work_mode(
        child.get("work_mode") or child.get("task_kind") or plan.get("work_mode") or plan.get("task_kind"),
        task_type=task_type,
        text=text,
    )
    domain = child.get("domain") or plan.get("domain") or infer_domain(text, target_file=target_file, task_type=task_type)
    artifact = child.get("artifact") or plan.get("artifact") or infer_artifact(text, domain=domain)
    operation = child.get("operation") or plan.get("operation") or infer_operation(text, mode=mode, artifact=artifact)
    return {
        "work_mode": mode,
        "domain": domain if domain in DOMAINS else "general",
        "artifact": artifact,
        "operation": operation,
        "validation": child.get("validation") or plan.get("validation") or infer_validation(text, domain=domain, artifact=artifact),
    }
