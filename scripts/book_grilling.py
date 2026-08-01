#!/usr/bin/env python3
"""Small, deterministic runtime for the Book Grilling skill.

The AI reads and teaches the work. This runtime only validates reviewed
artifacts, advances one question at a time, persists state, and renders the
standalone reader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Unix Codex hosts provide fcntl.
    fcntl = None


SCHEMA_VERSION = 1
RUNTIME_DIR = ".book-grilling"
STATE_FILE = "course.json"
PREFETCH_DIR = "prefetch"
PREFETCH_UNITS_DIR = "units"
PREFETCH_PACKAGE_FILE = "package.json"
PREFETCH_BATCH_FILE = "batch.json"
PREFETCH_JOBS_DIR = "jobs"
PREFETCH_JOB_FILE = "job.json"
PREFETCH_LOCK_FILE = ".lock"
DEFAULT_PREFETCH_BATCH_SIZE = 5
PREFETCH_LEASE_SECONDS = 4 * 60 * 60
TEMPLATE_FILE = (
    Path(__file__).resolve().parent.parent / "assets" / "reader-template.html"
)
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
NODE_PROVENANCE = {
    "source_explicit",
    "editorial_synthesis",
    "external_context",
    "contested_interpretation",
}
UNIT_STATUSES = {
    "future",
    "needs_preparation",
    "current",
    "completed",
    "invalid",
}
NODE_STATUSES = {"locked", "current", "resolved"}
REVIEW_CHECKS = {
    "source_complete",
    "coverage_complete",
    "answers_supported",
    "no_scope_inflation",
    "tree_valid",
    "citations_exact",
}
PREFETCH_JOB_STATUSES = {
    "queued",
    "generating",
    "pending_review",
    "reviewing",
    "repairing",
    "ready",
    "blocked",
    "consumed",
    "stale",
}


class BookGrillingError(RuntimeError):
    """A recoverable validation or state-transition failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BookGrillingError(f"JSON file does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BookGrillingError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BookGrillingError(f"JSON root must be an object: {path}")
    return value


def json_text(value: Any, *, pretty: bool = True) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=pretty,
        separators=None if pretty else (",", ":"),
    )


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BookGrillingError(f"Could not fingerprint {path}: {exc}") from exc
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_path(course_dir: Path) -> Path:
    return course_dir.resolve() / RUNTIME_DIR


def state_path(course_dir: Path) -> Path:
    return runtime_path(course_dir) / STATE_FILE


def prefetch_path(course_dir: Path) -> Path:
    return runtime_path(course_dir) / PREFETCH_DIR


def prefetch_units_path(course_dir: Path) -> Path:
    return prefetch_path(course_dir) / PREFETCH_UNITS_DIR


def prefetch_unit_path(course_dir: Path, unit_id: str) -> Path:
    return prefetch_units_path(course_dir) / unit_id


def prefetch_batch_path(course_dir: Path) -> Path:
    return prefetch_path(course_dir) / PREFETCH_BATCH_FILE


def prefetch_jobs_path(course_dir: Path) -> Path:
    return prefetch_path(course_dir) / PREFETCH_JOBS_DIR


def prefetch_job_path(course_dir: Path, unit_id: str) -> Path:
    return prefetch_jobs_path(course_dir) / unit_id / PREFETCH_JOB_FILE


def prefetch_job_attempt_path(
    course_dir: Path,
    unit_id: str,
    attempt: int,
) -> Path:
    return prefetch_jobs_path(course_dir) / unit_id / "attempts" / str(attempt)


@contextmanager
def prefetch_lock(course_dir: Path):
    """Serialize sidecar queue mutations without touching course.json."""
    path = prefetch_path(course_dir) / PREFETCH_LOCK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state(course_dir: Path) -> dict[str, Any]:
    path = state_path(course_dir)
    if not path.is_file():
        raise BookGrillingError(
            f"No Book Grilling course found at {course_dir}. Run init first."
        )
    return load_json(path)


def require_source_integrity(state: dict[str, Any]) -> None:
    path = Path(str(state.get("source", {}).get("path", "")))
    if not path.is_file():
        raise BookGrillingError(f"Authoritative source is missing: {path}")
    if file_sha256(path) != state["source"].get("sha256"):
        raise BookGrillingError(
            "Authoritative source fingerprint changed; invalidate or rebuild "
            "the course before prefetching"
        )


def validate_id(value: Any, label: str) -> str:
    identifier = str(value or "").strip()
    if not ID_PATTERN.fullmatch(identifier):
        raise BookGrillingError(
            f"{label} must use lowercase letters, digits, dots, underscores, "
            f"or hyphens: {identifier!r}"
        )
    return identifier


def require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BookGrillingError(f"{label} is required")
    return text


def source_unit_order(source_units: list[dict[str, Any]]) -> list[str]:
    children: dict[str, list[dict[str, Any]]] = {}
    for unit in source_units:
        children.setdefault(str(unit.get("parent_id", "")), []).append(unit)
    for items in children.values():
        items.sort(key=lambda item: (int(item["position"]), str(item["id"])))

    ordered: list[str] = []

    def visit(parent_id: str) -> None:
        for item in children.get(parent_id, []):
            ordered.append(str(item["id"]))
            visit(str(item["id"]))

    visit("")
    return ordered


def validate_manifest(
    raw: dict[str, Any],
    *,
    manifest_path: Path,
    course_dir: Path,
    page_path: Path | None,
) -> dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"manifest.schema_version must be {SCHEMA_VERSION}"
        )
    book = raw.get("book")
    if not isinstance(book, dict):
        raise BookGrillingError("manifest.book must be an object")
    normalized_book = {
        "id": validate_id(book.get("id"), "book.id"),
        "title": require_text(book.get("title"), "book.title"),
        "author": require_text(book.get("author"), "book.author"),
        "edition": require_text(book.get("edition"), "book.edition"),
        "language": require_text(book.get("language"), "book.language"),
    }

    source = raw.get("source")
    if not isinstance(source, dict):
        raise BookGrillingError("manifest.source must be an object")
    source_value = require_text(source.get("path"), "source.path")
    source_path = Path(source_value).expanduser()
    if not source_path.is_absolute():
        source_path = (manifest_path.parent / source_path).resolve()
    else:
        source_path = source_path.resolve()
    if not source_path.is_file():
        raise BookGrillingError(f"Authoritative source does not exist: {source_path}")
    normalized_source = {
        "path": str(source_path),
        "kind": require_text(source.get("kind"), "source.kind"),
        "sha256": file_sha256(source_path),
    }
    coverage_scope = str(source.get("coverage_scope", "")).strip()
    if coverage_scope not in {"complete", "partial"}:
        raise BookGrillingError(
            "source.coverage_scope must be complete or partial"
        )
    coverage_note = str(source.get("coverage_note", "")).strip()
    if coverage_scope == "partial" and not coverage_note:
        raise BookGrillingError(
            "source.coverage_note is required for a partial source"
        )
    normalized_source.update(
        {
            "coverage_scope": coverage_scope,
            "coverage_note": coverage_note,
        }
    )

    source_units = raw.get("source_units")
    if not isinstance(source_units, list) or not source_units:
        raise BookGrillingError("manifest.source_units must be a non-empty array")
    normalized_units: list[dict[str, Any]] = []
    seen: set[str] = set()
    sibling_positions: dict[str, list[int]] = {}
    learning_sequences: list[int] = []
    for index, item in enumerate(source_units, start=1):
        if not isinstance(item, dict):
            raise BookGrillingError(f"source_units[{index}] must be an object")
        unit_id = validate_id(item.get("id"), f"source_units[{index}].id")
        if unit_id in seen:
            raise BookGrillingError(f"Duplicate source unit id: {unit_id}")
        seen.add(unit_id)
        parent_id = str(item.get("parent_id", "")).strip()
        position = item.get("position")
        if not isinstance(position, int) or position < 1:
            raise BookGrillingError(f"{unit_id}.position must be a positive integer")
        learning_unit = bool(item.get("learning_unit", False))
        sequence = item.get("sequence")
        if learning_unit:
            if not isinstance(sequence, int) or sequence < 1:
                raise BookGrillingError(
                    f"{unit_id}.sequence must be a positive integer"
                )
            learning_sequences.append(sequence)
        elif sequence not in (None, ""):
            raise BookGrillingError(
                f"{unit_id}.sequence is allowed only for learning units"
            )
        normalized_units.append(
            {
                "id": unit_id,
                "parent_id": parent_id,
                "position": position,
                "kind": require_text(item.get("kind"), f"{unit_id}.kind"),
                "title": require_text(item.get("title"), f"{unit_id}.title"),
                "locator": require_text(item.get("locator"), f"{unit_id}.locator"),
                "learning_unit": learning_unit,
                "sequence": sequence if learning_unit else None,
                "split_origin": (
                    require_text(item.get("split_origin"), f"{unit_id}.split_origin")
                    if learning_unit
                    else ""
                ),
                "estimated_tokens": (
                    int(item.get("estimated_tokens", 0)) if learning_unit else 0
                ),
            }
        )
        sibling_positions.setdefault(parent_id, []).append(position)

    for unit in normalized_units:
        if unit["parent_id"] and unit["parent_id"] not in seen:
            raise BookGrillingError(
                f"{unit['id']}.parent_id does not exist: {unit['parent_id']!r}"
            )
        if unit["parent_id"] == unit["id"]:
            raise BookGrillingError(f"{unit['id']} cannot parent itself")
        if unit["learning_unit"]:
            if unit["split_origin"] not in {"author", "system"}:
                raise BookGrillingError(
                    f"{unit['id']}.split_origin must be author or system"
                )
            if unit["estimated_tokens"] < 1:
                raise BookGrillingError(
                    f"{unit['id']}.estimated_tokens must be positive"
                )

    for parent_id, positions in sibling_positions.items():
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise BookGrillingError(
                f"Sibling positions under {parent_id or '<root>'} must be "
                "contiguous from 1"
            )
    if sorted(learning_sequences) != list(range(1, len(learning_sequences) + 1)):
        raise BookGrillingError(
            "Learning-unit sequences must be contiguous from 1"
        )

    order = source_unit_order(normalized_units)
    if len(order) != len(normalized_units):
        raise BookGrillingError("Source structure contains a cycle or orphan")
    units_by_id = {unit["id"]: unit for unit in normalized_units}
    learning_ids = [
        unit["id"]
        for unit in sorted(
            (item for item in normalized_units if item["learning_unit"]),
            key=lambda item: int(item["sequence"]),
        )
    ]
    if not learning_ids:
        raise BookGrillingError("At least one source unit must be a learning unit")
    source_order_learning_ids = [
        unit_id for unit_id in order if units_by_id[unit_id]["learning_unit"]
    ]
    if learning_ids != source_order_learning_ids:
        raise BookGrillingError(
            "Learning-unit sequence must follow the author's source order"
        )
    for unit_id in learning_ids:
        parent_id = str(units_by_id[unit_id]["parent_id"])
        while parent_id:
            if units_by_id[parent_id]["learning_unit"]:
                raise BookGrillingError(
                    "Learning units cannot overlap as ancestor and descendant: "
                    f"{parent_id!r} contains {unit_id!r}"
                )
            parent_id = str(units_by_id[parent_id]["parent_id"])

    safe_context = raw.get("safe_context")
    if not isinstance(safe_context, dict):
        raise BookGrillingError("manifest.safe_context must be an object")
    source_token_limit = safe_context.get("source_token_limit")
    if not isinstance(source_token_limit, int) or source_token_limit < 1000:
        raise BookGrillingError(
            "safe_context.source_token_limit must be an integer of at least 1000"
        )
    oversized = [
        item["id"]
        for item in normalized_units
        if item["learning_unit"]
        and int(item["estimated_tokens"]) > source_token_limit
    ]
    if oversized:
        raise BookGrillingError(
            "Learning units exceed the declared safe source budget: "
            + ", ".join(oversized)
        )

    resolved_page = (
        page_path.resolve()
        if page_path is not None
        else (course_dir.resolve() / "book-grilling.html")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "book": normalized_book,
        "source": normalized_source,
        "source_units": normalized_units,
        "learning_unit_ids": learning_ids,
        "safe_context": {
            "source_token_limit": source_token_limit,
            "method": require_text(
                safe_context.get("method"), "safe_context.method"
            ),
        },
        "page_path": str(resolved_page),
    }


def tree_preorder(tree: dict[str, Any]) -> list[str]:
    nodes = tree["nodes"]
    children: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        children.setdefault(str(node.get("parent_id", "")), []).append(node)
    for items in children.values():
        items.sort(key=lambda item: (int(item["position"]), str(item["id"])))
    ordered: list[str] = []

    def visit(node_id: str) -> None:
        ordered.append(node_id)
        for child in children.get(node_id, []):
            visit(str(child["id"]))

    visit(str(tree["root_id"]))
    return ordered


def validate_tree(
    raw: dict[str, Any],
    *,
    unit_id: str,
    source_text: str,
) -> dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"tree.schema_version must be {SCHEMA_VERSION}"
        )
    if str(raw.get("unit_id", "")) != unit_id:
        raise BookGrillingError(
            f"tree.unit_id must match current unit {unit_id!r}"
        )
    source_hash = text_sha256(source_text)
    if str(raw.get("source_text_sha256", "")) != source_hash:
        raise BookGrillingError(
            "tree.source_text_sha256 does not match the supplied unit text"
        )
    root_id = validate_id(raw.get("root_id"), "tree.root_id")
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise BookGrillingError("tree.nodes must be a non-empty array")
    normalized_nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    sibling_positions: dict[str, list[int]] = {}
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            raise BookGrillingError(f"tree.nodes[{index}] must be an object")
        node_id = validate_id(node.get("id"), f"tree.nodes[{index}].id")
        if node_id in seen:
            raise BookGrillingError(f"Duplicate tree node id: {node_id}")
        seen.add(node_id)
        parent_id = str(node.get("parent_id", "")).strip()
        position = node.get("position")
        if not isinstance(position, int) or position < 1:
            raise BookGrillingError(f"{node_id}.position must be positive")
        provenance = str(node.get("provenance", "")).strip()
        if provenance not in NODE_PROVENANCE:
            raise BookGrillingError(
                f"{node_id}.provenance must be one of {sorted(NODE_PROVENANCE)}"
            )
        source = node.get("source")
        if not isinstance(source, dict):
            raise BookGrillingError(f"{node_id}.source must be an object")
        excerpt = require_text(source.get("excerpt"), f"{node_id}.source.excerpt")
        if excerpt not in source_text:
            raise BookGrillingError(
                f"{node_id}.source.excerpt is not an exact span of unit text"
            )
        normalized_nodes.append(
            {
                "id": node_id,
                "parent_id": parent_id,
                "position": position,
                "question": require_text(
                    node.get("question"), f"{node_id}.question"
                ),
                "recommended_answer": require_text(
                    node.get("recommended_answer"),
                    f"{node_id}.recommended_answer",
                ),
                "provenance": provenance,
                "source": {
                    "locator": require_text(
                        source.get("locator"), f"{node_id}.source.locator"
                    ),
                    "excerpt": excerpt,
                },
                "interpretive_note": str(
                    node.get("interpretive_note", "")
                ).strip(),
            }
        )
        sibling_positions.setdefault(parent_id, []).append(position)

    if root_id not in seen:
        raise BookGrillingError("tree.root_id does not name a node")
    roots = [node["id"] for node in normalized_nodes if not node["parent_id"]]
    if roots != [root_id]:
        raise BookGrillingError(
            f"Tree must have exactly root {root_id!r}; found {roots}"
        )
    for node in normalized_nodes:
        if node["parent_id"] and node["parent_id"] not in seen:
            raise BookGrillingError(
                f"{node['id']}.parent_id does not exist: {node['parent_id']!r}"
            )
    for parent_id, positions in sibling_positions.items():
        if sorted(positions) != list(range(1, len(positions) + 1)):
            raise BookGrillingError(
                f"Tree sibling positions under {parent_id or '<root>'} must "
                "be contiguous from 1"
            )

    coverage = raw.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        raise BookGrillingError("tree.coverage must be a non-empty array")
    normalized_coverage: list[dict[str, Any]] = []
    covered_nodes: set[str] = set()
    for index, item in enumerate(coverage, start=1):
        if not isinstance(item, dict):
            raise BookGrillingError(f"tree.coverage[{index}] must be an object")
        disposition = str(item.get("disposition", "")).strip()
        if disposition not in {"knowledge", "context", "rhetorical"}:
            raise BookGrillingError(
                f"coverage[{index}].disposition must be knowledge, context, "
                "or rhetorical"
            )
        node_ids = item.get("node_ids", [])
        if not isinstance(node_ids, list):
            raise BookGrillingError(f"coverage[{index}].node_ids must be an array")
        unknown = sorted(set(map(str, node_ids)) - seen)
        if unknown:
            raise BookGrillingError(
                f"coverage[{index}] references unknown nodes: {unknown}"
            )
        if disposition == "knowledge" and not node_ids:
            raise BookGrillingError(
                f"coverage[{index}] knowledge spans must name at least one node"
            )
        covered_nodes.update(map(str, node_ids))
        normalized_coverage.append(
            {
                "locator": require_text(
                    item.get("locator"), f"coverage[{index}].locator"
                ),
                "disposition": disposition,
                "node_ids": list(dict.fromkeys(map(str, node_ids))),
                "reason": require_text(
                    item.get("reason"), f"coverage[{index}].reason"
                ),
            }
        )
    missing_coverage = sorted(seen - covered_nodes)
    if missing_coverage:
        raise BookGrillingError(
            f"Tree nodes missing from coverage ledger: {missing_coverage}"
        )

    normalized = {
        "schema_version": SCHEMA_VERSION,
        "unit_id": unit_id,
        "title": require_text(raw.get("title"), "tree.title"),
        "source_text_sha256": source_hash,
        "root_id": root_id,
        "nodes": normalized_nodes,
        "coverage": normalized_coverage,
    }
    order = tree_preorder(normalized)
    if len(order) != len(normalized_nodes):
        raise BookGrillingError("Tree contains a cycle or unreachable node")
    return normalized


def validate_review(
    raw: dict[str, Any],
    *,
    artifact_type: str,
    artifact: dict[str, Any],
    source_hash: str,
    unit_id: str = "",
) -> dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"review.schema_version must be {SCHEMA_VERSION}"
        )
    if str(raw.get("artifact_type", "")) != artifact_type:
        raise BookGrillingError(
            f"review.artifact_type must be {artifact_type!r}"
        )
    if unit_id and str(raw.get("unit_id", "")) != unit_id:
        raise BookGrillingError(f"review.unit_id must be {unit_id!r}")
    if str(raw.get("verdict", "")) != "passed":
        raise BookGrillingError("Only a passed independent review can unlock content")
    if str(raw.get("artifact_sha256", "")) != value_sha256(artifact):
        raise BookGrillingError(
            "review.artifact_sha256 does not match the normalized artifact"
        )
    if str(raw.get("source_text_sha256", "")) != source_hash:
        raise BookGrillingError(
            "review.source_text_sha256 does not match the reviewed source"
        )
    reviewer = raw.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise BookGrillingError("review.reviewer.independent must be true")
    checks = raw.get("checks")
    if not isinstance(checks, dict):
        raise BookGrillingError("review.checks must be an object")
    missing = sorted(REVIEW_CHECKS - set(checks))
    failed = sorted(
        name for name in REVIEW_CHECKS if checks.get(name) is not True
    )
    if missing or failed:
        raise BookGrillingError(
            f"Independent review checks are incomplete or failed; "
            f"missing={missing}, failed={failed}"
        )
    issues = raw.get("issues")
    if not isinstance(issues, list) or issues:
        raise BookGrillingError(
            "A passed review must contain an empty issues array"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "unit_id": unit_id,
        "artifact_sha256": value_sha256(artifact),
        "source_text_sha256": source_hash,
        "reviewed_at": require_text(raw.get("reviewed_at"), "review.reviewed_at"),
        "reviewer": {
            "independent": True,
            "method": require_text(
                reviewer.get("method"), "review.reviewer.method"
            ),
        },
        "checks": {name: True for name in sorted(REVIEW_CHECKS)},
        "issues": [],
        "verdict": "passed",
    }


def validate_failed_review(
    raw: dict[str, Any],
    *,
    artifact: dict[str, Any],
    source_hash: str,
    unit_id: str,
) -> dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"review.schema_version must be {SCHEMA_VERSION}"
        )
    if str(raw.get("artifact_type", "")) != "unit_tree":
        raise BookGrillingError("review.artifact_type must be 'unit_tree'")
    if str(raw.get("unit_id", "")) != unit_id:
        raise BookGrillingError(f"review.unit_id must be {unit_id!r}")
    if str(raw.get("verdict", "")) != "failed":
        raise BookGrillingError("Recorded repair review verdict must be failed")
    if str(raw.get("artifact_sha256", "")) != value_sha256(artifact):
        raise BookGrillingError(
            "review.artifact_sha256 does not match the staged artifact"
        )
    if str(raw.get("source_text_sha256", "")) != source_hash:
        raise BookGrillingError(
            "review.source_text_sha256 does not match the staged source"
        )
    reviewer = raw.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise BookGrillingError("review.reviewer.independent must be true")
    checks = raw.get("checks")
    if not isinstance(checks, dict):
        raise BookGrillingError("review.checks must be an object")
    missing = sorted(REVIEW_CHECKS - set(checks))
    non_boolean = sorted(
        name for name in REVIEW_CHECKS if not isinstance(checks.get(name), bool)
    )
    failed = sorted(name for name in REVIEW_CHECKS if checks.get(name) is False)
    if missing or non_boolean or not failed:
        raise BookGrillingError(
            "A failed review needs every boolean check and at least one failure; "
            f"missing={missing}, non_boolean={non_boolean}, failed={failed}"
        )
    issues = raw.get("issues")
    if not isinstance(issues, list) or not issues:
        raise BookGrillingError("A failed review must describe at least one issue")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "unit_tree",
        "unit_id": unit_id,
        "artifact_sha256": value_sha256(artifact),
        "source_text_sha256": source_hash,
        "reviewed_at": require_text(raw.get("reviewed_at"), "review.reviewed_at"),
        "reviewer": {
            "independent": True,
            "method": require_text(
                reviewer.get("method"), "review.reviewer.method"
            ),
        },
        "checks": {name: bool(checks[name]) for name in sorted(REVIEW_CHECKS)},
        "issues": issues,
        "verdict": "failed",
    }


def course_fingerprint(state: dict[str, Any]) -> str:
    """Fingerprint immutable course/source structure, never learning progress."""
    return value_sha256(
        {
            "schema_version": state["schema_version"],
            "book": state["book"],
            "source": state["source"],
            "source_units": state["source_units"],
            "learning_unit_ids": state["learning_unit_ids"],
            "safe_context": state["safe_context"],
        }
    )


def source_unit(state: dict[str, Any], unit_id: str) -> dict[str, Any]:
    unit = next(
        (item for item in state["source_units"] if item["id"] == unit_id),
        None,
    )
    if not isinstance(unit, dict):
        raise BookGrillingError(f"Unknown learning unit: {unit_id}")
    return unit


def prefetch_candidate_unit_ids(state: dict[str, Any]) -> list[str]:
    """Return every current-or-future unit that can be prepared independently."""
    if state.get("book_status") != "learning":
        return []
    current_id = str(state.get("current_unit_id", ""))
    if not current_id:
        return []
    units = list(state["learning_unit_ids"])
    try:
        current_index = units.index(current_id)
    except ValueError as exc:
        raise BookGrillingError(
            f"Current unit is not in the learning sequence: {current_id!r}"
        ) from exc
    current_status = state["unit_records"][current_id]["status"]
    start = (
        current_index
        if current_status in {"needs_preparation", "invalid"}
        else current_index + 1
    )
    return [
        unit_id
        for unit_id in units[start:]
        if state["unit_records"][unit_id]["status"]
        in {"future", "needs_preparation", "invalid"}
    ]


def worker_fingerprint(worker_token: str) -> str:
    token = require_text(worker_token, "worker_token")
    return text_sha256(token)


def load_prefetch_batch(
    course_dir: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    path = prefetch_batch_path(course_dir)
    if not path.is_file():
        return None
    batch = load_json(path)
    if batch.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"Prefetch batch schema must be {SCHEMA_VERSION}"
        )
    batch_id = validate_id(batch.get("batch_id"), "batch.batch_id")
    mode = str(batch.get("mode", ""))
    if mode not in {"remaining", "next-batch"}:
        raise BookGrillingError("batch.mode must be remaining or next-batch")
    target_ids = batch.get("target_unit_ids")
    if not isinstance(target_ids, list):
        raise BookGrillingError("batch.target_unit_ids must be an array")
    target_ids = [validate_id(item, "batch target unit") for item in target_ids]
    if len(target_ids) != len(set(target_ids)):
        raise BookGrillingError("batch.target_unit_ids contains duplicates")
    learning_ids = state["learning_unit_ids"]
    if any(unit_id not in learning_ids for unit_id in target_ids):
        raise BookGrillingError("Prefetch batch contains an unknown unit")
    expected_order = sorted(target_ids, key=learning_ids.index)
    if target_ids != expected_order:
        raise BookGrillingError("Prefetch batch targets are out of source order")
    if str(batch.get("course_sha256", "")) != course_fingerprint(state):
        raise BookGrillingError(
            "Prefetch batch does not match the current immutable course"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "mode": mode,
        "course_sha256": course_fingerprint(state),
        "source_sha256": state["source"]["sha256"],
        "target_unit_ids": target_ids,
        "created_at": require_text(batch.get("created_at"), "batch.created_at"),
        "updated_at": require_text(batch.get("updated_at"), "batch.updated_at"),
    }


def write_prefetch_batch(course_dir: Path, batch: dict[str, Any]) -> None:
    atomic_write_text(prefetch_batch_path(course_dir), json_text(batch) + "\n")


def load_prefetch_job(
    course_dir: Path,
    unit_id: str,
) -> dict[str, Any] | None:
    path = prefetch_job_path(course_dir, unit_id)
    if not path.is_file():
        return None
    job = load_json(path)
    if job.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"Prefetch job schema must be {SCHEMA_VERSION}: {unit_id}"
        )
    if str(job.get("unit_id", "")) != unit_id:
        raise BookGrillingError(f"Prefetch job unit mismatch: {unit_id}")
    if job.get("status") not in PREFETCH_JOB_STATUSES:
        raise BookGrillingError(f"Prefetch job has invalid status: {unit_id}")
    return job


def write_prefetch_job(
    course_dir: Path,
    job: dict[str, Any],
) -> None:
    unit_id = validate_id(job.get("unit_id"), "job.unit_id")
    atomic_write_text(
        prefetch_job_path(course_dir, unit_id),
        json_text(job) + "\n",
    )


def new_prefetch_job(
    state: dict[str, Any],
    batch: dict[str, Any],
    unit_id: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch["batch_id"],
        "unit_id": unit_id,
        "course_sha256": course_fingerprint(state),
        "source_unit_sha256": value_sha256(source_unit(state, unit_id)),
        "status": "queued",
        "attempt": 0,
        "claim": None,
        "generated_by": "",
        "reviewed_by": "",
        "artifacts": None,
        "last_error": "",
        "created_at": now,
        "updated_at": now,
    }


def ensure_prefetch_jobs(
    course_dir: Path,
    state: dict[str, Any],
    batch: dict[str, Any],
) -> None:
    for unit_id in batch["target_unit_ids"]:
        if load_prefetch_job(course_dir, unit_id) is not None:
            continue
        job = new_prefetch_job(state, batch, unit_id)
        package_path = cached_unit_paths(course_dir, unit_id)["package"]
        if package_path.is_file():
            try:
                load_cached_unit(course_dir, state, unit_id)
                job["status"] = "ready"
            except BookGrillingError as exc:
                job["status"] = "blocked"
                job["last_error"] = str(exc)
        write_prefetch_job(course_dir, job)


def recover_prefetch_claims(
    course_dir: Path,
    batch: dict[str, Any],
    *,
    force: bool,
) -> list[str]:
    recovered: list[str] = []
    now_epoch = int(time.time())
    for unit_id in batch["target_unit_ids"]:
        job = load_prefetch_job(course_dir, unit_id)
        if not job or job["status"] not in {"generating", "reviewing"}:
            continue
        claim = job.get("claim")
        expires_at = int(claim.get("expires_at", 0)) if isinstance(claim, dict) else 0
        if not force and expires_at > now_epoch:
            continue
        job["status"] = (
            "pending_review"
            if job["status"] == "reviewing" and job.get("artifacts")
            else "repairing"
            if int(job.get("attempt", 0)) > 0
            else "queued"
        )
        job["claim"] = None
        job["updated_at"] = utc_now()
        job["last_error"] = "Recovered an interrupted worker claim"
        write_prefetch_job(course_dir, job)
        recovered.append(unit_id)
    return recovered


def prefetched_job_status(
    course_dir: Path,
    state: dict[str, Any],
    unit_id: str,
    *,
    deep_validate: bool,
) -> tuple[str, str]:
    record_status = state["unit_records"][unit_id]["status"]
    if record_status in {"current", "completed"}:
        return "consumed", ""
    package_path = cached_unit_paths(course_dir, unit_id)["package"]
    if package_path.is_file():
        if not deep_validate:
            return "ready", ""
        try:
            load_cached_unit(course_dir, state, unit_id)
            return "ready", ""
        except BookGrillingError as exc:
            return "blocked", str(exc)
    job = load_prefetch_job(course_dir, unit_id)
    if not job:
        return "queued", ""
    status = str(job["status"])
    if status == "ready":
        return "blocked", "Ready job is missing its validated package"
    claim = job.get("claim")
    if status in {"generating", "reviewing"} and isinstance(claim, dict):
        if int(claim.get("expires_at", 0)) <= int(time.time()):
            return (
                "pending_review" if status == "reviewing" else "repairing",
                "Worker lease expired; resume can reclaim this job",
            )
    return status, str(job.get("last_error", ""))


def prefetch_batch_status(
    course_dir: Path,
    state: dict[str, Any],
    *,
    include_units: bool,
    deep_validate: bool = True,
) -> dict[str, Any]:
    try:
        batch = load_prefetch_batch(course_dir, state)
    except BookGrillingError as exc:
        return {
            "status": "stale",
            "complete": False,
            "batch_id": "",
            "mode": "",
            "counts": {"stale": 1},
            "total": 0,
            "error": str(exc),
            "units": [],
        }
    if batch is None:
        return {
            "status": "idle",
            "complete": False,
            "batch_id": "",
            "mode": "",
            "counts": {},
            "total": 0,
            "error": "",
            "units": [],
        }
    counts: dict[str, int] = {}
    units: list[dict[str, Any]] = []
    for unit_id in batch["target_unit_ids"]:
        status, error = prefetched_job_status(
            course_dir,
            state,
            unit_id,
            deep_validate=deep_validate,
        )
        counts[status] = counts.get(status, 0) + 1
        if include_units:
            job = load_prefetch_job(course_dir, unit_id)
            units.append(
                {
                    "unit_id": unit_id,
                    "status": status,
                    "attempt": int(job.get("attempt", 0)) if job else 0,
                    "error": error,
                    "unit": source_unit(state, unit_id),
                }
            )
    complete = all(
        status in {"ready", "consumed"}
        for status in counts
        if counts[status]
    ) and sum(counts.values()) == len(batch["target_unit_ids"])
    blocked = any(counts.get(item, 0) for item in {"blocked", "stale"})
    status = "ready" if complete else "blocked" if blocked else "running"
    return {
        "status": status,
        "complete": complete,
        "batch_id": batch["batch_id"],
        "mode": batch["mode"],
        "counts": counts,
        "total": len(batch["target_unit_ids"]),
        "error": "",
        "units": units,
    }


def prefetch_target_unit_id(state: dict[str, Any]) -> str:
    """Return the one bounded look-ahead target, or the urgent current unit."""
    if state.get("book_status") != "learning":
        return ""
    current_id = str(state.get("current_unit_id", ""))
    if not current_id:
        return ""
    units = state["learning_unit_ids"]
    try:
        current_index = units.index(current_id)
    except ValueError as exc:
        raise BookGrillingError(
            f"Current unit is not in the learning sequence: {current_id!r}"
        ) from exc
    status = state["unit_records"][current_id]["status"]
    if status in {"needs_preparation", "invalid"}:
        return current_id
    if status == "current" and current_index + 1 < len(units):
        return str(units[current_index + 1])
    return ""


def cached_unit_paths(course_dir: Path, unit_id: str) -> dict[str, Path]:
    directory = prefetch_unit_path(course_dir, unit_id)
    return {
        "directory": directory,
        "source_text": directory / "unit.txt",
        "tree": directory / "tree.json",
        "review": directory / "review.json",
        "package": directory / PREFETCH_PACKAGE_FILE,
    }


def read_utf8(path: Path, label: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BookGrillingError(f"Could not read {label} {path}: {exc}") from exc
    if not text.strip():
        raise BookGrillingError(f"{label} cannot be empty")
    return text


def load_staged_prefetch_artifacts(
    course_dir: Path,
    state: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    unit_id = str(job["unit_id"])
    attempt = int(job.get("attempt", 0))
    if attempt < 1:
        raise BookGrillingError(f"Prefetch job {unit_id} has no staged attempt")
    attempt_dir = prefetch_job_attempt_path(course_dir, unit_id, attempt)
    source_path = attempt_dir / "unit.txt"
    tree_path = attempt_dir / "tree.json"
    source_text = read_utf8(source_path, "staged exact unit text")
    raw_tree = load_json(tree_path)
    tree = validate_tree(raw_tree, unit_id=unit_id, source_text=source_text)
    if tree != raw_tree:
        raise BookGrillingError("Staged tree is not normalized")
    artifacts = job.get("artifacts")
    if not isinstance(artifacts, dict):
        raise BookGrillingError(f"Prefetch job {unit_id} lacks artifact receipts")
    hashes = {
        "source_text_sha256": text_sha256(source_text),
        "tree_sha256": value_sha256(tree),
    }
    for key, value in hashes.items():
        if str(artifacts.get(key, "")) != value:
            raise BookGrillingError(
                f"Staged {unit_id} {key} is stale or corrupted"
            )
    if str(job.get("course_sha256", "")) != course_fingerprint(state):
        raise BookGrillingError(f"Prefetch job {unit_id} belongs to another course")
    if str(job.get("source_unit_sha256", "")) != value_sha256(
        source_unit(state, unit_id)
    ):
        raise BookGrillingError(
            f"Prefetch job {unit_id} source-unit metadata changed"
        )
    return {
        "source_text": source_text,
        "tree": tree,
        "source_path": source_path,
        "tree_path": tree_path,
        "attempt_dir": attempt_dir,
    }


def require_job_claim(
    job: dict[str, Any],
    *,
    worker_token: str,
    role: str,
) -> str:
    worker_sha256 = worker_fingerprint(worker_token)
    claim = job.get("claim")
    if not isinstance(claim, dict):
        raise BookGrillingError(
            f"Prefetch job {job['unit_id']} is not claimed"
        )
    if str(claim.get("worker_sha256", "")) != worker_sha256:
        raise BookGrillingError(
            f"Prefetch job {job['unit_id']} belongs to another worker"
        )
    if str(claim.get("role", "")) != role:
        raise BookGrillingError(
            f"Prefetch job {job['unit_id']} is not claimed for {role}"
        )
    if int(claim.get("expires_at", 0)) <= int(time.time()):
        raise BookGrillingError(
            f"Prefetch job {job['unit_id']} worker lease expired"
        )
    return worker_sha256


def load_cached_unit(
    course_dir: Path,
    state: dict[str, Any],
    unit_id: str,
) -> dict[str, Any]:
    paths = cached_unit_paths(course_dir, unit_id)
    package = load_json(paths["package"])
    if package.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"Cached package schema must be {SCHEMA_VERSION}"
        )
    if str(package.get("unit_id", "")) != unit_id:
        raise BookGrillingError("Cached package unit_id does not match its directory")
    expected = {
        "book_id": state["book"]["id"],
        "source_sha256": state["source"]["sha256"],
        "course_sha256": course_fingerprint(state),
        "source_unit_sha256": value_sha256(source_unit(state, unit_id)),
    }
    for key, value in expected.items():
        if str(package.get(key, "")) != value:
            raise BookGrillingError(
                f"Cached package {key} does not match the current course"
            )

    source_text = read_utf8(paths["source_text"], "cached exact unit text")
    raw_tree = load_json(paths["tree"])
    tree = validate_tree(raw_tree, unit_id=unit_id, source_text=source_text)
    if tree != raw_tree:
        raise BookGrillingError("Cached tree is not normalized")
    raw_review = load_json(paths["review"])
    review = validate_review(
        raw_review,
        artifact_type="unit_tree",
        artifact=tree,
        source_hash=text_sha256(source_text),
        unit_id=unit_id,
    )
    if review != raw_review:
        raise BookGrillingError("Cached review is not normalized")

    hashes = {
        "source_text_sha256": text_sha256(source_text),
        "tree_sha256": value_sha256(tree),
        "review_sha256": value_sha256(review),
    }
    for key, value in hashes.items():
        if str(package.get(key, "")) != value:
            raise BookGrillingError(f"Cached package {key} is stale or corrupted")
    return {
        "source_text": source_text,
        "tree": tree,
        "review": review,
        "package": package,
        "paths": paths,
    }


def prefetch_status(course_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    unit_id = prefetch_target_unit_id(state)
    if not unit_id:
        return {
            "unit_id": "",
            "status": "not_applicable",
            "need": "wait_for_progress" if state.get("book_status") == "learning" else "complete",
            "unit": None,
            "error": "",
        }
    paths = cached_unit_paths(course_dir, unit_id)
    status = "missing"
    error = ""
    if paths["package"].is_file():
        try:
            load_cached_unit(course_dir, state, unit_id)
            status = "ready"
        except BookGrillingError as exc:
            status = "invalid"
            error = str(exc)
    current_record = state["unit_records"][str(state["current_unit_id"])]
    if status == "ready" and current_record["status"] in {
        "needs_preparation",
        "invalid",
    }:
        need = "activate_prefetched_unit"
    elif status == "ready":
        need = "wait_for_progress"
    else:
        need = "prepare_prefetch_unit"
    return {
        "unit_id": unit_id,
        "status": status,
        "need": need,
        "unit": source_unit(state, unit_id),
        "error": error,
        "cache_dir": str(paths["directory"]),
    }


def install_unit_artifacts(
    state: dict[str, Any],
    course_dir: Path,
    *,
    unit_id: str,
    source_text: str,
    tree: dict[str, Any],
    review: dict[str, Any],
    prepared_via: str,
) -> dict[str, Any]:
    evidence_path = runtime_path(course_dir) / "units" / f"{unit_id}.txt"
    atomic_write_text(evidence_path, source_text)
    order = tree_preorder(tree)
    progress = {
        node_id: {
            "status": "current" if index == 0 else "locked",
            "open_questions": [],
            "learner_note": "",
            "stance": "",
            "resolved_at": "",
        }
        for index, node_id in enumerate(order)
    }
    state["unit_records"][unit_id].update(
        {
            "status": "current",
            "tree": tree,
            "review": review,
            "progress": progress,
            "current_node_id": order[0],
            "source_text_path": str(evidence_path),
            "prepared_at": utc_now(),
            "prepared_via": prepared_via,
            "completed_at": "",
        }
    )
    state["current_unit_id"] = unit_id
    state["current_node_id"] = order[0]
    return {
        "unit_id": unit_id,
        "tree_sha256": review["artifact_sha256"],
        "node_count": len(order),
        "prepared_via": prepared_via,
    }


def archive_prefetch_units(
    course_dir: Path,
    state: dict[str, Any],
    unit_ids: list[str],
    *,
    reason: str,
) -> list[str]:
    archived: list[str] = []
    archive_root = runtime_path(course_dir) / "history" / "prefetch"
    for unit_id in unit_ids:
        source_directory = prefetch_unit_path(course_dir, unit_id)
        if not source_directory.is_dir():
            continue
        archive_root.mkdir(parents=True, exist_ok=True)
        base_name = f"{unit_id}-r{state['revision']}"
        destination = archive_root / base_name
        suffix = 2
        while destination.exists():
            destination = archive_root / f"{base_name}-{suffix}"
            suffix += 1
        shutil.move(str(source_directory), str(destination))
        atomic_write_text(
            destination / "archive.json",
            json_text(
                {
                    "schema_version": SCHEMA_VERSION,
                    "unit_id": unit_id,
                    "reason": reason,
                    "archived_at": utc_now(),
                }
            )
            + "\n",
        )
        archived.append(str(destination))
    return archived


def set_prefetch_job_status(
    course_dir: Path,
    unit_id: str,
    status: str,
    *,
    error: str = "",
) -> None:
    if status not in PREFETCH_JOB_STATUSES:
        raise BookGrillingError(f"Invalid prefetch job status: {status}")
    job = load_prefetch_job(course_dir, unit_id)
    if job is None:
        return
    job["status"] = status
    job["claim"] = None
    job["last_error"] = error
    job["updated_at"] = utc_now()
    write_prefetch_job(course_dir, job)


def append_event(
    state: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
) -> None:
    events = state.setdefault("events", [])
    events.append(
        {
            "revision": int(state["revision"]),
            "type": event_type,
            "at": utc_now(),
            "payload": payload,
        }
    )
    if len(events) > 200:
        del events[:-200]


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for unit_id in state["learning_unit_ids"]:
        record = state["unit_records"][unit_id]
        public_record: dict[str, Any] = {
            "status": record["status"],
            "current_node_id": record.get("current_node_id", ""),
            "progress": record.get("progress", {}),
            "tree": None,
        }
        tree = record.get("tree")
        if isinstance(tree, dict):
            public_nodes = []
            progress = record.get("progress", {})
            for node in tree["nodes"]:
                node_status = progress.get(node["id"], {}).get("status", "locked")
                item = {
                    "id": node["id"],
                    "parent_id": node["parent_id"],
                    "position": node["position"],
                    "question": node["question"],
                    "status": node_status,
                }
                if node_status in {"current", "resolved"}:
                    item.update(
                        {
                            "recommended_answer": node["recommended_answer"],
                            "provenance": node["provenance"],
                            "source": node["source"],
                            "interpretive_note": node["interpretive_note"],
                        }
                    )
                public_nodes.append(item)
            public_record["tree"] = {
                "unit_id": tree["unit_id"],
                "title": tree["title"],
                "root_id": tree["root_id"],
                "nodes": public_nodes,
                "verified": record.get("review", {}).get("verdict") == "passed",
            }
        records[unit_id] = public_record
    synthesis = state.get("synthesis")
    public_synthesis = None
    if isinstance(synthesis, dict):
        public_synthesis = {
            "schema_version": synthesis["schema_version"],
            "question": synthesis["question"],
            "recommended_answer": synthesis["recommended_answer"],
            "unit_contributions": synthesis["unit_contributions"],
            "boundaries": synthesis["boundaries"],
            "review": {
                "verdict": synthesis.get("review", {}).get("verdict", ""),
                "reviewed_at": synthesis.get("review", {}).get(
                    "reviewed_at", ""
                ),
            },
        }
    return {
        "schema_version": state["schema_version"],
        "revision": state["revision"],
        "book": state["book"],
        "source": {
            "kind": state["source"]["kind"],
            "sha256": state["source"]["sha256"],
            "coverage_scope": state["source"]["coverage_scope"],
            "coverage_note": state["source"]["coverage_note"],
        },
        "source_units": state["source_units"],
        "learning_unit_ids": state["learning_unit_ids"],
        "unit_records": records,
        "current_unit_id": state["current_unit_id"],
        "current_node_id": state["current_node_id"],
        "book_status": state["book_status"],
        "synthesis": public_synthesis,
        "generated_at": utc_now(),
    }


def render_html(state: dict[str, Any]) -> str:
    try:
        template = TEMPLATE_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BookGrillingError(f"Could not read reader template: {exc}") from exc
    marker = "__BOOK_GRILLING_DATA__"
    if template.count(marker) != 1:
        raise BookGrillingError(
            "Reader template must contain exactly one data marker"
        )
    payload = json_text(public_state(state), pretty=False).replace("</", "<\\/")
    return template.replace(marker, payload)


def persist(state: dict[str, Any], course_dir: Path) -> None:
    atomic_write_text(state_path(course_dir), json_text(state) + "\n")
    page_path = Path(state["page_path"])
    atomic_write_text(page_path, render_html(state))


def context_payload(state: dict[str, Any]) -> dict[str, Any]:
    unit_id = str(state.get("current_unit_id", ""))
    node_id = str(state.get("current_node_id", ""))
    record = state["unit_records"].get(unit_id, {}) if unit_id else {}
    tree = record.get("tree") if isinstance(record, dict) else None
    current_node = None
    if isinstance(tree, dict) and node_id:
        current_node = next(
            (node for node in tree["nodes"] if node["id"] == node_id),
            None,
        )
    completed = sum(
        state["unit_records"][item]["status"] == "completed"
        for item in state["learning_unit_ids"]
    )
    need = "complete"
    if state["book_status"] == "ready_for_synthesis":
        need = "prepare_book_synthesis"
    elif state["book_status"] == "learning":
        if record.get("status") in {"needs_preparation", "invalid"}:
            need = "prepare_current_unit"
        elif record.get("status") == "current":
            need = "continue_current_question"
    course_dir = Path(str(state["course_dir"]))
    prefetch = prefetch_status(course_dir, state)
    if need == "prepare_current_unit" and prefetch["need"] == (
        "activate_prefetched_unit"
    ):
        need = "activate_prefetched_unit"
    return {
        "schema_version": state["schema_version"],
        "receipt": {
            "revision": state["revision"],
            "current_unit_id": unit_id,
            "current_node_id": node_id,
        },
        "book": state["book"],
        "book_status": state["book_status"],
        "progress": {
            "completed_units": completed,
            "total_units": len(state["learning_unit_ids"]),
        },
        "need": need,
        "current_unit": next(
            (
                item
                for item in state["source_units"]
                if item["id"] == unit_id
            ),
            None,
        ),
        "current_node": current_node,
        "open_questions": (
            record.get("progress", {}).get(node_id, {}).get("open_questions", [])
            if node_id
            else []
        ),
        "page_path": state["page_path"],
        "prefetch": prefetch,
        "prefetch_batch": prefetch_batch_status(
            course_dir,
            state,
            include_units=False,
            deep_validate=False,
        ),
    }


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    path = state_path(course_dir)
    if path.exists():
        raise BookGrillingError(
            f"Course already exists: {path}. This runtime never overwrites it."
        )
    manifest_path = args.manifest.resolve()
    normalized = validate_manifest(
        load_json(manifest_path),
        manifest_path=manifest_path,
        course_dir=course_dir,
        page_path=args.page,
    )
    unit_records = {
        unit_id: {
            "status": (
                "needs_preparation"
                if index == 0
                else "future"
            ),
            "tree": None,
            "review": None,
            "progress": {},
            "current_node_id": "",
            "completed_at": "",
        }
        for index, unit_id in enumerate(normalized["learning_unit_ids"])
    }
    state = {
        **normalized,
        "revision": 0,
        "course_dir": str(course_dir),
        "book_status": "learning",
        "current_unit_id": normalized["learning_unit_ids"][0],
        "current_node_id": "",
        "unit_records": unit_records,
        "synthesis": None,
        "events": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    append_event(
        state,
        "course_initialized",
        {"current_unit_id": state["current_unit_id"]},
    )
    persist(state, course_dir)
    return context_payload(state)


def command_prepare_unit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    if int(state["revision"]) != args.expected_revision:
        raise BookGrillingError(
            f"Stale revision: expected {args.expected_revision}, "
            f"actual {state['revision']}"
        )
    unit_id = str(state["current_unit_id"])
    if unit_id != args.expected_unit:
        raise BookGrillingError(
            f"Stale unit: expected {args.expected_unit!r}, actual {unit_id!r}"
        )
    record = state["unit_records"][unit_id]
    if record["status"] not in {"needs_preparation", "invalid"}:
        raise BookGrillingError(
            f"Unit {unit_id} cannot be prepared from status {record['status']!r}"
        )
    source_text = read_utf8(args.source_text, "exact unit text")
    tree = validate_tree(
        load_json(args.tree),
        unit_id=unit_id,
        source_text=source_text,
    )
    review = validate_review(
        load_json(args.review),
        artifact_type="unit_tree",
        artifact=tree,
        source_hash=text_sha256(source_text),
        unit_id=unit_id,
    )
    prepared = install_unit_artifacts(
        state,
        course_dir,
        unit_id=unit_id,
        source_text=source_text,
        tree=tree,
        review=review,
        prepared_via="foreground",
    )
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    archives = archive_prefetch_units(
        course_dir,
        state,
        [unit_id],
        reason="Superseded by foreground preparation",
    )
    if archives:
        prepared["cache_archive"] = archives[0]
    set_prefetch_job_status(course_dir, unit_id, "consumed")
    append_event(state, "unit_prepared", prepared)
    persist(state, course_dir)
    return context_payload(state)


def command_prefetch_context(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    return {
        "schema_version": SCHEMA_VERSION,
        "book": state["book"],
        "source": state["source"],
        "safe_context": state["safe_context"],
        "current_unit_id": state["current_unit_id"],
        "prefetch": prefetch_status(course_dir, state),
        "batch": prefetch_batch_status(
            course_dir,
            state,
            include_units=False,
            deep_validate=False,
        ),
    }


def command_prefetch_plan(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    require_source_integrity(state)
    mode = args.mode
    if args.batch_size < 1:
        raise BookGrillingError("batch_size must be positive")
    candidates = prefetch_candidate_unit_ids(state)
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        if batch is None:
            seed = f"{state['book']['id']}:{time.time_ns()}"
            now = utc_now()
            batch = {
                "schema_version": SCHEMA_VERSION,
                "batch_id": f"batch-{text_sha256(seed)[:16]}",
                "mode": mode,
                "course_sha256": course_fingerprint(state),
                "source_sha256": state["source"]["sha256"],
                "target_unit_ids": [],
                "created_at": now,
                "updated_at": now,
            }
        existing = list(batch["target_unit_ids"])
        if mode == "remaining":
            selected = candidates
            batch["mode"] = "remaining"
        else:
            unseen = [item for item in candidates if item not in existing]
            selected = unseen[: args.batch_size]
        combined = set(existing) | set(selected)
        batch["target_unit_ids"] = [
            unit_id
            for unit_id in state["learning_unit_ids"]
            if unit_id in combined
        ]
        batch["updated_at"] = utc_now()
        write_prefetch_batch(course_dir, batch)
        ensure_prefetch_jobs(course_dir, state, batch)
        for unit_id in selected:
            job = load_prefetch_job(course_dir, unit_id)
            if job and job["status"] == "stale":
                replacement = new_prefetch_job(state, batch, unit_id)
                replacement["attempt"] = int(job.get("attempt", 0))
                replacement["created_at"] = job.get("created_at", utc_now())
                replacement["last_error"] = "Requeued after invalidation"
                write_prefetch_job(course_dir, replacement)
        recovered = recover_prefetch_claims(
            course_dir,
            batch,
            force=False,
        )
    result = prefetch_batch_status(course_dir, state, include_units=True)
    result["recovered_expired_claims"] = recovered
    result["candidate_count"] = len(candidates)
    return result


def command_prefetch_status(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    require_source_integrity(state)
    return prefetch_batch_status(course_dir, state, include_units=True)


def command_prefetch_resume(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        if batch is None:
            raise BookGrillingError("No prefetch batch exists to resume")
        ensure_prefetch_jobs(course_dir, state, batch)
        recovered = recover_prefetch_claims(
            course_dir,
            batch,
            force=True,
        )
    result = prefetch_batch_status(course_dir, state, include_units=True)
    result["recovered_claims"] = recovered
    return result


def command_prefetch_claim(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    role = args.role
    worker_sha256 = worker_fingerprint(args.worker_token)
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        if batch is None:
            raise BookGrillingError("Run prefetch-plan before claiming work")
        ensure_prefetch_jobs(course_dir, state, batch)
        recover_prefetch_claims(course_dir, batch, force=False)
        selected: dict[str, Any] | None = None
        for unit_id in batch["target_unit_ids"]:
            job = load_prefetch_job(course_dir, unit_id)
            if not job:
                continue
            claim = job.get("claim")
            if (
                job["status"] in {"generating", "reviewing"}
                and isinstance(claim, dict)
                and claim.get("worker_sha256") == worker_sha256
                and claim.get("role") == role
            ):
                selected = job
                break
        if selected is None:
            eligible_statuses = (
                {"queued", "repairing"}
                if role == "generator"
                else {"pending_review"}
            )
            for unit_id in batch["target_unit_ids"]:
                job = load_prefetch_job(course_dir, unit_id)
                if not job or job["status"] not in eligible_statuses:
                    continue
                if role == "reviewer" and job.get("generated_by") == worker_sha256:
                    continue
                selected = job
                break
        if selected is None:
            return {
                "claimed": False,
                "role": role,
                "batch": prefetch_batch_status(
                    course_dir,
                    state,
                    include_units=False,
                    deep_validate=False,
                ),
            }
        selected["status"] = "generating" if role == "generator" else "reviewing"
        selected["claim"] = {
            "role": role,
            "worker_sha256": worker_sha256,
            "claimed_at": utc_now(),
            "expires_at": int(time.time()) + PREFETCH_LEASE_SECONDS,
        }
        selected["updated_at"] = utc_now()
        write_prefetch_job(course_dir, selected)
    unit_id = str(selected["unit_id"])
    staged = selected.get("artifacts") if role == "reviewer" else None
    return {
        "claimed": True,
        "role": role,
        "batch_id": selected["batch_id"],
        "unit_id": unit_id,
        "unit": source_unit(state, unit_id),
        "source": state["source"],
        "safe_context": state["safe_context"],
        "attempt": int(selected.get("attempt", 0)),
        "staged_artifacts": staged,
    }


def command_stage_prefetch_unit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    require_source_integrity(state)
    unit_id = validate_id(args.expected_unit, "expected_unit")
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        if batch is None or unit_id not in batch["target_unit_ids"]:
            raise BookGrillingError(f"Unit {unit_id} is not in the active batch")
        job = load_prefetch_job(course_dir, unit_id)
        if not job or job["status"] != "generating":
            raise BookGrillingError(f"Unit {unit_id} is not claimed for generation")
        generator_sha256 = require_job_claim(
            job,
            worker_token=args.worker_token,
            role="generator",
        )
        source_text = read_utf8(args.source_text, "prefetched exact unit text")
        tree = validate_tree(
            load_json(args.tree),
            unit_id=unit_id,
            source_text=source_text,
        )
        attempt = int(job.get("attempt", 0)) + 1
        attempt_dir = prefetch_job_attempt_path(course_dir, unit_id, attempt)
        source_path = attempt_dir / "unit.txt"
        tree_path = attempt_dir / "tree.json"
        atomic_write_text(source_path, source_text)
        atomic_write_text(tree_path, json_text(tree) + "\n")
        job.update(
            {
                "status": "pending_review",
                "attempt": attempt,
                "claim": None,
                "generated_by": generator_sha256,
                "reviewed_by": "",
                "artifacts": {
                    "source_text_path": str(source_path),
                    "tree_path": str(tree_path),
                    "source_text_sha256": text_sha256(source_text),
                    "tree_sha256": value_sha256(tree),
                },
                "last_error": "",
                "updated_at": utc_now(),
            }
        )
        write_prefetch_job(course_dir, job)
    return {
        "staged": job["artifacts"],
        "unit_id": unit_id,
        "attempt": attempt,
        "next": "independent_review",
        "batch": prefetch_batch_status(
            course_dir,
            state,
            include_units=False,
            deep_validate=False,
        ),
    }


def command_record_prefetch_review(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    unit_id = validate_id(args.expected_unit, "expected_unit")
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        if batch is None or unit_id not in batch["target_unit_ids"]:
            raise BookGrillingError(f"Unit {unit_id} is not in the active batch")
        job = load_prefetch_job(course_dir, unit_id)
        if not job or job["status"] != "reviewing":
            raise BookGrillingError(f"Unit {unit_id} is not claimed for review")
        reviewer_sha256 = require_job_claim(
            job,
            worker_token=args.worker_token,
            role="reviewer",
        )
        if reviewer_sha256 == job.get("generated_by"):
            raise BookGrillingError(
                "Independent reviewer must differ from the generator worker"
            )
        staged = load_staged_prefetch_artifacts(course_dir, state, job)
        review = validate_failed_review(
            load_json(args.review),
            artifact=staged["tree"],
            source_hash=text_sha256(staged["source_text"]),
            unit_id=unit_id,
        )
        review_path = staged["attempt_dir"] / "review.json"
        atomic_write_text(review_path, json_text(review) + "\n")
        job.update(
            {
                "status": "repairing",
                "claim": None,
                "reviewed_by": reviewer_sha256,
                "last_error": json_text(review["issues"], pretty=False),
                "updated_at": utc_now(),
            }
        )
        write_prefetch_job(course_dir, job)
    return {
        "unit_id": unit_id,
        "attempt": job["attempt"],
        "verdict": "failed",
        "next": "repair_and_restage",
        "issues": review["issues"],
        "batch": prefetch_batch_status(
            course_dir,
            state,
            include_units=False,
            deep_validate=False,
        ),
    }


def command_cache_unit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    require_source_integrity(state)
    unit_id = validate_id(args.expected_unit, "expected_unit")
    with prefetch_lock(course_dir):
        batch = load_prefetch_batch(course_dir, state)
        job: dict[str, Any] | None = None
        reviewer_sha256 = ""
        staged: dict[str, Any] | None = None
        if batch is not None and unit_id in batch["target_unit_ids"]:
            job = load_prefetch_job(course_dir, unit_id)
            if not job or job["status"] != "reviewing":
                raise BookGrillingError(
                    f"Batch unit {unit_id} is not claimed for independent review"
                )
            if not args.worker_token:
                raise BookGrillingError(
                    "Batch cache-unit requires the independent reviewer worker token"
                )
            reviewer_sha256 = require_job_claim(
                job,
                worker_token=args.worker_token,
                role="reviewer",
            )
            if reviewer_sha256 == job.get("generated_by"):
                raise BookGrillingError(
                    "Independent reviewer must differ from the generator worker"
                )
            staged = load_staged_prefetch_artifacts(course_dir, state, job)
        else:
            target_id = prefetch_target_unit_id(state)
            if not target_id:
                raise BookGrillingError(
                    "No bounded prefetch target is currently available"
                )
            if unit_id != target_id:
                raise BookGrillingError(
                    f"Stale prefetch target: expected {unit_id!r}, "
                    f"actual {target_id!r}"
                )

        record = state["unit_records"][unit_id]
        if record["status"] not in {"future", "needs_preparation", "invalid"}:
            raise BookGrillingError(
                f"Unit {unit_id} cannot be cached from status {record['status']!r}"
            )
        source_text = read_utf8(args.source_text, "prefetched exact unit text")
        tree = validate_tree(
            load_json(args.tree),
            unit_id=unit_id,
            source_text=source_text,
        )
        if staged is not None and (
            text_sha256(source_text) != text_sha256(staged["source_text"])
            or value_sha256(tree) != value_sha256(staged["tree"])
        ):
            raise BookGrillingError(
                "Reviewed batch inputs do not match the persisted staged attempt"
            )
        review = validate_review(
            load_json(args.review),
            artifact_type="unit_tree",
            artifact=tree,
            source_hash=text_sha256(source_text),
            unit_id=unit_id,
        )
        package = {
            "schema_version": SCHEMA_VERSION,
            "unit_id": unit_id,
            "book_id": state["book"]["id"],
            "source_sha256": state["source"]["sha256"],
            "course_sha256": course_fingerprint(state),
            "source_unit_sha256": value_sha256(source_unit(state, unit_id)),
            "source_text_sha256": text_sha256(source_text),
            "tree_sha256": value_sha256(tree),
            "review_sha256": value_sha256(review),
            "cached_at": utc_now(),
        }
        if batch is not None and job is not None:
            package.update(
                {
                    "batch_id": batch["batch_id"],
                    "generation_attempt": int(job["attempt"]),
                    "independent_worker_separation": True,
                }
            )
        paths = cached_unit_paths(course_dir, unit_id)
        # Remove any old ready marker before replacing artifacts. The new
        # package is written last and is the only ready marker.
        paths["package"].unlink(missing_ok=True)
        atomic_write_text(paths["source_text"], source_text)
        atomic_write_text(paths["tree"], json_text(tree) + "\n")
        atomic_write_text(paths["review"], json_text(review) + "\n")
        atomic_write_text(paths["package"], json_text(package) + "\n")
        if job is not None and staged is not None:
            atomic_write_text(
                staged["attempt_dir"] / "review.json",
                json_text(review) + "\n",
            )
            job.update(
                {
                    "status": "ready",
                    "claim": None,
                    "reviewed_by": reviewer_sha256,
                    "last_error": "",
                    "updated_at": utc_now(),
                }
            )
            write_prefetch_job(course_dir, job)
    return {
        "cached": package,
        "prefetch": prefetch_status(course_dir, state),
        "batch": prefetch_batch_status(
            course_dir,
            state,
            include_units=False,
            deep_validate=False,
        ),
    }


def command_activate_prefetched_unit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    if int(state["revision"]) != args.expected_revision:
        raise BookGrillingError(
            f"Stale revision: expected {args.expected_revision}, "
            f"actual {state['revision']}"
        )
    unit_id = str(state["current_unit_id"])
    if unit_id != args.expected_unit:
        raise BookGrillingError(
            f"Stale unit: expected {args.expected_unit!r}, actual {unit_id!r}"
        )
    record = state["unit_records"][unit_id]
    if record["status"] not in {"needs_preparation", "invalid"}:
        raise BookGrillingError(
            f"Unit {unit_id} cannot activate cache from status {record['status']!r}"
        )
    cached = load_cached_unit(course_dir, state, unit_id)
    prepared = install_unit_artifacts(
        state,
        course_dir,
        unit_id=unit_id,
        source_text=cached["source_text"],
        tree=cached["tree"],
        review=cached["review"],
        prepared_via="prefetch",
    )
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    archives = archive_prefetch_units(
        course_dir,
        state,
        [unit_id],
        reason="Promoted into the authoritative current unit",
    )
    if archives:
        prepared["cache_archive"] = archives[0]
    set_prefetch_job_status(course_dir, unit_id, "consumed")
    append_event(state, "prefetched_unit_activated", prepared)
    persist(state, course_dir)
    return context_payload(state)


def command_commit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    if int(state["revision"]) != args.expected_revision:
        raise BookGrillingError(
            f"Stale revision: expected {args.expected_revision}, "
            f"actual {state['revision']}"
        )
    unit_id = str(state["current_unit_id"])
    node_id = str(state["current_node_id"])
    if unit_id != args.expected_unit or node_id != args.expected_node:
        raise BookGrillingError(
            "Stale learning target: expected "
            f"{args.expected_unit!r}/{args.expected_node!r}, actual "
            f"{unit_id!r}/{node_id!r}"
        )
    record = state["unit_records"][unit_id]
    if record["status"] != "current":
        raise BookGrillingError(f"Unit {unit_id} is not current")
    progress = record["progress"]
    if progress[node_id]["status"] != "current":
        raise BookGrillingError(f"Node {node_id} is not current")
    turn = load_json(args.turn)
    if str(turn.get("node_id", "")) != node_id:
        raise BookGrillingError("turn.node_id must match the current node")
    outcome = str(turn.get("outcome", "")).strip()
    if outcome not in {"open", "resolved"}:
        raise BookGrillingError("turn.outcome must be open or resolved")
    prefetched_prepared: dict[str, Any] | None = None
    prefetch_error = ""

    if outcome == "open":
        question = require_text(
            turn.get("open_question"), "turn.open_question"
        )
        progress[node_id]["open_questions"].append(
            {"text": question, "recorded_at": utc_now()}
        )
        event_payload = {
            "unit_id": unit_id,
            "node_id": node_id,
            "outcome": "open",
        }
    else:
        stance = str(turn.get("stance", "understood")).strip()
        if stance not in {"understood", "understood-but-disagrees"}:
            raise BookGrillingError(
                "turn.stance must be understood or understood-but-disagrees"
            )
        progress[node_id].update(
            {
                "status": "resolved",
                "learner_note": str(turn.get("learner_note", "")).strip(),
                "stance": stance,
                "resolved_at": utc_now(),
            }
        )
        order = tree_preorder(record["tree"])
        current_index = order.index(node_id)
        if current_index + 1 < len(order):
            next_node_id = order[current_index + 1]
            progress[next_node_id]["status"] = "current"
            record["current_node_id"] = next_node_id
            state["current_node_id"] = next_node_id
        else:
            record["status"] = "completed"
            record["current_node_id"] = ""
            record["completed_at"] = utc_now()
            state["current_node_id"] = ""
            units = state["learning_unit_ids"]
            unit_index = units.index(unit_id)
            if unit_index + 1 < len(units):
                next_unit_id = units[unit_index + 1]
                state["current_unit_id"] = next_unit_id
                state["unit_records"][next_unit_id][
                    "status"
                ] = "needs_preparation"
                package_path = cached_unit_paths(course_dir, next_unit_id)["package"]
                if package_path.is_file():
                    try:
                        cached = load_cached_unit(course_dir, state, next_unit_id)
                        prefetched_prepared = install_unit_artifacts(
                            state,
                            course_dir,
                            unit_id=next_unit_id,
                            source_text=cached["source_text"],
                            tree=cached["tree"],
                            review=cached["review"],
                            prepared_via="prefetch",
                        )
                    except BookGrillingError as exc:
                        # A bad optional cache never blocks valid learning progress.
                        prefetch_error = str(exc)
            else:
                state["current_unit_id"] = ""
                state["book_status"] = "ready_for_synthesis"
        event_payload = {
            "unit_id": unit_id,
            "node_id": node_id,
            "outcome": "resolved",
            "next_unit_id": state["current_unit_id"],
            "next_node_id": state["current_node_id"],
        }
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    append_event(state, "question_committed", event_payload)
    if prefetched_prepared is not None:
        archives = archive_prefetch_units(
            course_dir,
            state,
            [prefetched_prepared["unit_id"]],
            reason="Promoted into the authoritative current unit",
        )
        if archives:
            prefetched_prepared["cache_archive"] = archives[0]
        set_prefetch_job_status(
            course_dir,
            prefetched_prepared["unit_id"],
            "consumed",
        )
        append_event(state, "prefetched_unit_activated", prefetched_prepared)
    elif prefetch_error:
        append_event(
            state,
            "prefetch_activation_skipped",
            {
                "unit_id": state["current_unit_id"],
                "reason": prefetch_error,
            },
        )
    persist(state, course_dir)
    return context_payload(state)


def validate_synthesis(
    raw: dict[str, Any],
    *,
    learning_unit_ids: list[str],
) -> dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise BookGrillingError(
            f"synthesis.schema_version must be {SCHEMA_VERSION}"
        )
    contributions = raw.get("unit_contributions")
    if not isinstance(contributions, list):
        raise BookGrillingError("synthesis.unit_contributions must be an array")
    normalized_contributions = []
    seen: set[str] = set()
    for index, item in enumerate(contributions, start=1):
        if not isinstance(item, dict):
            raise BookGrillingError(
                f"synthesis.unit_contributions[{index}] must be an object"
            )
        unit_id = str(item.get("unit_id", "")).strip()
        if unit_id not in learning_unit_ids or unit_id in seen:
            raise BookGrillingError(
                f"Invalid or duplicate synthesis unit contribution: {unit_id!r}"
            )
        seen.add(unit_id)
        normalized_contributions.append(
            {
                "unit_id": unit_id,
                "contribution": require_text(
                    item.get("contribution"),
                    f"unit_contributions[{index}].contribution",
                ),
            }
        )
    if seen != set(learning_unit_ids):
        raise BookGrillingError(
            "Book synthesis must include every learning unit exactly once"
        )
    boundaries = raw.get("boundaries", [])
    if not isinstance(boundaries, list) or not all(
        isinstance(item, str) and item.strip() for item in boundaries
    ):
        raise BookGrillingError(
            "synthesis.boundaries must be an array of non-empty strings"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "question": require_text(raw.get("question"), "synthesis.question"),
        "recommended_answer": require_text(
            raw.get("recommended_answer"), "synthesis.recommended_answer"
        ),
        "unit_contributions": normalized_contributions,
        "boundaries": [item.strip() for item in boundaries],
    }


def command_finalize(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    if int(state["revision"]) != args.expected_revision:
        raise BookGrillingError(
            f"Stale revision: expected {args.expected_revision}, "
            f"actual {state['revision']}"
        )
    if state["book_status"] != "ready_for_synthesis":
        raise BookGrillingError(
            "Every learning unit must be completed before book synthesis"
        )
    synthesis = validate_synthesis(
        load_json(args.synthesis),
        learning_unit_ids=state["learning_unit_ids"],
    )
    review = validate_review(
        load_json(args.review),
        artifact_type="book_synthesis",
        artifact=synthesis,
        source_hash=state["source"]["sha256"],
    )
    state["synthesis"] = {
        **synthesis,
        "review": review,
    }
    state["book_status"] = "completed"
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    append_event(
        state,
        "book_completed",
        {"synthesis_sha256": review["artifact_sha256"]},
    )
    persist(state, course_dir)
    return context_payload(state)


def command_invalidate(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    if int(state["revision"]) != args.expected_revision:
        raise BookGrillingError(
            f"Stale revision: expected {args.expected_revision}, "
            f"actual {state['revision']}"
        )
    unit_id = args.unit
    if unit_id not in state["learning_unit_ids"]:
        raise BookGrillingError(f"Unknown learning unit: {unit_id}")
    reason = require_text(args.reason, "reason")
    start = state["learning_unit_ids"].index(unit_id)
    affected_ids = list(state["learning_unit_ids"][start:])
    history_dir = runtime_path(course_dir) / "history"
    archived: list[str] = []
    prefetched_archived = archive_prefetch_units(
        course_dir,
        state,
        affected_ids,
        reason=reason,
    )
    for affected_id in affected_ids:
        set_prefetch_job_status(
            course_dir,
            affected_id,
            "stale",
            error=f"Invalidated with {unit_id}: {reason}",
        )
        record = state["unit_records"][affected_id]
        if record.get("tree") is not None:
            history_path = (
                history_dir
                / f"{affected_id}-r{state['revision']}.json"
            )
            atomic_write_text(
                history_path,
                json_text(
                    {
                        "unit_id": affected_id,
                        "reason": reason,
                        "archived_at": utc_now(),
                        "record": record,
                    }
                )
                + "\n",
            )
            archived.append(str(history_path))
        state["unit_records"][affected_id] = {
            "status": (
                "invalid" if affected_id == unit_id else "future"
            ),
            "tree": None,
            "review": None,
            "progress": {},
            "current_node_id": "",
            "completed_at": "",
        }
    state["book_status"] = "learning"
    state["current_unit_id"] = unit_id
    state["current_node_id"] = ""
    state["synthesis"] = None
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    append_event(
        state,
        "unit_invalidated",
        {
            "unit_id": unit_id,
            "reason": reason,
            "archives": archived,
            "prefetch_archives": prefetched_archived,
        },
    )
    persist(state, course_dir)
    return context_payload(state)


def validate_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append("state schema version is invalid")
    source_path = Path(str(state.get("source", {}).get("path", "")))
    if not source_path.is_file():
        errors.append(f"authoritative source is missing: {source_path}")
    elif file_sha256(source_path) != state["source"].get("sha256"):
        errors.append("authoritative source fingerprint changed")
    if state.get("book_status") not in {
        "learning",
        "ready_for_synthesis",
        "completed",
    }:
        errors.append("book_status is invalid")
    records = state.get("unit_records")
    if not isinstance(records, dict):
        return errors + ["unit_records must be an object"]
    for unit_id in state.get("learning_unit_ids", []):
        record = records.get(unit_id)
        if not isinstance(record, dict):
            errors.append(f"missing unit record: {unit_id}")
            continue
        if record.get("status") not in UNIT_STATUSES:
            errors.append(f"{unit_id} has invalid status")
        tree = record.get("tree")
        if isinstance(tree, dict):
            source_text_path = Path(str(record.get("source_text_path", "")))
            source_text = ""
            if not source_text_path.is_file():
                errors.append(f"{unit_id} exact source text is missing")
            else:
                try:
                    source_text = source_text_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    errors.append(f"{unit_id} exact source text is unreadable")
            if source_text:
                try:
                    normalized_tree = validate_tree(
                        tree,
                        unit_id=unit_id,
                        source_text=source_text,
                    )
                    if normalized_tree != tree:
                        errors.append(f"{unit_id} tree is not normalized")
                except BookGrillingError as exc:
                    errors.append(f"{unit_id} tree is invalid: {exc}")
            review = record.get("review")
            if not isinstance(review, dict):
                errors.append(f"{unit_id} review is missing")
            elif source_text:
                try:
                    validate_review(
                        review,
                        artifact_type="unit_tree",
                        artifact=tree,
                        source_hash=text_sha256(source_text),
                        unit_id=unit_id,
                    )
                except BookGrillingError as exc:
                    errors.append(f"{unit_id} review is invalid: {exc}")
            tree_node_ids = {node["id"] for node in tree.get("nodes", [])}
            progress_by_node = record.get("progress", {})
            if set(progress_by_node) != tree_node_ids:
                errors.append(f"{unit_id} progress does not match tree nodes")
            for node_id, progress in progress_by_node.items():
                if progress.get("status") not in NODE_STATUSES:
                    errors.append(f"{unit_id}/{node_id} has invalid progress")
            if record.get("status") == "completed" and any(
                progress.get("status") != "resolved"
                for progress in progress_by_node.values()
            ):
                errors.append(f"{unit_id} is completed with unresolved nodes")
            if record.get("status") == "current":
                current_ids = [
                    node_id
                    for node_id, progress in progress_by_node.items()
                    if progress.get("status") == "current"
                ]
                if current_ids != [record.get("current_node_id")]:
                    errors.append(f"{unit_id} does not have exactly one current node")
    current_unit = str(state.get("current_unit_id", ""))
    current_node = str(state.get("current_node_id", ""))
    if state.get("book_status") == "learning" and not current_unit:
        errors.append("learning course needs a current unit")
    if current_node:
        record = records.get(current_unit, {})
        if (
            record.get("progress", {})
            .get(current_node, {})
            .get("status")
            != "current"
        ):
            errors.append("current_node_id does not name the current node")
    if state.get("book_status") == "completed":
        synthesis_with_review = state.get("synthesis")
        if not isinstance(synthesis_with_review, dict):
            errors.append("completed book is missing synthesis")
        else:
            synthesis = {
                key: synthesis_with_review.get(key)
                for key in (
                    "schema_version",
                    "question",
                    "recommended_answer",
                    "unit_contributions",
                    "boundaries",
                )
            }
            try:
                normalized_synthesis = validate_synthesis(
                    synthesis,
                    learning_unit_ids=state["learning_unit_ids"],
                )
                if normalized_synthesis != synthesis:
                    errors.append("book synthesis is not normalized")
                validate_review(
                    synthesis_with_review.get("review", {}),
                    artifact_type="book_synthesis",
                    artifact=synthesis,
                    source_hash=state["source"]["sha256"],
                )
            except BookGrillingError as exc:
                errors.append(f"book synthesis review is invalid: {exc}")
    return errors


def command_audit(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    errors = validate_state(state)
    warnings: list[str] = []
    cache_root = prefetch_units_path(course_dir)
    if cache_root.is_dir():
        known_units = set(state.get("learning_unit_ids", []))
        for directory in sorted(cache_root.iterdir()):
            if not directory.is_dir():
                continue
            if directory.name not in known_units:
                warnings.append(f"unknown prefetched unit directory: {directory.name}")
                continue
            try:
                load_cached_unit(course_dir, state, directory.name)
            except BookGrillingError as exc:
                warnings.append(f"{directory.name} prefetch cache is invalid: {exc}")
    batch = prefetch_batch_status(course_dir, state, include_units=True)
    if batch["status"] == "stale":
        warnings.append(f"prefetch batch is stale: {batch['error']}")
    elif batch["status"] == "blocked":
        blocked_units = [
            item["unit_id"]
            for item in batch["units"]
            if item["status"] in {"blocked", "stale"}
        ]
        warnings.append(
            "prefetch batch has blocked units: " + ", ".join(blocked_units)
        )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "revision": state["revision"],
        "book_status": state["book_status"],
        "page_path": state["page_path"],
        "prefetch_batch": {
            key: batch[key]
            for key in ("status", "complete", "batch_id", "counts", "total")
        },
    }


def command_context(args: argparse.Namespace) -> dict[str, Any]:
    return context_payload(read_state(args.course_dir.resolve()))


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    course_dir = args.course_dir.resolve()
    state = read_state(course_dir)
    errors = validate_state(state)
    if errors:
        raise BookGrillingError(
            "Cannot render an invalid course:\n- " + "\n- ".join(errors)
        )
    atomic_write_text(Path(state["page_path"]), render_html(state))
    return {
        "rendered": state["page_path"],
        "revision": state["revision"],
    }


def command_fingerprint(args: argparse.Namespace) -> dict[str, Any]:
    if args.json_file:
        value = load_json(args.json_file.resolve())
        return {"sha256": value_sha256(value), "kind": "canonical-json"}
    if args.text_file:
        try:
            text = args.text_file.resolve().read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BookGrillingError(f"Could not read text file: {exc}") from exc
        return {"sha256": text_sha256(text), "kind": "utf-8-text"}
    raise BookGrillingError("Choose --json-file or --text-file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book_grilling.py",
        description="Validated state and standalone reader for Book Grilling.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize one book course.")
    init.add_argument("course_dir", type=Path)
    init.add_argument("--manifest", type=Path, required=True)
    init.add_argument("--page", type=Path)
    init.set_defaults(handler=command_init)

    context = subparsers.add_parser(
        "context", help="Return the compact next-turn context."
    )
    context.add_argument("course_dir", type=Path)
    context.set_defaults(handler=command_context)

    prefetch_context = subparsers.add_parser(
        "prefetch-context",
        help="Return exact-next cache status plus compact batch progress.",
    )
    prefetch_context.add_argument("course_dir", type=Path)
    prefetch_context.set_defaults(handler=command_prefetch_context)

    prefetch_plan = subparsers.add_parser(
        "prefetch-plan",
        help="Create or extend a persistent multi-unit prefetch batch.",
    )
    prefetch_plan.add_argument("course_dir", type=Path)
    prefetch_plan.add_argument(
        "--mode",
        choices=("remaining", "next-batch"),
        default="remaining",
    )
    prefetch_plan.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_PREFETCH_BATCH_SIZE,
    )
    prefetch_plan.set_defaults(handler=command_prefetch_plan)

    prefetch_status_parser = subparsers.add_parser(
        "prefetch-status",
        help="Validate every target and report persistent batch progress.",
    )
    prefetch_status_parser.add_argument("course_dir", type=Path)
    prefetch_status_parser.set_defaults(handler=command_prefetch_status)

    prefetch_resume = subparsers.add_parser(
        "prefetch-resume",
        help="Recover interrupted worker claims while preserving artifacts.",
    )
    prefetch_resume.add_argument("course_dir", type=Path)
    prefetch_resume.set_defaults(handler=command_prefetch_resume)

    prefetch_claim = subparsers.add_parser(
        "prefetch-claim",
        help="Atomically claim one ordered generation or review job.",
    )
    prefetch_claim.add_argument("course_dir", type=Path)
    prefetch_claim.add_argument(
        "--role",
        choices=("generator", "reviewer"),
        required=True,
    )
    prefetch_claim.add_argument("--worker-token", required=True)
    prefetch_claim.set_defaults(handler=command_prefetch_claim)

    stage_prefetch = subparsers.add_parser(
        "stage-prefetch-unit",
        help="Persist one normalized candidate before independent review.",
    )
    stage_prefetch.add_argument("course_dir", type=Path)
    stage_prefetch.add_argument("--tree", type=Path, required=True)
    stage_prefetch.add_argument("--source-text", type=Path, required=True)
    stage_prefetch.add_argument("--expected-unit", required=True)
    stage_prefetch.add_argument("--worker-token", required=True)
    stage_prefetch.set_defaults(handler=command_stage_prefetch_unit)

    record_prefetch_review = subparsers.add_parser(
        "record-prefetch-review",
        help="Persist a failed independent review and queue a repair.",
    )
    record_prefetch_review.add_argument("course_dir", type=Path)
    record_prefetch_review.add_argument("--review", type=Path, required=True)
    record_prefetch_review.add_argument("--expected-unit", required=True)
    record_prefetch_review.add_argument("--worker-token", required=True)
    record_prefetch_review.set_defaults(handler=command_record_prefetch_review)

    cache_unit = subparsers.add_parser(
        "cache-unit",
        help="Validate and cache one independently reviewed batch or next unit.",
    )
    cache_unit.add_argument("course_dir", type=Path)
    cache_unit.add_argument("--tree", type=Path, required=True)
    cache_unit.add_argument("--review", type=Path, required=True)
    cache_unit.add_argument("--source-text", type=Path, required=True)
    cache_unit.add_argument("--expected-unit", required=True)
    cache_unit.add_argument("--worker-token")
    cache_unit.set_defaults(handler=command_cache_unit)

    activate_prefetched = subparsers.add_parser(
        "activate-prefetched-unit",
        help="Install the validated cache for the current unprepared unit.",
    )
    activate_prefetched.add_argument("course_dir", type=Path)
    activate_prefetched.add_argument("--expected-revision", type=int, required=True)
    activate_prefetched.add_argument("--expected-unit", required=True)
    activate_prefetched.set_defaults(handler=command_activate_prefetched_unit)

    fingerprint = subparsers.add_parser(
        "fingerprint", help="Fingerprint a review artifact or exact unit text."
    )
    group = fingerprint.add_mutually_exclusive_group(required=True)
    group.add_argument("--json-file", type=Path)
    group.add_argument("--text-file", type=Path)
    fingerprint.set_defaults(handler=command_fingerprint)

    prepare = subparsers.add_parser(
        "prepare-unit",
        help="Install one independently reviewed unit question tree.",
    )
    prepare.add_argument("course_dir", type=Path)
    prepare.add_argument("--tree", type=Path, required=True)
    prepare.add_argument("--review", type=Path, required=True)
    prepare.add_argument("--source-text", type=Path, required=True)
    prepare.add_argument("--expected-revision", type=int, required=True)
    prepare.add_argument("--expected-unit", required=True)
    prepare.set_defaults(handler=command_prepare_unit)

    commit = subparsers.add_parser(
        "commit", help="Record one open question or resolve one current node."
    )
    commit.add_argument("course_dir", type=Path)
    commit.add_argument("--turn", type=Path, required=True)
    commit.add_argument("--expected-revision", type=int, required=True)
    commit.add_argument("--expected-unit", required=True)
    commit.add_argument("--expected-node", required=True)
    commit.set_defaults(handler=command_commit)

    finalize = subparsers.add_parser(
        "finalize", help="Install the independently reviewed book synthesis."
    )
    finalize.add_argument("course_dir", type=Path)
    finalize.add_argument("--synthesis", type=Path, required=True)
    finalize.add_argument("--review", type=Path, required=True)
    finalize.add_argument("--expected-revision", type=int, required=True)
    finalize.set_defaults(handler=command_finalize)

    invalidate = subparsers.add_parser(
        "invalidate-unit",
        help="Archive and invalidate one unit and every later unit.",
    )
    invalidate.add_argument("course_dir", type=Path)
    invalidate.add_argument("--unit", required=True)
    invalidate.add_argument("--reason", required=True)
    invalidate.add_argument("--expected-revision", type=int, required=True)
    invalidate.set_defaults(handler=command_invalidate)

    render = subparsers.add_parser(
        "render", help="Regenerate the standalone reader."
    )
    render.add_argument("course_dir", type=Path)
    render.set_defaults(handler=command_render)

    audit = subparsers.add_parser(
        "audit", help="Validate source integrity and persisted state."
    )
    audit.add_argument("course_dir", type=Path)
    audit.set_defaults(handler=command_audit)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except BookGrillingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
