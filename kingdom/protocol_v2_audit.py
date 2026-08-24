"""Append-only physical-call evidence for ADI Benchmark Protocol v2.

The store deliberately has no resume mode.  A Protocol v2 experiment must point
at a directory which does not yet exist, so evidence from an earlier run can
never be extended or overwritten accidentally.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping


AUDIT_SCHEMA_VERSION = 1
DEFAULT_GENERATION_CALLS = 3
DEFAULT_OLLAMA_NUM_CTX = 32_768
DEFAULT_OLLAMA_NUM_PREDICT = 2_048
DEFAULT_OLLAMA_TEMPERATURE = 0.2
DEFAULT_OLLAMA_SEED = 42_001
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900


class BudgetExceeded(RuntimeError):
    """Raised before transport when a condition has spent its generation budget."""


class AuditInvariantError(RuntimeError):
    """Raised after preserving evidence when transport violates the audit contract."""


@dataclass(frozen=True)
class AuditCallRecord:
    """Small in-memory index for an immutable on-disk call artifact."""

    sequence: int
    call_id: str
    artifact_path: str
    artifact_file_sha256: str
    status: str
    condition: str
    chapter: int
    purpose: str
    role: str
    budget_class: str
    prompt_sha256: str
    response_sha256: str
    error_type: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_safe(value: Any) -> Any:
    """Make transport metadata durable without silently dropping unknown values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return {
        "python_type": f"{type(value).__module__}.{type(value).__qualname__}",
        "repr": repr(value),
    }


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _pretty_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, payload: bytes) -> None:
    """Create one file and fail rather than replace an existing artifact."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # os.fdopen owns the descriptor.  The partial file remains evidence that
        # artifact persistence itself failed; it must not be silently replaced.
        raise


def _error_payload(error: BaseException | None) -> Mapping[str, Any] | None:
    if error is None:
        return None
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
        "repr": repr(error),
        "traceback": rendered,
        "sha256": _sha256_text(rendered),
    }


class ProtocolV2AuditStore:
    """Budgeted model interface which preserves every physical request.

    ``ask_fn`` must implement Hive's model-call keyword interface.  In
    particular, it must honor ``max_retries=1`` and populate the supplied
    ``metadata`` mapping with ``physical_attempts``.  Successful calls must also
    report ``done`` and ``done_reason``.  Missing or contradictory metadata is
    treated as an audit failure after the complete raw response is persisted.
    """

    def __init__(
        self,
        ask_fn: Callable[..., str],
        audit_dir: str | Path,
        *,
        model: str,
        model_digest: str,
        generation_calls_per_chapter: int = DEFAULT_GENERATION_CALLS,
        request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ollama_num_ctx: int = DEFAULT_OLLAMA_NUM_CTX,
        ollama_num_predict: int = DEFAULT_OLLAMA_NUM_PREDICT,
        ollama_temperature: float = DEFAULT_OLLAMA_TEMPERATURE,
        ollama_seed: int = DEFAULT_OLLAMA_SEED,
        transport_name: str = "ollama",
    ) -> None:
        if generation_calls_per_chapter < 1:
            raise ValueError("generation_calls_per_chapter must be at least 1")
        if not model.strip():
            raise ValueError("model must not be empty")
        if not model_digest.strip():
            raise ValueError("model_digest must not be empty")

        self.ask_fn = ask_fn
        self.audit_dir = Path(audit_dir)
        self.calls_dir = self.audit_dir / "calls"
        self.events_path = self.audit_dir / "events.jsonl"
        self.config_path = self.audit_dir / "audit_config.json"
        self.model = model
        self.model_digest = model_digest
        self.generation_calls_per_chapter = generation_calls_per_chapter
        self.request_timeout_seconds = request_timeout_seconds
        self.ollama_num_ctx = ollama_num_ctx
        self.ollama_num_predict = ollama_num_predict
        self.ollama_temperature = ollama_temperature
        self.ollama_seed = ollama_seed
        self.transport_name = transport_name
        self._lock = threading.Lock()
        self._next_sequence = 1
        self._generation_counts: dict[tuple[str, int], int] = {}
        self._records: list[AuditCallRecord] = []

        # No exist_ok: even an empty pre-existing path could belong to another
        # experiment and therefore makes this run unsafe.
        self.audit_dir.mkdir(parents=True, exist_ok=False)
        self.calls_dir.mkdir(exist_ok=False)
        _write_exclusive(self.events_path, b"")

        created_at = _utc_now()
        self._config: dict[str, Any] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "created_at_utc": created_at,
            "fresh_directory_required": True,
            "artifact_layout": "one immutable calls/call_NNNNNN.json per ask",
            "journal": "append-only events.jsonl with call_started/call_finished",
            "generation_calls_per_condition_chapter": generation_calls_per_chapter,
            "transport": {
                "name": transport_name,
                "authorized_physical_attempts_per_logical_call": 1,
            },
            "runtime": self._runtime_settings(role=None),
        }
        config_payload = dict(self._config)
        config_payload["config_payload_sha256"] = _sha256_bytes(
            _canonical_json_bytes(config_payload)
        )
        self._config = config_payload
        _write_exclusive(self.config_path, _pretty_json_bytes(config_payload))

    def _runtime_settings(self, *, role: str | None) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_digest": self.model_digest,
            "role": role,
            "request_timeout_seconds": self.request_timeout_seconds,
            "options": {
                "num_ctx": self.ollama_num_ctx,
                "num_predict": self.ollama_num_predict,
                "temperature": self.ollama_temperature,
                "seed": self.ollama_seed,
            },
            "max_retries": 1,
            "system": None,
        }

    @property
    def frozen_config(self) -> Mapping[str, Any]:
        """Return a defensive copy suitable for inclusion in a run manifest."""

        return copy.deepcopy(self._config)

    @property
    def records(self) -> tuple[AuditCallRecord, ...]:
        return tuple(self._records)

    @property
    def last_call_id(self) -> str | None:
        return self._records[-1].call_id if self._records else None

    def generation_count(self, condition: str, chapter: int) -> int:
        return self._generation_counts.get((condition, chapter), 0)

    def _append_event(self, event: Mapping[str, Any]) -> None:
        line = _canonical_json_bytes(dict(event))
        with self.events_path.open("ab") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _validate_labels(
        *, condition: str, chapter: int, purpose: str, role: str, budget_class: str
    ) -> None:
        values = {
            "condition": condition,
            "purpose": purpose,
            "role": role,
            "budget_class": budget_class,
        }
        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(chapter, int) or isinstance(chapter, bool) or chapter < 1:
            raise ValueError("chapter must be a positive integer")

    def ask(
        self,
        prompt: str,
        *,
        condition: str,
        chapter: int,
        purpose: str,
        role: str = "default",
        budget_class: str = "generation",
    ) -> str:
        """Make exactly one authorized transport attempt and persist its evidence."""

        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        self._validate_labels(
            condition=condition,
            chapter=chapter,
            purpose=purpose,
            role=role,
            budget_class=budget_class,
        )

        # Holding the lock across transport gives call IDs and journal events a
        # deterministic order even if a future runner invokes this concurrently.
        with self._lock:
            if budget_class == "generation":
                budget_key = (condition, chapter)
                used = self._generation_counts.get(budget_key, 0)
                if used >= self.generation_calls_per_chapter:
                    raise BudgetExceeded(
                        f"{condition} chapter {chapter} exceeded generation call budget "
                        f"({self.generation_calls_per_chapter})"
                    )
                # A failed or rejected physical request still spends the fixed
                # experimental budget.
                self._generation_counts[budget_key] = used + 1

            sequence = self._next_sequence
            self._next_sequence += 1
            call_id = f"call_{sequence:06d}"
            artifact_path = self.calls_dir / f"{call_id}.json"
            started_at = _utc_now()
            started_monotonic_ns = time.monotonic_ns()
            runtime = self._runtime_settings(role=role)
            prompt_sha256 = _sha256_text(prompt)
            request = {
                "logical_call_id": call_id,
                "physical_request_id": f"{call_id}.physical_1",
                "condition": condition,
                "chapter": chapter,
                "purpose": purpose,
                "role": role,
                "budget_class": budget_class,
                "prompt": prompt,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": len(prompt),
                "runtime": runtime,
                "transport_name": self.transport_name,
            }
            self._append_event(
                {
                    "schema_version": AUDIT_SCHEMA_VERSION,
                    "event": "call_started",
                    "sequence": sequence,
                    "call_id": call_id,
                    "at_utc": started_at,
                    "request": request,
                }
            )

            transport_metadata: MutableMapping[str, Any] = {}
            response = ""
            transport_error: Exception | None = None
            try:
                response = self.ask_fn(
                    prompt,
                    role=role,
                    timeout=self.request_timeout_seconds,
                    model=self.model,
                    options={
                        "num_ctx": self.ollama_num_ctx,
                        "num_predict": self.ollama_num_predict,
                        "temperature": self.ollama_temperature,
                        "seed": self.ollama_seed,
                    },
                    max_retries=1,
                    metadata=transport_metadata,
                )
                if not isinstance(response, str):
                    raise TypeError(
                        f"model transport returned {type(response).__name__}, expected str"
                    )
            except Exception as error:
                transport_error = error

            finished_monotonic_ns = time.monotonic_ns()
            finished_at = _utc_now()
            safe_metadata = _json_safe(dict(transport_metadata))
            reported_attempts = transport_metadata.get("physical_attempts")
            audit_error: AuditInvariantError | None = None
            if reported_attempts != 1:
                audit_error = AuditInvariantError(
                    "transport must report exactly one physical attempt; "
                    f"reported {reported_attempts!r}"
                )
            elif transport_error is None and transport_metadata.get("done") is not True:
                audit_error = AuditInvariantError(
                    "successful transport must report done=true"
                )
            elif transport_error is None and str(
                transport_metadata.get("done_reason") or ""
            ).casefold() in {"length", "max_tokens"}:
                audit_error = AuditInvariantError(
                    "transport response was truncated at the fixed output-token limit"
                )
            elif transport_error is None and str(
                transport_metadata.get("done_reason") or ""
            ).casefold() != "stop":
                audit_error = AuditInvariantError(
                    "successful transport must report done_reason='stop'"
                )
            elif transport_error is None and (
                isinstance(transport_metadata.get("prompt_eval_count"), bool)
                or not isinstance(transport_metadata.get("prompt_eval_count"), int)
                or transport_metadata.get("prompt_eval_count") <= 0
            ):
                audit_error = AuditInvariantError(
                    "successful transport must report a positive "
                    "prompt_eval_count"
                )
            elif transport_error is None and (
                isinstance(transport_metadata.get("eval_count"), bool)
                or not isinstance(transport_metadata.get("eval_count"), int)
                or transport_metadata.get("eval_count") <= 0
            ):
                audit_error = AuditInvariantError(
                    "successful transport must report a positive eval_count"
                )
            elif transport_error is None and transport_metadata[
                "prompt_eval_count"
            ] >= (self.ollama_num_ctx - self.ollama_num_predict):
                audit_error = AuditInvariantError(
                    "prompt token count left less than the frozen output allowance; "
                    "possible input truncation"
                )
            elif transport_error is None and transport_metadata[
                "eval_count"
            ] > self.ollama_num_predict:
                audit_error = AuditInvariantError(
                    "transport exceeded the frozen output-token limit"
                )

            final_error: Exception | None = audit_error or transport_error
            if audit_error is not None:
                status = "audit_invariant_error"
            elif transport_error is not None:
                status = "transport_error"
            else:
                status = "completed"

            response_sha256 = _sha256_text(response)
            artifact: dict[str, Any] = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "sequence": sequence,
                "call_id": call_id,
                "status": status,
                "request": request,
                "response": {
                    "text": response,
                    "sha256": response_sha256,
                    "chars": len(response),
                },
                "transport": {
                    "authorized_physical_attempts": 1,
                    "reported_physical_attempts": _json_safe(reported_attempts),
                    "metadata": safe_metadata,
                    "error": _error_payload(transport_error),
                },
                "audit_error": _error_payload(audit_error),
                "timing": {
                    "started_at_utc": started_at,
                    "finished_at_utc": finished_at,
                    "started_monotonic_ns": started_monotonic_ns,
                    "finished_monotonic_ns": finished_monotonic_ns,
                    "elapsed_ns": finished_monotonic_ns - started_monotonic_ns,
                    "elapsed_seconds": round(
                        (finished_monotonic_ns - started_monotonic_ns) / 1_000_000_000,
                        9,
                    ),
                },
            }
            artifact["artifact_payload_sha256"] = _sha256_bytes(
                _canonical_json_bytes(artifact)
            )
            artifact_bytes = _pretty_json_bytes(artifact)
            artifact_file_sha256 = _sha256_bytes(artifact_bytes)
            _write_exclusive(artifact_path, artifact_bytes)

            finish_event = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "event": "call_finished",
                "sequence": sequence,
                "call_id": call_id,
                "at_utc": finished_at,
                "status": status,
                "artifact": str(artifact_path.relative_to(self.audit_dir)).replace(
                    "\\", "/"
                ),
                "artifact_file_sha256": artifact_file_sha256,
                "response_sha256": response_sha256,
                "error": _error_payload(final_error),
            }
            self._append_event(finish_event)

            error_type = ""
            if final_error is not None:
                error_type = f"{type(final_error).__module__}.{type(final_error).__qualname__}"
            record = AuditCallRecord(
                sequence=sequence,
                call_id=call_id,
                artifact_path=str(artifact_path),
                artifact_file_sha256=artifact_file_sha256,
                status=status,
                condition=condition,
                chapter=chapter,
                purpose=purpose,
                role=role,
                budget_class=budget_class,
                prompt_sha256=prompt_sha256,
                response_sha256=response_sha256,
                error_type=error_type,
            )
            self._records.append(record)

            if audit_error is not None:
                if transport_error is not None:
                    raise audit_error from transport_error
                raise audit_error
            if transport_error is not None:
                raise transport_error
            return response

    def manifest_index(self) -> Mapping[str, Any]:
        """Return the current immutable-artifact index for a run manifest/result."""

        return {
            "audit_config": copy.deepcopy(self._config),
            "events_path": str(self.events_path),
            "call_count": len(self._records),
            "last_call_id": self.last_call_id,
            "calls": [asdict(record) for record in self._records],
        }


# A descriptive alias for runner code which treats this object as its model.
AuditedBudgetedModel = ProtocolV2AuditStore
