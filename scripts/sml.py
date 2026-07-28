#!/usr/bin/env python3
"""Fast, transactional runtime for the Socratic Map Learning skill.

The authoritative learning state lives in SQLite. HTML is a deterministic,
replaceable view generated from that state; an AI never needs to patch it.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import http.server
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from validate_learning_map import LearningMapParser, validate as validate_map


SCHEMA_VERSION = 7
GRAPH_SCHEMA_VERSION = 7
RUNTIME_DIRNAME = ".socratic-map"
DB_FILENAME = "course.sqlite3"
BLUEPRINT_FILENAME = "blueprint.json"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
DIAGNOSES = {"mastered", "partial", "misconception", "unknown"}
EVIDENCE_KINDS = {
    "none",
    "own_words_reason",
    "correct_distinction",
    "correct_transfer",
}
MASTERY_EVIDENCE = EVIDENCE_KINDS - {"none"}
RELATION_MASTERY_LEVELS = {
    "unassessed",
    "understood",
    "reconstructable",
    "transferable",
    "retained",
}
LEARNING_PHASES = {
    "understanding",
    "verification",
    "critical",
    "transfer",
    "synthesis",
}
INTERACTION_KINDS = {
    "judge",
    "distinguish",
    "fill",
    "reason",
    "connect",
    "reconstruct",
    "interpret",
    "transfer",
}
RELATION_TYPES = {
    "root",
    "supports",
    "entails",
    "distinguishes",
    "limits",
    "applies",
    "contrasts",
    "previews",
    "repairs",
    "answers",
    "grounds",
    "requires",
    "motivates",
    "clarifies",
    "example_of",
    "cannot_ground",
    "causes",
    "enables",
    "prevents",
    "part_of",
    "produces",
    "transforms",
    "is_a",
    "precedes",
    "objects_to",
    "responds_to",
}
NODE_TYPES = {
    "question",
    "claim",
    "distinction",
    "mechanism",
    "example",
    "boundary",
    "objection",
}
RELATION_LABELS = {
    "supports": "支持",
    "entails": "推出",
    "distinguishes": "区分",
    "limits": "限制",
    "applies": "应用于",
    "contrasts": "形成对照",
    "previews": "预示",
    "repairs": "修正",
    "answers": "回答",
    "grounds": "提供根据",
    "requires": "要求",
    "motivates": "推动",
    "clarifies": "澄清",
    "example_of": "作为例证",
    "cannot_ground": "不能为其奠基",
    "causes": "导致",
    "enables": "使之成为可能",
    "prevents": "阻止",
    "part_of": "构成",
    "produces": "产生",
    "transforms": "转化为",
    "is_a": "属于",
    "precedes": "先于",
    "objects_to": "反驳",
    "responds_to": "回应",
}
STATUS_LABELS = {
    "mastered": "已掌握",
    "current": "正在学习",
    "future": "尚未展开",
}


class SkillError(RuntimeError):
    """A recoverable course-model or state-transition error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SkillError(f"JSON file not found: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SkillError(f"Expected a JSON object in {path}")
    return value


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def runtime_dir(course_dir: Path) -> Path:
    return course_dir.resolve() / RUNTIME_DIRNAME


def database_path(course_dir: Path) -> Path:
    return runtime_dir(course_dir) / DB_FILENAME


def blueprint_path(course_dir: Path) -> Path:
    return runtime_dir(course_dir) / BLUEPRINT_FILENAME


def template_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "map-template-v7.html"
    )


def progress_template_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "progress-template-v2.html"
    )


def default_progress_path(map_path: Path) -> Path:
    return map_path.with_name(f"{map_path.stem}-progress.html")


def course_progress_path(connection: sqlite3.Connection) -> Path:
    stored = get_meta_optional(connection, "progress_path")
    if stored:
        return Path(str(stored))
    return default_progress_path(Path(get_meta(connection, "map_path")))


def resolve_locator(
    locator: str,
    *,
    base_dir: Path,
    kind: str,
) -> str:
    if kind != "file" or not locator:
        return locator
    candidate = Path(locator).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return str(candidate)


def normalize_blueprint(
    blueprint: dict[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    result = json.loads(json.dumps(blueprint))
    incoming_schema = result.get("schema_version", 2)
    if incoming_schema in {2, 3, 4, 5, 6}:
        result["schema_version"] = SCHEMA_VERSION
    course = result.setdefault("course", {})
    course.setdefault("subtitle", "通过一次一问的对话，建立可回顾的系统关系。")
    course.setdefault("language", "zh-CN")
    source = course.setdefault("source", {})
    source.setdefault("kind", "text")
    source.setdefault("locator", "")
    source.setdefault("edition", "")
    source["locator"] = resolve_locator(
        str(source.get("locator", "")),
        base_dir=base_dir,
        kind=str(source.get("kind", "text")),
    )

    for position, section in enumerate(result.get("sections", []), start=1):
        section.setdefault("position", position)
        section.setdefault("summary", "")

    for position, anchor in enumerate(result.get("source_anchors", []), start=1):
        anchor.setdefault("position", position)
        anchor.setdefault("note", "")

    for position, node in enumerate(result.get("nodes", []), start=1):
        node.setdefault("position", position)
        node.setdefault("parent", "")
        node.setdefault("prerequisites", [])
        node.setdefault("relation", "supports" if node.get("parent") else "root")
        node.setdefault(
            "node_type",
            "question" if not node.get("parent") else "claim",
        )
        node.setdefault("common_confusions", [])
        node.setdefault("allowed_next", [])
        node.setdefault("is_final", False)
        node.setdefault("frontier_open", False)
        node.setdefault("preview", False)

    if "semantic_edges" not in result:
        result["semantic_edges"] = legacy_semantic_edges(result.get("nodes", []))
    for edge in result.get("semantic_edges", []):
        edge.setdefault("relation", "supports")
        edge.setdefault(
            "label",
            RELATION_LABELS.get(str(edge.get("relation")), str(edge.get("relation", ""))),
        )
        edge.setdefault("rationale", "")
        edge.setdefault("source_refs", [])
        edge.setdefault("origin", "reviewed")

    result.setdefault(
        "argument_atlas",
        legacy_argument_atlas_from_blueprint(result),
    )
    atlas = result["argument_atlas"]
    if isinstance(atlas, dict):
        atlas.setdefault("version", 1)
        atlas.setdefault("default_map_id", "")
        atlas.setdefault("maps", [])
        atlas.setdefault("inferences", [])
        atlas.setdefault(
            "system_spine",
            legacy_system_spine_from_atlas(atlas),
        )
        atlas.setdefault(
            "source_structure",
            legacy_source_structure_from_atlas(atlas),
        )
        source_structure = atlas["source_structure"]
        if isinstance(source_structure, dict):
            source_structure.setdefault("version", 1)
            source_structure.setdefault("label", "原书结构")
            source_structure.setdefault("unit_term", "章节")
            source_structure.setdefault("work_mode", "theory")
            source_structure.setdefault("units", [])
            for position, unit in enumerate(
                source_structure.get("units", []),
                start=1,
            ):
                if not isinstance(unit, dict):
                    continue
                unit.setdefault("position", position)
                unit.setdefault("parent_id", "")
                unit.setdefault("kind", "section")
                unit.setdefault("summary", "")
                unit.setdefault("source_refs", [])
        units = (
            source_structure.get("units", [])
            if isinstance(source_structure, dict)
            else []
        )
        fallback_unit_id = str(units[0].get("id", "")) if units else ""
        system_spine = atlas.get("system_spine", {})
        if isinstance(system_spine, dict):
            for stage in system_spine.get("stages", []):
                if not isinstance(stage, dict):
                    continue
                stage.setdefault("primary_unit_id", fallback_unit_id)
                stage.setdefault("related_unit_ids", [])

    initial = result.setdefault("initial_state", {})
    initial.setdefault("mastered", [])
    initial.setdefault("current", "")
    return result


def legacy_argument_atlas_from_blueprint(
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    """Build a recoverable v5 view for older blueprints.

    The result is deliberately marked as migrated. It keeps old courses
    renderable, but a deliberate v5 restructuring should replace it with
    reviewed multi-premise inference steps.
    """

    sections = list(blueprint.get("sections", []))
    nodes = list(blueprint.get("nodes", []))
    semantic_edges = list(blueprint.get("semantic_edges", []))
    node_by_id = {
        str(node.get("id", "")): node
        for node in nodes
        if node.get("id")
    }
    maps: list[dict[str, Any]] = []
    inferences: list[dict[str, Any]] = []
    initial = blueprint.get("initial_state", {})
    current_id = str(initial.get("current", ""))
    default_map_id = ""

    for section in sections:
        section_id = str(section.get("id", ""))
        section_nodes = [
            node
            for node in nodes
            if node.get("section") == section_id
            and node.get("node_type") != "question"
        ]
        question_nodes = [
            node
            for node in nodes
            if node.get("section") == section_id
            and node.get("node_type") == "question"
        ]
        map_id = f"map-{section_id}"
        contains_current = any(
            node.get("id") == current_id for node in section_nodes
        )
        status = "current" if contains_current else (
            "mastered" if section_nodes else "future"
        )
        conclusion_id = (
            str(section_nodes[-1].get("id", ""))
            if section_nodes
            else ""
        )
        maps.append(
            {
                "id": map_id,
                "kind": "argument",
                "parent_id": "",
                "entry_node_id": "",
                "title": str(section.get("title", "")),
                "question": (
                    str(question_nodes[0].get("title", ""))
                    if question_nodes
                    else str(section.get("title", ""))
                ),
                "summary": str(section.get("summary", "")),
                "position": int(section.get("position", len(maps) + 1)),
                "status": status,
                "conclusion_id": conclusion_id,
                "node_ids": [
                    str(node.get("id", "")) for node in section_nodes
                ],
                "source_refs": list(
                    dict.fromkeys(
                        anchor
                        for node in section_nodes
                        for anchor in node.get("source_refs", [])
                    )
                ),
                "origin": "migrated",
            }
        )
        if contains_current:
            default_map_id = map_id

        visible_ids = {
            str(node.get("id", "")) for node in section_nodes
        }
        for edge in semantic_edges:
            source_id = str(edge.get("from", ""))
            target_id = str(edge.get("to", ""))
            if source_id not in visible_ids or target_id not in visible_ids:
                continue
            inferences.append(
                {
                    "id": f"inference-{edge.get('id', '')}",
                    "map_id": map_id,
                    "premise_ids": [source_id],
                    "conclusion_id": target_id,
                    "bridge": str(
                        edge.get("rationale")
                        or edge.get("label")
                        or "由此前提推出。"
                    ),
                    "kind": "supports",
                    "source_refs": list(edge.get("source_refs", [])),
                    "mastery_edge_ids": [str(edge.get("id", ""))],
                    "origin": "migrated",
                }
            )

    if not default_map_id and maps:
        default_map_id = maps[0]["id"]
    return {
        "version": 1,
        "default_map_id": default_map_id,
        "maps": maps,
        "inferences": inferences,
    }


def legacy_system_spine_from_atlas(
    atlas: dict[str, Any],
) -> dict[str, Any]:
    """Create a conservative system spine for pre-v6 argument atlases.

    It exposes only independent root questions and labels every transition as
    migrated. A reviewed course should replace this generated sequence with a
    source-grounded problem chain.
    """

    maps = [
        argument_map
        for argument_map in atlas.get("maps", [])
        if isinstance(argument_map, dict)
        and not argument_map.get("parent_id")
    ]
    maps.sort(
        key=lambda item: (
            int(item.get("position", 0)),
            str(item.get("id", "")),
        )
    )
    stages = []
    for position, argument_map in enumerate(maps, start=1):
        future = argument_map.get("status") == "future"
        stages.append(
            {
                "id": f"stage-{argument_map.get('id', position)}",
                "position": position,
                "arc_id": "arc-course",
                "question": str(argument_map.get("question", "")),
                "map_id": str(argument_map.get("id", "")),
                "answer_id": (
                    ""
                    if future
                    else str(argument_map.get("conclusion_id", ""))
                ),
                "source_refs": list(
                    argument_map.get("source_refs", [])
                ),
                "origin": "migrated",
            }
        )
    transitions = []
    for first, second in zip(stages, stages[1:]):
        transitions.append(
            {
                "id": f"transition-{first['id']}-{second['id']}",
                "from_stage_id": first["id"],
                "to_stage_id": second["id"],
                "relation": "must_ask",
                "label": "因此必须追问",
                "bridge": (
                    "上一问题的结论改变了问题条件，因此必须继续审查"
                    "下一问题。"
                ),
                "source_refs": [],
                "origin": "migrated",
            }
        )
    return {
        "version": 1,
        "title": "全书问题推进",
        "summary": "由旧版独立论证自动迁移的问题顺序，等待来源审校。",
        "terminal_mastery": (
            "学习者能够从总问题出发，复原关键结论、理由、后续问题"
            "及其合法边界。"
        ),
        "arcs": [
            {
                "id": "arc-course",
                "position": 1,
                "title": "课程问题链",
                "summary": "等待来源审校的迁移结构。",
                "stage_ids": [stage["id"] for stage in stages],
            }
        ],
        "stages": stages,
        "transitions": transitions,
    }


def legacy_source_structure_from_atlas(
    atlas: dict[str, Any],
) -> dict[str, Any]:
    """Create one conservative source unit for pre-v7 courses."""

    return {
        "version": 1,
        "label": "原书结构",
        "unit_term": "章节",
        "work_mode": "theory",
        "units": [
            {
                "id": "unit-course",
                "position": 1,
                "parent_id": "",
                "kind": "work",
                "title": "全书",
                "summary": "尚未建立更细的原书结构，所有问题暂归于全书。",
                "source_refs": [],
            }
        ],
    }


def ensure_atlas_source_structure(
    atlas: dict[str, Any],
) -> dict[str, Any]:
    """Add v7 source navigation to an existing atlas without losing proofs."""

    upgraded = json.loads(json.dumps(atlas))
    source_structure = upgraded.setdefault(
        "source_structure",
        legacy_source_structure_from_atlas(upgraded),
    )
    source_structure.setdefault("version", 1)
    source_structure.setdefault("label", "原书结构")
    source_structure.setdefault("unit_term", "章节")
    source_structure.setdefault("work_mode", "theory")
    source_structure.setdefault("units", [])
    units = source_structure.get("units", [])
    fallback_unit_id = (
        str(units[0].get("id", ""))
        if units and isinstance(units[0], dict)
        else ""
    )
    system_spine = upgraded.setdefault(
        "system_spine",
        legacy_system_spine_from_atlas(upgraded),
    )
    for stage in system_spine.get("stages", []):
        if not isinstance(stage, dict):
            continue
        stage.setdefault("primary_unit_id", fallback_unit_id)
        stage.setdefault("related_unit_ids", [])
    return upgraded


def validate_argument_atlas(
    atlas: Any,
    *,
    nodes: dict[str, dict[str, Any]],
    semantic_edge_ids: set[str],
    anchor_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(atlas, dict):
        return ["argument_atlas must be an object"]
    if atlas.get("version") != 1:
        errors.append("argument_atlas.version must be 1")

    maps = atlas.get("maps")
    if not isinstance(maps, list) or not maps:
        errors.append("argument_atlas.maps must be a non-empty array")
        maps = []
    inferences = atlas.get("inferences")
    if not isinstance(inferences, list):
        errors.append("argument_atlas.inferences must be an array")
        inferences = []

    map_ids: list[str] = []
    maps_by_id: dict[str, dict[str, Any]] = {}
    for index, argument_map in enumerate(maps, start=1):
        if not isinstance(argument_map, dict):
            errors.append(f"argument_atlas.maps[{index}] must be an object")
            continue
        map_id = str(argument_map.get("id", ""))
        map_ids.append(map_id)
        if not ID_PATTERN.match(map_id):
            errors.append(f"argument map id is invalid: {map_id!r}")
            continue
        maps_by_id[map_id] = argument_map
        if argument_map.get("kind") not in {"book", "argument"}:
            errors.append(f"{map_id}.kind must be book or argument")
        if argument_map.get("status") not in {
            "mastered",
            "current",
            "future",
        }:
            errors.append(
                f"{map_id}.status must be mastered, current, or future"
            )
        for field in ("title", "question", "summary"):
            if not argument_map.get(field):
                errors.append(f"{map_id}.{field} is required")
        node_ids = argument_map.get("node_ids")
        if not isinstance(node_ids, list):
            errors.append(f"{map_id}.node_ids must be an array")
            node_ids = []
        if len(node_ids) != len(set(node_ids)):
            errors.append(f"{map_id}.node_ids contains duplicates")
        for node_id in node_ids:
            if node_id not in nodes:
                errors.append(f"{map_id}: unknown node {node_id!r}")
            elif nodes[node_id].get("node_type") == "question":
                errors.append(
                    f"{map_id}: question node {node_id!r} cannot appear "
                    "inside an argument graph"
                )
        conclusion_id = str(argument_map.get("conclusion_id", ""))
        if argument_map.get("status") == "future":
            if node_ids or conclusion_id:
                errors.append(
                    f"{map_id}: future maps must not expose answer nodes"
                )
        else:
            if not node_ids:
                errors.append(f"{map_id}: visible map needs proposition nodes")
            if conclusion_id not in node_ids:
                errors.append(
                    f"{map_id}.conclusion_id must be one of its node_ids"
                )
        for anchor_id in argument_map.get("source_refs", []):
            if anchor_id not in anchor_ids:
                errors.append(
                    f"{map_id}: unknown source anchor {anchor_id!r}"
                )
        if argument_map.get("origin") not in {"reviewed", "migrated"}:
            errors.append(f"{map_id}.origin must be reviewed or migrated")

    duplicate_maps = sorted(
        {item for item in map_ids if item and map_ids.count(item) > 1}
    )
    if duplicate_maps:
        errors.append(f"Duplicate argument map ids: {duplicate_maps}")
    default_map_id = str(atlas.get("default_map_id", ""))
    if default_map_id not in maps_by_id:
        errors.append("argument_atlas.default_map_id must name a map")

    system_spine = atlas.get("system_spine")
    if not isinstance(system_spine, dict):
        errors.append("argument_atlas.system_spine must be an object")
        system_spine = {}
    elif system_spine.get("version") != 1:
        errors.append("argument_atlas.system_spine.version must be 1")
    for field in ("title", "summary", "terminal_mastery"):
        if not system_spine.get(field):
            errors.append(f"argument_atlas.system_spine.{field} is required")

    stages = system_spine.get("stages", [])
    if not isinstance(stages, list) or not stages:
        errors.append("argument_atlas.system_spine.stages must be non-empty")
        stages = []
    stage_ids: list[str] = []
    stages_by_id: dict[str, dict[str, Any]] = {}
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            errors.append(f"system_spine.stages[{index}] must be an object")
            continue
        stage_id = str(stage.get("id", ""))
        stage_ids.append(stage_id)
        if not ID_PATTERN.match(stage_id):
            errors.append(f"system stage id is invalid: {stage_id!r}")
            continue
        stages_by_id[stage_id] = stage
        if not stage.get("question"):
            errors.append(f"{stage_id}.question is required")
        if not isinstance(stage.get("position"), int):
            errors.append(f"{stage_id}.position must be an integer")
        map_id = str(stage.get("map_id", ""))
        argument_map = maps_by_id.get(map_id)
        if argument_map is None:
            errors.append(f"{stage_id}: unknown proof map {map_id!r}")
        else:
            answer_id = str(stage.get("answer_id", ""))
            if argument_map.get("status") == "future":
                if answer_id:
                    errors.append(
                        f"{stage_id}: future stage must not expose an answer"
                    )
            elif answer_id != str(argument_map.get("conclusion_id", "")):
                errors.append(
                    f"{stage_id}.answer_id must equal the proof map conclusion"
                )
        for anchor_id in stage.get("source_refs", []):
            if anchor_id not in anchor_ids:
                errors.append(
                    f"{stage_id}: unknown source anchor {anchor_id!r}"
                )
        if stage.get("origin") not in {"reviewed", "migrated"}:
            errors.append(f"{stage_id}.origin must be reviewed or migrated")

    duplicate_stages = sorted(
        {item for item in stage_ids if item and stage_ids.count(item) > 1}
    )
    if duplicate_stages:
        errors.append(f"Duplicate system stage ids: {duplicate_stages}")
    ordered_stages = sorted(
        [
            stage
            for stage in stages
            if isinstance(stage, dict)
            and str(stage.get("id", "")) in stages_by_id
        ],
        key=lambda item: int(item.get("position", 0)),
    )
    ordered_ids = [str(stage.get("id", "")) for stage in ordered_stages]
    positions = [int(stage.get("position", 0)) for stage in ordered_stages]
    if positions != list(range(1, len(positions) + 1)):
        errors.append("system stage positions must be contiguous from 1")

    source_structure = atlas.get("source_structure")
    if not isinstance(source_structure, dict):
        errors.append("argument_atlas.source_structure must be an object")
        source_structure = {}
    elif source_structure.get("version") != 1:
        errors.append("argument_atlas.source_structure.version must be 1")
    for field in ("label", "unit_term", "work_mode"):
        if not source_structure.get(field):
            errors.append(
                f"argument_atlas.source_structure.{field} is required"
            )
    if source_structure.get("work_mode") not in {
        "theory",
        "history",
        "practical",
        "literature",
        "mixed",
    }:
        errors.append(
            "argument_atlas.source_structure.work_mode must be theory, "
            "history, practical, literature, or mixed"
        )
    units = source_structure.get("units", [])
    if not isinstance(units, list) or not units:
        errors.append(
            "argument_atlas.source_structure.units must be non-empty"
        )
        units = []
    unit_ids: list[str] = []
    units_by_id: dict[str, dict[str, Any]] = {}
    sibling_positions: set[tuple[str, int]] = set()
    for index, unit in enumerate(units, start=1):
        if not isinstance(unit, dict):
            errors.append(f"source_structure.units[{index}] must be an object")
            continue
        unit_id = str(unit.get("id", ""))
        unit_ids.append(unit_id)
        if not ID_PATTERN.match(unit_id):
            errors.append(f"source unit id is invalid: {unit_id!r}")
            continue
        units_by_id[unit_id] = unit
        if not unit.get("title") or not unit.get("kind"):
            errors.append(f"{unit_id}: title and kind are required")
        position = unit.get("position")
        if not isinstance(position, int) or position < 1:
            errors.append(f"{unit_id}.position must be a positive integer")
        else:
            sibling_key = (str(unit.get("parent_id", "")), position)
            if sibling_key in sibling_positions:
                errors.append(
                    f"{unit_id}: duplicate sibling source-unit position "
                    f"{position}"
                )
            sibling_positions.add(sibling_key)
        for anchor_id in unit.get("source_refs", []):
            if anchor_id not in anchor_ids:
                errors.append(
                    f"{unit_id}: unknown source anchor {anchor_id!r}"
                )
    if len(unit_ids) != len(set(unit_ids)):
        errors.append("source_structure.units contains duplicate ids")
    for unit_id, unit in units_by_id.items():
        parent_id = str(unit.get("parent_id", ""))
        if parent_id and parent_id not in units_by_id:
            errors.append(f"{unit_id}: unknown parent source unit {parent_id!r}")
        seen = {unit_id}
        cursor = parent_id
        while cursor:
            if cursor in seen:
                errors.append(f"{unit_id}: source-unit parent cycle detected")
                break
            seen.add(cursor)
            parent = units_by_id.get(cursor)
            if parent is None:
                break
            cursor = str(parent.get("parent_id", ""))

    for stage_id, stage in stages_by_id.items():
        primary_unit_id = str(stage.get("primary_unit_id", ""))
        if primary_unit_id not in units_by_id:
            errors.append(
                f"{stage_id}.primary_unit_id must name a source unit"
            )
        related_unit_ids = stage.get("related_unit_ids", [])
        if not isinstance(related_unit_ids, list):
            errors.append(f"{stage_id}.related_unit_ids must be an array")
            related_unit_ids = []
        if len(related_unit_ids) != len(set(related_unit_ids)):
            errors.append(f"{stage_id}.related_unit_ids contains duplicates")
        if primary_unit_id in related_unit_ids:
            errors.append(
                f"{stage_id}: primary source unit cannot also be related"
            )
        for unit_id in related_unit_ids:
            if unit_id not in units_by_id:
                errors.append(
                    f"{stage_id}: unknown related source unit {unit_id!r}"
                )

    arcs = system_spine.get("arcs", [])
    if not isinstance(arcs, list) or not arcs:
        errors.append("argument_atlas.system_spine.arcs must be non-empty")
        arcs = []
    arc_ids: list[str] = []
    covered_stage_ids: list[str] = []
    for index, arc in enumerate(arcs, start=1):
        if not isinstance(arc, dict):
            errors.append(f"system_spine.arcs[{index}] must be an object")
            continue
        arc_id = str(arc.get("id", ""))
        arc_ids.append(arc_id)
        if not ID_PATTERN.match(arc_id):
            errors.append(f"system arc id is invalid: {arc_id!r}")
        if not arc.get("title") or not arc.get("summary"):
            errors.append(f"{arc_id}: title and summary are required")
        arc_stage_ids = arc.get("stage_ids", [])
        if not isinstance(arc_stage_ids, list) or not arc_stage_ids:
            errors.append(f"{arc_id}.stage_ids must be non-empty")
            continue
        for stage_id in arc_stage_ids:
            if stage_id not in stages_by_id:
                errors.append(f"{arc_id}: unknown stage {stage_id!r}")
            covered_stage_ids.append(str(stage_id))
            if stages_by_id.get(str(stage_id), {}).get("arc_id") != arc_id:
                errors.append(
                    f"{stage_id}.arc_id must match containing arc {arc_id}"
                )
    if len(arc_ids) != len(set(arc_ids)):
        errors.append("system_spine.arcs contains duplicate ids")
    if sorted(covered_stage_ids) != sorted(ordered_ids):
        errors.append(
            "system arcs must cover every stage exactly once"
        )

    transitions = system_spine.get("transitions", [])
    if not isinstance(transitions, list):
        errors.append(
            "argument_atlas.system_spine.transitions must be an array"
        )
        transitions = []
    expected_pairs = list(zip(ordered_ids, ordered_ids[1:]))
    actual_pairs: list[tuple[str, str]] = []
    transition_ids: list[str] = []
    for index, transition in enumerate(transitions, start=1):
        if not isinstance(transition, dict):
            errors.append(
                f"system_spine.transitions[{index}] must be an object"
            )
            continue
        transition_id = str(transition.get("id", ""))
        transition_ids.append(transition_id)
        if not ID_PATTERN.match(transition_id):
            errors.append(
                f"system transition id is invalid: {transition_id!r}"
            )
        source_stage = str(transition.get("from_stage_id", ""))
        target_stage = str(transition.get("to_stage_id", ""))
        actual_pairs.append((source_stage, target_stage))
        if source_stage not in stages_by_id:
            errors.append(
                f"{transition_id}: unknown source stage {source_stage!r}"
            )
        if target_stage not in stages_by_id:
            errors.append(
                f"{transition_id}: unknown target stage {target_stage!r}"
            )
        if transition.get("relation") != "must_ask":
            errors.append(
                f"{transition_id}.relation must be must_ask"
            )
        if transition.get("label") != "因此必须追问":
            errors.append(
                f"{transition_id}.label must be 因此必须追问"
            )
        if not transition.get("bridge"):
            errors.append(f"{transition_id}.bridge is required")
        for anchor_id in transition.get("source_refs", []):
            if anchor_id not in anchor_ids:
                errors.append(
                    f"{transition_id}: unknown source anchor {anchor_id!r}"
                )
        if transition.get("origin") not in {"reviewed", "migrated"}:
            errors.append(
                f"{transition_id}.origin must be reviewed or migrated"
            )
    if actual_pairs != expected_pairs:
        errors.append(
            "system transitions must connect each consecutive stage once"
        )
    if len(transition_ids) != len(set(transition_ids)):
        errors.append("system_spine.transitions contains duplicate ids")

    for map_id, argument_map in maps_by_id.items():
        parent_id = str(argument_map.get("parent_id", ""))
        entry_node_id = str(argument_map.get("entry_node_id", ""))
        if parent_id:
            parent = maps_by_id.get(parent_id)
            if parent is None:
                errors.append(f"{map_id}: unknown parent map {parent_id!r}")
            elif entry_node_id not in parent.get("node_ids", []):
                errors.append(
                    f"{map_id}.entry_node_id must belong to its parent map"
                )
            elif (
                argument_map.get("status") != "future"
                and str(argument_map.get("conclusion_id", ""))
                != entry_node_id
            ):
                errors.append(
                    f"{map_id}.conclusion_id must equal entry_node_id so "
                    "the child proof can expand inline without duplicating "
                    "its conclusion"
                )
        elif entry_node_id:
            errors.append(f"{map_id}: root map cannot have entry_node_id")

        seen = {map_id}
        cursor = parent_id
        while cursor:
            if cursor in seen:
                errors.append(
                    f"{map_id}: argument-map parent cycle detected"
                )
                break
            seen.add(cursor)
            parent = maps_by_id.get(cursor)
            if parent is None:
                break
            cursor = str(parent.get("parent_id", ""))

        if argument_map.get("status") != "future":
            path_node_ids: set[str] = set()
            cursor_map: dict[str, Any] | None = argument_map
            while cursor_map is not None:
                path_node_ids.update(
                    map(str, cursor_map.get("node_ids", []))
                )
                cursor_parent_id = str(
                    cursor_map.get("parent_id", "")
                )
                cursor_map = (
                    maps_by_id.get(cursor_parent_id)
                    if cursor_parent_id
                    else None
                )
            if len(path_node_ids) > 12:
                errors.append(
                    f"{map_id}: inline root-to-child path exposes "
                    f"{len(path_node_ids)} propositions; maximum is 12"
                )

    inference_ids: list[str] = []
    inferences_by_map: dict[str, list[dict[str, Any]]] = {}
    for index, inference in enumerate(inferences, start=1):
        if not isinstance(inference, dict):
            errors.append(
                f"argument_atlas.inferences[{index}] must be an object"
            )
            continue
        inference_id = str(inference.get("id", ""))
        inference_ids.append(inference_id)
        if not ID_PATTERN.match(inference_id):
            errors.append(f"inference id is invalid: {inference_id!r}")
        map_id = str(inference.get("map_id", ""))
        argument_map = maps_by_id.get(map_id)
        if argument_map is None:
            errors.append(
                f"{inference_id}: unknown argument map {map_id!r}"
            )
            continue
        if argument_map.get("status") == "future":
            errors.append(
                f"{inference_id}: future maps cannot expose inferences"
            )
        premise_ids = inference.get("premise_ids")
        if not isinstance(premise_ids, list) or not premise_ids:
            errors.append(f"{inference_id}.premise_ids must be non-empty")
            premise_ids = []
        if len(premise_ids) != len(set(premise_ids)):
            errors.append(f"{inference_id}.premise_ids contains duplicates")
        conclusion_id = str(inference.get("conclusion_id", ""))
        map_node_ids = set(argument_map.get("node_ids", []))
        for node_id in premise_ids:
            if node_id not in map_node_ids:
                errors.append(
                    f"{inference_id}: premise {node_id!r} is not in {map_id}"
                )
        if conclusion_id not in map_node_ids:
            errors.append(
                f"{inference_id}: conclusion {conclusion_id!r} "
                f"is not in {map_id}"
            )
        if conclusion_id in premise_ids:
            errors.append(f"{inference_id}: conclusion cannot be a premise")
        if not inference.get("bridge"):
            errors.append(f"{inference_id}.bridge is required")
        if inference.get("kind") not in {
            "supports",
            "objects",
            "responds",
            "limits",
        }:
            errors.append(
                f"{inference_id}.kind must be supports, objects, responds, "
                "or limits"
            )
        for anchor_id in inference.get("source_refs", []):
            if anchor_id not in anchor_ids:
                errors.append(
                    f"{inference_id}: unknown source anchor {anchor_id!r}"
                )
        for edge_id in inference.get("mastery_edge_ids", []):
            if edge_id not in semantic_edge_ids:
                errors.append(
                    f"{inference_id}: unknown mastery edge {edge_id!r}"
                )
        if inference.get("origin") not in {"reviewed", "migrated"}:
            errors.append(
                f"{inference_id}.origin must be reviewed or migrated"
            )
        inferences_by_map.setdefault(map_id, []).append(inference)

    duplicate_inferences = sorted(
        {
            item
            for item in inference_ids
            if item and inference_ids.count(item) > 1
        }
    )
    if duplicate_inferences:
        errors.append(f"Duplicate inference ids: {duplicate_inferences}")

    for map_id, argument_map in maps_by_id.items():
        if argument_map.get("status") == "future":
            continue
        node_ids = set(argument_map.get("node_ids", []))
        if len(node_ids) > 12:
            errors.append(
                f"{map_id}: {len(node_ids)} visible propositions exceed "
                "the hard limit of 12; split a subargument"
            )
        reachable = {str(argument_map.get("conclusion_id", ""))}
        changed = True
        while changed:
            changed = False
            for inference in inferences_by_map.get(map_id, []):
                if inference.get("conclusion_id") not in reachable:
                    continue
                for premise_id in inference.get("premise_ids", []):
                    if premise_id not in reachable:
                        reachable.add(premise_id)
                        changed = True
        unreachable = sorted(node_ids - reachable)
        if unreachable:
            errors.append(
                f"{map_id}: propositions do not contribute to the final "
                f"conclusion: {unreachable}"
            )
    return errors


def legacy_semantic_edges(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a recoverable first graph for v2 courses.

    These edges are explicitly marked ``legacy`` because a lesson parent is not
    automatically a reviewed knowledge relation. ``audit`` keeps reminding the
    course author to replace them with source-reviewed semantic edges.
    """

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for node in nodes:
        node_id = str(node.get("id", ""))
        parent = str(node.get("parent", ""))
        relation = str(node.get("relation", "supports"))
        if parent and node_id:
            key = (parent, node_id, relation)
            if key not in seen:
                seen.add(key)
                edges.append(
                    {
                        "id": f"legacy-parent-{parent}-{node_id}",
                        "from": parent,
                        "to": node_id,
                        "relation": relation if relation != "root" else "supports",
                        "label": RELATION_LABELS.get(relation, "承接"),
                        "rationale": str(
                            node.get("bridge", "由旧版教学父子关系迁移，等待语义复核。")
                        ),
                        "source_refs": list(node.get("source_refs", [])),
                        "origin": "legacy",
                    }
                )
        for prerequisite in node.get("prerequisites", []):
            prerequisite_id = str(prerequisite)
            key = (prerequisite_id, node_id, "requires")
            if not prerequisite_id or not node_id or key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "id": f"legacy-prerequisite-{prerequisite_id}-{node_id}",
                    "from": prerequisite_id,
                    "to": node_id,
                    "relation": "requires",
                    "label": "作为前提",
                    "rationale": "由旧版 prerequisites 迁移。",
                    "source_refs": list(node.get("source_refs", [])),
                    "origin": "legacy",
                }
            )
    return edges


def dependency_cycles(nodes: dict[str, dict[str, Any]]) -> list[str]:
    cycles: set[str] = set()

    def visit(start: str) -> None:
        stack: list[tuple[str, tuple[str, ...]]] = [(start, ())]
        while stack:
            node_id, ancestry = stack.pop()
            if node_id in ancestry:
                cycles.add(start)
                continue
            node = nodes.get(node_id)
            if node is None:
                continue
            dependencies = []
            if node.get("parent"):
                dependencies.append(node["parent"])
            dependencies.extend(node.get("prerequisites", []))
            next_ancestry = ancestry + (node_id,)
            stack.extend((dependency, next_ancestry) for dependency in dependencies)

    for node_id in nodes:
        visit(node_id)
    return sorted(cycles)


def validate_blueprint(blueprint: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if blueprint.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION}, got "
            f"{blueprint.get('schema_version')!r}"
        )

    course = blueprint.get("course")
    if not isinstance(course, dict):
        return errors + ["course must be an object"]

    for field in ("id", "title", "language", "source"):
        if not course.get(field):
            errors.append(f"course.{field} is required")
    if course.get("id") and not ID_PATTERN.match(str(course["id"])):
        errors.append("course.id must match [a-z0-9][a-z0-9._-]*")
    source = course.get("source")
    if isinstance(source, dict):
        if source.get("kind") not in {"file", "text", "url", "document"}:
            errors.append("course.source.kind must be file, text, url, or document")
        if "locator" not in source:
            errors.append("course.source.locator is required (it may be empty for text)")
    else:
        errors.append("course.source must be an object")

    sections = blueprint.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty array")
        sections = []
    section_ids: list[str] = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            errors.append(f"sections[{index}] must be an object")
            continue
        section_id = str(section.get("id", ""))
        section_ids.append(section_id)
        if not ID_PATTERN.match(section_id):
            errors.append(f"sections[{index}].id is invalid: {section_id!r}")
        if not section.get("title"):
            errors.append(f"sections[{index}].title is required")
    duplicate_sections = sorted(
        {item for item in section_ids if item and section_ids.count(item) > 1}
    )
    if duplicate_sections:
        errors.append(f"Duplicate section ids: {duplicate_sections}")
    section_id_set = set(section_ids)

    anchors = blueprint.get("source_anchors")
    if not isinstance(anchors, list) or not anchors:
        errors.append("source_anchors must be a non-empty array")
        anchors = []
    anchor_ids: list[str] = []
    for index, anchor in enumerate(anchors, start=1):
        if not isinstance(anchor, dict):
            errors.append(f"source_anchors[{index}] must be an object")
            continue
        anchor_id = str(anchor.get("id", ""))
        anchor_ids.append(anchor_id)
        if not ID_PATTERN.match(anchor_id):
            errors.append(f"source_anchors[{index}].id is invalid: {anchor_id!r}")
        if not anchor.get("locator"):
            errors.append(f"source_anchors[{index}].locator is required")
    duplicate_anchors = sorted(
        {item for item in anchor_ids if item and anchor_ids.count(item) > 1}
    )
    if duplicate_anchors:
        errors.append(f"Duplicate source anchor ids: {duplicate_anchors}")
    anchor_id_set = set(anchor_ids)

    node_list = blueprint.get("nodes")
    if not isinstance(node_list, list) or not node_list:
        errors.append("nodes must be a non-empty array")
        node_list = []

    node_ids: list[str] = []
    nodes: dict[str, dict[str, Any]] = {}
    required_text = (
        "title",
        "summary",
        "detail",
        "bridge",
        "next",
        "mastery_criterion",
    )
    for index, node in enumerate(node_list, start=1):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = str(node.get("id", ""))
        node_ids.append(node_id)
        if not ID_PATTERN.match(node_id):
            errors.append(f"nodes[{index}].id is invalid: {node_id!r}")
        if node_id:
            nodes[node_id] = node
        for field in required_text:
            if not node.get(field):
                errors.append(f"{node_id or f'nodes[{index}]'}.{field} is required")
        if node.get("section") not in section_id_set:
            errors.append(
                f"{node_id or f'nodes[{index}]'}: unknown section {node.get('section')!r}"
            )
        if node.get("relation") not in RELATION_TYPES:
            errors.append(
                f"{node_id or f'nodes[{index}]'}: invalid relation "
                f"{node.get('relation')!r}"
            )
        if node.get("node_type") not in NODE_TYPES:
            errors.append(
                f"{node_id or f'nodes[{index}]'}: invalid node_type "
                f"{node.get('node_type')!r}"
            )
        for list_field in (
            "prerequisites",
            "source_refs",
            "common_confusions",
            "allowed_next",
        ):
            if not isinstance(node.get(list_field), list):
                errors.append(f"{node_id or f'nodes[{index}]'}.{list_field} must be an array")
        if not node.get("source_refs"):
            errors.append(f"{node_id or f'nodes[{index}]'}.source_refs must not be empty")
        for anchor_id in node.get("source_refs", []):
            if anchor_id not in anchor_id_set:
                errors.append(f"{node_id}: unknown source anchor {anchor_id!r}")

    duplicate_nodes = sorted(
        {item for item in node_ids if item and node_ids.count(item) > 1}
    )
    if duplicate_nodes:
        errors.append(f"Duplicate node ids: {duplicate_nodes}")
    node_id_set = set(node_ids)

    roots: list[str] = []
    for node_id, node in nodes.items():
        parent = node.get("parent", "")
        if parent:
            if parent not in node_id_set:
                errors.append(f"{node_id}: missing parent {parent!r}")
            if node.get("relation") == "root":
                errors.append(f"{node_id}: non-root node cannot use relation 'root'")
        else:
            roots.append(node_id)
            if node.get("relation") != "root":
                errors.append(f"{node_id}: root node must use relation 'root'")

        dependencies = list(node.get("prerequisites", []))
        for dependency in dependencies:
            if dependency not in node_id_set:
                errors.append(f"{node_id}: missing prerequisite {dependency!r}")
            if dependency == node_id:
                errors.append(f"{node_id}: cannot depend on itself")

        allowed_next = list(node.get("allowed_next", []))
        if node.get("is_final") and allowed_next:
            errors.append(f"{node_id}: final node cannot have allowed_next")
        if node.get("frontier_open") and (node.get("is_final") or allowed_next):
            errors.append(
                f"{node_id}: frontier_open requires is_final=false and no allowed_next"
            )
        if (
            not node.get("is_final")
            and not node.get("frontier_open")
            and not allowed_next
        ):
            errors.append(
                f"{node_id}: non-final node needs allowed_next; extend the frontier before use"
            )
        for target in allowed_next:
            if target not in node_id_set:
                errors.append(f"{node_id}: allowed_next target not found: {target!r}")

    if not roots:
        errors.append("Expected at least one root question or proposition")

    semantic_edges = blueprint.get("semantic_edges")
    if not isinstance(semantic_edges, list):
        errors.append("semantic_edges must be an array")
        semantic_edges = []
    edge_ids: list[str] = []
    semantic_degree = {node_id: 0 for node_id in node_id_set}
    for index, edge in enumerate(semantic_edges, start=1):
        if not isinstance(edge, dict):
            errors.append(f"semantic_edges[{index}] must be an object")
            continue
        edge_id = str(edge.get("id", ""))
        edge_ids.append(edge_id)
        if not ID_PATTERN.match(edge_id):
            errors.append(f"semantic_edges[{index}].id is invalid: {edge_id!r}")
        source_id = str(edge.get("from", ""))
        target_id = str(edge.get("to", ""))
        if source_id not in node_id_set:
            errors.append(f"{edge_id}: unknown from node {source_id!r}")
        if target_id not in node_id_set:
            errors.append(f"{edge_id}: unknown to node {target_id!r}")
        if source_id and source_id == target_id:
            errors.append(f"{edge_id}: semantic edge cannot point to itself")
        if source_id in semantic_degree:
            semantic_degree[source_id] += 1
        if target_id in semantic_degree:
            semantic_degree[target_id] += 1
        relation = edge.get("relation")
        if relation not in RELATION_TYPES - {"root"}:
            errors.append(f"{edge_id}: invalid semantic relation {relation!r}")
        if not edge.get("label"):
            errors.append(f"{edge_id}: label is required")
        if not edge.get("rationale"):
            errors.append(f"{edge_id}: rationale is required")
        if edge.get("origin") not in {"reviewed", "legacy"}:
            errors.append(f"{edge_id}: origin must be 'reviewed' or 'legacy'")
        if not isinstance(edge.get("source_refs"), list):
            errors.append(f"{edge_id}.source_refs must be an array")
        for anchor_id in edge.get("source_refs", []):
            if anchor_id not in anchor_id_set:
                errors.append(f"{edge_id}: unknown source anchor {anchor_id!r}")

    duplicate_edges = sorted(
        {item for item in edge_ids if item and edge_ids.count(item) > 1}
    )
    if duplicate_edges:
        errors.append(f"Duplicate semantic edge ids: {duplicate_edges}")
    if len(node_id_set) > 1:
        isolated = sorted(
            node_id for node_id, degree in semantic_degree.items() if degree == 0
        )
        if isolated:
            errors.append(
                "Every non-trivial course node needs a semantic relation; "
                f"isolated nodes: {isolated}"
            )

    errors.extend(
        validate_argument_atlas(
            blueprint.get("argument_atlas"),
            nodes=nodes,
            semantic_edge_ids=set(edge_ids),
            anchor_ids=anchor_id_set,
        )
    )

    cycles = dependency_cycles(nodes)
    if cycles:
        errors.append(f"Dependency cycle detected from: {cycles}")

    initial = blueprint.get("initial_state")
    if not isinstance(initial, dict):
        errors.append("initial_state must be an object")
        initial = {}
    current = initial.get("current", "")
    mastered = initial.get("mastered", [])
    if current not in node_id_set:
        errors.append(f"initial_state.current not found: {current!r}")
    if not isinstance(mastered, list):
        errors.append("initial_state.mastered must be an array")
        mastered = []
    mastered_set = set(mastered)
    for node_id in mastered:
        if node_id not in node_id_set:
            errors.append(f"initial_state.mastered node not found: {node_id!r}")
    if current in mastered_set:
        errors.append("initial_state.current cannot already be mastered")

    def dependencies_for(node_id: str) -> set[str]:
        node = nodes.get(node_id, {})
        return set(node.get("prerequisites", []))

    for node_id in mastered_set:
        missing = dependencies_for(node_id) - mastered_set
        if missing:
            errors.append(
                f"initial mastered node {node_id} has unmastered dependencies {sorted(missing)}"
            )
    if current in nodes:
        missing = dependencies_for(current) - mastered_set
        if missing:
            errors.append(
                f"initial current node {current} has unmastered dependencies {sorted(missing)}"
            )
    return errors


def open_database(course_dir: Path) -> sqlite3.Connection:
    path = database_path(course_dir)
    if not path.is_file():
        raise SkillError(
            f"No optimized course runtime at {path}. Run 'sml.py init' or "
            "'sml.py import-html' once."
        )
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_graph_schema(connection, path)
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def get_meta_optional(
    connection: sqlite3.Connection,
    key: str,
    default: Any = None,
) -> Any:
    row = connection.execute(
        "SELECT value_json FROM meta WHERE key = ?",
        (key,),
    ).fetchone()
    return default if row is None else json.loads(row["value_json"])


def legacy_argument_atlas_from_database(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    sections = [
        dict(row)
        for row in connection.execute(
            "SELECT id, title, summary, position FROM sections "
            "ORDER BY position, id"
        ).fetchall()
    ]
    nodes = []
    for row in connection.execute(
        "SELECT * FROM nodes ORDER BY position, id"
    ).fetchall():
        nodes.append(
            {
                "id": row["id"],
                "section": row["section_id"],
                "node_type": row["node_type"],
                "position": row["position"],
                "title": row["title"],
                "source_refs": json.loads(row["source_refs_json"]),
            }
        )
    semantic_edges = []
    for row in connection.execute(
        "SELECT * FROM semantic_edges ORDER BY id"
    ).fetchall():
        semantic_edges.append(
            {
                "id": row["id"],
                "from": row["from_node_id"],
                "to": row["to_node_id"],
                "label": row["label"],
                "rationale": row["rationale"],
                "source_refs": json.loads(row["source_refs_json"]),
            }
        )
    return legacy_argument_atlas_from_blueprint(
        {
            "sections": sections,
            "nodes": nodes,
            "semantic_edges": semantic_edges,
            "initial_state": {
                "current": get_meta_optional(
                    connection,
                    "current_node_id",
                    "",
                )
            },
        }
    )


def ensure_graph_schema(connection: sqlite3.Connection, path: Path) -> None:
    """Upgrade an existing runtime without losing learning state."""

    node_columns = table_columns(connection, "nodes")
    edge_table_exists = bool(table_columns(connection, "semantic_edges"))
    edge_state_exists = bool(table_columns(connection, "edge_state"))
    edge_evidence_exists = bool(table_columns(connection, "edge_evidence"))
    current_schema = int(
        get_meta_optional(connection, "schema_version", 2)
    )
    has_argument_atlas = (
        get_meta_optional(connection, "argument_atlas") is not None
    )
    needs_upgrade = (
        "node_type" not in node_columns
        or not edge_table_exists
        or not edge_state_exists
        or not edge_evidence_exists
        or current_schema < SCHEMA_VERSION
        or not has_argument_atlas
    )
    if not needs_upgrade:
        metadata_changed = False
        if get_meta_optional(connection, "progress_path") is None:
            set_meta(
                connection,
                "progress_path",
                str(
                    default_progress_path(
                        Path(get_meta(connection, "map_path"))
                    )
                ),
            )
            metadata_changed = True
        if get_meta_optional(connection, "unit_packet") is None:
            set_meta(connection, "unit_packet", {})
            metadata_changed = True
        if get_meta_optional(connection, "unit_packets") is None:
            legacy_packet = get_meta_optional(connection, "unit_packet", {})
            packets = {}
            if isinstance(legacy_packet, dict) and legacy_packet.get(
                "current_node_id"
            ):
                packets[str(legacy_packet["current_node_id"])] = legacy_packet
            set_meta(connection, "unit_packets", packets)
            metadata_changed = True
        if get_meta_optional(connection, "learning_phases") is None:
            current_id = str(get_meta_optional(connection, "current_node_id", ""))
            set_meta(
                connection,
                "learning_phases",
                {current_id: "understanding"} if current_id else {},
            )
            metadata_changed = True
        if get_meta_optional(connection, "latest_inference_step_id") is None:
            set_meta(connection, "latest_inference_step_id", "")
            metadata_changed = True
        if metadata_changed:
            connection.commit()
        return

    backup = path.with_name(f"course-pre-v{SCHEMA_VERSION}-backup.sqlite3")
    if not backup.exists():
        backup_connection = sqlite3.connect(backup)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()

    connection.execute("BEGIN IMMEDIATE")
    try:
        if "node_type" not in node_columns:
            connection.execute(
                "ALTER TABLE nodes ADD COLUMN node_type TEXT NOT NULL DEFAULT 'claim'"
            )
            connection.execute(
                "UPDATE nodes SET node_type = 'question' WHERE parent_id = ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS semantic_edges (
              id TEXT PRIMARY KEY,
              from_node_id TEXT NOT NULL REFERENCES nodes(id),
              to_node_id TEXT NOT NULL REFERENCES nodes(id),
              relation TEXT NOT NULL,
              label TEXT NOT NULL,
              rationale TEXT NOT NULL,
              source_refs_json TEXT NOT NULL,
              origin TEXT NOT NULL CHECK (origin IN ('reviewed', 'legacy'))
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_state (
              edge_id TEXT PRIMARY KEY REFERENCES semantic_edges(id)
                ON DELETE CASCADE,
              mastery_level TEXT NOT NULL DEFAULT 'unassessed'
                CHECK (
                  mastery_level IN (
                    'unassessed',
                    'understood',
                    'reconstructable',
                    'transferable',
                    'retained'
                  )
                )
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_evidence (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              edge_id TEXT NOT NULL REFERENCES semantic_edges(id)
                ON DELETE CASCADE,
              revision INTEGER NOT NULL,
              mastery_level TEXT NOT NULL,
              evidence_kind TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        edge_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM semantic_edges"
            ).fetchone()["count"]
        )
        if edge_count == 0:
            for row in connection.execute(
                "SELECT * FROM nodes ORDER BY position, id"
            ).fetchall():
                if row["parent_id"]:
                    relation = (
                        row["relation"] if row["relation"] != "root" else "supports"
                    )
                    insert_semantic_edge(
                        connection,
                        {
                            "id": f"legacy-parent-{row['parent_id']}-{row['id']}",
                            "from": row["parent_id"],
                            "to": row["id"],
                            "relation": relation,
                            "label": RELATION_LABELS.get(relation, "承接"),
                            "rationale": row["bridge"],
                            "source_refs": row_json(row, "source_refs_json"),
                            "origin": "legacy",
                        },
                    )
                for prerequisite in row_json(row, "prerequisites_json"):
                    insert_semantic_edge(
                        connection,
                        {
                            "id": (
                                f"legacy-prerequisite-{prerequisite}-{row['id']}"
                            ),
                            "from": prerequisite,
                            "to": row["id"],
                            "relation": "requires",
                            "label": "作为前提",
                            "rationale": "由旧版 prerequisites 迁移。",
                            "source_refs": row_json(row, "source_refs_json"),
                            "origin": "legacy",
                        },
                    )
        connection.execute(
            """
            INSERT OR IGNORE INTO edge_state(edge_id, mastery_level)
            SELECT id, 'unassessed' FROM semantic_edges
            """
        )
        if not has_argument_atlas:
            set_meta(
                connection,
                "argument_atlas",
                legacy_argument_atlas_from_database(connection),
            )
        atlas = get_meta(connection, "argument_atlas")
        set_meta(
            connection,
            "argument_atlas",
            ensure_atlas_source_structure(atlas),
        )
        if get_meta_optional(connection, "inference_mastery") is None:
            set_meta(connection, "inference_mastery", {})
        if get_meta_optional(connection, "progress_path") is None:
            set_meta(
                connection,
                "progress_path",
                str(
                    default_progress_path(
                        Path(get_meta(connection, "map_path"))
                    )
                ),
            )
        if get_meta_optional(connection, "unit_packet") is None:
            set_meta(connection, "unit_packet", {})
        if get_meta_optional(connection, "unit_packets") is None:
            legacy_packet = get_meta_optional(connection, "unit_packet", {})
            packets = {}
            if isinstance(legacy_packet, dict) and legacy_packet.get(
                "current_node_id"
            ):
                packets[str(legacy_packet["current_node_id"])] = legacy_packet
            set_meta(connection, "unit_packets", packets)
        if get_meta_optional(connection, "learning_phases") is None:
            current_id = str(get_meta_optional(connection, "current_node_id", ""))
            set_meta(
                connection,
                "learning_phases",
                {current_id: "understanding"} if current_id else {},
            )
        if get_meta_optional(connection, "latest_inference_step_id") is None:
            set_meta(connection, "latest_inference_step_id", "")
        set_meta(connection, "schema_version", SCHEMA_VERSION)
        set_meta(connection, "graph_schema_version", GRAPH_SCHEMA_VERSION)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE meta (
          key TEXT PRIMARY KEY,
          value_json TEXT NOT NULL
        );
        CREATE TABLE sections (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          position INTEGER NOT NULL
        );
        CREATE TABLE source_anchors (
          id TEXT PRIMARY KEY,
          locator TEXT NOT NULL,
          note TEXT NOT NULL,
          position INTEGER NOT NULL
        );
        CREATE TABLE nodes (
          id TEXT PRIMARY KEY,
          parent_id TEXT NOT NULL,
          section_id TEXT NOT NULL REFERENCES sections(id),
          position INTEGER NOT NULL,
          relation TEXT NOT NULL,
          node_type TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          detail TEXT NOT NULL,
          bridge TEXT NOT NULL,
          next_text TEXT NOT NULL,
          mastery_criterion TEXT NOT NULL,
          prerequisites_json TEXT NOT NULL,
          source_refs_json TEXT NOT NULL,
          common_confusions_json TEXT NOT NULL,
          allowed_next_json TEXT NOT NULL,
          is_final INTEGER NOT NULL CHECK (is_final IN (0, 1)),
          frontier_open INTEGER NOT NULL CHECK (frontier_open IN (0, 1)),
          preview INTEGER NOT NULL CHECK (preview IN (0, 1))
        );
        CREATE TABLE semantic_edges (
          id TEXT PRIMARY KEY,
          from_node_id TEXT NOT NULL REFERENCES nodes(id),
          to_node_id TEXT NOT NULL REFERENCES nodes(id),
          relation TEXT NOT NULL,
          label TEXT NOT NULL,
          rationale TEXT NOT NULL,
          source_refs_json TEXT NOT NULL,
          origin TEXT NOT NULL CHECK (origin IN ('reviewed', 'legacy'))
        );
        CREATE TABLE edge_state (
          edge_id TEXT PRIMARY KEY REFERENCES semantic_edges(id)
            ON DELETE CASCADE,
          mastery_level TEXT NOT NULL DEFAULT 'unassessed'
            CHECK (
              mastery_level IN (
                'unassessed',
                'understood',
                'reconstructable',
                'transferable',
                'retained'
              )
            )
        );
        CREATE TABLE edge_evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          edge_id TEXT NOT NULL REFERENCES semantic_edges(id)
            ON DELETE CASCADE,
          revision INTEGER NOT NULL,
          mastery_level TEXT NOT NULL,
          evidence_kind TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE node_state (
          node_id TEXT PRIMARY KEY REFERENCES nodes(id),
          status TEXT NOT NULL CHECK (status IN ('mastered', 'current', 'future'))
        );
        CREATE TABLE evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          node_id TEXT NOT NULL REFERENCES nodes(id),
          revision INTEGER NOT NULL,
          diagnosis TEXT NOT NULL,
          evidence_kind TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          revision INTEGER NOT NULL UNIQUE,
          event_type TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """
    )


def set_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        INSERT INTO meta(key, value_json) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
        """,
        (key, json_text(value)),
    )


def get_meta(connection: sqlite3.Connection, key: str) -> Any:
    row = connection.execute(
        "SELECT value_json FROM meta WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        raise SkillError(f"Course database is missing meta key {key!r}")
    return json.loads(row["value_json"])


def insert_semantic_edge(
    connection: sqlite3.Connection,
    edge: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO semantic_edges(
          id, from_node_id, to_node_id, relation, label, rationale,
          source_refs_json, origin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge["id"],
            edge["from"],
            edge["to"],
            edge["relation"],
            edge["label"],
            edge["rationale"],
            json_text(edge.get("source_refs", [])),
            edge.get("origin", "reviewed"),
        ),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO edge_state(edge_id, mastery_level)
        VALUES (?, 'unassessed')
        """,
        (edge["id"],),
    )


def source_snapshot(course: dict[str, Any]) -> dict[str, Any]:
    source = dict(course.get("source", {}))
    locator = str(source.get("locator", ""))
    kind = str(source.get("kind", "text"))
    fingerprint = ""
    if kind == "file" and locator:
        path = Path(locator)
        if not path.is_file():
            raise SkillError(f"Authoritative source file not found: {path}")
        fingerprint = sha256_file(path)
    source["sha256"] = fingerprint
    return source


def initialize_course(
    course_dir: Path,
    blueprint: dict[str, Any],
    *,
    map_path: Path,
    force: bool,
) -> dict[str, Any]:
    course_dir = course_dir.resolve()
    runtime = runtime_dir(course_dir)
    db_target = database_path(course_dir)
    if db_target.exists() and not force:
        raise SkillError(
            f"Optimized runtime already exists: {db_target}. "
            "Use --force only when replacement is explicitly intended."
        )
    runtime.mkdir(parents=True, exist_ok=True)
    map_path = map_path.resolve()
    map_path.parent.mkdir(parents=True, exist_ok=True)

    errors = validate_blueprint(blueprint)
    if errors:
        raise SkillError("Blueprint validation failed:\n- " + "\n- ".join(errors))

    source = source_snapshot(blueprint["course"])
    descriptor, db_temp_name = tempfile.mkstemp(
        prefix=".course.",
        suffix=".sqlite3",
        dir=runtime,
    )
    os.close(descriptor)
    db_temp = Path(db_temp_name)
    db_temp.unlink(missing_ok=True)
    connection = sqlite3.connect(db_temp)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    temporary_map: Path | None = None
    temporary_progress: Path | None = None
    try:
        create_schema(connection)
        course = blueprint["course"]
        initial = blueprint["initial_state"]
        initial_mastered = set(initial["mastered"])
        current = initial["current"]

        meta_values = {
            "schema_version": SCHEMA_VERSION,
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "course_id": course["id"],
            "course_title": course["title"],
            "course_subtitle": course.get("subtitle", ""),
            "course_language": course.get("language", "zh-CN"),
            "course_source": source,
            "course_dir": str(course_dir),
            "map_path": str(map_path),
            "progress_path": str(default_progress_path(map_path)),
            "revision": 0,
            "current_node_id": current,
            "course_complete": False,
            "blueprint_sha256": sha256_text(pretty_json(blueprint)),
            "argument_atlas": blueprint["argument_atlas"],
            "inference_mastery": {},
            "unit_packet": {},
            "unit_packets": {},
            "learning_phases": {current: "understanding"},
            "latest_inference_step_id": "",
        }
        for key, value in meta_values.items():
            set_meta(connection, key, value)

        for section in sorted(
            blueprint["sections"],
            key=lambda item: (int(item["position"]), item["id"]),
        ):
            connection.execute(
                "INSERT INTO sections(id, title, summary, position) VALUES (?, ?, ?, ?)",
                (
                    section["id"],
                    section["title"],
                    section.get("summary", ""),
                    int(section["position"]),
                ),
            )

        for anchor in sorted(
            blueprint["source_anchors"],
            key=lambda item: (int(item["position"]), item["id"]),
        ):
            connection.execute(
                """
                INSERT INTO source_anchors(id, locator, note, position)
                VALUES (?, ?, ?, ?)
                """,
                (
                    anchor["id"],
                    anchor["locator"],
                    anchor.get("note", ""),
                    int(anchor["position"]),
                ),
            )

        for node in sorted(
            blueprint["nodes"],
            key=lambda item: (int(item["position"]), item["id"]),
        ):
            connection.execute(
                """
                INSERT INTO nodes(
                  id, parent_id, section_id, position, relation, node_type,
                  title, summary,
                  detail, bridge, next_text, mastery_criterion,
                  prerequisites_json, source_refs_json, common_confusions_json,
                  allowed_next_json, is_final, frontier_open, preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node["id"],
                    node.get("parent", ""),
                    node["section"],
                    int(node["position"]),
                    node["relation"],
                    node["node_type"],
                    node["title"],
                    node["summary"],
                    node["detail"],
                    node["bridge"],
                    node["next"],
                    node["mastery_criterion"],
                    json_text(node.get("prerequisites", [])),
                    json_text(node["source_refs"]),
                    json_text(node.get("common_confusions", [])),
                    json_text(node.get("allowed_next", [])),
                    int(bool(node.get("is_final"))),
                    int(bool(node.get("frontier_open"))),
                    int(bool(node.get("preview"))),
                ),
            )
            status = (
                "mastered"
                if node["id"] in initial_mastered
                else "current"
                if node["id"] == current
                else "future"
            )
            connection.execute(
                "INSERT INTO node_state(node_id, status) VALUES (?, ?)",
                (node["id"], status),
            )

        for edge in sorted(
            blueprint["semantic_edges"],
            key=lambda item: item["id"],
        ):
            insert_semantic_edge(connection, edge)

        connection.execute(
            """
            INSERT INTO events(revision, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                0,
                "initialized",
                json_text(
                    {
                        "current": current,
                        "mastered": sorted(initial_mastered),
                        "source_sha256": source.get("sha256", ""),
                    }
                ),
                utc_now(),
            ),
        )
        connection.commit()

        (
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        ) = render_bundle_to_temporary(connection)
        connection.close()
        os.replace(db_temp, db_target)
        install_render_bundle(
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        )
        temporary_map = None
        temporary_progress = None
        atomic_write_text(blueprint_path(course_dir), pretty_json(blueprint))
    except Exception:
        connection.close()
        if temporary_map is not None:
            temporary_map.unlink(missing_ok=True)
        if temporary_progress is not None:
            temporary_progress.unlink(missing_ok=True)
        db_temp.unlink(missing_ok=True)
        raise

    with open_database(course_dir) as ready:
        return context_payload(ready)


def row_json(row: sqlite3.Row, field: str) -> list[str]:
    value = json.loads(row[field])
    if not isinstance(value, list):
        raise SkillError(f"Database field {field} is not an array for node {row['id']}")
    return [str(item) for item in value]


def status_icon(status: str) -> str:
    if status == "mastered":
        return (
            '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true">'
            '<path d="m3.5 8.2 2.8 2.7 6.2-6.1" stroke="currentColor" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg>"
        )
    if status == "current":
        return (
            '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true">'
            '<circle cx="8" cy="8" r="4.5" stroke="currentColor" stroke-width="1.6"/>'
            '<circle cx="8" cy="8" r="1.5" fill="currentColor"/></svg>'
        )
    return (
        '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true">'
        '<path d="M3 8h10" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round"/></svg>'
    )


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def node_source_text(
    row: sqlite3.Row,
    anchors: dict[str, sqlite3.Row],
) -> str:
    locators = [
        anchors[anchor_id]["locator"]
        for anchor_id in row_json(row, "source_refs_json")
        if anchor_id in anchors
    ]
    return "；".join(locators)


def edge_source_text(
    row: sqlite3.Row,
    anchors: dict[str, sqlite3.Row],
) -> str:
    locators = [
        anchors[anchor_id]["locator"]
        for anchor_id in row_json(row, "source_refs_json")
        if anchor_id in anchors
    ]
    return "；".join(locators)


def compact_edge(
    row: sqlite3.Row,
    *,
    anchors: dict[str, sqlite3.Row],
) -> dict[str, Any]:
    payload = {
        "id": row["id"],
        "from": row["from_node_id"],
        "to": row["to_node_id"],
        "relation": row["relation"],
        "label": row["label"],
        "rationale": row["rationale"],
        "source": edge_source_text(row, anchors),
        "origin": row["origin"],
    }
    if "mastery_level" in row.keys():
        payload["mastery_level"] = row["mastery_level"]
    return payload


def node_depth(node_id: str, nodes: dict[str, sqlite3.Row]) -> int:
    depth = 0
    seen: set[str] = set()
    cursor = nodes[node_id]["parent_id"]
    while cursor and cursor not in seen and cursor in nodes:
        seen.add(cursor)
        depth += 1
        cursor = nodes[cursor]["parent_id"]
    return depth


def _render_html_v3_legacy(connection: sqlite3.Connection) -> str:
    """Retained only as a migration reference for pre-v5 course data."""
    template = template_path().read_text(encoding="utf-8")
    all_sections = connection.execute(
        "SELECT * FROM sections ORDER BY position, id"
    ).fetchall()
    rows = connection.execute(
        """
        SELECT n.*, s.status
        FROM nodes n
        JOIN node_state s ON s.node_id = n.id
        ORDER BY n.position, n.id
        """
    ).fetchall()
    edge_rows = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        ORDER BY e.id
        """
    ).fetchall()
    anchor_rows = connection.execute(
        "SELECT * FROM source_anchors ORDER BY position, id"
    ).fetchall()
    anchors = {row["id"]: row for row in anchor_rows}
    nodes = {row["id"]: row for row in rows}
    node_position = {
        row["id"]: index for index, row in enumerate(rows, start=1)
    }
    rows_by_section: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        rows_by_section.setdefault(row["section_id"], []).append(row)
    sections = [
        section for section in all_sections if rows_by_section.get(section["id"])
    ]
    if not rows or not sections:
        raise SkillError("Course needs at least one visible section and node")

    revision = int(get_meta(connection, "revision"))
    complete = bool(get_meta(connection, "course_complete"))
    current_id = str(get_meta(connection, "current_node_id"))
    current_row = nodes.get(current_id)
    selected_row = current_row
    if selected_row is None:
        mastered_rows = [row for row in rows if row["status"] == "mastered"]
        selected_row = mastered_rows[-1] if mastered_rows else rows[0]

    counts = {
        "total": len(rows),
        "mastered": sum(row["status"] == "mastered" for row in rows),
        "current": sum(row["status"] == "current" for row in rows),
        "future": sum(row["status"] == "future" for row in rows),
    }
    progress = (
        round(counts["mastered"] / counts["total"] * 100, 1)
        if counts["total"]
        else 0
    )
    active_section = (
        current_row["section_id"]
        if current_row is not None
        else selected_row["section_id"]
    )

    latest_mastered_row = connection.execute(
        """
        SELECT node_id FROM evidence
        WHERE diagnosis = 'mastered'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    latest_mastered = (
        latest_mastered_row["node_id"] if latest_mastered_row else ""
    )

    latest_evidence: dict[str, sqlite3.Row] = {}
    for evidence_row in connection.execute(
        "SELECT * FROM evidence ORDER BY id"
    ).fetchall():
        latest_evidence[evidence_row["node_id"]] = evidence_row

    def evidence_text(node_id: str) -> str:
        evidence = latest_evidence.get(node_id)
        if evidence is None:
            return "尚无学习证据。"
        diagnosis_labels = {
            "mastered": "已掌握",
            "partial": "方向正确，仍缺一条关系",
            "misconception": "已记录并正在修正一个关键混淆",
            "unknown": "尚未形成可用判断",
        }
        kind_labels = {
            "own_words_reason": "能够用自己的话说明理由",
            "correct_distinction": "能够作出关键区分",
            "correct_transfer": "能够迁移到新例子",
            "none": "尚未达到掌握证据标准",
        }
        return (
            f"Revision {evidence['revision']} · "
            f"{diagnosis_labels.get(evidence['diagnosis'], evidence['diagnosis'])} · "
            f"{kind_labels.get(evidence['evidence_kind'], evidence['evidence_kind'])}"
        )

    problem_items: list[str] = []
    node_items: dict[str, str] = {}
    section_payload: list[dict[str, Any]] = []
    type_labels = {
        "question": "总问题",
        "claim": "结论",
        "distinction": "区分",
        "mechanism": "机制",
        "example": "例子",
        "boundary": "边界",
        "objection": "反驳",
    }

    semantic_edges: list[dict[str, Any]] = []
    for edge in edge_rows:
        from_row = nodes[edge["from_node_id"]]
        to_row = nodes[edge["to_node_id"]]
        semantic_edges.append(
            {
                **compact_edge(edge, anchors=anchors),
                "from_title": from_row["title"],
                "to_title": to_row["title"],
                "from_section": from_row["section_id"],
                "to_section": to_row["section_id"],
            }
        )

    def section_sources(section_rows: list[sqlite3.Row]) -> tuple[str, list[str]]:
        locators: list[str] = []
        for section_row in section_rows:
            for anchor_id in row_json(section_row, "source_refs_json"):
                anchor = anchors.get(anchor_id)
                if anchor is None:
                    continue
                locator = str(anchor["locator"])
                if locator and locator not in locators:
                    locators.append(locator)
        if not locators:
            return "尚未标注原文位置", []
        short = locators[0]
        if len(locators) > 1:
            short += f" · 另 {len(locators) - 1} 处"
        return short, locators

    def section_diagram(
        section_id: str,
        section_rows: list[sqlite3.Row],
    ) -> tuple[str, str]:
        internal = [
            edge
            for edge in semantic_edges
            if edge["from_section"] == section_id
            and edge["to_section"] == section_id
        ]
        if len(section_rows) == 1 and section_rows[0]["node_type"] == "question":
            return (
                "问题骨架",
                "当前只公开核心问题；答案和详细论证将在学习到这里后展开。",
            )
        relation_counts: dict[str, int] = {}
        for edge in internal:
            relation_counts[edge["relation"]] = (
                relation_counts.get(edge["relation"], 0) + 1
            )
        mechanism_nodes = sum(
            row["node_type"] == "mechanism" for row in section_rows
        )
        distinction_edges = sum(
            relation_counts.get(name, 0)
            for name in ("distinguishes", "contrasts")
        )
        causal_edges = sum(
            relation_counts.get(name, 0)
            for name in ("motivates", "repairs")
        )
        reason_edges = sum(
            relation_counts.get(name, 0)
            for name in ("grounds", "supports", "entails", "answers", "requires")
        )
        if mechanism_nodes >= 2 and mechanism_nodes > reason_edges:
            return (
                "机制图",
                "这个问题主要解释多个认识环节怎样共同产生经验。",
            )
        if distinction_edges >= max(2, causal_edges, reason_edges):
            return (
                "分类图",
                "这个问题主要通过关键区分排除容易混淆的答案。",
            )
        if causal_edges > reason_edges:
            return (
                "因果图",
                "这个问题主要追踪一种认识要求如何产生后续结果。",
            )
        return (
            "论证图",
            "这个问题由多条理由汇合到结论，适合从前提追踪到当前缺口。",
        )

    for index, section in enumerate(sections, start=1):
        section_id = section["id"]
        section_rows = rows_by_section[section_id]
        active = section_id == active_section
        section_current = next(
            (row for row in section_rows if row["status"] == "current"),
            None,
        )
        mastered_rows = [
            row for row in section_rows if row["status"] == "mastered"
        ]
        if section_current is not None:
            problem_status = "current"
            problem_status_label = "正在学习"
            answer_class = "problem-gap"
            answer_text = f"当前缺口：{section_current['summary']}"
        elif len(mastered_rows) == len(section_rows):
            problem_status = "mastered"
            problem_status_label = "已掌握"
            answer_class = "problem-answer"
            answer_candidates = [
                row
                for row in mastered_rows
                if row["node_type"] in {"claim", "distinction", "mechanism"}
            ]
            answer_row = answer_candidates[-1] if answer_candidates else mastered_rows[-1]
            answer_text = f"已得到：{answer_row['summary']}"
        else:
            problem_status = "future"
            problem_status_label = "尚未展开"
            answer_class = "problem-answer locked"
            answer_text = "答案尚未解锁"
        source_short, source_full = section_sources(section_rows)
        diagram_type, diagram_reason = section_diagram(
            section_id,
            section_rows,
        )
        problem_items.append(
            "<li>"
            f'<button id="{escape(section_id)}" '
            f'class="problem-item {problem_status}{" active" if active else ""}" '
            f'type="button" data-section-id="{escape(section_id)}" '
            f'data-problem-status="{problem_status}"'
            + (' aria-current="step"' if active else "")
            + ">"
            '<span class="problem-topline">'
            f'<span class="problem-index-number">{index:02d}</span>'
            f'<span class="problem-state">{status_icon(problem_status)}'
            f"{problem_status_label}</span>"
            "</span>"
            f'<strong class="problem-question">{escape(section["title"])}</strong>'
            f'<span class="problem-role">{escape(section["summary"])}</span>'
            f'<span class="problem-source">{escape(source_short)}</span>'
            f'<span class="{answer_class}">{escape(answer_text)}</span>'
            "</button></li>"
        )
        section_payload.append(
            {
                "id": section_id,
                "title": section["title"],
                "role": section["summary"],
                "status": problem_status,
                "status_label": problem_status_label,
                "answer": answer_text,
                "source": source_short,
                "source_full": source_full,
                "diagram_type": diagram_type,
                "diagram_reason": diagram_reason,
                "node_ids": [row["id"] for row in section_rows],
            }
        )
        for row in section_rows:
            status = row["status"]
            label = STATUS_LABELS[status]
            aria_current = ' aria-current="step"' if status == "current" else ""
            preview_label = " · 预览" if row["preview"] else ""
            recent_class = (
                " recently-mastered" if row["id"] == latest_mastered else ""
            )
            source_text = node_source_text(row, anchors)
            answer_hidden = status == "future"
            public_summary = (
                "答案将在学习到本问题后展开。"
                if answer_hidden
                else row["summary"]
            )
            public_detail = (
                "这是全书问题索引中的未来问题。当前只公开问题本身和原文位置。"
                if answer_hidden
                else row["detail"]
            )
            public_bridge = (
                "该问题与前后问题的关系已经记录，但具体答案尚未解锁。"
                if answer_hidden
                else row["bridge"]
            )
            public_next = (
                "继续完成当前学习路线后解锁。"
                if answer_hidden
                else row["next_text"]
            )
            public_mastery = (
                "学习到此问题后显示掌握标准。"
                if answer_hidden
                else row["mastery_criterion"]
            )
            node_markup = (
                f'<button id="{escape(row["id"])}" '
                f'class="knowledge-node {status}{recent_class}" type="button" '
                f'data-parent="{escape(row["parent_id"])}" '
                f'data-section="{escape(section_id)}" '
                f'data-node-type="{escape(row["node_type"])}" '
                f'data-status="{status}" '
                f'data-position="{node_position[row["id"]]}" '
                f'data-answer-hidden="{"true" if answer_hidden else "false"}" '
                f'data-source="{escape(source_text)}" '
                f'data-title="{escape(row["title"])}" '
                f'data-summary="{escape(public_summary)}" '
                f'data-detail="{escape(public_detail)}" '
                f'data-bridge="{escape(public_bridge)}" '
                f'data-next="{escape(public_next)}" '
                f'data-mastery="{escape(public_mastery)}" '
                f'data-evidence="{escape(evidence_text(row["id"]))}" '
                f'aria-label="{escape(label + "：" + row["title"])}"{aria_current}>'
                '<span class="node-topline">'
                f'<span class="node-type">{escape(type_labels[row["node_type"]])}</span>'
                f'<span class="status-pill">{status_icon(status)}{label}{preview_label}</span>'
                "</span>"
                f'<span class="node-title">{escape(row["title"])}</span>'
                f'<span class="node-summary">{escape(public_summary)}</span>'
                f'<span class="node-index">{node_position[row["id"]]:02d}</span>'
                "</button>"
            )
            node_items[row["id"]] = node_markup

    def collect_directional(
        start_id: str,
        direction: str,
        limit: int = 9,
    ) -> set[str]:
        internal = [
            edge
            for edge in semantic_edges
            if edge["from_section"] == active_section
            and edge["to_section"] == active_section
        ]
        result = {start_id}
        queue = [start_id]
        while queue and len(result) < limit:
            cursor = queue.pop(0)
            for edge in internal:
                next_id = ""
                if direction == "incoming" and edge["to"] == cursor:
                    next_id = edge["from"]
                if direction == "outgoing" and edge["from"] == cursor:
                    next_id = edge["to"]
                if not next_id or next_id in result:
                    continue
                result.add(next_id)
                queue.append(next_id)
        return result

    def initial_visible_node_ids() -> list[str]:
        selected_id = selected_row["id"]
        if selected_row["status"] == "future":
            return [selected_id]
        internal = [
            edge
            for edge in semantic_edges
            if edge["from_section"] == active_section
            and edge["to_section"] == active_section
        ]
        visible = {selected_id}
        for edge in internal:
            if edge["to"] == selected_id:
                visible.add(edge["from"])
            if edge["from"] == selected_id:
                visible.add(edge["to"])
        if len(visible) < 5:
            for node_id in (
                collect_directional(selected_id, "incoming", 6)
                | collect_directional(selected_id, "outgoing", 6)
            ):
                if len(visible) >= 9:
                    break
                visible.add(node_id)

        incoming = sorted(
            [
                edge["from"]
                for edge in internal
                if edge["to"] == selected_id and edge["from"] in visible
            ],
            key=lambda node_id: node_position[node_id],
        )
        outgoing = sorted(
            [
                edge["to"]
                for edge in internal
                if edge["from"] == selected_id and edge["to"] in visible
            ],
            key=lambda node_id: node_position[node_id],
        )
        ordered: list[str] = []
        for node_id in (
            incoming
            + [selected_id]
            + outgoing
            + sorted(visible, key=lambda item: node_position[item])
        ):
            if node_id not in ordered:
                ordered.append(node_id)
        return ordered[:9]

    initial_node_ids = initial_visible_node_ids()
    initial_node_set = set(initial_node_ids)
    initial_node_markup = "\n".join(
        node_items[node_id] for node_id in initial_node_ids
    )
    bank_node_markup = "\n".join(
        node_items[row["id"]]
        for row in rows
        if row["id"] not in initial_node_set
    )

    def relation_list_for(node_id: str) -> str:
        relevant = [
            edge
            for edge in semantic_edges
            if node_id in {edge["from"], edge["to"]}
        ]
        if not relevant:
            return '<p class="empty-relations">暂无已审查的语义关系。</p>'
        items = []
        for edge in relevant:
            outgoing = edge["from"] == node_id
            peer_title = (
                edge["to_title"] if outgoing else edge["from_title"]
            )
            direction = "推出" if outgoing else "承接"
            items.append(
                '<li class="semantic-relation-item">'
                f'<span class="edge-direction">{direction}</span>'
                f"<strong>{escape(edge['label'])}</strong>"
                f"<span>{escape(peer_title)}</span>"
                f"<p>{escape(edge['rationale'])}</p></li>"
            )
        return "<ul>" + "".join(items) + "</ul>"

    source = get_meta(connection, "course_source")
    source_locator = str(source.get("locator", ""))
    source_name = (
        Path(source_locator).name
        if source.get("kind") == "file" and source_locator
        else source_locator or source.get("edition") or source.get("kind", "source")
    )
    selected_status = selected_row["status"]
    edge_json = json.dumps(
        semantic_edges,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    section_json = json.dumps(
        section_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    selected_answer_hidden = selected_status == "future"
    replacements = {
        "LANG": get_meta(connection, "course_language"),
        "META_DESCRIPTION": (
            f"{get_meta(connection, 'course_title')} 的问题导向学习地图"
        ),
        "PAGE_TITLE": f"{get_meta(connection, 'course_title')} · 问题导向学习地图",
        "COURSE_ID": get_meta(connection, "course_id"),
        "REVISION": revision,
        "COMPLETE": "true" if complete else "false",
        "COMPLETE_DISPLAY": "block" if complete else "none",
        "COURSE_TITLE": get_meta(connection, "course_title"),
        "COURSE_SUBTITLE": get_meta(connection, "course_subtitle"),
        "MAP_TITLE": get_meta(connection, "course_title"),
        "TOTAL": counts["total"],
        "MASTERED": counts["mastered"],
        "CURRENT_COUNT": counts["current"],
        "FUTURE": counts["future"],
        "PROGRESS_ARIA": (
            f"知识图共有{counts['total']}个节点，"
            f"已掌握{counts['mastered']}个，正在学习{counts['current']}个"
        ),
        "PROGRESS_TEXT": f"{counts['mastered']} / {counts['total']}",
        "PROGRESS_PERCENT": progress,
        "PROBLEM_ITEMS": "\n".join(problem_items),
        "INITIAL_NODE_ITEMS": initial_node_markup,
        "INITIAL_VISIBLE_COUNT": len(initial_node_ids),
        "NODE_ITEMS": bank_node_markup,
        "EDGE_JSON": edge_json,
        "SECTION_JSON": section_json,
        "ACTIVE_SECTION": active_section,
        "CURRENT_NODE_ID": current_id,
        "LOCATE_DISABLED": (
            'disabled aria-disabled="true"' if complete else ""
        ),
        "INSPECTOR_STATUS": (
            f"{status_icon(selected_status)}{STATUS_LABELS[selected_status]}"
        ),
        "INSPECTOR_TITLE": selected_row["title"],
        "INSPECTOR_DETAIL": (
            "答案尚未解锁。"
            if selected_answer_hidden
            else selected_row["detail"]
        ),
        "INSPECTOR_SOURCE": node_source_text(selected_row, anchors),
        "INSPECTOR_BRIDGE": (
            "等待学习路线解锁。"
            if selected_answer_hidden
            else selected_row["bridge"]
        ),
        "INSPECTOR_NEXT": (
            "继续当前问题。"
            if selected_answer_hidden
            else selected_row["next_text"]
        ),
        "INSPECTOR_MASTERY": (
            "解锁后显示。"
            if selected_answer_hidden
            else selected_row["mastery_criterion"]
        ),
        "INSPECTOR_EVIDENCE": evidence_text(selected_row["id"]),
        "INSPECTOR_RELATIONS": relation_list_for(selected_row["id"]),
        "SOURCE_LABEL": f"当前依据：{source_name}",
        "STRUCTURE_STATUS": "八问结构 · 已确认",
    }
    raw_keys = {
        "PROBLEM_ITEMS",
        "INITIAL_NODE_ITEMS",
        "NODE_ITEMS",
        "EDGE_JSON",
        "SECTION_JSON",
        "INSPECTOR_STATUS",
        "INSPECTOR_RELATIONS",
        "LOCATE_DISABLED",
        "COMPLETE_DISPLAY",
    }
    for key, value in replacements.items():
        replacement = str(value)
        if key not in raw_keys:
            replacement = escape(replacement)
        template = template.replace("{{" + key + "}}", replacement)

    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", template)))
    if leftovers:
        raise SkillError(f"Unresolved map template placeholders: {leftovers}")
    return template


def relation_family(relation: str) -> str:
    families = {
        "argument": {
            "supports",
            "grounds",
            "entails",
            "answers",
            "requires",
            "cannot_ground",
        },
        "challenge": {"objects_to", "responds_to", "repairs", "limits"},
        "causal": {"causes", "enables", "prevents", "motivates"},
        "mechanism": {"part_of", "produces", "transforms"},
        "classification": {"is_a", "distinguishes", "contrasts"},
        "application": {"applies", "example_of", "clarifies"},
        "process": {"precedes", "previews"},
    }
    for family, members in families.items():
        if relation in members:
            return family
    return "argument"


def graph_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return the v5 argument atlas plus its learner-mastery overlay."""

    argument_atlas = get_meta(connection, "argument_atlas")
    active_node_id = str(get_meta(connection, "current_node_id"))
    revealed_node_ids = {
        str(node_id)
        for argument_map in argument_atlas.get("maps", [])
        if argument_map.get("status") != "future"
        and str(argument_map.get("conclusion_id", "")) == active_node_id
        for node_id in argument_map.get("node_ids", [])
    }
    anchors = {
        row["id"]: row
        for row in connection.execute(
            "SELECT * FROM source_anchors ORDER BY position, id"
        ).fetchall()
    }
    section_rows = connection.execute(
        """
        SELECT s.*
        FROM sections s
        WHERE EXISTS (
          SELECT 1 FROM nodes n WHERE n.section_id = s.id
        )
        ORDER BY s.position, s.id
        """
    ).fetchall()
    node_rows = connection.execute(
        """
        SELECT n.*, ns.status
        FROM nodes n
        JOIN node_state ns ON ns.node_id = n.id
        ORDER BY n.position, n.id
        """
    ).fetchall()
    latest_evidence_rows = connection.execute(
        """
        SELECT e.*
        FROM evidence e
        JOIN (
          SELECT node_id, MAX(revision) AS revision
          FROM evidence GROUP BY node_id
        ) latest
          ON latest.node_id = e.node_id
         AND latest.revision = e.revision
        """
    ).fetchall()
    latest_evidence = {
        row["node_id"]: {
            "revision": row["revision"],
            "diagnosis": row["diagnosis"],
            "evidence_kind": row["evidence_kind"],
        }
        for row in latest_evidence_rows
    }

    nodes: list[dict[str, Any]] = []
    node_lookup: dict[str, dict[str, Any]] = {}
    for row in node_rows:
        hidden = (
            row["status"] == "future"
            and row["id"] not in revealed_node_ids
        )
        payload = {
            "id": row["id"],
            "section": row["section_id"],
            "position": int(row["position"]),
            "node_type": row["node_type"],
            "title": row["title"],
            "summary": (
                "答案将在学习到这里后展开。"
                if hidden
                else row["summary"]
            ),
            "detail": (
                "当前只公开问题本身与原文位置。"
                if hidden
                else row["detail"]
            ),
            "bridge": (
                "具体论证将在进入本问题后显示。"
                if hidden
                else row["bridge"]
            ),
            "next": (
                "完成当前学习路线后解锁。"
                if hidden
                else row["next_text"]
            ),
            "mastery_criterion": (
                "进入该问题后显示关系掌握标准。"
                if hidden
                else row["mastery_criterion"]
            ),
            "status": row["status"],
            "answer_hidden": hidden,
            "source": node_source_text(row, anchors),
            "evidence": latest_evidence.get(row["id"]),
            "is_current": row["status"] == "current",
        }
        nodes.append(payload)
        node_lookup[row["id"]] = payload

    edge_rows = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        ORDER BY e.id
        """
    ).fetchall()
    edges: list[dict[str, Any]] = []
    for row in edge_rows:
        source = node_lookup.get(row["from_node_id"])
        target = node_lookup.get(row["to_node_id"])
        if source is None or target is None:
            continue
        edges.append(
            {
                "id": row["id"],
                "from": row["from_node_id"],
                "to": row["to_node_id"],
                "from_section": source["section"],
                "to_section": target["section"],
                "relation": row["relation"],
                "family": relation_family(row["relation"]),
                "label": row["label"],
                "rationale": row["rationale"],
                "source": edge_source_text(row, anchors),
                "origin": row["origin"],
                "mastery_level": row["mastery_level"],
            }
        )

    nodes_by_section: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        nodes_by_section.setdefault(node["section"], []).append(node)

    current_id = str(get_meta(connection, "current_node_id"))
    current_node = node_lookup.get(current_id)
    sections: list[dict[str, Any]] = []
    for section in section_rows:
        section_nodes = nodes_by_section.get(section["id"], [])
        if any(node["status"] == "current" for node in section_nodes):
            status = "current"
        elif section_nodes and all(
            node["status"] == "mastered" for node in section_nodes
        ):
            status = "mastered"
        else:
            status = "future"
        internal = [
            edge
            for edge in edges
            if edge["from_section"] == section["id"]
            and edge["to_section"] == section["id"]
        ]
        family_counts: dict[str, int] = {}
        for edge in internal:
            family_counts[edge["family"]] = (
                family_counts.get(edge["family"], 0) + 1
            )
        dominant_family = (
            max(family_counts, key=family_counts.get)
            if family_counts
            else "argument"
        )
        sections.append(
            {
                "id": section["id"],
                "title": section["title"],
                "summary": section["summary"],
                "position": int(section["position"]),
                "status": status,
                "diagram_family": dominant_family,
                "node_ids": [node["id"] for node in section_nodes],
                "mastered_nodes": sum(
                    node["status"] == "mastered" for node in section_nodes
                ),
                "total_nodes": len(section_nodes),
            }
        )

    overview_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in edges:
        if edge["from_section"] == edge["to_section"]:
            continue
        key = (edge["from_section"], edge["to_section"])
        group = overview_groups.setdefault(
            key,
            {
                "id": f"overview-{key[0]}-{key[1]}",
                "from": key[0],
                "to": key[1],
                "relation": edge["relation"],
                "family": edge["family"],
                "labels": [],
                "edge_ids": [],
            },
        )
        group["edge_ids"].append(edge["id"])
        if edge["label"] not in group["labels"]:
            group["labels"].append(edge["label"])
    overview_edges = []
    for group in overview_groups.values():
        labels = group.pop("labels")
        group["label"] = "；".join(labels[:2])
        if len(labels) > 2:
            group["label"] += f"；另 {len(labels) - 2} 条"
        overview_edges.append(group)

    inference_mastery = get_meta_optional(
        connection,
        "inference_mastery",
        {},
    )
    mastery_rank = {
        level: index
        for index, level in enumerate(
            (
                "unassessed",
                "understood",
                "reconstructable",
                "transferable",
                "retained",
            )
        )
    }
    edge_lookup = {edge["id"]: edge for edge in edges}

    def atlas_source_text(source_refs: list[str]) -> str:
        parts = []
        for anchor_id in source_refs:
            anchor = anchors.get(anchor_id)
            if anchor is None:
                continue
            text = str(anchor["locator"])
            if anchor["note"]:
                text += f"（{anchor['note']}）"
            parts.append(text)
        return "；".join(parts) or "来源待补充"

    atlas_maps: list[dict[str, Any]] = []
    for argument_map in argument_atlas.get("maps", []):
        payload = dict(argument_map)
        map_nodes = [
            node_lookup[node_id]
            for node_id in argument_map.get("node_ids", [])
            if node_id in node_lookup
        ]
        if argument_map.get("status") == "future":
            payload["status"] = "future"
        elif any(node["status"] == "current" for node in map_nodes):
            payload["status"] = "current"
        elif map_nodes and all(
            node["status"] == "mastered" for node in map_nodes
        ):
            payload["status"] = "mastered"
        payload["source"] = atlas_source_text(
            list(argument_map.get("source_refs", []))
        )
        atlas_maps.append(payload)
    atlas_map_by_id = {
        argument_map["id"]: argument_map
        for argument_map in atlas_maps
    }

    atlas_inferences: list[dict[str, Any]] = []
    for inference in argument_atlas.get("inferences", []):
        payload = dict(inference)
        explicit_level = inference_mastery.get(inference["id"])
        if explicit_level in mastery_rank:
            mastery_level = explicit_level
        else:
            linked_levels = [
                edge_lookup[edge_id]["mastery_level"]
                for edge_id in inference.get("mastery_edge_ids", [])
                if edge_id in edge_lookup
            ]
            mastery_level = (
                min(linked_levels, key=mastery_rank.get)
                if linked_levels
                else "unassessed"
            )
        payload["mastery_level"] = mastery_level
        payload["source"] = atlas_source_text(
            list(inference.get("source_refs", []))
        )
        atlas_inferences.append(payload)

    current_map_id = ""
    if current_id:
        def argument_map_depth(argument_map: dict[str, Any]) -> int:
            depth = 0
            parent_id = str(argument_map.get("parent_id", ""))
            seen = {argument_map["id"]}
            while parent_id and parent_id not in seen:
                seen.add(parent_id)
                parent = atlas_map_by_id.get(parent_id)
                if parent is None:
                    break
                depth += 1
                parent_id = str(parent.get("parent_id", ""))
            return depth

        current_candidates = [
            argument_map
            for argument_map in atlas_maps
            if current_id in argument_map.get("node_ids", [])
            and argument_map.get("kind") == "argument"
        ]
        if current_candidates:
            current_map_id = sorted(
                current_candidates,
                key=lambda item: (
                    -argument_map_depth(item),
                    int(item.get("position", 0)),
                ),
            )[0]["id"]
    if not current_map_id:
        current_map_id = str(argument_atlas.get("default_map_id", ""))

    system_spine = json.loads(
        json.dumps(argument_atlas.get("system_spine", {}))
    )
    for stage in system_spine.get("stages", []):
        proof_map = atlas_map_by_id.get(str(stage.get("map_id", "")))
        answer = node_lookup.get(str(stage.get("answer_id", "")))
        matched_question_node = next(
            (
                node
                for node in nodes
                if str(node.get("title", "")).strip()
                == str(stage.get("question", "")).strip()
            ),
            None,
        )
        stage_node = answer or matched_question_node
        current_matches_stage = bool(
            current_node
            and (
                str(stage.get("answer_id", "")) == current_id
                or (
                    proof_map is not None
                    and current_id in proof_map.get("node_ids", [])
                )
                or (
                    not stage.get("answer_id")
                    and str(stage.get("question", "")).strip()
                    == str(current_node.get("title", "")).strip()
                )
            )
        )
        if current_matches_stage:
            stage["status"] = "current"
        elif stage_node is not None:
            stage["status"] = stage_node.get("status", "future")
        elif proof_map is None or proof_map.get("status") == "future":
            stage["status"] = "future"
        else:
            stage["status"] = proof_map.get("status", "mastered")
        stage["source"] = atlas_source_text(
            list(stage.get("source_refs", []))
        )
    for transition in system_spine.get("transitions", []):
        transition["source"] = atlas_source_text(
            list(transition.get("source_refs", []))
        )

    stage_by_id = {
        str(stage.get("id", "")): stage
        for stage in system_spine.get("stages", [])
    }
    source_structure = json.loads(
        json.dumps(
            argument_atlas.get(
                "source_structure",
                legacy_source_structure_from_atlas(argument_atlas),
            )
        )
    )
    source_units = source_structure.get("units", [])
    unit_by_id = {
        str(unit.get("id", "")): unit
        for unit in source_units
        if isinstance(unit, dict)
    }
    children_by_unit: dict[str, list[str]] = {}
    for unit in source_units:
        unit_id = str(unit.get("id", ""))
        parent_id = str(unit.get("parent_id", ""))
        children_by_unit.setdefault(parent_id, []).append(unit_id)
        unit["source"] = atlas_source_text(
            list(unit.get("source_refs", []))
        )
        unit["primary_stage_ids"] = [
            stage_id
            for stage_id, stage in stage_by_id.items()
            if str(stage.get("primary_unit_id", "")) == unit_id
        ]
        unit["related_stage_ids"] = [
            stage_id
            for stage_id, stage in stage_by_id.items()
            if unit_id in stage.get("related_unit_ids", [])
        ]
    for child_ids in children_by_unit.values():
        child_ids.sort(
            key=lambda unit_id: (
                int(unit_by_id.get(unit_id, {}).get("position", 0)),
                unit_id,
            )
        )
    for unit in source_units:
        unit["child_ids"] = list(
            children_by_unit.get(str(unit.get("id", "")), [])
        )

    def descendant_stage_ids(unit_id: str) -> list[str]:
        collected = list(
            unit_by_id.get(unit_id, {}).get("primary_stage_ids", [])
        )
        for child_id in children_by_unit.get(unit_id, []):
            collected.extend(descendant_stage_ids(child_id))
        return list(dict.fromkeys(collected))

    for unit in source_units:
        all_stage_ids = descendant_stage_ids(str(unit.get("id", "")))
        unit["all_stage_ids"] = all_stage_ids
        unit_stages = [
            stage_by_id[stage_id]
            for stage_id in all_stage_ids
            if stage_id in stage_by_id
        ]
        unit["completed"] = sum(
            stage.get("status") == "mastered"
            for stage in unit_stages
        )
        unit["total"] = len(unit_stages)
        if any(stage.get("status") == "current" for stage in unit_stages):
            unit["status"] = "current"
        elif unit_stages and all(
            stage.get("status") == "mastered"
            for stage in unit_stages
        ):
            unit["status"] = "mastered"
        else:
            unit["status"] = "future"

    relation_counts = {level: 0 for level in RELATION_MASTERY_LEVELS}
    for edge in edges:
        relation_counts[edge["mastery_level"]] += 1
    node_counts = {"mastered": 0, "current": 0, "future": 0}
    for node in nodes:
        node_counts[node["status"]] += 1
    learning_phases = get_meta_optional(connection, "learning_phases", {})
    if not isinstance(learning_phases, dict):
        learning_phases = {}
    unit_packets = get_meta_optional(connection, "unit_packets", {})
    if not isinstance(unit_packets, dict):
        unit_packets = {}
    map_unit_packets: dict[str, Any] = {}
    for node_id, packet in unit_packets.items():
        if not isinstance(packet, dict):
            continue
        excerpts = []
        for excerpt in packet.get("excerpts", []):
            if not isinstance(excerpt, dict):
                continue
            public_excerpt = {
                key: excerpt[key]
                for key in ("id", "text", "full_text", "translation")
                if excerpt.get(key)
            }
            if public_excerpt.get("text"):
                excerpts.append(public_excerpt)
        if excerpts:
            map_unit_packets[str(node_id)] = {
                "unit_title": str(packet.get("unit_title", "")),
                "excerpts": excerpts,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "revision": int(get_meta(connection, "revision")),
        "complete": bool(get_meta(connection, "course_complete")),
        "course": {
            "id": get_meta(connection, "course_id"),
            "title": get_meta(connection, "course_title"),
            "subtitle": get_meta(connection, "course_subtitle"),
            "language": get_meta(connection, "course_language"),
            "source": get_meta(connection, "course_source"),
            "map_path": get_meta(connection, "map_path"),
            "progress_path": str(course_progress_path(connection)),
        },
        "current": {
            "node_id": current_id,
            "section_id": current_node["section"] if current_node else "",
            "map_id": current_map_id,
        },
        "learning_cycle": {
            "current_phase": (
                str(learning_phases.get(current_id, "understanding"))
                if current_id
                else "synthesis"
            ),
            "phase_by_node": learning_phases,
            "latest_inference_step_id": str(
                get_meta_optional(
                    connection,
                    "latest_inference_step_id",
                    "",
                )
            ),
        },
        "unit_packets": map_unit_packets,
        "progress": {
            "nodes": node_counts,
            "relations": relation_counts,
        },
        "sections": sections,
        "nodes": nodes,
        "edges": edges,
        "overview_edges": sorted(
            overview_edges,
            key=lambda item: (item["from"], item["to"]),
        ),
        "argument_atlas": {
            "version": argument_atlas.get("version", 1),
            "default_map_id": argument_atlas.get("default_map_id", ""),
            "source_structure": source_structure,
            "system_spine": system_spine,
            "maps": atlas_maps,
            "inferences": atlas_inferences,
        },
    }


def render_html(
    connection: sqlite3.Connection,
    *,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Render the v7 source-guided question reader as standalone HTML."""

    template = template_path().read_text(encoding="utf-8")
    if snapshot is None:
        snapshot = graph_snapshot(connection)
    course = snapshot["course"]
    progress_href = urllib.parse.quote(
        Path(course["progress_path"]).name
    )
    replacements = {
        "LANG": course.get("language", "zh-CN"),
        "PAGE_TITLE": f"{course['title']} · 原书问题地图",
        "COURSE_TITLE": course["title"],
        "COURSE_SUBTITLE": course.get("subtitle", ""),
        "COURSE_ID": course["id"],
        "REVISION": str(snapshot["revision"]),
        "CURRENT_NODE_ID": snapshot["current"]["node_id"],
        "PROGRESS_HREF": progress_href,
        "GRAPH_DATA": json_text(snapshot).replace("</", "<\\/"),
    }
    for key, value in replacements.items():
        template = template.replace(f"{{{{{key}}}}}", escape(value) if key != "GRAPH_DATA" else value)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", template)))
    if leftovers:
        raise SkillError(f"Unresolved map template placeholders: {leftovers}")
    return template


def learning_progress_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build separate reading-position and relation-mastery progress."""

    atlas = snapshot["argument_atlas"]
    spine = atlas["system_spine"]
    stages = list(spine.get("stages", []))
    arcs = list(spine.get("arcs", []))
    stage_by_id = {stage["id"]: stage for stage in stages}
    arc_by_id = {arc["id"]: arc for arc in arcs}

    completed_stages = [
        stage for stage in stages if stage.get("status") == "mastered"
    ]
    current_stage = next(
        (stage for stage in stages if stage.get("status") == "current"),
        None,
    )
    if current_stage is None:
        current_stage = next(
            (stage for stage in stages if stage.get("status") == "future"),
            stages[-1] if stages else None,
        )

    total_stages = len(stages)
    reading_percent = (
        round(len(completed_stages) * 100 / total_stages)
        if total_stages
        else 0
    )

    map_by_id = {
        argument_map["id"]: argument_map
        for argument_map in atlas.get("maps", [])
    }
    eligible_inferences = [
        inference
        for inference in atlas.get("inferences", [])
        if map_by_id.get(str(inference.get("map_id", "")), {}).get("status")
        != "future"
    ]
    robust_levels = {"reconstructable", "transferable", "retained"}
    engaged_levels = robust_levels | {"understood"}
    robust_inferences = [
        inference
        for inference in eligible_inferences
        if inference.get("mastery_level") in robust_levels
    ]
    engaged_inferences = [
        inference
        for inference in eligible_inferences
        if inference.get("mastery_level") in engaged_levels
    ]
    mastery_percent = (
        round(len(robust_inferences) * 100 / len(eligible_inferences))
        if eligible_inferences
        else 0
    )

    current_arc = (
        arc_by_id.get(str(current_stage.get("arc_id", "")))
        if current_stage
        else None
    )
    current_position = (
        int(current_stage.get("position", 0)) if current_stage else 0
    )
    current_source = (
        str(current_stage.get("source", "")) if current_stage else ""
    )
    source_structure = atlas.get("source_structure", {})
    source_units = list(source_structure.get("units", []))
    current_unit = next(
        (
            unit
            for unit in source_units
            if current_stage
            and unit.get("id") == current_stage.get("primary_unit_id")
        ),
        None,
    )
    source_unit_payloads = []
    for unit in source_units:
        source_unit_payloads.append(
            {
                **unit,
                "questions": [
                    stage_by_id[stage_id]
                    for stage_id in unit.get("primary_stage_ids", [])
                    if stage_id in stage_by_id
                ],
            }
        )

    arc_payloads = []
    for arc in arcs:
        arc_stages = [
            stage_by_id[stage_id]
            for stage_id in arc.get("stage_ids", [])
            if stage_id in stage_by_id
        ]
        arc_payloads.append(
            {
                **arc,
                "stages": arc_stages,
                "completed": sum(
                    stage.get("status") == "mastered"
                    for stage in arc_stages
                ),
                "total": len(arc_stages),
            }
        )

    node_counts = snapshot["progress"]["nodes"]
    return {
        "revision": snapshot["revision"],
        "reading": {
            "completed": len(completed_stages),
            "total": total_stages,
            "percent": reading_percent,
            "current_position": current_position,
            "current_question": (
                str(current_stage.get("question", ""))
                if current_stage
                else "课程已完成"
            ),
            "current_source": current_source,
            "current_arc": (
                str(current_arc.get("title", ""))
                if current_arc
                else ""
            ),
            "current_unit": (
                str(current_unit.get("title", ""))
                if current_unit
                else ""
            ),
        },
        "mastery": {
            "robust": len(robust_inferences),
            "engaged": len(engaged_inferences),
            "total": len(eligible_inferences),
            "percent": mastery_percent,
            "mastered_nodes": int(node_counts.get("mastered", 0)),
            "active_nodes": int(node_counts.get("current", 0)),
            "future_nodes": int(node_counts.get("future", 0)),
        },
        "arcs": arc_payloads,
        "source_structure": {
            "label": source_structure.get("label", "原书结构"),
            "unit_term": source_structure.get("unit_term", "章节"),
            "work_mode": source_structure.get("work_mode", "theory"),
            "units": source_unit_payloads,
        },
    }


def progress_source_items(
    progress: dict[str, Any],
    *,
    map_href: str,
) -> str:
    structure = progress["source_structure"]
    units = list(structure.get("units", []))
    unit_by_id = {str(unit.get("id", "")): unit for unit in units}
    children: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        children.setdefault(str(unit.get("parent_id", "")), []).append(unit)
    for siblings in children.values():
        siblings.sort(key=lambda unit: (int(unit.get("position", 0)), str(unit.get("id", ""))))

    def render_unit(unit: dict[str, Any], depth: int) -> str:
        unit_id = str(unit.get("id", ""))
        status = str(unit.get("status", "future"))
        questions = list(unit.get("questions", []))
        child_units = children.get(unit_id, [])
        current = status == "current"
        opened = " open" if current or depth == 0 else ""
        body: list[str] = []
        summary = str(unit.get("summary", "")).strip()
        if summary:
            body.append(f"<p>{escape(summary)}</p>")
        if questions:
            body.append('<ol class="question-list">')
            for stage in sorted(
                questions,
                key=lambda item: int(item.get("position", 0)),
            ):
                stage_status = str(stage.get("status", "future"))
                aria = ' aria-current="step"' if stage_status == "current" else ""
                href = (
                    f"{map_href}#question="
                    f"{urllib.parse.quote(str(stage.get('id', '')))}"
                )
                body.append(
                    f'<li class="{escape(stage_status)}">'
                    f'<a href="{href}"{aria}>'
                    '<span class="status-dot" aria-hidden="true"></span>'
                    f'<span>第 {int(stage.get("position", 0))} 问 · '
                    f'{escape(str(stage.get("question", "")))}</span>'
                    "</a></li>"
                )
            body.append("</ol>")
        elif not child_units:
            body.append('<p class="empty-note">尚未编入问题</p>')
        for child in child_units:
            body.append(render_unit(child, depth + 1))
        return (
            f'<details class="source-unit {escape(status)}" '
            f'style="--depth: {depth}"{opened}>'
            "<summary>"
            '<span class="unit-title">'
            f'<strong>{escape(str(unit.get("title", "")))}</strong>'
            "</span>"
            f'<span class="unit-count">{int(unit.get("completed", 0))} / '
            f'{int(unit.get("total", 0))} 问</span>'
            "</summary>"
            f'<div class="unit-body">{"".join(body)}</div>'
            "</details>"
        )

    return "".join(render_unit(unit, 0) for unit in children.get("", []))


def render_progress_html(
    connection: sqlite3.Connection,
    *,
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Render the standalone reading and mastery progress page."""

    if snapshot is None:
        snapshot = graph_snapshot(connection)
    progress = learning_progress_payload(snapshot)
    course = snapshot["course"]
    reading = progress["reading"]
    mastery = progress["mastery"]
    work_mode = str(progress["source_structure"].get("work_mode", "theory"))
    mastery_copy = {
        "theory": ("条关键推理", "论证掌握"),
        "history": ("条关键历史关系", "历史关系掌握"),
        "practical": ("条关键实践关系", "实践关系掌握"),
        "literature": ("条关键解释关系", "解释关系掌握"),
        "mixed": ("条关键关系", "关系掌握"),
    }.get(work_mode, ("条关键关系", "关系掌握"))
    template = progress_template_path().read_text(encoding="utf-8")
    map_href = urllib.parse.quote(Path(course["map_path"]).name)
    replacements = {
        "LANG": course.get("language", "zh-CN"),
        "PAGE_TITLE": f"{course['title']} · 学习进度",
        "COURSE_TITLE": course["title"],
        "COURSE_SUBTITLE": course.get("subtitle", ""),
        "COURSE_ID": course["id"],
        "REVISION": str(snapshot["revision"]),
        "MAP_HREF": map_href,
        "READING_PERCENT": str(reading["percent"]),
        "READING_COMPLETED": str(reading["completed"]),
        "READING_TOTAL": str(reading["total"]),
        "CURRENT_POSITION": str(reading["current_position"]),
        "CURRENT_ARC": reading["current_arc"],
        "CURRENT_UNIT": reading["current_unit"],
        "CURRENT_QUESTION": reading["current_question"],
        "CURRENT_SOURCE": reading["current_source"],
        "MASTERY_PERCENT": str(mastery["percent"]),
        "MASTERY_ROBUST": str(mastery["robust"]),
        "MASTERY_ENGAGED": str(mastery["engaged"]),
        "MASTERY_TOTAL": str(mastery["total"]),
        "MASTERY_UNIT": mastery_copy[0],
        "MASTERY_LABEL": mastery_copy[1],
        "MASTERED_NODES": str(mastery["mastered_nodes"]),
        "SOURCE_LABEL": progress["source_structure"]["label"],
        "SOURCE_UNIT_ITEMS": progress_source_items(
            progress,
            map_href=map_href,
        ),
        "PROGRESS_DATA": json_text(progress).replace("</", "<\\/"),
    }
    raw_keys = {"SOURCE_UNIT_ITEMS", "PROGRESS_DATA"}
    for key, value in replacements.items():
        replacement = str(value)
        if key not in raw_keys:
            replacement = escape(replacement)
        template = template.replace(f"{{{{{key}}}}}", replacement)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", template)))
    if leftovers:
        raise SkillError(
            f"Unresolved progress template placeholders: {leftovers}"
        )
    return template


def render_to_temporary(
    connection: sqlite3.Connection,
    map_path: Path,
    *,
    snapshot: dict[str, Any] | None = None,
) -> Path:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{map_path.name}.",
        suffix=".html",
        dir=map_path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(render_html(connection, snapshot=snapshot))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def render_progress_to_temporary(
    connection: sqlite3.Connection,
    progress_path: Path,
    *,
    snapshot: dict[str, Any] | None = None,
) -> Path:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{progress_path.name}.",
        suffix=".html",
        dir=progress_path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(render_progress_html(connection, snapshot=snapshot))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def validate_progress_page(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors = []
    required = (
        'data-sml-progress="2"',
        'id="reading-progress"',
        'id="mastery-progress"',
        'id="source-timeline"',
        'id="progress-data"',
        'role="progressbar"',
        "阅读位置",
        "掌握进度",
        "原书进度",
    )
    for marker in required:
        if marker not in text:
            errors.append(f"Progress page missing required marker: {marker}")
    if re.search(r"\{\{[A-Z0-9_]+\}\}", text):
        errors.append("Progress page contains unresolved placeholders")
    return errors


def render_bundle_to_temporary(
    connection: sqlite3.Connection,
) -> tuple[Path, Path, Path, Path]:
    """Render and validate the map and progress page from one snapshot."""

    map_path = Path(get_meta(connection, "map_path"))
    progress_path = course_progress_path(connection)
    snapshot = graph_snapshot(connection)
    map_temporary: Path | None = None
    progress_temporary: Path | None = None
    try:
        map_temporary = render_to_temporary(
            connection,
            map_path,
            snapshot=snapshot,
        )
        progress_temporary = render_progress_to_temporary(
            connection,
            progress_path,
            snapshot=snapshot,
        )
        map_errors, _, _ = validate_map(map_temporary)
        if map_errors:
            raise SkillError(
                "Generated map validation failed:\n- "
                + "\n- ".join(map_errors)
            )
        progress_errors = validate_progress_page(progress_temporary)
        if progress_errors:
            raise SkillError(
                "Generated progress page validation failed:\n- "
                + "\n- ".join(progress_errors)
            )
        return map_path, map_temporary, progress_path, progress_temporary
    except Exception:
        if map_temporary is not None:
            map_temporary.unlink(missing_ok=True)
        if progress_temporary is not None:
            progress_temporary.unlink(missing_ok=True)
        raise


def install_render_bundle(
    map_path: Path,
    map_temporary: Path,
    progress_path: Path,
    progress_temporary: Path,
) -> None:
    """Install both derived views; stale files are repaired on next context."""

    os.replace(progress_temporary, progress_path)
    os.replace(map_temporary, map_path)


def render_atomic(connection: sqlite3.Connection) -> Path:
    (
        map_path,
        temporary,
        progress_path,
        progress_temporary,
    ) = render_bundle_to_temporary(connection)
    try:
        install_render_bundle(
            map_path,
            temporary,
            progress_path,
            progress_temporary,
        )
    finally:
        temporary.unlink(missing_ok=True)
        progress_temporary.unlink(missing_ok=True)
    return map_path


def compact_node(
    row: sqlite3.Row,
    *,
    anchors: dict[str, sqlite3.Row],
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "detail": row["detail"],
        "bridge": row["bridge"],
        "next": row["next_text"],
        "relation": row["relation"],
        "source": node_source_text(row, anchors),
        "mastery_criterion": row["mastery_criterion"],
        "common_confusions": row_json(row, "common_confusions_json"),
    }


def normalize_unit_packet(
    raw: dict[str, Any],
    *,
    current_node_id: str,
    source_sha256: str,
) -> dict[str, Any]:
    """Validate and normalize a prepared source packet for one learning unit."""

    if not isinstance(raw, dict):
        raise SkillError("Unit packet must be a JSON object")
    packet_node_id = str(raw.get("current_node_id", "")).strip()
    if packet_node_id != current_node_id:
        raise SkillError(
            "Unit packet current_node_id does not match the active node: "
            f"{packet_node_id!r} != {current_node_id!r}"
        )
    packet_source = str(raw.get("source_sha256", "")).strip()
    if packet_source and source_sha256 and packet_source != source_sha256:
        raise SkillError(
            "Unit packet source_sha256 does not match the authoritative source"
        )
    excerpts = raw.get("excerpts")
    if not isinstance(excerpts, list) or not 1 <= len(excerpts) <= 12:
        raise SkillError("Unit packet excerpts must contain 1 to 12 entries")

    normalized_excerpts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    optional_fields = (
        "full_text",
        "translation",
        "connection",
        "term",
        "question_seed",
        "interaction_kind",
        "expected_answer",
        "scope_boundary",
        "locator",
    )
    for index, item in enumerate(excerpts, start=1):
        if not isinstance(item, dict):
            raise SkillError(f"Unit packet excerpt {index} must be an object")
        excerpt_id = str(item.get("id", f"excerpt-{index}")).strip()
        text = str(item.get("text", "")).strip()
        if not excerpt_id or excerpt_id in seen_ids:
            raise SkillError(
                f"Unit packet excerpt {index} has a missing or duplicate id"
            )
        if not text:
            raise SkillError(f"Unit packet excerpt {excerpt_id!r} has no text")
        seen_ids.add(excerpt_id)
        normalized_item = {"id": excerpt_id, "text": text}
        for field in optional_fields:
            value = str(item.get(field, "")).strip()
            if value:
                normalized_item[field] = value
        interaction_kind = normalized_item.get("interaction_kind", "")
        if interaction_kind and interaction_kind not in INTERACTION_KINDS:
            raise SkillError(
                f"Unit packet excerpt {excerpt_id!r} has invalid "
                f"interaction_kind {interaction_kind!r}"
            )
        required_premises = item.get("required_premises", [])
        if required_premises is None:
            required_premises = []
        if not isinstance(required_premises, list) or not all(
            isinstance(value, str) and value.strip()
            for value in required_premises
        ):
            raise SkillError(
                f"Unit packet excerpt {excerpt_id!r} required_premises "
                "must be a list of non-empty strings"
            )
        if required_premises:
            normalized_item["required_premises"] = [
                value.strip() for value in required_premises
            ]
        normalized_excerpts.append(normalized_item)

    return {
        "version": 2,
        "status": "ready",
        "current_node_id": current_node_id,
        "unit_title": str(raw.get("unit_title", "")).strip(),
        "source_sha256": source_sha256 or packet_source,
        "prepared_at": utc_now(),
        "excerpts": normalized_excerpts,
    }


def active_unit_packet_payload(
    connection: sqlite3.Connection,
    *,
    current_node_id: str,
    include_full: bool,
) -> dict[str, Any]:
    if not current_node_id:
        return {"status": "complete", "current_node_id": ""}
    packets = get_meta_optional(connection, "unit_packets", {})
    packet = (
        packets.get(current_node_id, {})
        if isinstance(packets, dict)
        else {}
    )
    if not packet:
        packet = get_meta_optional(connection, "unit_packet", {})
    source = get_meta(connection, "course_source")
    source_sha256 = str(source.get("sha256", ""))
    ready = bool(
        isinstance(packet, dict)
        and packet.get("status") == "ready"
        and packet.get("current_node_id") == current_node_id
        and (
            not source_sha256
            or packet.get("source_sha256") == source_sha256
        )
        and packet.get("excerpts")
    )
    if not ready:
        return {
            "status": "missing",
            "current_node_id": current_node_id,
        }
    if include_full:
        return packet
    return {
        "status": "ready",
        "current_node_id": current_node_id,
        "prepared_at": packet.get("prepared_at", ""),
        "excerpt_count": len(packet.get("excerpts", [])),
    }


def context_payload(
    connection: sqlite3.Connection,
    *,
    include_unit_packet: bool = True,
) -> dict[str, Any]:
    revision = int(get_meta(connection, "revision"))
    current_id = str(get_meta(connection, "current_node_id"))
    complete = bool(get_meta(connection, "course_complete"))
    anchor_rows = connection.execute("SELECT * FROM source_anchors").fetchall()
    anchors = {row["id"]: row for row in anchor_rows}
    counts_rows = connection.execute(
        "SELECT status, COUNT(*) AS count FROM node_state GROUP BY status"
    ).fetchall()
    counts = {"mastered": 0, "current": 0, "future": 0}
    for row in counts_rows:
        counts[row["status"]] = int(row["count"])
    counts["total"] = sum(counts.values())
    learning_phases = get_meta_optional(connection, "learning_phases", {})
    if not isinstance(learning_phases, dict):
        learning_phases = {}
    current_phase = (
        str(learning_phases.get(current_id, "understanding"))
        if current_id
        else "synthesis"
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "course": {
            "id": get_meta(connection, "course_id"),
            "title": get_meta(connection, "course_title"),
            "source": get_meta(connection, "course_source"),
        },
        "receipt": {
            "revision": revision,
            "current_node_id": current_id,
        },
        "progress": counts,
        "complete": complete,
        "map_path": get_meta(connection, "map_path"),
        "progress_path": str(course_progress_path(connection)),
        "map_hash": f"#{current_id}" if current_id else "",
        "unit_packet": active_unit_packet_payload(
            connection,
            current_node_id=current_id,
            include_full=include_unit_packet,
        ),
        "learning_cycle": {
            "current_phase": current_phase,
            "phase_by_node": learning_phases,
            "latest_inference_step_id": str(
                get_meta_optional(
                    connection,
                    "latest_inference_step_id",
                    "",
                )
            ),
        },
        "current": None,
        "parent": None,
        "prerequisites": [],
        "allowed_next": [],
        "semantic_relations": {"incoming": [], "outgoing": []},
        "argument_inferences": [],
        "recent_mastered": [],
    }
    if complete:
        return payload

    row = connection.execute(
        """
        SELECT n.*, s.status
        FROM nodes n JOIN node_state s ON s.node_id = n.id
        WHERE n.id = ?
        """,
        (current_id,),
    ).fetchone()
    if row is None:
        raise SkillError(f"Current node not found: {current_id}")
    payload["current"] = compact_node(row, anchors=anchors)
    payload["current"]["is_final"] = bool(row["is_final"])
    payload["current"]["frontier_open"] = bool(row["frontier_open"])

    incoming_rows = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        WHERE e.to_node_id = ?
        ORDER BY e.relation, e.id
        """,
        (current_id,),
    ).fetchall()
    outgoing_rows = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        WHERE e.from_node_id = ?
        ORDER BY e.relation, e.id
        """,
        (current_id,),
    ).fetchall()
    payload["semantic_relations"] = {
        "incoming": [
            compact_edge(edge, anchors=anchors) for edge in incoming_rows
        ],
        "outgoing": [
            compact_edge(edge, anchors=anchors) for edge in outgoing_rows
        ],
    }
    atlas = get_meta(connection, "argument_atlas")
    inference_mastery = get_meta_optional(
        connection,
        "inference_mastery",
        {},
    )
    payload["argument_inferences"] = [
        {
            "id": inference["id"],
            "map_id": inference["map_id"],
            "premise_ids": list(inference.get("premise_ids", [])),
            "conclusion_id": inference["conclusion_id"],
            "bridge": inference["bridge"],
            "kind": inference["kind"],
            "mastery_level": inference_mastery.get(
                inference["id"],
                "unassessed",
            ),
        }
        for inference in atlas.get("inferences", [])
        if current_id in set(inference.get("premise_ids", []))
        or inference.get("conclusion_id") == current_id
    ]

    if row["parent_id"]:
        parent = connection.execute(
            """
            SELECT n.*, s.status
            FROM nodes n JOIN node_state s ON s.node_id = n.id
            WHERE n.id = ?
            """,
            (row["parent_id"],),
        ).fetchone()
        if parent:
            payload["parent"] = {
                "id": parent["id"],
                "title": parent["title"],
                "summary": parent["summary"],
                "status": parent["status"],
            }

    prerequisites = row_json(row, "prerequisites_json")
    if prerequisites:
        placeholders = ",".join("?" for _ in prerequisites)
        prerequisite_rows = connection.execute(
            f"""
            SELECT n.id, n.title, n.summary, s.status
            FROM nodes n JOIN node_state s ON s.node_id = n.id
            WHERE n.id IN ({placeholders})
            ORDER BY n.position, n.id
            """,
            prerequisites,
        ).fetchall()
        payload["prerequisites"] = [dict(item) for item in prerequisite_rows]

    allowed_next = row_json(row, "allowed_next_json")
    if allowed_next:
        placeholders = ",".join("?" for _ in allowed_next)
        next_rows = connection.execute(
            f"""
            SELECT id, title, summary, mastery_criterion
            FROM nodes
            WHERE id IN ({placeholders})
            ORDER BY position, id
            """,
            allowed_next,
        ).fetchall()
        payload["allowed_next"] = [dict(item) for item in next_rows]

    recent = connection.execute(
        """
        SELECT n.id, n.title, n.summary
        FROM nodes n
        JOIN node_state s ON s.node_id = n.id
        WHERE s.status = 'mastered'
        ORDER BY n.position DESC, n.id DESC
        LIMIT 3
        """
    ).fetchall()
    payload["recent_mastered"] = [dict(item) for item in recent]
    return payload


def prepare_unit(
    course_dir: Path,
    packet_path: Path,
    *,
    expected_revision: int,
    expected_current: str,
) -> dict[str, Any]:
    """Cache a source-grounded packet without changing learning progress."""

    raw = load_json(packet_path)
    connection = open_database(course_dir)
    try:
        connection.execute("BEGIN IMMEDIATE")
        revision = int(get_meta(connection, "revision"))
        current_id = str(get_meta(connection, "current_node_id"))
        if bool(get_meta(connection, "course_complete")):
            raise SkillError("Course is already complete")
        if revision != expected_revision:
            raise SkillError(
                f"Stale revision: expected {expected_revision}, actual {revision}. "
                "Run context and retry."
            )
        if current_id != expected_current:
            raise SkillError(
                f"Stale current node: expected {expected_current!r}, "
                f"actual {current_id!r}. Run context and retry."
            )
        course_source = get_meta(connection, "course_source")
        normalized = normalize_unit_packet(
            raw,
            current_node_id=current_id,
            source_sha256=str(course_source.get("sha256", "")),
        )
        set_meta(connection, "unit_packet", normalized)
        packets = get_meta_optional(connection, "unit_packets", {})
        if not isinstance(packets, dict):
            packets = {}
        packets[current_id] = normalized
        set_meta(connection, "unit_packets", packets)
        phases = get_meta_optional(connection, "learning_phases", {})
        if not isinstance(phases, dict):
            phases = {}
        phases.setdefault(current_id, "understanding")
        set_meta(connection, "learning_phases", phases)
        connection.commit()
        result = context_payload(connection)
        result["prepared_unit"] = {
            "current_node_id": current_id,
            "excerpt_count": len(normalized["excerpts"]),
            "prepared_at": normalized["prepared_at"],
        }
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def map_revision(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        head = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r'data-revision="(\d+)"', head)
    return int(match.group(1)) if match else None


def ensure_map_current(connection: sqlite3.Connection) -> None:
    expected = int(get_meta(connection, "revision"))
    map_path = Path(get_meta(connection, "map_path"))
    progress_path = course_progress_path(connection)
    if (
        map_revision(map_path) != expected
        or map_revision(progress_path) != expected
    ):
        render_atomic(connection)


def node_dependencies(row: sqlite3.Row) -> set[str]:
    return set(row_json(row, "prerequisites_json"))


def commit_turn(
    course_dir: Path,
    *,
    expected_revision: int,
    expected_current: str,
    diagnosis: str,
    evidence_kind: str,
    next_node: str | None,
    learning_phase: str | None = None,
    relation_edge_id: str | None = None,
    relation_level: str | None = None,
    inference_step_id: str | None = None,
    inference_level: str | None = None,
) -> dict[str, Any]:
    if diagnosis not in DIAGNOSES:
        raise SkillError(f"Invalid diagnosis: {diagnosis}")
    if evidence_kind not in EVIDENCE_KINDS:
        raise SkillError(f"Invalid evidence kind: {evidence_kind}")
    if diagnosis == "mastered" and evidence_kind not in MASTERY_EVIDENCE:
        raise SkillError("A mastered decision requires mastery evidence")
    if diagnosis != "mastered" and evidence_kind != "none":
        raise SkillError("Non-mastered decisions must use evidence kind 'none'")
    if diagnosis != "mastered" and next_node:
        raise SkillError("Only a mastered decision may advance to another node")
    if learning_phase and learning_phase not in LEARNING_PHASES:
        raise SkillError(f"Invalid learning phase: {learning_phase}")
    if bool(relation_edge_id) != bool(relation_level):
        raise SkillError(
            "--relation-edge and --relation-level must be supplied together"
        )
    if relation_level and relation_level not in RELATION_MASTERY_LEVELS - {
        "unassessed"
    }:
        raise SkillError(f"Invalid relation mastery level: {relation_level}")
    if relation_edge_id and diagnosis != "mastered":
        raise SkillError("Relation mastery evidence requires a mastered decision")
    if bool(inference_step_id) != bool(inference_level):
        raise SkillError(
            "--inference-step and --inference-level must be supplied together"
        )
    if relation_edge_id and inference_step_id:
        raise SkillError(
            "Record either an inference step or a legacy relation edge, not both"
        )
    if inference_level and inference_level not in RELATION_MASTERY_LEVELS - {
        "unassessed"
    }:
        raise SkillError(f"Invalid inference mastery level: {inference_level}")
    if inference_step_id and diagnosis != "mastered":
        raise SkillError("Inference mastery evidence requires a mastered decision")

    connection = open_database(course_dir)
    temporary_map: Path | None = None
    temporary_progress: Path | None = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        revision = int(get_meta(connection, "revision"))
        current_id = str(get_meta(connection, "current_node_id"))
        complete = bool(get_meta(connection, "course_complete"))
        if complete:
            raise SkillError("Course is already complete")
        if revision != expected_revision:
            raise SkillError(
                f"Stale revision: expected {expected_revision}, actual {revision}. "
                "Run context and retry."
            )
        if current_id != expected_current:
            raise SkillError(
                f"Stale current node: expected {expected_current!r}, "
                f"actual {current_id!r}. Run context and retry."
            )

        current = connection.execute(
            "SELECT * FROM nodes WHERE id = ?",
            (current_id,),
        ).fetchone()
        if current is None:
            raise SkillError(f"Current node not found: {current_id}")

        relation_row: sqlite3.Row | None = None
        if relation_edge_id:
            relation_row = connection.execute(
                """
                SELECT e.*, COALESCE(es.mastery_level, 'unassessed')
                  AS mastery_level
                FROM semantic_edges e
                LEFT JOIN edge_state es ON es.edge_id = e.id
                WHERE e.id = ?
                """,
                (relation_edge_id,),
            ).fetchone()
            if relation_row is None:
                raise SkillError(
                    f"Relation edge not found: {relation_edge_id}"
                )
            if current_id not in {
                relation_row["from_node_id"],
                relation_row["to_node_id"],
            }:
                raise SkillError(
                    "Relation evidence must target an edge touching the "
                    "current learning node"
                )

        inference_step: dict[str, Any] | None = None
        if inference_step_id:
            atlas = get_meta(connection, "argument_atlas")
            inference_step = next(
                (
                    item
                    for item in atlas.get("inferences", [])
                    if item.get("id") == inference_step_id
                ),
                None,
            )
            if inference_step is None:
                raise SkillError(
                    f"Inference step not found: {inference_step_id}"
                )
            touching = set(inference_step.get("premise_ids", []))
            touching.add(str(inference_step.get("conclusion_id", "")))
            if current_id not in touching:
                raise SkillError(
                    "Inference evidence must target a step touching the "
                    "current learning node"
                )

        selected_target = ""
        if diagnosis == "mastered":
            allowed_next = row_json(current, "allowed_next_json")
            if current["is_final"]:
                if allowed_next:
                    raise SkillError("Final node unexpectedly has allowed_next targets")
                if next_node:
                    raise SkillError("Final node cannot advance to another node")
                connection.execute(
                    "UPDATE node_state SET status = 'mastered' WHERE node_id = ?",
                    (current_id,),
                )
                set_meta(connection, "current_node_id", "")
                set_meta(connection, "course_complete", True)
            else:
                if not allowed_next:
                    raise SkillError(
                        "The compiled frontier ends at this node. Extend the graph "
                        "before marking it mastered."
                    )
                if next_node:
                    if next_node not in allowed_next:
                        raise SkillError(
                            f"Next node {next_node!r} is not allowed; choose from "
                            f"{allowed_next}"
                        )
                    selected_target = next_node
                elif len(allowed_next) == 1:
                    selected_target = allowed_next[0]
                else:
                    raise SkillError(
                        f"Multiple next nodes are allowed; choose one of {allowed_next}"
                    )

                target = connection.execute(
                    """
                    SELECT n.*, s.status
                    FROM nodes n JOIN node_state s ON s.node_id = n.id
                    WHERE n.id = ?
                    """,
                    (selected_target,),
                ).fetchone()
                if target is None:
                    raise SkillError(f"Next node not found: {selected_target}")
                if target["status"] != "future":
                    raise SkillError(
                        f"Next node {selected_target} is not future; "
                        f"status is {target['status']}"
                    )

                mastered = {
                    row["node_id"]
                    for row in connection.execute(
                        "SELECT node_id FROM node_state WHERE status = 'mastered'"
                    )
                }
                mastered.add(current_id)
                missing = node_dependencies(target) - mastered
                if missing:
                    raise SkillError(
                        f"Next node {selected_target} has unmastered dependencies: "
                        f"{sorted(missing)}"
                    )

                connection.execute(
                    "UPDATE node_state SET status = 'mastered' WHERE node_id = ?",
                    (current_id,),
                )
                connection.execute(
                    "UPDATE node_state SET status = 'current' WHERE node_id = ?",
                    (selected_target,),
                )
                set_meta(connection, "current_node_id", selected_target)

        learning_phases = get_meta_optional(
            connection,
            "learning_phases",
            {},
        )
        if not isinstance(learning_phases, dict):
            learning_phases = {}
        if diagnosis == "mastered":
            learning_phases[current_id] = "synthesis"
            if selected_target:
                learning_phases.setdefault(selected_target, "understanding")
        elif learning_phase:
            learning_phases[current_id] = learning_phase
        else:
            learning_phases.setdefault(current_id, "understanding")
        set_meta(connection, "learning_phases", learning_phases)

        new_revision = revision + 1
        set_meta(connection, "revision", new_revision)
        connection.execute(
            """
            INSERT INTO evidence(
              node_id, revision, diagnosis, evidence_kind, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (current_id, new_revision, diagnosis, evidence_kind, utc_now()),
        )
        if relation_row is not None and relation_level is not None:
            level_order = {
                level: index
                for index, level in enumerate(
                    (
                        "unassessed",
                        "understood",
                        "reconstructable",
                        "transferable",
                        "retained",
                    )
                )
            }
            previous_level = str(relation_row["mastery_level"])
            if level_order[relation_level] < level_order[previous_level]:
                raise SkillError(
                    "Routine learning commits cannot downgrade relation mastery; "
                    "use a reviewed structural repair instead"
                )
            connection.execute(
                """
                UPDATE edge_state SET mastery_level = ? WHERE edge_id = ?
                """,
                (relation_level, relation_edge_id),
            )
            connection.execute(
                """
                INSERT INTO edge_evidence(
                  edge_id, revision, mastery_level, evidence_kind, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    relation_edge_id,
                    new_revision,
                    relation_level,
                    evidence_kind,
                    utc_now(),
                ),
            )
        if inference_step is not None and inference_level is not None:
            level_order = {
                level: index
                for index, level in enumerate(
                    (
                        "unassessed",
                        "understood",
                        "reconstructable",
                        "transferable",
                        "retained",
                    )
                )
            }
            inference_mastery = get_meta_optional(
                connection,
                "inference_mastery",
                {},
            )
            previous_level = str(
                inference_mastery.get(
                    inference_step_id,
                    "unassessed",
                )
            )
            if level_order[inference_level] < level_order[previous_level]:
                raise SkillError(
                    "Routine learning commits cannot downgrade inference "
                    "mastery; use a reviewed structural repair instead"
                )
            inference_mastery[inference_step_id] = inference_level
            set_meta(
                connection,
                "inference_mastery",
                inference_mastery,
            )
            set_meta(
                connection,
                "latest_inference_step_id",
                inference_step_id,
            )
        connection.execute(
            """
            INSERT INTO events(revision, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                new_revision,
                "turn_committed",
                json_text(
                    {
                        "node_id": current_id,
                        "diagnosis": diagnosis,
                        "evidence_kind": evidence_kind,
                        "next_node_id": selected_target,
                        "learning_phase": learning_phases.get(
                            selected_target or current_id,
                            "synthesis" if diagnosis == "mastered" else "understanding",
                        ),
                        "relation_edge_id": relation_edge_id or "",
                        "relation_level": relation_level or "",
                        "inference_step_id": inference_step_id or "",
                        "inference_level": inference_level or "",
                    }
                ),
                utc_now(),
            ),
        )

        database_errors = validate_database(connection, deep=False)
        if database_errors:
            raise SkillError(
                "Projected database state is invalid:\n- "
                + "\n- ".join(database_errors)
            )

        (
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        ) = render_bundle_to_temporary(connection)
        connection.commit()
        install_render_bundle(
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        )
        temporary_map = None
        temporary_progress = None
        result = context_payload(connection, include_unit_packet=False)
        result["committed"] = {
            "diagnosis": diagnosis,
            "evidence_kind": evidence_kind,
            "previous_node_id": current_id,
            "next_node_id": selected_target,
            "learning_phase": learning_phases.get(
                selected_target or current_id,
                "synthesis" if diagnosis == "mastered" else "understanding",
            ),
            "relation_edge_id": relation_edge_id or "",
            "relation_level": relation_level or "",
            "inference_step_id": inference_step_id or "",
            "inference_level": inference_level or "",
        }
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        if temporary_map is not None:
            temporary_map.unlink(missing_ok=True)
        if temporary_progress is not None:
            temporary_progress.unlink(missing_ok=True)
        connection.close()


def validate_database(
    connection: sqlite3.Connection,
    *,
    deep: bool,
) -> list[str]:
    errors: list[str] = []
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"SQLite integrity check failed: {integrity}")

    rows = connection.execute(
        """
        SELECT n.*, s.status
        FROM nodes n JOIN node_state s ON s.node_id = n.id
        ORDER BY n.position, n.id
        """
    ).fetchall()
    nodes = {row["id"]: row for row in rows}
    statuses = {row["id"]: row["status"] for row in rows}
    complete = bool(get_meta(connection, "course_complete"))
    current_id = str(get_meta(connection, "current_node_id"))
    current_nodes = [node_id for node_id, status in statuses.items() if status == "current"]
    expected_current = 0 if complete else 1
    if len(current_nodes) != expected_current:
        errors.append(
            f"Expected {expected_current} current node(s), found {current_nodes}"
        )
    if complete and current_id:
        errors.append("Complete course must have an empty current_node_id")
    if not complete and current_nodes and current_nodes[0] != current_id:
        errors.append(
            f"meta current_node_id {current_id!r} does not match {current_nodes}"
        )
    learning_phases = get_meta_optional(connection, "learning_phases", {})
    if not isinstance(learning_phases, dict):
        errors.append("learning_phases must be an object")
        learning_phases = {}
    else:
        for node_id, phase in learning_phases.items():
            if node_id not in nodes:
                errors.append(
                    f"learning_phases references missing node {node_id}"
                )
            if phase not in LEARNING_PHASES:
                errors.append(
                    f"{node_id}: invalid learning phase {phase!r}"
                )
    if current_id and current_id not in learning_phases:
        errors.append("Current node must have a learning phase")

    unit_packets = get_meta_optional(connection, "unit_packets", {})
    if not isinstance(unit_packets, dict):
        errors.append("unit_packets must be an object")
    else:
        for node_id, packet in unit_packets.items():
            if node_id not in nodes:
                errors.append(f"unit_packets references missing node {node_id}")
            if not isinstance(packet, dict):
                errors.append(f"{node_id}: unit packet must be an object")
                continue
            if packet.get("current_node_id") != node_id:
                errors.append(
                    f"{node_id}: archived unit packet node id does not match"
                )

    cycles = dependency_cycles(
        {
            node_id: {
                "parent": row["parent_id"],
                "prerequisites": row_json(row, "prerequisites_json"),
            }
            for node_id, row in nodes.items()
        }
    )
    if cycles:
        errors.append(f"Dependency cycle detected from: {cycles}")

    roots = [node_id for node_id, row in nodes.items() if not row["parent_id"]]
    if not roots:
        errors.append("Knowledge graph has no root question or proposition")

    for node_id, row in nodes.items():
        if row["parent_id"] and row["parent_id"] not in nodes:
            errors.append(f"{node_id}: missing parent {row['parent_id']}")
        for dependency in row_json(row, "prerequisites_json"):
            if dependency not in nodes:
                errors.append(f"{node_id}: missing prerequisite {dependency}")
        allowed_next = row_json(row, "allowed_next_json")
        if row["is_final"] and allowed_next:
            errors.append(f"{node_id}: final node has allowed_next targets")
        if row["frontier_open"] and (row["is_final"] or allowed_next):
            errors.append(
                f"{node_id}: invalid frontier_open/final/allowed_next combination"
            )
        if not row["is_final"] and not row["frontier_open"] and not allowed_next:
            errors.append(f"{node_id}: closed non-final node has no allowed_next")
        for target in allowed_next:
            if target not in nodes:
                errors.append(f"{node_id}: missing allowed_next target {target}")
        if row["status"] in {"mastered", "current"}:
            missing = {
                dependency
                for dependency in node_dependencies(row)
                if statuses.get(dependency) != "mastered"
            }
            if missing:
                errors.append(
                    f"{node_id}: {row['status']} node has unmastered dependencies "
                    f"{sorted(missing)}"
                )

    edge_rows = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        ORDER BY e.id
        """
    ).fetchall()
    semantic_degree = {node_id: 0 for node_id in nodes}
    for edge in edge_rows:
        if edge["from_node_id"] not in nodes:
            errors.append(
                f"{edge['id']}: missing from node {edge['from_node_id']}"
            )
        if edge["to_node_id"] not in nodes:
            errors.append(
                f"{edge['id']}: missing to node {edge['to_node_id']}"
            )
        if edge["from_node_id"] == edge["to_node_id"]:
            errors.append(f"{edge['id']}: semantic edge points to itself")
        if edge["relation"] not in RELATION_TYPES - {"root"}:
            errors.append(
                f"{edge['id']}: invalid semantic relation {edge['relation']}"
            )
        if not edge["label"] or not edge["rationale"]:
            errors.append(f"{edge['id']}: label and rationale are required")
        if edge["mastery_level"] not in RELATION_MASTERY_LEVELS:
            errors.append(
                f"{edge['id']}: invalid relation mastery "
                f"{edge['mastery_level']!r}"
            )
        if edge["from_node_id"] in semantic_degree:
            semantic_degree[edge["from_node_id"]] += 1
        if edge["to_node_id"] in semantic_degree:
            semantic_degree[edge["to_node_id"]] += 1
    if len(nodes) > 1:
        isolated = sorted(
            node_id for node_id, degree in semantic_degree.items() if degree == 0
        )
        if isolated:
            errors.append(f"Semantic graph has isolated nodes: {isolated}")

    atlas_nodes = {
        node_id: {
            "id": node_id,
            "node_type": row["node_type"],
        }
        for node_id, row in nodes.items()
    }
    atlas = get_meta(connection, "argument_atlas")
    anchor_ids = {
        row["id"]
        for row in connection.execute(
            "SELECT id FROM source_anchors"
        ).fetchall()
    }
    edge_ids = {row["id"] for row in edge_rows}
    errors.extend(
        validate_argument_atlas(
            atlas,
            nodes=atlas_nodes,
            semantic_edge_ids=edge_ids,
            anchor_ids=anchor_ids,
        )
    )
    inference_ids = {
        item["id"] for item in atlas.get("inferences", [])
    }
    inference_mastery = get_meta_optional(
        connection,
        "inference_mastery",
        {},
    )
    if not isinstance(inference_mastery, dict):
        errors.append("inference_mastery must be an object")
    else:
        for inference_id, level in inference_mastery.items():
            if inference_id not in inference_ids:
                errors.append(
                    f"inference_mastery references missing step {inference_id}"
                )
            if level not in RELATION_MASTERY_LEVELS:
                errors.append(
                    f"{inference_id}: invalid inference mastery {level!r}"
                )
    latest_inference_step_id = str(
        get_meta_optional(connection, "latest_inference_step_id", "")
    )
    if (
        latest_inference_step_id
        and latest_inference_step_id not in inference_ids
    ):
        errors.append(
            "latest_inference_step_id references missing step "
            f"{latest_inference_step_id}"
        )

    if deep:
        source = get_meta(connection, "course_source")
        if source.get("kind") == "file" and source.get("locator"):
            path = Path(source["locator"])
            if not path.is_file():
                errors.append(f"Authoritative source file not found: {path}")
            else:
                actual = sha256_file(path)
                expected = source.get("sha256", "")
                if expected and actual != expected:
                    errors.append(
                        "Authoritative source hash changed; rebuild source anchors "
                        "before continuing"
                    )
    return errors


def graph_audit_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    nodes = connection.execute(
        """
        SELECT n.id, n.parent_id, n.section_id, n.position
        FROM nodes n ORDER BY n.position, n.id
        """
    ).fetchall()
    edges = connection.execute(
        """
        SELECT e.*, COALESCE(es.mastery_level, 'unassessed') AS mastery_level
        FROM semantic_edges e
        LEFT JOIN edge_state es ON es.edge_id = e.id
        ORDER BY e.id
        """
    ).fetchall()
    section_by_node = {row["id"]: row["section_id"] for row in nodes}
    incoming = {row["id"]: 0 for row in nodes}
    relation_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    relation_mastery_counts = {
        level: 0 for level in RELATION_MASTERY_LEVELS
    }
    cross_section = 0
    exact_parent_edges = 0
    for edge in edges:
        incoming[edge["to_node_id"]] = incoming.get(edge["to_node_id"], 0) + 1
        relation_counts[edge["relation"]] = (
            relation_counts.get(edge["relation"], 0) + 1
        )
        origin_counts[edge["origin"]] = origin_counts.get(edge["origin"], 0) + 1
        relation_mastery_counts[edge["mastery_level"]] += 1
        if (
            section_by_node.get(edge["from_node_id"])
            != section_by_node.get(edge["to_node_id"])
        ):
            cross_section += 1
        target = next(
            (row for row in nodes if row["id"] == edge["to_node_id"]),
            None,
        )
        if target and target["parent_id"] == edge["from_node_id"]:
            exact_parent_edges += 1

    lesson_route_edges = sum(
        len(row_json(row, "allowed_next_json"))
        for row in connection.execute(
            "SELECT id, allowed_next_json FROM nodes"
        ).fetchall()
    )
    multi_incoming = sum(count > 1 for count in incoming.values())
    sections_with_nodes = len(set(section_by_node.values()))
    warnings: list[str] = []
    edge_count = len(edges)
    node_count = len(nodes)
    atlas = get_meta(connection, "argument_atlas")
    argument_maps = list(atlas.get("maps", []))
    inference_steps = list(atlas.get("inferences", []))
    system_spine = atlas.get("system_spine", {})
    system_arcs = list(system_spine.get("arcs", []))
    system_stages = list(system_spine.get("stages", []))
    system_transitions = list(system_spine.get("transitions", []))
    reviewed_system_stages = sum(
        bool(stage.get("answer_id")) for stage in system_stages
    )
    future_system_stages = len(system_stages) - reviewed_system_stages
    migrated_system_stages = sum(
        stage.get("origin") == "migrated"
        for stage in system_stages
    )
    migrated_system_transitions = sum(
        transition.get("origin") == "migrated"
        for transition in system_transitions
    )
    visible_maps = [
        argument_map
        for argument_map in argument_maps
        if argument_map.get("status") != "future"
    ]
    multi_premise_steps = sum(
        len(inference.get("premise_ids", [])) > 1
        for inference in inference_steps
    )
    migrated_maps = sum(
        argument_map.get("origin") == "migrated"
        for argument_map in argument_maps
    )
    migrated_inferences = sum(
        inference.get("origin") == "migrated"
        for inference in inference_steps
    )
    largest_visible_map = max(
        (
            len(argument_map.get("node_ids", []))
            for argument_map in visible_maps
        ),
        default=0,
    )
    maps_by_id = {
        str(argument_map.get("id", "")): argument_map
        for argument_map in argument_maps
    }
    inline_path_sizes: list[int] = []
    for argument_map in visible_maps:
        path_node_ids: set[str] = set()
        cursor: dict[str, Any] | None = argument_map
        seen_maps: set[str] = set()
        while cursor is not None:
            cursor_id = str(cursor.get("id", ""))
            if cursor_id in seen_maps:
                break
            seen_maps.add(cursor_id)
            path_node_ids.update(map(str, cursor.get("node_ids", [])))
            parent_id = str(cursor.get("parent_id", ""))
            cursor = maps_by_id.get(parent_id) if parent_id else None
        inline_path_sizes.append(len(path_node_ids))
    largest_inline_path = max(inline_path_sizes, default=0)
    inference_mastery = get_meta_optional(
        connection,
        "inference_mastery",
        {},
    )
    inference_mastery_counts = {
        level: 0 for level in RELATION_MASTERY_LEVELS
    }
    for inference in inference_steps:
        level = inference_mastery.get(
            inference["id"],
            "unassessed",
        )
        if level not in inference_mastery_counts:
            level = "unassessed"
        inference_mastery_counts[level] += 1
    if migrated_maps or migrated_inferences:
        warnings.append(
            "论证图仍包含自动迁移结构；请用审核后的多前提推理关节替换。"
        )
    if migrated_system_stages or migrated_system_transitions:
        warnings.append(
            "系统主链仍包含自动迁移的问题或过渡；请用来源审校后的问题推进替换。"
        )
    if len(visible_maps) >= 3 and multi_premise_steps == 0:
        warnings.append(
            "可见论证没有共同前提汇合，可能仍把论证误画成单线顺序。"
        )
    if node_count >= 8 and multi_incoming == 0:
        warnings.append(
            "知识图没有任何多前提汇合点，可能仍在用单线教学顺序代替系统关系。"
        )
    if node_count >= 8 and sections_with_nodes > 1 and cross_section == 0:
        warnings.append(
            "知识图没有跨章节关系，无法显示前文结论如何支撑后文。"
        )
    if edge_count:
        legacy_ratio = origin_counts.get("legacy", 0) / edge_count
        parent_ratio = exact_parent_edges / edge_count
        dominant = max(relation_counts.values()) / edge_count
        if node_count >= 8 and legacy_ratio >= 0.6 and parent_ratio >= 0.6:
            warnings.append(
                "多数语义边仍由旧版父子顺序自动迁移，地图可能呈现为学习流水账。"
            )
        if node_count >= 8 and dominant >= 0.75:
            warnings.append(
                "超过四分之三的知识边使用同一种关系，请复核是否遗漏区分、限制、应用或反驳。"
            )

    return {
        "ok": not warnings,
        "metrics": {
            "nodes": node_count,
            "semantic_edges": edge_count,
            "lesson_route_edges": lesson_route_edges,
            "multi_incoming_nodes": multi_incoming,
            "cross_section_edges": cross_section,
            "relation_counts": relation_counts,
            "origin_counts": origin_counts,
            "relation_mastery_counts": relation_mastery_counts,
            "argument_maps": len(argument_maps),
            "visible_argument_maps": len(visible_maps),
            "future_argument_maps": len(argument_maps) - len(visible_maps),
            "system_arcs": len(system_arcs),
            "system_stages": len(system_stages),
            "reviewed_system_stages": reviewed_system_stages,
            "future_system_stages": future_system_stages,
            "system_transitions": len(system_transitions),
            "migrated_system_stages": migrated_system_stages,
            "migrated_system_transitions": migrated_system_transitions,
            "inference_steps": len(inference_steps),
            "multi_premise_inferences": multi_premise_steps,
            "largest_visible_map": largest_visible_map,
            "largest_inline_path": largest_inline_path,
            "migrated_argument_maps": migrated_maps,
            "migrated_inferences": migrated_inferences,
            "inference_mastery_counts": inference_mastery_counts,
        },
        "warnings": warnings,
        "map_path": get_meta(connection, "map_path"),
    }


def validate_course(course_dir: Path, *, deep: bool) -> dict[str, Any]:
    with open_database(course_dir) as connection:
        database_errors = validate_database(connection, deep=deep)
        ensure_map_current(connection)
        map_path = Path(get_meta(connection, "map_path"))
        progress_path = course_progress_path(connection)
        map_errors, warnings, counts = validate_map(map_path)
        progress_errors = validate_progress_page(progress_path)
        audit = graph_audit_payload(connection)
        errors = database_errors + map_errors + progress_errors
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings + audit["warnings"],
            "graph_metrics": audit["metrics"],
            "counts": counts,
            "revision": get_meta(connection, "revision"),
            "map_path": str(map_path),
            "progress_path": str(progress_path),
            "deep": deep,
        }


def database_to_blueprint(connection: sqlite3.Connection) -> dict[str, Any]:
    sections = [
        dict(row)
        for row in connection.execute(
            "SELECT id, title, summary, position FROM sections ORDER BY position, id"
        )
    ]
    anchors = [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, locator, note, position
            FROM source_anchors ORDER BY position, id
            """
        )
    ]
    nodes: list[dict[str, Any]] = []
    for row in connection.execute(
        "SELECT * FROM nodes ORDER BY position, id"
    ):
        nodes.append(
            {
                "id": row["id"],
                "parent": row["parent_id"],
                "section": row["section_id"],
                "position": row["position"],
                "relation": row["relation"],
                "node_type": row["node_type"],
                "title": row["title"],
                "summary": row["summary"],
                "detail": row["detail"],
                "bridge": row["bridge"],
                "next": row["next_text"],
                "mastery_criterion": row["mastery_criterion"],
                "prerequisites": row_json(row, "prerequisites_json"),
                "source_refs": row_json(row, "source_refs_json"),
                "common_confusions": row_json(row, "common_confusions_json"),
                "allowed_next": row_json(row, "allowed_next_json"),
                "is_final": bool(row["is_final"]),
                "frontier_open": bool(row["frontier_open"]),
                "preview": bool(row["preview"]),
            }
        )
    semantic_edges = [
        {
            "id": row["id"],
            "from": row["from_node_id"],
            "to": row["to_node_id"],
            "relation": row["relation"],
            "label": row["label"],
            "rationale": row["rationale"],
            "source_refs": row_json(row, "source_refs_json"),
            "origin": row["origin"],
        }
        for row in connection.execute(
            "SELECT * FROM semantic_edges ORDER BY id"
        ).fetchall()
    ]
    mastered = [
        row["node_id"]
        for row in connection.execute(
            "SELECT node_id FROM node_state WHERE status = 'mastered' ORDER BY node_id"
        )
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "course": {
            "id": get_meta(connection, "course_id"),
            "title": get_meta(connection, "course_title"),
            "subtitle": get_meta(connection, "course_subtitle"),
            "language": get_meta(connection, "course_language"),
            "source": {
                key: value
                for key, value in get_meta(connection, "course_source").items()
                if key != "sha256"
            },
        },
        "sections": sections,
        "source_anchors": anchors,
        "semantic_edges": semantic_edges,
        "argument_atlas": get_meta(connection, "argument_atlas"),
        "nodes": nodes,
        "initial_state": {
            "mastered": mastered,
            "current": get_meta(connection, "current_node_id"),
        },
    }


def extend_course(course_dir: Path, fragment_path: Path) -> dict[str, Any]:
    fragment = load_json(fragment_path)
    connection = open_database(course_dir)
    temporary_map: Path | None = None
    temporary_progress: Path | None = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        blueprint = database_to_blueprint(connection)
        section_ids = {item["id"] for item in blueprint["sections"]}
        anchor_ids = {item["id"] for item in blueprint["source_anchors"]}
        node_ids = {item["id"] for item in blueprint["nodes"]}
        edge_ids = {item["id"] for item in blueprint["semantic_edges"]}

        for section in fragment.get("sections", []):
            if section.get("id") in section_ids:
                raise SkillError(f"Section already exists: {section.get('id')}")
            blueprint["sections"].append(section)
            section_ids.add(section.get("id"))
        for anchor in fragment.get("source_anchors", []):
            if anchor.get("id") in anchor_ids:
                raise SkillError(f"Source anchor already exists: {anchor.get('id')}")
            blueprint["source_anchors"].append(anchor)
            anchor_ids.add(anchor.get("id"))
        for node in fragment.get("nodes", []):
            if node.get("id") in node_ids:
                raise SkillError(f"Node already exists: {node.get('id')}")
            blueprint["nodes"].append(node)
            node_ids.add(node.get("id"))
        for edge in fragment.get("semantic_edges", []):
            if edge.get("id") in edge_ids:
                raise SkillError(f"Semantic edge already exists: {edge.get('id')}")
            blueprint["semantic_edges"].append(edge)
            edge_ids.add(edge.get("id"))

        additions = fragment.get("add_allowed_next", {})
        if not isinstance(additions, dict):
            raise SkillError("add_allowed_next must be an object")
        final_updates = fragment.get("set_final", {})
        if not isinstance(final_updates, dict):
            raise SkillError("set_final must be an object")
        by_id = {item["id"]: item for item in blueprint["nodes"]}
        for node_id, is_final in final_updates.items():
            if node_id not in by_id:
                raise SkillError(f"set_final node not found: {node_id}")
            if not isinstance(is_final, bool):
                raise SkillError(f"set_final[{node_id}] must be true or false")
            by_id[node_id]["is_final"] = is_final
        for source_id, targets in additions.items():
            if source_id not in by_id:
                raise SkillError(f"add_allowed_next source not found: {source_id}")
            if not isinstance(targets, list):
                raise SkillError(f"add_allowed_next[{source_id}] must be an array")
            existing = list(by_id[source_id].get("allowed_next", []))
            by_id[source_id]["allowed_next"] = list(dict.fromkeys(existing + targets))
            by_id[source_id]["frontier_open"] = False

        normalized = normalize_blueprint(
            blueprint,
            base_dir=fragment_path.resolve().parent,
        )
        errors = validate_blueprint(normalized)
        if errors:
            raise SkillError(
                "Extended blueprint validation failed:\n- " + "\n- ".join(errors)
            )

        existing_sections = {
            row["id"] for row in connection.execute("SELECT id FROM sections")
        }
        existing_anchors = {
            row["id"] for row in connection.execute("SELECT id FROM source_anchors")
        }
        existing_nodes = {
            row["id"] for row in connection.execute("SELECT id FROM nodes")
        }
        existing_edges = {
            row["id"]
            for row in connection.execute("SELECT id FROM semantic_edges")
        }
        for section in normalized["sections"]:
            if section["id"] not in existing_sections:
                connection.execute(
                    "INSERT INTO sections(id, title, summary, position) VALUES (?, ?, ?, ?)",
                    (
                        section["id"],
                        section["title"],
                        section.get("summary", ""),
                        int(section["position"]),
                    ),
                )
        for anchor in normalized["source_anchors"]:
            if anchor["id"] not in existing_anchors:
                connection.execute(
                    """
                    INSERT INTO source_anchors(id, locator, note, position)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        anchor["id"],
                        anchor["locator"],
                        anchor.get("note", ""),
                        int(anchor["position"]),
                    ),
                )
        for node in normalized["nodes"]:
            if node["id"] not in existing_nodes:
                connection.execute(
                    """
                    INSERT INTO nodes(
                      id, parent_id, section_id, position, relation, node_type,
                      title, summary,
                      detail, bridge, next_text, mastery_criterion,
                      prerequisites_json, source_refs_json, common_confusions_json,
                      allowed_next_json, is_final, frontier_open, preview
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node["id"],
                        node.get("parent", ""),
                        node["section"],
                        int(node["position"]),
                        node["relation"],
                        node["node_type"],
                        node["title"],
                        node["summary"],
                        node["detail"],
                        node["bridge"],
                        node["next"],
                        node["mastery_criterion"],
                        json_text(node.get("prerequisites", [])),
                        json_text(node["source_refs"]),
                        json_text(node.get("common_confusions", [])),
                        json_text(node.get("allowed_next", [])),
                        int(bool(node.get("is_final"))),
                        int(bool(node.get("frontier_open"))),
                        int(bool(node.get("preview"))),
                    ),
                )
                connection.execute(
                    "INSERT INTO node_state(node_id, status) VALUES (?, 'future')",
                    (node["id"],),
                )

        for edge in normalized["semantic_edges"]:
            if edge["id"] not in existing_edges:
                insert_semantic_edge(connection, edge)

        for source_id in additions:
            by_id[source_id]["frontier_open"] = False
            connection.execute(
                """
                UPDATE nodes
                SET allowed_next_json = ?, frontier_open = 0
                WHERE id = ?
                """,
                (json_text(by_id[source_id]["allowed_next"]), source_id),
            )
        for node_id in final_updates:
            connection.execute(
                "UPDATE nodes SET is_final = ? WHERE id = ?",
                (int(bool(by_id[node_id]["is_final"])), node_id),
            )

        revision = int(get_meta(connection, "revision")) + 1
        set_meta(connection, "revision", revision)
        set_meta(
            connection,
            "blueprint_sha256",
            sha256_text(pretty_json(normalized)),
        )
        connection.execute(
            """
            INSERT INTO events(revision, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                revision,
                "graph_extended",
                json_text(
                    {
                        "nodes": [
                            item.get("id") for item in fragment.get("nodes", [])
                        ],
                        "sections": [
                            item.get("id") for item in fragment.get("sections", [])
                        ],
                        "semantic_edges": [
                            item.get("id")
                            for item in fragment.get("semantic_edges", [])
                        ],
                    }
                ),
                utc_now(),
            ),
        )

        database_errors = validate_database(connection, deep=False)
        if database_errors:
            raise SkillError(
                "Extended database state is invalid:\n- "
                + "\n- ".join(database_errors)
            )
        (
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        ) = render_bundle_to_temporary(connection)
        connection.commit()
        install_render_bundle(
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        )
        temporary_map = None
        temporary_progress = None
        atomic_write_text(blueprint_path(course_dir), pretty_json(normalized))
        result = context_payload(connection)
        result["extended"] = {
            "nodes": [item.get("id") for item in fragment.get("nodes", [])],
            "sections": [item.get("id") for item in fragment.get("sections", [])],
            "semantic_edges": [
                item.get("id") for item in fragment.get("semantic_edges", [])
            ],
        }
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        if temporary_map is not None:
            temporary_map.unlink(missing_ok=True)
        if temporary_progress is not None:
            temporary_progress.unlink(missing_ok=True)
        connection.close()


def structure_course(course_dir: Path, overlay_path: Path) -> dict[str, Any]:
    """Apply a reviewed structural overlay without changing learning state."""

    overlay = load_json(overlay_path)
    connection = open_database(course_dir)
    temporary_map: Path | None = None
    temporary_progress: Path | None = None
    revision_before = int(get_meta(connection, "revision"))
    backup = runtime_dir(course_dir) / f"structure-backup-r{revision_before}.sqlite3"
    if not backup.exists():
        backup_connection = sqlite3.connect(backup)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()
    try:
        connection.execute("BEGIN IMMEDIATE")
        blueprint = database_to_blueprint(connection)
        source_update = overlay.get("course_source")
        if source_update is not None:
            if not isinstance(source_update, dict):
                raise SkillError("course_source must be an object")
            blueprint["course"]["source"] = source_update
        sections_by_id = {item["id"]: item for item in blueprint["sections"]}
        for section in overlay.get("sections_upsert", []):
            if not isinstance(section, dict) or not section.get("id"):
                raise SkillError("sections_upsert entries need an id")
            existing = sections_by_id.get(section["id"])
            if existing:
                existing.update(section)
            else:
                blueprint["sections"].append(section)
                sections_by_id[section["id"]] = section

        nodes_by_id = {item["id"]: item for item in blueprint["nodes"]}
        node_updates = overlay.get("node_updates", {})
        if not isinstance(node_updates, dict):
            raise SkillError("node_updates must be an object")
        allowed_update_fields = {
            "section",
            "node_type",
            "parent",
            "position",
            "relation",
            "title",
            "summary",
            "detail",
            "bridge",
            "next",
            "mastery_criterion",
            "prerequisites",
            "source_refs",
            "common_confusions",
            "allowed_next",
            "is_final",
            "frontier_open",
            "preview",
        }
        for node_id, updates in node_updates.items():
            if node_id not in nodes_by_id:
                raise SkillError(f"node_updates node not found: {node_id}")
            if not isinstance(updates, dict):
                raise SkillError(f"node_updates[{node_id}] must be an object")
            unknown = set(updates) - allowed_update_fields
            if unknown:
                raise SkillError(
                    f"node_updates[{node_id}] has unsupported fields: "
                    f"{sorted(unknown)}"
                )
            nodes_by_id[node_id].update(updates)

        new_edges = overlay.get("semantic_edges", [])
        if not isinstance(new_edges, list):
            raise SkillError("semantic_edges must be an array")
        if overlay.get("replace_semantic_edges"):
            blueprint["semantic_edges"] = list(new_edges)
        else:
            edges_by_id = {
                item["id"]: item for item in blueprint["semantic_edges"]
            }
            for edge in new_edges:
                if not isinstance(edge, dict) or not edge.get("id"):
                    raise SkillError("semantic_edges entries need an id")
                edges_by_id[edge["id"]] = edge
            blueprint["semantic_edges"] = list(edges_by_id.values())

        argument_atlas_update = overlay.get("argument_atlas")
        if argument_atlas_update is not None:
            if not isinstance(argument_atlas_update, dict):
                raise SkillError("argument_atlas must be an object")
            blueprint["argument_atlas"] = argument_atlas_update
        source_structure_update = overlay.get("source_structure")
        if source_structure_update is not None:
            if not isinstance(source_structure_update, dict):
                raise SkillError("source_structure must be an object")
            blueprint["argument_atlas"][
                "source_structure"
            ] = source_structure_update
        stage_unit_assignments = overlay.get("stage_unit_assignments", {})
        if not isinstance(stage_unit_assignments, dict):
            raise SkillError("stage_unit_assignments must be an object")
        if stage_unit_assignments:
            stages_by_id = {
                item["id"]: item
                for item in blueprint["argument_atlas"]["system_spine"][
                    "stages"
                ]
            }
            for stage_id, assignment in stage_unit_assignments.items():
                if stage_id not in stages_by_id:
                    raise SkillError(
                        f"stage_unit_assignments stage not found: {stage_id}"
                    )
                if not isinstance(assignment, dict):
                    raise SkillError(
                        f"stage_unit_assignments[{stage_id}] must be an object"
                    )
                unknown = set(assignment) - {
                    "primary_unit_id",
                    "related_unit_ids",
                }
                if unknown:
                    raise SkillError(
                        f"stage_unit_assignments[{stage_id}] has unsupported "
                        f"fields: {sorted(unknown)}"
                    )
                stages_by_id[stage_id].update(assignment)
        argument_atlas_changed = bool(
            argument_atlas_update is not None
            or source_structure_update is not None
            or stage_unit_assignments
        )

        normalized = normalize_blueprint(
            blueprint,
            base_dir=overlay_path.resolve().parent,
        )
        errors = validate_blueprint(normalized)
        if errors:
            raise SkillError(
                "Structured blueprint validation failed:\n- "
                + "\n- ".join(errors)
            )
        if source_update is not None:
            set_meta(
                connection,
                "course_source",
                source_snapshot(normalized["course"]),
            )
        if argument_atlas_changed:
            set_meta(
                connection,
                "argument_atlas",
                normalized["argument_atlas"],
            )
            inference_ids = {
                item["id"]
                for item in normalized["argument_atlas"]["inferences"]
            }
            previous_mastery = get_meta_optional(
                connection,
                "inference_mastery",
                {},
            )
            set_meta(
                connection,
                "inference_mastery",
                {
                    key: value
                    for key, value in previous_mastery.items()
                    if key in inference_ids
                },
            )

        for section in normalized["sections"]:
            connection.execute(
                """
                INSERT INTO sections(id, title, summary, position)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title = excluded.title,
                  summary = excluded.summary,
                  position = excluded.position
                """,
                (
                    section["id"],
                    section["title"],
                    section.get("summary", ""),
                    int(section["position"]),
                ),
            )
        for node_id in node_updates:
            node = nodes_by_id[node_id]
            connection.execute(
                """
                UPDATE nodes
                SET
                  parent_id = ?,
                  section_id = ?,
                  position = ?,
                  relation = ?,
                  node_type = ?,
                  title = ?,
                  summary = ?,
                  detail = ?,
                  bridge = ?,
                  next_text = ?,
                  mastery_criterion = ?,
                  prerequisites_json = ?,
                  source_refs_json = ?,
                  common_confusions_json = ?,
                  allowed_next_json = ?,
                  is_final = ?,
                  frontier_open = ?,
                  preview = ?
                WHERE id = ?
                """,
                (
                    node.get("parent", ""),
                    node["section"],
                    int(node["position"]),
                    node["relation"],
                    node["node_type"],
                    node["title"],
                    node["summary"],
                    node["detail"],
                    node["bridge"],
                    node["next"],
                    node["mastery_criterion"],
                    json_text(node.get("prerequisites", [])),
                    json_text(node["source_refs"]),
                    json_text(node.get("common_confusions", [])),
                    json_text(node.get("allowed_next", [])),
                    int(bool(node.get("is_final"))),
                    int(bool(node.get("frontier_open"))),
                    int(bool(node.get("preview"))),
                    node_id,
                ),
            )

        if overlay.get("replace_semantic_edges"):
            connection.execute("DELETE FROM semantic_edges")
        for edge in normalized["semantic_edges"]:
            connection.execute(
                """
                INSERT INTO semantic_edges(
                  id, from_node_id, to_node_id, relation, label, rationale,
                  source_refs_json, origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  from_node_id = excluded.from_node_id,
                  to_node_id = excluded.to_node_id,
                  relation = excluded.relation,
                  label = excluded.label,
                  rationale = excluded.rationale,
                  source_refs_json = excluded.source_refs_json,
                  origin = excluded.origin
                """,
                (
                    edge["id"],
                    edge["from"],
                    edge["to"],
                    edge["relation"],
                    edge["label"],
                    edge["rationale"],
                    json_text(edge.get("source_refs", [])),
                    edge.get("origin", "reviewed"),
                ),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO edge_state(edge_id, mastery_level)
            SELECT id, 'unassessed' FROM semantic_edges
            """
        )

        revision = revision_before + 1
        set_meta(connection, "revision", revision)
        set_meta(
            connection,
            "blueprint_sha256",
            sha256_text(pretty_json(normalized)),
        )
        connection.execute(
            """
            INSERT INTO events(revision, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                revision,
                "graph_structured",
                json_text(
                    {
                        "overlay": str(overlay_path),
                        "replace_semantic_edges": bool(
                            overlay.get("replace_semantic_edges")
                        ),
                        "course_source_updated": source_update is not None,
                        "argument_atlas_updated": (
                            argument_atlas_changed
                        ),
                        "source_structure_updated": (
                            source_structure_update is not None
                        ),
                        "stage_unit_assignments": sorted(
                            stage_unit_assignments
                        ),
                        "node_updates": sorted(node_updates),
                        "semantic_edges": len(normalized["semantic_edges"]),
                    }
                ),
                utc_now(),
            ),
        )

        database_errors = validate_database(connection, deep=False)
        if database_errors:
            raise SkillError(
                "Structured database state is invalid:\n- "
                + "\n- ".join(database_errors)
            )
        (
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        ) = render_bundle_to_temporary(connection)
        connection.commit()
        install_render_bundle(
            map_path,
            temporary_map,
            progress_path,
            temporary_progress,
        )
        temporary_map = None
        temporary_progress = None
        atomic_write_text(blueprint_path(course_dir), pretty_json(normalized))
        result = context_payload(connection)
        result["structured"] = {
            "semantic_edges": len(normalized["semantic_edges"]),
            "argument_maps": len(
                normalized["argument_atlas"]["maps"]
            ),
            "inference_steps": len(
                normalized["argument_atlas"]["inferences"]
            ),
            "system_stages": len(
                normalized["argument_atlas"]["system_spine"]["stages"]
            ),
            "system_transitions": len(
                normalized["argument_atlas"]["system_spine"][
                    "transitions"
                ]
            ),
            "node_updates": sorted(node_updates),
            "backup": str(backup),
        }
        result["graph_audit"] = graph_audit_payload(connection)
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        if temporary_map is not None:
            temporary_map.unlink(missing_ok=True)
        if temporary_progress is not None:
            temporary_progress.unlink(missing_ok=True)
        connection.close()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "imported-course"


def import_legacy_html(
    course_dir: Path,
    legacy_map: Path,
    *,
    course_id: str | None,
    title: str | None,
    force: bool,
) -> dict[str, Any]:
    legacy_map = legacy_map.resolve()
    if not legacy_map.is_file():
        raise SkillError(f"Legacy map not found: {legacy_map}")
    source_text = legacy_map.read_text(encoding="utf-8")
    parser = LearningMapParser()
    parser.feed(source_text)
    if not parser.nodes:
        raise SkillError("Legacy map has no .knowledge-node buttons")

    detected_title = title
    if not detected_title:
        match = re.search(r"<h1[^>]*>(.*?)</h1>", source_text, flags=re.I | re.S)
        if match:
            detected_title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    detected_title = detected_title or legacy_map.stem
    course_id = course_id or slugify(legacy_map.stem)
    backup = runtime_dir(course_dir) / "legacy-map-backup.html"

    source_values = sorted(
        {
            node.attributes.get("data-source", "").strip()
            for node in parser.nodes
            if node.attributes.get("data-source", "").strip()
        }
    )
    anchor_id_by_source = {
        source: f"imported-source-{index:03d}"
        for index, source in enumerate(source_values, start=1)
    }
    children: dict[str, list[str]] = {node.node_id: [] for node in parser.nodes}
    for node in parser.nodes:
        if node.parent in children:
            children[node.parent].append(node.node_id)

    nodes: list[dict[str, Any]] = []
    mastered: list[str] = []
    current = ""
    for position, node in enumerate(parser.nodes, start=1):
        status = node.status
        if status == "mastered":
            mastered.append(node.node_id)
        elif status == "current":
            current = node.node_id
        source_value = node.attributes.get("data-source", "").strip()
        nodes.append(
            {
                "id": node.node_id,
                "parent": node.parent,
                "section": "imported",
                "position": position,
                "relation": "root" if not node.parent else "supports",
                "title": node.attributes.get("data-title", node.node_id),
                "summary": node.attributes.get(
                    "data-title",
                    node.node_id,
                ),
                "detail": node.attributes.get("data-detail", "Imported node"),
                "bridge": node.attributes.get("data-bridge", "Imported dependency"),
                "next": node.attributes.get("data-next", "Continue the argument"),
                "mastery_criterion": (
                    "The learner explains the governing relation in their own "
                    "words and gives a relevant reason."
                ),
                "prerequisites": [],
                "source_refs": [anchor_id_by_source[source_value]],
                "common_confusions": [],
                "allowed_next": children.get(node.node_id, []),
                "is_final": status != "current" and not children.get(node.node_id),
                "frontier_open": status == "current" and not children.get(node.node_id),
                "preview": False,
            }
        )
    if not current:
        raise SkillError("Legacy map must contain exactly one current node")

    blueprint = normalize_blueprint(
        {
            "schema_version": SCHEMA_VERSION,
            "course": {
                "id": course_id,
                "title": detected_title,
                "subtitle": "从旧版HTML地图迁移的课程。",
                "language": "zh-CN",
                "source": {
                    "kind": "document",
                    "locator": str(backup),
                    "edition": "legacy-html-import",
                },
            },
            "sections": [
                {
                    "id": "imported",
                    "title": "已迁移课程",
                    "summary": "保留原有节点和学习状态",
                    "position": 1,
                }
            ],
            "source_anchors": [
                {
                    "id": anchor_id_by_source[source],
                    "locator": source,
                    "note": "Imported from data-source",
                    "position": index,
                }
                for index, source in enumerate(source_values, start=1)
            ],
            "nodes": nodes,
            "initial_state": {"mastered": mastered, "current": current},
        },
        base_dir=legacy_map.parent,
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_map, backup)
    result = initialize_course(
        course_dir,
        blueprint,
        map_path=legacy_map,
        force=force,
    )
    result["legacy_backup"] = str(backup)
    return result


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.blueprint.resolve()
    blueprint = normalize_blueprint(
        load_json(source_path),
        base_dir=source_path.parent,
    )
    map_path = (
        args.map_path.expanduser()
        if args.map_path
        else args.course_dir.resolve() / "learning-map" / "index.html"
    )
    if not map_path.is_absolute():
        map_path = args.course_dir.resolve() / map_path
    return initialize_course(
        args.course_dir,
        blueprint,
        map_path=map_path,
        force=args.force,
    )


def command_context(args: argparse.Namespace) -> dict[str, Any]:
    with open_database(args.course_dir) as connection:
        ensure_map_current(connection)
        return context_payload(connection)


def command_prepare_unit(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_unit(
        args.course_dir,
        args.packet.resolve(),
        expected_revision=args.expected_revision,
        expected_current=args.expected_current,
    )


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    with open_database(args.course_dir) as connection:
        path = render_atomic(connection)
        return {
            "ok": True,
            "revision": get_meta(connection, "revision"),
            "map_path": str(path),
            "progress_path": str(course_progress_path(connection)),
        }


def command_audit(args: argparse.Namespace) -> dict[str, Any]:
    with open_database(args.course_dir) as connection:
        ensure_map_current(connection)
        return graph_audit_payload(connection)


def serve_course(course_dir: Path, host: str, port: int) -> dict[str, Any]:
    """Serve the graph shell and live snapshots without mutating course state."""

    resolved_course = course_dir.resolve()
    with open_database(resolved_course) as connection:
        map_path = Path(get_meta(connection, "map_path"))
        progress_path = course_progress_path(connection)
        render_atomic(connection)

    class CourseHandler(http.server.BaseHTTPRequestHandler):
        def send_bytes(
            self,
            body: bytes,
            *,
            content_type: str,
            status: int = 200,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/snapshot":
                try:
                    with open_database(resolved_course) as connection:
                        payload = graph_snapshot(connection)
                    self.send_bytes(
                        pretty_json(payload).encode("utf-8"),
                        content_type="application/json; charset=utf-8",
                    )
                except (SkillError, sqlite3.Error) as exc:
                    self.send_bytes(
                        json_text({"ok": False, "error": str(exc)}).encode(
                            "utf-8"
                        ),
                        content_type="application/json; charset=utf-8",
                        status=500,
                    )
                return
            map_url_path = "/" + urllib.parse.quote(map_path.name)
            if parsed.path in {"/", "/index.html", map_url_path}:
                try:
                    body = map_path.read_bytes()
                except OSError as exc:
                    self.send_bytes(
                        str(exc).encode("utf-8"),
                        content_type="text/plain; charset=utf-8",
                        status=500,
                    )
                    return
                self.send_bytes(
                    body,
                    content_type="text/html; charset=utf-8",
                )
                return
            progress_url_path = "/" + urllib.parse.quote(progress_path.name)
            if parsed.path in {"/progress.html", progress_url_path}:
                try:
                    body = progress_path.read_bytes()
                except OSError as exc:
                    self.send_bytes(
                        str(exc).encode("utf-8"),
                        content_type="text/plain; charset=utf-8",
                        status=500,
                    )
                    return
                self.send_bytes(
                    body,
                    content_type="text/html; charset=utf-8",
                )
                return
            self.send_bytes(
                b"Not found",
                content_type="text/plain; charset=utf-8",
                status=404,
            )

        def log_message(self, format: str, *args: Any) -> None:
            return

    try:
        server = http.server.ThreadingHTTPServer((host, port), CourseHandler)
    except OSError as exc:
        raise SkillError(f"Could not start live map server: {exc}") from exc
    url = f"http://{host}:{server.server_port}/"
    print(
        pretty_json(
            {
                "ok": True,
                "mode": "live",
                "url": url,
                "map_path": str(map_path),
            }
        ),
        end="",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"ok": True, "mode": "stopped", "url": url}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sml.py",
        description="Transactional runtime for Socratic Map Learning courses.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize an optimized course from a validated blueprint.",
    )
    init_parser.add_argument("course_dir", type=Path)
    init_parser.add_argument("--blueprint", type=Path, required=True)
    init_parser.add_argument("--map-path", type=Path)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=command_init)

    import_parser = subparsers.add_parser(
        "import-html",
        help="Migrate a legacy HTML map into the optimized runtime.",
    )
    import_parser.add_argument("course_dir", type=Path)
    import_parser.add_argument("--map", type=Path, required=True)
    import_parser.add_argument("--course-id")
    import_parser.add_argument("--title")
    import_parser.add_argument("--force", action="store_true")
    import_parser.set_defaults(
        handler=lambda args: import_legacy_html(
            args.course_dir,
            args.map,
            course_id=args.course_id,
            title=args.title,
            force=args.force,
        )
    )

    context_parser = subparsers.add_parser(
        "context",
        help="Return only the compact context needed for the next teaching turn.",
    )
    context_parser.add_argument("course_dir", type=Path)
    context_parser.set_defaults(handler=command_context)

    prepare_parser = subparsers.add_parser(
        "prepare-unit",
        help="Cache a source packet for the active unit without advancing it.",
    )
    prepare_parser.add_argument("course_dir", type=Path)
    prepare_parser.add_argument("--packet", type=Path, required=True)
    prepare_parser.add_argument("--expected-revision", type=int, required=True)
    prepare_parser.add_argument("--expected-current", required=True)
    prepare_parser.set_defaults(handler=command_prepare_unit)

    commit_parser = subparsers.add_parser(
        "commit",
        help="Commit one mastery decision as a compare-and-swap transaction.",
    )
    commit_parser.add_argument("course_dir", type=Path)
    commit_parser.add_argument("--expected-revision", type=int, required=True)
    commit_parser.add_argument("--expected-current", required=True)
    commit_parser.add_argument(
        "--diagnosis",
        required=True,
        choices=sorted(DIAGNOSES),
    )
    commit_parser.add_argument(
        "--evidence-kind",
        required=True,
        choices=sorted(EVIDENCE_KINDS),
    )
    commit_parser.add_argument(
        "--learning-phase",
        choices=sorted(LEARNING_PHASES),
        help="Active local learning-cycle phase after this turn.",
    )
    commit_parser.add_argument("--next")
    commit_parser.add_argument(
        "--relation-edge",
        help="Key semantic edge demonstrated by this mastered answer.",
    )
    commit_parser.add_argument(
        "--relation-level",
        choices=sorted(RELATION_MASTERY_LEVELS - {"unassessed"}),
        help="Deprecated compatibility: mastery level for --relation-edge.",
    )
    commit_parser.add_argument(
        "--inference-step",
        help="Key multi-premise inference demonstrated by this answer.",
    )
    commit_parser.add_argument(
        "--inference-level",
        choices=sorted(RELATION_MASTERY_LEVELS - {"unassessed"}),
        help="Highest demonstrated mastery level for --inference-step.",
    )
    commit_parser.set_defaults(
        handler=lambda args: commit_turn(
            args.course_dir,
            expected_revision=args.expected_revision,
            expected_current=args.expected_current,
            diagnosis=args.diagnosis,
            evidence_kind=args.evidence_kind,
            next_node=args.next,
            learning_phase=args.learning_phase,
            relation_edge_id=args.relation_edge,
            relation_level=args.relation_level,
            inference_step_id=args.inference_step,
            inference_level=args.inference_level,
        )
    )

    extend_parser = subparsers.add_parser(
        "extend",
        help="Validate and append a precompiled graph fragment.",
    )
    extend_parser.add_argument("course_dir", type=Path)
    extend_parser.add_argument("--fragment", type=Path, required=True)
    extend_parser.set_defaults(
        handler=lambda args: extend_course(args.course_dir, args.fragment.resolve())
    )

    structure_parser = subparsers.add_parser(
        "structure",
        help="Apply a reviewed knowledge-graph overlay without changing mastery.",
    )
    structure_parser.add_argument("course_dir", type=Path)
    structure_parser.add_argument("--overlay", type=Path, required=True)
    structure_parser.set_defaults(
        handler=lambda args: structure_course(
            args.course_dir,
            args.overlay.resolve(),
        )
    )

    render_parser = subparsers.add_parser(
        "render",
        help="Regenerate the HTML view from authoritative course state.",
    )
    render_parser.add_argument("course_dir", type=Path)
    render_parser.set_defaults(handler=command_render)

    audit_parser = subparsers.add_parser(
        "audit",
        help="Report whether the semantic graph still resembles a lesson ledger.",
    )
    audit_parser.add_argument("course_dir", type=Path)
    audit_parser.set_defaults(handler=command_audit)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate database, graph, source fingerprint, and generated HTML.",
    )
    validate_parser.add_argument("course_dir", type=Path)
    validate_parser.add_argument("--deep", action="store_true")
    validate_parser.set_defaults(
        handler=lambda args: validate_course(args.course_dir, deep=args.deep)
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the stable live-learning page on this computer.",
    )
    serve_parser.add_argument("course_dir", type=Path)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(
        handler=lambda args: serve_course(
            args.course_dir,
            args.host,
            args.port,
        )
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except SkillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"ERROR: SQLite failure: {exc}", file=sys.stderr)
        return 3
    print(pretty_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
