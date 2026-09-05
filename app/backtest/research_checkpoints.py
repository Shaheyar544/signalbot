"""Durable, identity-bound state for long-running research orchestration.

Checkpoints intentionally contain trusted local Python objects (pickle) so a
resumed run can reuse immutable canonical audit evidence without lossy Decimal
or datetime conversion.  The adjacent JSON manifest is the auditable contract
and is always validated before an object is loaded.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
from typing import Any


def jsonable(value: Any) -> Any:
    from dataclasses import asdict, is_dataclass
    from decimal import Decimal
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, tuple): return [jsonable(item) for item in value]
    if isinstance(value, list): return [jsonable(item) for item in value]
    if isinstance(value, dict): return {str(key): jsonable(item) for key, item in value.items()}
    return value


def atomic_json_write(path: str | Path, value: Any) -> None:
    """Write JSON atomically; a stopped process can leave only its temp file."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    encoded = json.dumps(jsonable(value), indent=2, sort_keys=True).encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


class ResearchCheckpointStore:
    """Stores completed independent units only when their full identity matches."""
    def __init__(self, root: str | Path, identity: dict[str, Any], *, mode: str = "fresh") -> None:
        self.identity = jsonable(identity)
        self.identity_hash = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self.root = Path(root) / str(identity["research_run_id"])
        if mode == "restart" and self.root.exists():
            # This directory is scoped to one immutable research identity.
            for item in self.root.glob("*"):
                item.unlink()
        self.root.mkdir(parents=True, exist_ok=True)
        self.resume = mode == "resume"

    def _base(self, phase: str, parameters: dict[str, Any]) -> Path:
        digest = hashlib.sha256(json.dumps(jsonable({"phase": phase, "parameters": parameters}), sort_keys=True).encode()).hexdigest()
        return self.root / f"{phase}-{digest}"

    def load(self, phase: str, parameters: dict[str, Any]) -> Any | None:
        if not self.resume:
            return None
        base = self._base(phase, parameters)
        manifest, payload = base.with_suffix(".json"), base.with_suffix(".pkl")
        if not manifest.exists() or not payload.exists():
            return None
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
            if (record.get("identity_hash") != self.identity_hash or record.get("identity") != self.identity
                    or record.get("phase") != phase or record.get("parameters") != jsonable(parameters)):
                return None
            with payload.open("rb") as handle:
                return pickle.load(handle)
        except (OSError, ValueError, pickle.UnpicklingError):
            return None

    def save(self, phase: str, parameters: dict[str, Any], value: Any) -> None:
        base = self._base(phase, parameters)
        temporary = base.with_suffix(".pkl.tmp")
        with temporary.open("wb") as handle:
            pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, base.with_suffix(".pkl"))
        atomic_json_write(base.with_suffix(".json"), {
            "identity": self.identity, "identity_hash": self.identity_hash,
            "phase": phase, "parameters": parameters,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })


class ResearchProgress:
    """One atomic, human-readable progress artifact for an active run."""
    def __init__(self, path: str | Path, identity: dict[str, Any], total_units: int) -> None:
        self.path, self.identity, self.total = Path(path), jsonable(identity), total_units
        self.started = datetime.now(timezone.utc)
        self.completed = 0
        self.errors: list[dict[str, Any]] = []

    def update(self, phase: str, *, completed_units: int | None = None, cache_hits: int = 0,
               cache_misses: int = 0, replay_count: int = 0, status: str = "RUNNING") -> dict[str, Any]:
        if completed_units is not None: self.completed = completed_units
        elapsed = (datetime.now(timezone.utc) - self.started).total_seconds()
        eta = (elapsed / self.completed * (self.total - self.completed)) if self.completed else None
        value = {"research_run_id": self.identity["research_run_id"], "started_at": self.started.isoformat(),
                 "updated_at": datetime.now(timezone.utc).isoformat(), "current_phase": phase,
                 "completed_units": self.completed, "total_units": self.total,
                 "progress_percent": (self.completed * 100 / self.total) if self.total else 100,
                 "elapsed_seconds": elapsed, "estimated_remaining_seconds": eta,
                 "replay_count": replay_count, "cache_hits": cache_hits, "cache_misses": cache_misses,
                 "errors": self.errors, "status": status}
        atomic_json_write(self.path, value)
        return value

    def error(self, phase: str, parameters: dict[str, Any], exception: Exception) -> None:
        self.errors.append({"phase": phase, "parameters": jsonable(parameters),
                            "exception_type": type(exception).__name__, "message": str(exception)})
