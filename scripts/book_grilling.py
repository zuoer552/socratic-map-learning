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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
RUNTIME_DIR = ".book-grilling"
STATE_FILE = "course.json"
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


def read_state(course_dir: Path) -> dict[str, Any]:
    path = state_path(course_dir)
    if not path.is_file():
        raise BookGrillingError(
            f"No Book Grilling course found at {course_dir}. Run init first."
        )
    return load_json(path)


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
    try:
        source_text = args.source_text.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BookGrillingError(
            f"Could not read exact unit text {args.source_text}: {exc}"
        ) from exc
    if not source_text.strip():
        raise BookGrillingError("Exact unit text cannot be empty")
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
    record.update(
        {
            "status": "current",
            "tree": tree,
            "review": review,
            "progress": progress,
            "current_node_id": order[0],
            "source_text_path": str(evidence_path),
            "prepared_at": utc_now(),
            "completed_at": "",
        }
    )
    state["current_node_id"] = order[0]
    state["revision"] = int(state["revision"]) + 1
    state["updated_at"] = utc_now()
    append_event(
        state,
        "unit_prepared",
        {
            "unit_id": unit_id,
            "tree_sha256": review["artifact_sha256"],
            "node_count": len(order),
        },
    )
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
    history_dir = runtime_path(course_dir) / "history"
    archived: list[str] = []
    for affected_id in state["learning_unit_ids"][start:]:
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
        {"unit_id": unit_id, "reason": reason, "archives": archived},
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
    state = read_state(args.course_dir.resolve())
    errors = validate_state(state)
    return {
        "ok": not errors,
        "errors": errors,
        "revision": state["revision"],
        "book_status": state["book_status"],
        "page_path": state["page_path"],
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
