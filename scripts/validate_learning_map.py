#!/usr/bin/env python3
"""Validate legacy and generated Socratic knowledge-atlas HTML files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


REQUIRED_DATA = (
    "data-parent",
    "data-status",
    "data-source",
    "data-title",
    "data-detail",
    "data-bridge",
    "data-next",
)

STATUS_CLASSES = {"mastered", "current", "future"}
STATUS_ALIASES = {
    "mastered": {"mastered", "已掌握", "刚刚掌握"},
    "current": {"current", "正在学习"},
    "future": {"future", "尚未展开"},
}


@dataclass(frozen=True)
class Node:
    node_id: str
    classes: frozenset[str]
    parent: str
    attributes: dict[str, str]
    text: str

    @property
    def status(self) -> str:
        states = STATUS_CLASSES & set(self.classes)
        return next(iter(states)) if len(states) == 1 else ""


class LearningMapParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[Node] = []
        self.has_viewport = False
        self.has_skip_link = False
        self.has_reduced_motion = False
        self.has_focus_visible = False
        self.has_problem_index = False
        self.has_reasoning_canvas = False
        self.has_breadcrumb = False
        self.has_mobile_reasoning = False
        self.has_graph_viewport = False
        self.has_graph_svg = False
        self.has_graph_inspector = False
        self.has_problem_list = False
        self.body_attributes: dict[str, str] = {}
        self.progress_attributes: dict[str, str] = {}
        self.view_names: set[str] = set()
        self.mode_names: set[str] = set()
        self.lens_names: set[str] = set()
        self.semantic_edge_text: list[str] = []
        self.graph_data_text: list[str] = []
        self._inside_semantic_edges = False
        self._inside_graph_data = False
        self._node_attributes: dict[str, str] | None = None
        self._node_classes: frozenset[str] = frozenset()
        self._node_text: list[str] = []
        self._node_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {name: value or "" for name, value in attrs}

        if tag == "meta" and attributes.get("name") == "viewport":
            self.has_viewport = "width=device-width" in attributes.get("content", "")

        if tag == "body":
            self.body_attributes = attributes

        classes = frozenset(attributes.get("class", "").split())
        if tag == "a" and "skip-link" in classes:
            self.has_skip_link = True

        if attributes.get("id") == "progress-summary":
            self.progress_attributes = attributes
        if attributes.get("id") == "problem-index":
            self.has_problem_index = True
        if attributes.get("id") == "reasoning-canvas":
            self.has_reasoning_canvas = True
        if attributes.get("id") == "reasoning-breadcrumb":
            self.has_breadcrumb = True
        if attributes.get("id") == "mobile-reasoning":
            self.has_mobile_reasoning = True
        if attributes.get("id") == "graph-viewport":
            self.has_graph_viewport = True
        if attributes.get("id") == "graph-svg":
            self.has_graph_svg = True
        if attributes.get("id") == "inspector-title":
            self.has_graph_inspector = True
        if attributes.get("id") == "problem-list":
            self.has_problem_list = True
        if attributes.get("data-view"):
            self.view_names.add(attributes["data-view"])
        if attributes.get("data-mode"):
            self.mode_names.add(attributes["data-mode"])
        if attributes.get("data-lens"):
            self.lens_names.add(attributes["data-lens"])
        if tag == "script" and attributes.get("id") == "semantic-edge-data":
            self._inside_semantic_edges = True
        if tag == "script" and attributes.get("id") == "graph-data":
            self._inside_graph_data = True

        if self._node_attributes is not None:
            self._node_depth += 1

        if tag == "button" and "knowledge-node" in classes:
            self._node_attributes = attributes
            self._node_classes = classes
            self._node_text = []
            self._node_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside_semantic_edges:
            self._inside_semantic_edges = False
        if tag == "script" and self._inside_graph_data:
            self._inside_graph_data = False
        if self._node_attributes is None:
            return
        self._node_depth -= 1
        if self._node_depth != 0:
            return

        self.nodes.append(
            Node(
                node_id=self._node_attributes.get("id", ""),
                classes=self._node_classes,
                parent=self._node_attributes.get("data-parent", ""),
                attributes=self._node_attributes,
                text=" ".join(" ".join(self._node_text).split()),
            )
        )
        self._node_attributes = None
        self._node_classes = frozenset()
        self._node_text = []

    def handle_data(self, data: str) -> None:
        if self._inside_semantic_edges:
            self.semantic_edge_text.append(data)
        if self._inside_graph_data:
            self.graph_data_text.append(data)
        if "prefers-reduced-motion" in data:
            self.has_reduced_motion = True
        if ":focus-visible" in data:
            self.has_focus_visible = True
        if self._node_attributes is not None and data.strip():
            self._node_text.append(data.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("map_path", type=Path)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Reserved for compatibility; human-readable output remains the default.",
    )
    return parser.parse_args()


def find_cycles(nodes: dict[str, Node]) -> list[str]:
    cycles: list[str] = []

    for start in nodes:
        seen: set[str] = set()
        cursor = start
        while cursor:
            if cursor in seen:
                cycles.append(start)
                break
            seen.add(cursor)
            parent = nodes.get(cursor)
            if parent is None:
                break
            cursor = parent.parent

    return sorted(set(cycles))


def int_attribute(
    attributes: dict[str, str],
    name: str,
    errors: list[str],
) -> int | None:
    raw = attributes.get(name)
    if raw is None or raw == "":
        errors.append(f"Progress summary missing {name}")
        return None
    try:
        return int(raw)
    except ValueError:
        errors.append(f"Progress summary {name} is not an integer: {raw!r}")
        return None


def validate_v4(
    parser: LearningMapParser,
    source_text: str,
) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = "".join(parser.graph_data_text).strip()
    if not raw:
        return ["Missing v4 graph-data snapshot"], warnings, {}
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"Invalid v4 graph-data JSON: {exc}"], warnings, {}
    if not isinstance(snapshot, dict):
        return ["v4 graph-data must be an object"], warnings, {}
    if snapshot.get("schema_version") != 4:
        errors.append(
            "v4 graph-data schema_version must be 4, got "
            f"{snapshot.get('schema_version')!r}"
        )

    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    sections = snapshot.get("sections")
    overview_edges = snapshot.get("overview_edges")
    if not isinstance(nodes, list) or not nodes:
        errors.append("v4 graph-data needs at least one node")
        nodes = []
    if not isinstance(edges, list):
        errors.append("v4 graph-data edges must be an array")
        edges = []
    if not isinstance(sections, list) or not sections:
        errors.append("v4 graph-data needs at least one problem section")
        sections = []
    if not isinstance(overview_edges, list):
        errors.append("v4 graph-data overview_edges must be an array")
        overview_edges = []

    node_ids = [str(node.get("id", "")) for node in nodes if isinstance(node, dict)]
    duplicate_nodes = sorted(
        {node_id for node_id in node_ids if node_id and node_ids.count(node_id) > 1}
    )
    if duplicate_nodes:
        errors.append(f"Duplicate v4 node ids: {duplicate_nodes}")
    if any(not node_id for node_id in node_ids):
        errors.append("v4 graph-data contains a node without id")
    node_id_set = set(node_ids)

    section_ids = [
        str(section.get("id", ""))
        for section in sections
        if isinstance(section, dict)
    ]
    if len(section_ids) != len(set(section_ids)):
        errors.append("Duplicate v4 problem section ids")
    section_id_set = set(section_ids)

    valid_statuses = {"mastered", "current", "future"}
    current_nodes: list[str] = []
    counts = {"nodes": len(nodes), "mastered": 0, "current": 0, "future": 0}
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("v4 graph-data node must be an object")
            continue
        node_id = str(node.get("id", ""))
        status = str(node.get("status", ""))
        if status not in valid_statuses:
            errors.append(f"{node_id}: invalid v4 status {status!r}")
        else:
            counts[status] += 1
        if status == "current":
            current_nodes.append(node_id)
        if node.get("section") not in section_id_set:
            errors.append(f"{node_id}: unknown problem section {node.get('section')!r}")
        if not node.get("title"):
            errors.append(f"{node_id}: missing complete question or proposition")
        if not node.get("source"):
            errors.append(f"{node_id}: missing source anchor text")
        if status == "future" and node.get("answer_hidden") is not True:
            errors.append(f"{node_id}: future answer is not hidden")

    complete = bool(snapshot.get("complete"))
    expected_current = 0 if complete else 1
    if len(current_nodes) != expected_current:
        errors.append(
            f"Expected {expected_current} current v4 node(s), found {current_nodes}"
        )
    current_payload = snapshot.get("current", {})
    if isinstance(current_payload, dict):
        expected_id = str(current_payload.get("node_id", ""))
        actual_id = current_nodes[0] if current_nodes else ""
        if expected_id != actual_id:
            errors.append(
                f"v4 current payload {expected_id!r} does not match {actual_id!r}"
            )

    valid_mastery = {
        "unassessed",
        "understood",
        "reconstructable",
        "transferable",
        "retained",
    }
    edge_ids: set[str] = set()
    connected_nodes: set[str] = set()
    required_edge_fields = {
        "id",
        "from",
        "to",
        "relation",
        "label",
        "rationale",
        "source",
    }
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("v4 graph-data edge must be an object")
            continue
        edge_id = str(edge.get("id", ""))
        missing = sorted(field for field in required_edge_fields if not edge.get(field))
        if missing:
            errors.append(f"{edge_id or '<edge>'}: missing v4 edge fields {missing}")
        if edge_id in edge_ids:
            errors.append(f"Duplicate v4 edge id: {edge_id}")
        edge_ids.add(edge_id)
        source = str(edge.get("from", ""))
        target = str(edge.get("to", ""))
        if source not in node_id_set:
            errors.append(f"{edge_id}: missing source node {source}")
        if target not in node_id_set:
            errors.append(f"{edge_id}: missing target node {target}")
        connected_nodes.update((source, target))
        mastery = edge.get("mastery_level")
        if mastery not in valid_mastery:
            errors.append(f"{edge_id}: invalid relation mastery {mastery!r}")

    if len(nodes) > 1:
        isolated = sorted(node_id_set - connected_nodes)
        if isolated:
            errors.append(f"v4 graph has semantically isolated nodes: {isolated}")

    if parser.mode_names != {"overview", "problem"}:
        errors.append(
            "v4 map needs exactly overview and problem modes, found "
            f"{sorted(parser.mode_names)}"
        )
    if parser.lens_names != {"all", "why", "uses"}:
        errors.append(
            "v4 map needs all, why, and uses relation lenses, found "
            f"{sorted(parser.lens_names)}"
        )
    if not parser.has_graph_viewport:
        errors.append("v4 map is missing the stable graph viewport")
    if not parser.has_graph_svg:
        errors.append("v4 map is missing the SVG knowledge graph")
    if not parser.has_graph_inspector:
        errors.append("v4 map is missing the node and relation inspector")
    if not parser.has_problem_list:
        errors.append("v4 map is missing the whole-book problem navigation")
    forbidden_runtime = {
        "scrollIntoView": "selection must not move the page viewport",
        "restoreNodesToBank": "v4 must not reparent cards into a grid",
        "grid-template-columns: repeat(auto-fit": "v4 must not use an auto-fit card grid",
        "return lines.slice(0, 4)": "v4 must not silently truncate node titles",
    }
    for token, reason in forbidden_runtime.items():
        if token in source_text:
            errors.append(f"Forbidden v4 behavior {token!r}: {reason}")
    for function_name, next_name in (
        ("selectNode", "selectEdge"),
        ("selectEdge", "openProblem"),
    ):
        match = re.search(
            rf"function {function_name}\b([\s\S]*?)function {next_name}\b",
            source_text,
        )
        if not match:
            errors.append(f"v4 runtime is missing {function_name}()")
        elif "renderGraph(" in match.group(1):
            errors.append(
                f"{function_name}() must not recalculate graph layout"
            )
    if 'class: "edge-hit"' not in source_text:
        errors.append("v4 edges need a wide keyboard and pointer hit target")
    content_geometry_requirements = {
        "function estimateTextWidth(": (
            "v4 nodes need width-aware text measurement"
        ),
        "function wrapTextToWidth(": (
            "v4 nodes need width-aware multilingual wrapping"
        ),
        "function nodeMetrics(": (
            "v4 node dimensions must derive from wrapped content"
        ),
        "function placeEdgeLabel(": (
            "v4 edge labels need collision-aware placement"
        ),
        'id="node-clip-defs"': (
            "v4 node text needs a final clipping safety boundary"
        ),
        'id="edge-label-layer"': (
            "v4 edge labels need a dedicated visual layer"
        ),
        'id="edge-label-leader-layer"': (
            "v4 label leaders need a layer below every edge label"
        ),
    }
    for token, reason in content_geometry_requirements.items():
        if token not in source_text:
            errors.append(reason)
    leader_style_match = re.search(
        r"\.edge-label-leader\s*\{(?P<body>[\s\S]*?)\}",
        source_text,
    )
    if (
        leader_style_match is None
        or re.search(
            r"\bopacity:\s*0\s*;",
            leader_style_match.group("body"),
        )
        is None
    ):
        errors.append(
            "v4 non-semantic label leaders must be hidden by default"
        )
    leader_disclosure_requirements = {
        ".edge-label-leader.interaction-visible": (
            "v4 label leaders must reveal on pointer or keyboard interaction"
        ),
        ".edge-label-leader.selected": (
            "v4 selected relations must reveal displaced-label leaders"
        ),
        "function setEdgeLeaderActive(": (
            "v4 label leaders need one reusable disclosure controller"
        ),
        'label.addEventListener("pointerenter"': (
            "v4 label leaders must reveal on pointer hover"
        ),
        'label.addEventListener("pointerleave"': (
            "v4 label leaders must hide after pointer hover"
        ),
        'label.addEventListener("focus"': (
            "v4 label leaders must reveal on keyboard focus"
        ),
        'label.addEventListener("blur"': (
            "v4 label leaders must hide after keyboard focus"
        ),
        'leader.classList.toggle(\n            "selected"': (
            "v4 relation selection must be mirrored onto its label leader"
        ),
    }
    for token, reason in leader_disclosure_requirements.items():
        if token not in source_text:
            errors.append(reason)
    edge_layer_index = source_text.find('id="edge-layer"')
    edge_label_leader_layer_index = source_text.find(
        'id="edge-label-leader-layer"'
    )
    edge_label_layer_index = source_text.find('id="edge-label-layer"')
    node_layer_index = source_text.find('id="node-layer"')
    if not (
        edge_layer_index >= 0
        and edge_layer_index < edge_label_leader_layer_index
        < edge_label_layer_index < node_layer_index
    ):
        errors.append(
            "v4 visual stack must be paths, leaders, labels, then nodes"
        )
    interaction_requirements = {
        '"pointerdown"': "v4 graph viewport needs pointer-drag panning",
        '"pointermove"': "v4 graph viewport needs pointer-drag movement",
        '"wheel"': "v4 graph viewport needs wheel zoom",
        "setPointerCapture(": "v4 pointer drag must capture the pointer",
        "releasePointerCapture(": "v4 pointer drag must release the pointer",
        "function setZoomAt(": "v4 wheel zoom must stay anchored to the cursor",
        "{ passive: false }": "v4 wheel zoom must prevent page scrolling",
    }
    for token, reason in interaction_requirements.items():
        if token not in source_text:
            errors.append(reason)
    pointer_down_start = source_text.find(
        'graphViewport.addEventListener("pointerdown"'
    )
    pointer_move_start = source_text.find(
        'graphViewport.addEventListener("pointermove"'
    )
    finish_pan_start = source_text.find("function finishPan")
    if (
        pointer_down_start >= 0
        and pointer_move_start > pointer_down_start
        and finish_pan_start > pointer_move_start
    ):
        pointer_down_block = source_text[pointer_down_start:pointer_move_start]
        pointer_move_block = source_text[pointer_move_start:finish_pan_start]
        if "setPointerCapture(" in pointer_down_block:
            errors.append(
                "v4 pointer capture must not steal an ordinary node click"
            )
        if "setPointerCapture(" not in pointer_move_block:
            errors.append(
                "v4 pointer capture must begin after the drag threshold"
            )

    if not parser.has_viewport:
        errors.append("Missing responsive viewport meta")
    if not parser.has_focus_visible:
        warnings.append("No :focus-visible rule detected")
    if not parser.has_reduced_motion:
        warnings.append("No prefers-reduced-motion rule detected")
    if not parser.has_skip_link:
        warnings.append("No skip link detected")
    return errors, warnings, counts


def _relative_luminance(hex_color: str) -> float:
    value = int(hex_color.removeprefix("#"), 16)
    channels = (
        (value >> 16) & 255,
        (value >> 8) & 255,
        value & 255,
    )
    linear = []
    for channel in channels:
        normalized = channel / 255
        linear.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    foreground_luminance = _relative_luminance(foreground)
    background_luminance = _relative_luminance(background)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def validate_v5_contrast(source_text: str) -> list[str]:
    errors: list[str] = []
    style_match = re.search(r"<style>([\s\S]*?)</style>", source_text)
    style = style_match.group(1) if style_match else ""
    light_match = re.search(r":root\s*\{([\s\S]*?)\}", style)
    dark_match = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{"
        r"[\s\S]*?:root\s*\{([\s\S]*?)\}",
        style,
    )

    def variables(block: str) -> dict[str, str]:
        return {
            name: color.lower()
            for name, color in re.findall(
                r"(--[\w-]+)\s*:\s*(#[\da-fA-F]{6})\s*;",
                block,
            )
        }

    light = variables(light_match.group(1) if light_match else "")
    dark = {
        **light,
        **variables(dark_match.group(1) if dark_match else ""),
    }
    surfaces = (
        "default",
        "conclusion",
        "objection",
        "boundary",
        "junction",
        "junction-objection",
        "junction-boundary",
    )
    for theme_name, tokens in (("light", light), ("dark", dark)):
        for surface in surfaces:
            background_name = f"--{surface}-bg"
            foreground_name = f"--{surface}-fg"
            muted_name = f"--{surface}-muted"
            border_name = f"--{surface}-border"
            for token_name in (
                background_name,
                foreground_name,
                muted_name,
                border_name,
            ):
                if token_name not in tokens:
                    errors.append(
                        f"v5 {theme_name} theme misses contrast token "
                        f"{token_name}"
                    )
            for label, foreground_name_to_check in (
                ("primary", foreground_name),
                ("secondary", muted_name),
            ):
                if (
                    background_name not in tokens
                    or foreground_name_to_check not in tokens
                ):
                    continue
                ratio = _contrast_ratio(
                    tokens[foreground_name_to_check],
                    tokens[background_name],
                )
                if ratio < 4.5:
                    errors.append(
                        f"v5 {theme_name} {surface} {label} text contrast "
                        f"is {ratio:.2f}:1; expected at least 4.5:1"
                    )
            if (
                "--page" in tokens
                and background_name in tokens
                and border_name in tokens
            ):
                boundary_ratio = max(
                    _contrast_ratio(
                        tokens[background_name],
                        tokens["--page"],
                    ),
                    _contrast_ratio(
                        tokens[border_name],
                        tokens["--page"],
                    ),
                )
                if boundary_ratio < 3:
                    errors.append(
                        f"v5 {theme_name} {surface} surface boundary "
                        f"contrast is {boundary_ratio:.2f}:1; "
                        "expected at least 3:1"
                    )

    contrast_contracts = {
        r"\.node-surface\s*\{[\s\S]*?fill:\s*var\(--node-bg\)": (
            "v5 proposition surfaces must consume --node-bg"
        ),
        r"\.node-title\s*\{[\s\S]*?fill:\s*var\(--node-fg\)": (
            "v5 proposition titles must consume --node-fg"
        ),
        r"\.node-type\s*\{[\s\S]*?fill:\s*var\(--node-muted\)": (
            "v5 proposition labels must consume --node-muted"
        ),
        r"\.node-status\s*\{[\s\S]*?fill:\s*var\(--node-muted\)": (
            "v5 proposition statuses must consume --node-muted"
        ),
        (
            r"\.junction-surface\s*\{[\s\S]*?"
            r"fill:\s*var\(--junction-surface-bg\)"
        ): "v5 inference surfaces must consume semantic junction tokens",
        (
            r"\.junction-text\s*\{[\s\S]*?"
            r"fill:\s*var\(--junction-surface-fg\)"
        ): "v5 inference text must consume semantic junction tokens",
    }
    for pattern, reason in contrast_contracts.items():
        if not re.search(pattern, style):
            errors.append(reason)

    conclusion_index = style.rfind(".argument-node.conclusion {")
    boundary_index = style.find(".argument-node.boundary")
    objection_index = style.find(".argument-node.objection")
    if (
        conclusion_index < 0
        or conclusion_index < boundary_index
        or conclusion_index < objection_index
    ):
        errors.append(
            "v5 final-conclusion palette must override "
            "objection/boundary palettes"
        )
    return errors


def validate_v5(
    parser: LearningMapParser,
    source_text: str,
) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = "".join(parser.graph_data_text).strip()
    if not raw:
        return ["Missing v5 graph-data snapshot"], warnings, {}
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"Invalid v5 graph-data JSON: {exc}"], warnings, {}
    if not isinstance(snapshot, dict):
        return ["v5 graph-data must be an object"], warnings, {}
    if snapshot.get("schema_version") != 5:
        errors.append(
            "v5 graph-data schema_version must be 5, got "
            f"{snapshot.get('schema_version')!r}"
        )

    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("v5 graph-data needs proposition nodes")
        nodes = []
    node_by_id = {
        str(node.get("id", "")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    if len(node_by_id) != len(nodes):
        errors.append("v5 graph-data has duplicate or missing node ids")
    statuses = {"mastered", "current", "future"}
    counts = {
        "nodes": len(nodes),
        "mastered": 0,
        "current": 0,
        "future": 0,
        "maps": 0,
        "inferences": 0,
    }
    current_nodes = []
    for node_id, node in node_by_id.items():
        status = node.get("status")
        if status not in statuses:
            errors.append(f"{node_id}: invalid v5 status {status!r}")
        else:
            counts[status] += 1
        if status == "current":
            current_nodes.append(node_id)
        if not node.get("title"):
            errors.append(f"{node_id}: proposition title is required")
        if not node.get("source"):
            errors.append(f"{node_id}: source text is required")
        if status == "future" and node.get("answer_hidden") is not True:
            errors.append(f"{node_id}: future answer is not hidden")

    complete = bool(snapshot.get("complete"))
    expected_current = 0 if complete else 1
    if len(current_nodes) != expected_current:
        errors.append(
            f"Expected {expected_current} current v5 node(s), "
            f"found {current_nodes}"
        )

    atlas = snapshot.get("argument_atlas")
    if not isinstance(atlas, dict):
        errors.append("v5 graph-data needs argument_atlas")
        atlas = {}
    if atlas.get("version") != 1:
        errors.append("v5 argument_atlas.version must be 1")
    maps = atlas.get("maps")
    inferences = atlas.get("inferences")
    if not isinstance(maps, list) or not maps:
        errors.append("v5 argument_atlas needs maps")
        maps = []
    if not isinstance(inferences, list):
        errors.append("v5 argument_atlas.inferences must be an array")
        inferences = []
    counts["maps"] = len(maps)
    counts["inferences"] = len(inferences)
    map_by_id = {
        str(argument_map.get("id", "")): argument_map
        for argument_map in maps
        if isinstance(argument_map, dict) and argument_map.get("id")
    }
    if len(map_by_id) != len(maps):
        errors.append("v5 argument maps have duplicate or missing ids")
    if atlas.get("default_map_id") not in map_by_id:
        errors.append("v5 default_map_id does not name an argument map")

    valid_mastery = {
        "unassessed",
        "understood",
        "reconstructable",
        "transferable",
        "retained",
    }
    inferences_by_map: dict[str, list[dict[str, object]]] = {}
    inference_ids: set[str] = set()
    for inference in inferences:
        if not isinstance(inference, dict):
            errors.append("v5 inference step must be an object")
            continue
        inference_id = str(inference.get("id", ""))
        if not inference_id or inference_id in inference_ids:
            errors.append(
                f"v5 inference has duplicate or missing id {inference_id!r}"
            )
        inference_ids.add(inference_id)
        map_id = str(inference.get("map_id", ""))
        if map_id not in map_by_id:
            errors.append(
                f"{inference_id}: missing argument map {map_id!r}"
            )
            continue
        premise_ids = inference.get("premise_ids")
        if not isinstance(premise_ids, list) or not premise_ids:
            errors.append(f"{inference_id}: premise_ids must be non-empty")
            premise_ids = []
        if not inference.get("bridge"):
            errors.append(f"{inference_id}: explicit reasoning bridge is required")
        if not inference.get("conclusion_id"):
            errors.append(f"{inference_id}: conclusion_id is required")
        map_node_ids = set(map_by_id[map_id].get("node_ids", []))
        for premise_id in premise_ids:
            if premise_id not in map_node_ids:
                errors.append(
                    f"{inference_id}: premise {premise_id!r} is not in {map_id}"
                )
        if inference.get("conclusion_id") not in map_node_ids:
            errors.append(
                f"{inference_id}: conclusion "
                f"{inference.get('conclusion_id')!r} is not in {map_id}"
            )
        if not inference.get("source"):
            errors.append(f"{inference_id}: source text is required")
        if inference.get("mastery_level") not in valid_mastery:
            errors.append(
                f"{inference_id}: invalid inference mastery "
                f"{inference.get('mastery_level')!r}"
            )
        inferences_by_map.setdefault(map_id, []).append(inference)

    for map_id, argument_map in map_by_id.items():
        for field in ("title", "question", "summary", "status"):
            if not argument_map.get(field):
                errors.append(f"{map_id}.{field} is required")
        node_ids = argument_map.get("node_ids")
        if not isinstance(node_ids, list):
            errors.append(f"{map_id}.node_ids must be an array")
            node_ids = []
        parent_id = str(argument_map.get("parent_id", ""))
        entry_node_id = str(argument_map.get("entry_node_id", ""))
        if parent_id:
            parent = map_by_id.get(parent_id)
            if parent is None:
                errors.append(f"{map_id}: missing parent map {parent_id!r}")
            elif entry_node_id not in parent.get("node_ids", []):
                errors.append(
                    f"{map_id}: entry proposition is absent from its parent"
                )
            elif (
                argument_map.get("status") != "future"
                and argument_map.get("conclusion_id") != entry_node_id
            ):
                errors.append(
                    f"{map_id}: child conclusion must equal its parent "
                    "entry proposition for inline expansion"
                )
        elif entry_node_id:
            errors.append(f"{map_id}: root map cannot have entry_node_id")
        if argument_map.get("status") == "future":
            if node_ids or argument_map.get("conclusion_id"):
                errors.append(f"{map_id}: future answer is exposed")
            continue
        if len(node_ids) > 12:
            errors.append(
                f"{map_id}: more than 12 propositions require a subargument"
            )
        conclusion_id = str(argument_map.get("conclusion_id", ""))
        if conclusion_id not in node_ids:
            errors.append(
                f"{map_id}: conclusion must belong to the argument map"
            )
        for node_id in node_ids:
            node = node_by_id.get(str(node_id))
            if node is None:
                errors.append(f"{map_id}: missing proposition {node_id!r}")
            elif node.get("node_type") == "question":
                errors.append(
                    f"{map_id}: question {node_id!r} appears as a graph node"
                )

        reachable = {conclusion_id}
        changed = True
        while changed:
            changed = False
            for inference in inferences_by_map.get(map_id, []):
                if inference.get("conclusion_id") not in reachable:
                    continue
                for premise_id in inference.get("premise_ids", []):
                    if premise_id not in reachable:
                        reachable.add(str(premise_id))
                        changed = True
        unreachable = sorted(set(map(str, node_ids)) - reachable)
        if unreachable:
            errors.append(
                f"{map_id}: propositions do not contribute to the conclusion: "
                f"{unreachable}"
            )

        path_node_ids: set[str] = set()
        cursor = argument_map
        seen_maps: set[str] = set()
        while cursor:
            cursor_id = str(cursor.get("id", ""))
            if cursor_id in seen_maps:
                errors.append(f"{map_id}: argument-map parent cycle")
                break
            seen_maps.add(cursor_id)
            path_node_ids.update(map(str, cursor.get("node_ids", [])))
            cursor_parent_id = str(cursor.get("parent_id", ""))
            cursor = (
                map_by_id.get(cursor_parent_id)
                if cursor_parent_id
                else None
            )
        if len(path_node_ids) > 12:
            errors.append(
                f"{map_id}: inline expansion path exposes "
                f"{len(path_node_ids)} propositions; maximum is 12"
            )

    required_tokens = {
        'id="argument-list"': "v5 needs a separate argument navigator",
        'id="breadcrumbs"': "v5 needs hierarchy breadcrumbs",
        'id="graph-viewport"': "v5 needs a stable graph viewport",
        'id="graph-svg"': "v5 needs a real SVG argument graph",
        'id="flow-layer"': "v5 needs a dedicated reason-flow layer",
        'id="inference-layer"': "v5 needs visible inference junctions",
        'id="node-layer"': "v5 needs proposition nodes above flows",
        'id="inspector-title"': "v5 needs a proposition/inference inspector",
        "function argumentLayout(": "v5 needs deterministic RTL layout",
        "function inferenceMetrics(": "v5 needs content-sized inference junctions",
        "function wrapTextToWidth(": "v5 needs width-aware text wrapping",
        "function composeArgumentGraph(": (
            "v5 needs continuous inline subargument composition"
        ),
        "function toggleSubargument(": (
            "v5 needs inline subargument disclosure"
        ),
        "function removeExpandedBranch(": (
            "v5 needs recursive subargument collapse"
        ),
        "function captureNodeAnchor(": (
            "v5 inline expansion must preserve its shared conclusion"
        ),
        "renderGraph({ anchor })": (
            "v5 inline relayout must restore its shared-node anchor"
        ),
        ".filter((argumentMap) => !argumentMap.parent_id)": (
            "v5 page navigation must list only independent root arguments"
        ),
        "childrenByParent.get(childMap.parent_id)": (
            "v5 inline disclosure must enforce sibling accordion behavior"
        ),
        "const savedViews = new Map()": "v5 must preserve parent viewport state",
        "const expandedMapIds = new Set()": (
            "v5 needs explicit inline disclosure state"
        ),
        "history.pushState(": "v5 navigation must integrate with browser history",
        '"popstate"': "v5 browser back must restore the previous argument map",
        "selectedNodeId,\n          selectedInferenceId": (
            "v5 saved views must preserve graph selection"
        ),
        "function setZoomAt(": "v5 wheel zoom must anchor to the cursor",
        'group.addEventListener("click", activate)': (
            "v5 proposition and inference items must be clickable"
        ),
        "premise_ids": "v5 needs multi-premise inference data",
        "conclusion_id": "v5 needs an explicit conclusion per inference",
        "左边是结论": "v5 must state the RTL reading rule",
        "右边是理由": "v5 must state the RTL reading rule",
    }
    for token, reason in required_tokens.items():
        if token not in source_text:
            errors.append(reason)
    forbidden_tokens = {
        "edge-label-leader": (
            "v5 reasoning bridges are junctions, not detached edge labels"
        ),
        "restoreNodesToBank": "v5 must not reparent card nodes",
        "scrollIntoView": "v5 selection must not move the page",
        "grid-template-columns: repeat(auto-fit": (
            "v5 must not fall back to a card grid"
        ),
        "return lines.slice(0, 4)": "v5 must not truncate propositions",
        "const navigationStack = []": (
            "v5 subarguments must not use a page-navigation stack"
        ),
        "function goBack(": (
            "v5 subarguments must collapse inline instead of navigating back"
        ),
        'id="open-submap"': (
            "v5 must use an inline subargument toggle, not page navigation"
        ),
    }
    for token, reason in forbidden_tokens.items():
        if token in source_text:
            errors.append(f"Forbidden v5 behavior {token!r}: {reason}")

    for function_name, next_name in (
        ("selectNode", "selectInference"),
        ("selectInference", "applyHighlights"),
    ):
        match = re.search(
            rf"function {function_name}\b([\s\S]*?)function {next_name}\b",
            source_text,
        )
        if not match:
            errors.append(f"v5 runtime is missing {function_name}()")
        elif "renderGraph(" in match.group(1):
            errors.append(
                f"{function_name}() must not recalculate graph layout"
            )

    interaction_requirements = {
        '"pointerdown"': "v5 graph viewport needs pointer-drag panning",
        '"pointermove"': "v5 graph viewport needs pointer-drag movement",
        '"wheel"': "v5 graph viewport needs wheel zoom",
        "setPointerCapture(": "v5 pointer drag must capture after intent",
        "releasePointerCapture(": "v5 pointer drag must release capture",
        "{ passive: false }": "v5 wheel zoom must prevent page scrolling",
    }
    for token, reason in interaction_requirements.items():
        if token not in source_text:
            errors.append(reason)
    pointer_down_start = source_text.find(
        'graphViewport.addEventListener("pointerdown"'
    )
    pointer_move_start = source_text.find(
        'graphViewport.addEventListener("pointermove"'
    )
    finish_pan_start = source_text.find("function finishPan")
    if (
        pointer_down_start >= 0
        and pointer_move_start > pointer_down_start
        and finish_pan_start > pointer_move_start
    ):
        pointer_down_block = source_text[pointer_down_start:pointer_move_start]
        pointer_move_block = source_text[pointer_move_start:finish_pan_start]
        if "setPointerCapture(" in pointer_down_block:
            errors.append("v5 pointer capture starts before drag intent")
        if "setPointerCapture(" not in pointer_move_block:
            errors.append("v5 pointer capture must begin after 5px movement")

    if not parser.has_viewport:
        errors.append("Missing responsive viewport meta")
    if not parser.has_focus_visible:
        warnings.append("No :focus-visible rule detected")
    if not parser.has_reduced_motion:
        warnings.append("No prefers-reduced-motion rule detected")
    if not parser.has_skip_link:
        warnings.append("No skip link detected")
    errors.extend(validate_v5_contrast(source_text))
    return errors, warnings, counts


def validate_v6(
    parser: LearningMapParser,
    source_text: str,
) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = "".join(parser.graph_data_text).strip()
    if not raw:
        return ["Missing v6 graph-data snapshot"], warnings, {}
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"Invalid v6 graph-data JSON: {exc}"], warnings, {}
    if not isinstance(snapshot, dict):
        return ["v6 graph-data must be an object"], warnings, {}
    if snapshot.get("schema_version") != 6:
        errors.append(
            "v6 graph-data schema_version must be 6, got "
            f"{snapshot.get('schema_version')!r}"
        )

    nodes = snapshot.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("v6 graph-data needs proposition nodes")
        nodes = []
    node_by_id = {
        str(node.get("id", "")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    if len(node_by_id) != len(nodes):
        errors.append("v6 graph-data has duplicate or missing node ids")
    valid_statuses = {"mastered", "current", "future"}
    current_nodes: list[str] = []
    counts = {
        "nodes": len(nodes),
        "mastered": 0,
        "current": 0,
        "future": 0,
        "maps": 0,
        "inferences": 0,
        "stages": 0,
        "transitions": 0,
    }
    for node_id, node in node_by_id.items():
        status = node.get("status")
        if status not in valid_statuses:
            errors.append(f"{node_id}: invalid v6 status {status!r}")
        else:
            counts[status] += 1
        if status == "current":
            current_nodes.append(node_id)
        if not node.get("title"):
            errors.append(f"{node_id}: proposition title is required")
        if not node.get("source"):
            errors.append(f"{node_id}: source text is required")
        if status == "future" and node.get("answer_hidden") is not True:
            errors.append(f"{node_id}: future answer is not hidden")
    expected_current = 0 if snapshot.get("complete") else 1
    if len(current_nodes) != expected_current:
        errors.append(
            f"Expected {expected_current} current v6 node(s), "
            f"found {current_nodes}"
        )

    atlas = snapshot.get("argument_atlas")
    if not isinstance(atlas, dict):
        errors.append("v6 graph-data needs argument_atlas")
        atlas = {}
    maps = atlas.get("maps")
    inferences = atlas.get("inferences")
    if not isinstance(maps, list) or not maps:
        errors.append("v6 argument_atlas needs maps")
        maps = []
    if not isinstance(inferences, list):
        errors.append("v6 argument_atlas.inferences must be an array")
        inferences = []
    counts["maps"] = len(maps)
    counts["inferences"] = len(inferences)
    map_by_id = {
        str(argument_map.get("id", "")): argument_map
        for argument_map in maps
        if isinstance(argument_map, dict) and argument_map.get("id")
    }
    if len(map_by_id) != len(maps):
        errors.append("v6 argument maps have duplicate or missing ids")

    inference_ids: set[str] = set()
    for inference in inferences:
        if not isinstance(inference, dict):
            errors.append("v6 inference step must be an object")
            continue
        inference_id = str(inference.get("id", ""))
        if not inference_id or inference_id in inference_ids:
            errors.append(
                f"v6 inference has duplicate or missing id {inference_id!r}"
            )
        inference_ids.add(inference_id)
        argument_map = map_by_id.get(str(inference.get("map_id", "")))
        if argument_map is None:
            errors.append(f"{inference_id}: proof map is missing")
            continue
        premises = inference.get("premise_ids")
        if not isinstance(premises, list) or not premises:
            errors.append(f"{inference_id}: premise_ids must be non-empty")
            premises = []
        if not inference.get("bridge"):
            errors.append(f"{inference_id}: bridge is required")
        if not inference.get("conclusion_id"):
            errors.append(f"{inference_id}: conclusion_id is required")
        if not inference.get("source"):
            errors.append(f"{inference_id}: source text is required")
        map_node_ids = set(map(str, argument_map.get("node_ids", [])))
        for premise_id in premises:
            if str(premise_id) not in map_node_ids:
                errors.append(
                    f"{inference_id}: premise {premise_id!r} is outside its map"
                )
        if str(inference.get("conclusion_id", "")) not in map_node_ids:
            errors.append(
                f"{inference_id}: conclusion is outside its proof map"
            )

    system_spine = atlas.get("system_spine")
    if not isinstance(system_spine, dict):
        errors.append("v6 argument_atlas needs system_spine")
        system_spine = {}
    for field in ("title", "summary", "terminal_mastery"):
        if not system_spine.get(field):
            errors.append(f"v6 system_spine.{field} is required")
    stages = system_spine.get("stages")
    transitions = system_spine.get("transitions")
    arcs = system_spine.get("arcs")
    if not isinstance(stages, list) or not stages:
        errors.append("v6 system_spine needs stages")
        stages = []
    if not isinstance(transitions, list):
        errors.append("v6 system_spine.transitions must be an array")
        transitions = []
    if not isinstance(arcs, list) or not arcs:
        errors.append("v6 system_spine needs arcs")
        arcs = []
    counts["stages"] = len(stages)
    counts["transitions"] = len(transitions)
    ordered_stages = sorted(
        [stage for stage in stages if isinstance(stage, dict)],
        key=lambda stage: int(stage.get("position", 0)),
    )
    stage_ids = [str(stage.get("id", "")) for stage in ordered_stages]
    if not all(stage_ids) or len(stage_ids) != len(set(stage_ids)):
        errors.append("v6 system stages have duplicate or missing ids")
    stage_by_id = {
        str(stage.get("id", "")): stage for stage in ordered_stages
    }
    for expected_position, stage in enumerate(ordered_stages, start=1):
        stage_id = str(stage.get("id", ""))
        if stage.get("position") != expected_position:
            errors.append("v6 system stage positions must be contiguous")
        if not stage.get("question"):
            errors.append(f"{stage_id}: question is required")
        argument_map = map_by_id.get(str(stage.get("map_id", "")))
        if argument_map is None:
            errors.append(f"{stage_id}: proof map is missing")
            continue
        answer_id = str(stage.get("answer_id", ""))
        if argument_map.get("status") == "future":
            if answer_id:
                errors.append(f"{stage_id}: future answer is exposed")
        elif answer_id != str(argument_map.get("conclusion_id", "")):
            errors.append(
                f"{stage_id}: answer must equal its proof conclusion"
            )
        if not stage.get("source"):
            errors.append(f"{stage_id}: source text is required")

    expected_pairs = list(zip(stage_ids, stage_ids[1:]))
    actual_pairs = []
    for transition in transitions:
        if not isinstance(transition, dict):
            errors.append("v6 system transition must be an object")
            continue
        actual_pairs.append(
            (
                str(transition.get("from_stage_id", "")),
                str(transition.get("to_stage_id", "")),
            )
        )
        if transition.get("label") != "因此必须追问":
            errors.append("v6 system transition needs the fixed relation label")
        if transition.get("relation") != "must_ask":
            errors.append("v6 system transition relation must be must_ask")
        if not transition.get("bridge"):
            errors.append("v6 system transition needs a visible bridge")
        if not transition.get("source"):
            errors.append("v6 system transition needs source text")
    if actual_pairs != expected_pairs:
        errors.append(
            "v6 transitions must connect every consecutive stage exactly once"
        )
    covered = [
        str(stage_id)
        for arc in arcs
        if isinstance(arc, dict)
        for stage_id in arc.get("stage_ids", [])
    ]
    if sorted(covered) != sorted(stage_ids):
        errors.append("v6 arcs must cover every stage exactly once")
    for stage_id, stage in stage_by_id.items():
        containing = [
            arc
            for arc in arcs
            if stage_id in arc.get("stage_ids", [])
        ]
        if len(containing) != 1:
            continue
        if stage.get("arc_id") != containing[0].get("id"):
            errors.append(f"{stage_id}: arc_id does not match its arc")

    required_tokens = {
        'id="graph-viewport"': "v6 needs one stable system canvas",
        'id="graph-svg"': "v6 needs a real SVG graph",
        'id="arc-layer"': "v6 needs system arc grouping",
        'id="system-flow-layer"': "v6 needs a separate problem-flow layer",
        'id="flow-layer"': "v6 needs a protected reason-flow layer",
        'id="inference-layer"': "v6 needs inference junctions",
        'id="node-layer"': "v6 needs proposition nodes",
        'id="stage-layer"': "v6 needs problem headers above proof layers",
        'id="inspector-title"': "v6 needs an inspector",
        'id="outline-list"': "v6 needs in-canvas stage navigation",
        "function systemLayout(": "v6 needs deterministic vertical layout",
        "function argumentLayout(": "v6 needs deterministic RTL proof layout",
        "function composeArgumentGraph(": "v6 needs inline proof composition",
        "function toggleStageProof(": "v6 needs stage proof disclosure",
        "function toggleSubargument(": "v6 needs nested proof disclosure",
        "function captureNodeAnchor(": (
            "v6 expansion must preserve the shared proposition anchor"
        ),
        "function referenceLabel(": (
            "v6 must reference canonical earlier conclusions without duplication"
        ),
        "canonicalElsewhere": (
            "v6 must keep one canonical position per system conclusion"
        ),
        "function createTransition(": (
            "v6 needs visible because-therefore problem transitions"
        ),
        "function setZoomAt(": "v6 wheel zoom must anchor to the cursor",
        "左边是结论": "v6 must state the local RTL reading rule",
        "右边是理由": "v6 must state the local RTL reading rule",
    }
    for token, reason in required_tokens.items():
        if token not in source_text:
            errors.append(reason)
    forbidden_tokens = {
        "scrollIntoView": "selection must never move the page",
        "grid-template-columns: repeat(auto-fit": (
            "the system graph must not become a card grid"
        ),
        "const navigationStack = []": (
            "subarguments must not navigate to another page"
        ),
        "history.pushState(": (
            "v6 uses one stable system canvas, not page-level proof navigation"
        ),
        "edge-label-leader": (
            "reasoning bridges must remain first-class surfaces"
        ),
        "return lines.slice(0, 4)": "proposition text must not be truncated",
    }
    for token, reason in forbidden_tokens.items():
        if token in source_text:
            errors.append(f"Forbidden v6 behavior {token!r}: {reason}")

    for function_name, next_name in (
        ("selectNode", "selectInference"),
        ("selectInference", "selectStage"),
        ("selectStage", "selectTransition"),
    ):
        match = re.search(
            rf"function {function_name}\b([\s\S]*?)function {next_name}\b",
            source_text,
        )
        if not match:
            errors.append(f"v6 runtime is missing {function_name}()")
        elif "renderSystem(" in match.group(1):
            errors.append(
                f"{function_name}() must not recalculate layout on selection"
            )

    for token, reason in {
        '"pointerdown"': "v6 canvas needs pointer-drag panning",
        '"pointermove"': "v6 canvas needs pointer-drag movement",
        '"wheel"': "v6 canvas needs wheel zoom",
        "setPointerCapture(": "v6 drag must capture after intent",
        "releasePointerCapture(": "v6 drag must release capture",
        "{ passive: false }": "v6 wheel zoom must prevent page scrolling",
    }.items():
        if token not in source_text:
            errors.append(reason)
    pointer_down_start = source_text.find(
        'graphViewport.addEventListener("pointerdown"'
    )
    pointer_move_start = source_text.find(
        'graphViewport.addEventListener("pointermove"'
    )
    finish_pan_start = source_text.find("function finishPan")
    if (
        pointer_down_start >= 0
        and pointer_move_start > pointer_down_start
        and finish_pan_start > pointer_move_start
    ):
        pointer_down_block = source_text[pointer_down_start:pointer_move_start]
        pointer_move_block = source_text[pointer_move_start:finish_pan_start]
        if "setPointerCapture(" in pointer_down_block:
            errors.append("v6 pointer capture starts before drag intent")
        if "setPointerCapture(" not in pointer_move_block:
            errors.append("v6 pointer capture must begin after drag threshold")

    if not parser.has_viewport:
        errors.append("Missing responsive viewport meta")
    if not parser.has_focus_visible:
        warnings.append("No :focus-visible rule detected")
    if not parser.has_reduced_motion:
        warnings.append("No prefers-reduced-motion rule detected")
    if not parser.has_skip_link:
        warnings.append("No skip link detected")
    errors.extend(validate_v5_contrast(source_text))
    return errors, warnings, counts


def validate_v7_contrast(source_text: str) -> list[str]:
    errors: list[str] = []
    style_match = re.search(r"<style>([\s\S]*?)</style>", source_text)
    style = style_match.group(1) if style_match else ""
    root_match = re.search(r":root\s*\{([\s\S]*?)\}", style)
    dark_match = re.search(
        r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{"
        r"[\s\S]*?:root\s*\{([\s\S]*?)\}",
        style,
    )

    def variables(block: str) -> dict[str, str]:
        return {
            name: color.lower()
            for name, color in re.findall(
                r"(--[\w-]+)\s*:\s*(#[\da-fA-F]{6})\s*;",
                block,
            )
        }

    light = variables(root_match.group(1) if root_match else "")
    dark = {**light, **variables(dark_match.group(1) if dark_match else "")}
    for theme_name, tokens in (("light", light), ("dark", dark)):
        for surface in (
            "default",
            "conclusion",
            "objection",
            "boundary",
            "junction",
            "junction-objection",
            "junction-boundary",
        ):
            background = f"--{surface}-bg"
            foreground = f"--{surface}-fg"
            muted = f"--{surface}-muted"
            border = f"--{surface}-border"
            for token in (background, foreground, muted, border):
                if token not in tokens:
                    errors.append(
                        f"v7 {theme_name} theme misses contrast token {token}"
                    )
            for label, text_token in (("primary", foreground), ("secondary", muted)):
                if background in tokens and text_token in tokens:
                    ratio = _contrast_ratio(tokens[text_token], tokens[background])
                    if ratio < 4.5:
                        errors.append(
                            f"v7 {theme_name} {surface} {label} text contrast "
                            f"is {ratio:.2f}:1; expected at least 4.5:1"
                        )
    contracts = {
        r"\.proposition\s*\{[\s\S]*?background:\s*var\(--default-bg\)": (
            "v7 propositions must consume semantic background tokens"
        ),
        r"\.proposition\s*\{[\s\S]*?color:\s*var\(--default-fg\)": (
            "v7 propositions must consume semantic foreground tokens"
        ),
        r"\.inference-card\s*\{[\s\S]*?background:\s*var\(--junction-bg\)": (
            "v7 inference bridges must consume semantic junction tokens"
        ),
    }
    for pattern, reason in contracts.items():
        if not re.search(pattern, style):
            errors.append(reason)
    return errors


def validate_v7(
    parser: LearningMapParser,
    source_text: str,
) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []
    raw = "".join(parser.graph_data_text).strip()
    if not raw:
        return ["Missing v7 graph-data snapshot"], warnings, {}
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"Invalid v7 graph-data JSON: {exc}"], warnings, {}
    if not isinstance(snapshot, dict):
        return ["v7 graph-data must be an object"], warnings, {}
    if snapshot.get("schema_version") != 7:
        errors.append(
            "v7 graph-data schema_version must be 7, got "
            f"{snapshot.get('schema_version')!r}"
        )

    nodes = snapshot.get("nodes")
    atlas = snapshot.get("argument_atlas")
    if not isinstance(nodes, list) or not nodes:
        errors.append("v7 graph-data needs proposition nodes")
        nodes = []
    if not isinstance(atlas, dict):
        errors.append("v7 graph-data needs argument_atlas")
        atlas = {}
    current_payload = snapshot.get("current", {})
    current_node_id = (
        str(current_payload.get("node_id", ""))
        if isinstance(current_payload, dict)
        else ""
    )
    revealed_node_ids = {
        str(node_id)
        for argument_map in atlas.get("maps", [])
        if isinstance(argument_map, dict)
        and argument_map.get("status") != "future"
        and str(argument_map.get("conclusion_id", "")) == current_node_id
        for node_id in argument_map.get("node_ids", [])
    }
    node_by_id = {
        str(node.get("id", "")): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    if len(node_by_id) != len(nodes):
        errors.append("v7 graph-data has duplicate or missing node ids")
    counts = {
        "nodes": len(nodes),
        "mastered": 0,
        "current": 0,
        "future": 0,
        "maps": 0,
        "inferences": 0,
        "stages": 0,
        "transitions": 0,
        "units": 0,
    }
    for node_id, node in node_by_id.items():
        status = node.get("status")
        if status not in {"mastered", "current", "future"}:
            errors.append(f"{node_id}: invalid v7 status {status!r}")
        else:
            counts[status] += 1
        if not node.get("title") or not node.get("source"):
            errors.append(f"{node_id}: proposition needs title and source")
        if (
            status == "future"
            and node.get("answer_hidden") is not True
            and node_id not in revealed_node_ids
        ):
            errors.append(f"{node_id}: future answer is not hidden")

    maps = atlas.get("maps")
    inferences = atlas.get("inferences")
    if not isinstance(maps, list) or not maps:
        errors.append("v7 argument_atlas needs maps")
        maps = []
    if not isinstance(inferences, list):
        errors.append("v7 argument_atlas.inferences must be an array")
        inferences = []
    counts["maps"] = len(maps)
    counts["inferences"] = len(inferences)
    map_by_id = {
        str(argument_map.get("id", "")): argument_map
        for argument_map in maps
        if isinstance(argument_map, dict) and argument_map.get("id")
    }
    if len(map_by_id) != len(maps):
        errors.append("v7 argument maps have duplicate or missing ids")
    for inference in inferences:
        if not isinstance(inference, dict):
            errors.append("v7 inference must be an object")
            continue
        argument_map = map_by_id.get(str(inference.get("map_id", "")))
        if argument_map is None:
            errors.append(f"{inference.get('id', '')}: proof map is missing")
            continue
        map_nodes = set(map(str, argument_map.get("node_ids", [])))
        premises = inference.get("premise_ids")
        if not isinstance(premises, list) or not premises:
            errors.append(f"{inference.get('id', '')}: premises are required")
            premises = []
        if not inference.get("bridge") or not inference.get("source"):
            errors.append(f"{inference.get('id', '')}: bridge and source are required")
        for node_id in [*map(str, premises), str(inference.get("conclusion_id", ""))]:
            if node_id not in map_nodes:
                errors.append(
                    f"{inference.get('id', '')}: {node_id!r} is outside its map"
                )

    spine = atlas.get("system_spine")
    if not isinstance(spine, dict):
        errors.append("v7 argument_atlas needs system_spine")
        spine = {}
    stages = spine.get("stages")
    transitions = spine.get("transitions")
    if not isinstance(stages, list) or not stages:
        errors.append("v7 system spine needs stages")
        stages = []
    if not isinstance(transitions, list):
        errors.append("v7 system spine transitions must be an array")
        transitions = []
    counts["stages"] = len(stages)
    counts["transitions"] = len(transitions)
    ordered = sorted(
        [stage for stage in stages if isinstance(stage, dict)],
        key=lambda stage: int(stage.get("position", 0)),
    )
    stage_ids = [str(stage.get("id", "")) for stage in ordered]
    if not all(stage_ids) or len(stage_ids) != len(set(stage_ids)):
        errors.append("v7 system stages have duplicate or missing ids")
    if [stage.get("position") for stage in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        errors.append("v7 system stage positions must be contiguous")
    expected_pairs = list(zip(stage_ids, stage_ids[1:]))
    actual_pairs = [
        (
            str(transition.get("from_stage_id", "")),
            str(transition.get("to_stage_id", "")),
        )
        for transition in transitions
        if isinstance(transition, dict)
    ]
    if actual_pairs != expected_pairs:
        errors.append("v7 transitions must connect consecutive questions")

    structure = atlas.get("source_structure")
    if not isinstance(structure, dict):
        errors.append("v7 argument_atlas needs source_structure")
        structure = {}
    units = structure.get("units")
    if not isinstance(units, list) or not units:
        errors.append("v7 source_structure needs units")
        units = []
    counts["units"] = len(units)
    unit_by_id = {
        str(unit.get("id", "")): unit
        for unit in units
        if isinstance(unit, dict) and unit.get("id")
    }
    if len(unit_by_id) != len(units):
        errors.append("v7 source units have duplicate or missing ids")
    for unit_id, unit in unit_by_id.items():
        if not unit.get("title") or not unit.get("kind"):
            errors.append(f"{unit_id}: source unit needs title and kind")
        parent_id = str(unit.get("parent_id", ""))
        if parent_id and parent_id not in unit_by_id:
            errors.append(f"{unit_id}: missing parent unit {parent_id!r}")
    for stage in ordered:
        stage_id = str(stage.get("id", ""))
        if str(stage.get("map_id", "")) not in map_by_id:
            errors.append(f"{stage_id}: proof map is missing")
        if str(stage.get("primary_unit_id", "")) not in unit_by_id:
            errors.append(f"{stage_id}: primary source unit is missing")
        related = stage.get("related_unit_ids", [])
        if not isinstance(related, list):
            errors.append(f"{stage_id}: related_unit_ids must be an array")
        elif any(str(unit_id) not in unit_by_id for unit_id in related):
            errors.append(f"{stage_id}: related source unit is missing")

    required = {
        'id="source-sidebar"': "v7 needs a source-structure sidebar",
        'id="source-panel"': "v7 needs source navigation",
        'id="spine-panel"': "v7 needs a secondary problem chain",
        'id="main-content"': "v7 needs one page-level reading area",
        'id="content"': "v7 needs one question-page outlet",
        'id="current-link"': "v7 needs a current-question shortcut",
        "function renderSourceNavigation(": "v7 needs source navigation rendering",
        "function renderContentsPage(": "v7 needs a source contents page",
        "function renderUnitPage(": "v7 needs source-unit landing pages",
        "function renderQuestionPage(": "v7 needs unique question pages",
        "function renderProofFor(": "v7 needs local proof rendering",
        "function renderReasoning(": "v7 needs progressive proof disclosure",
        "function routeFromHash(": "v7 needs stable deep links",
        'window.addEventListener("hashchange"': "v7 needs hash navigation",
        '<div class="proof-arrow" aria-hidden="true">↑</div>':
            "v7 needs upward proof arrows",
        '<div class="premise-row">': "v7 needs proof premise rows",
    }
    for token, reason in required.items():
        if token not in source_text:
            errors.append(reason)
    if not any(
        token in source_text
        for token in (
            '<section class="proof-section" aria-label="局部关系">',
            '<section class="proof-section" aria-label="局部论证">',
        )
    ):
        errors.append("v7 needs a directly available local relation")
    forbidden = {
        'id="graph-viewport"': "free canvas is forbidden",
        'id="graph-svg"': "single giant SVG is forbidden",
        "function setZoomAt(": "canvas zoom is forbidden",
        "function systemLayout(": "whole-book canvas layout is forbidden",
        "function argumentLayout(": "free graph layout is forbidden",
        '"pointerdown"': "canvas panning is forbidden",
        '"wheel"': "canvas zoom is forbidden",
        "左边是结论": "old right-to-left grammar is forbidden",
        "右边是理由": "old right-to-left grammar is forbidden",
        "局部关系图": "redundant proof heading is forbidden",
        "这个回答凭什么成立": "redundant proof heading is forbidden",
        "阅读规则": "self-explaining interface copy is forbidden",
        "SOURCE-GROUNDED READING": "decorative interface taxonomy is forbidden",
        "阅读入口": "redundant navigation heading is forbidden",
    }
    for token, reason in forbidden.items():
        if token in source_text:
            errors.append(f"Forbidden v7 behavior {token!r}: {reason}")
    if not parser.has_viewport:
        errors.append("Missing responsive viewport meta")
    if not parser.has_focus_visible:
        warnings.append("No :focus-visible rule detected")
    if not parser.has_reduced_motion:
        warnings.append("No prefers-reduced-motion rule detected")
    if not parser.has_skip_link:
        warnings.append("No skip link detected")
    errors.extend(validate_v7_contrast(source_text))
    return errors, warnings, counts


def validate(path: Path) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not path.is_file():
        return [f"Map file not found: {path}"], warnings, {}

    parser = LearningMapParser()
    try:
        source_text = path.read_text(encoding="utf-8")
        parser.feed(source_text)
    except (OSError, UnicodeError) as exc:
        return [f"Could not read map: {exc}"], warnings, {}

    if parser.body_attributes.get("data-sml-version") == "7":
        return validate_v7(parser, source_text)
    if parser.body_attributes.get("data-sml-version") == "6":
        return validate_v6(parser, source_text)
    if parser.body_attributes.get("data-sml-version") == "5":
        return validate_v5(parser, source_text)
    if parser.body_attributes.get("data-sml-version") == "4":
        return validate_v4(parser, source_text)

    if not parser.nodes:
        errors.append("No .knowledge-node buttons found")
        return errors, warnings, {}

    ids = [node.node_id for node in parser.nodes]
    empty_ids = [index for index, node_id in enumerate(ids, start=1) if not node_id]
    if empty_ids:
        errors.append(f"Nodes without id at positions: {empty_ids}")

    duplicate_ids = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    if duplicate_ids:
        errors.append(f"Duplicate node ids: {duplicate_ids}")

    node_by_id = {node.node_id: node for node in parser.nodes if node.node_id}
    map_version = parser.body_attributes.get("data-sml-version", "")
    is_generated = map_version in {"2", "3"}
    is_v3 = map_version == "3"

    for node in parser.nodes:
        missing = [
            name
            for name in REQUIRED_DATA
            if name not in node.attributes
            or (name != "data-parent" and not node.attributes[name])
        ]
        if is_generated and not node.attributes.get("data-mastery"):
            missing.append("data-mastery")
        if is_v3 and not node.attributes.get("data-node-type"):
            missing.append("data-node-type")
        if missing:
            errors.append(f"{node.node_id or '<missing-id>'}: missing {missing}")

        states = STATUS_CLASSES & set(node.classes)
        if len(states) != 1:
            errors.append(
                f"{node.node_id or '<missing-id>'}: expected one status class, "
                f"found {sorted(states)}"
            )
        else:
            state = next(iter(states))
            data_status = node.attributes.get("data-status", "")
            if data_status not in STATUS_ALIASES[state]:
                errors.append(
                    f"{node.node_id}: data-status {data_status!r} conflicts with class {state!r}"
                )

        if node.parent and node.parent not in node_by_id:
            errors.append(f"{node.node_id}: missing parent {node.parent}")

        if not node.text:
            errors.append(f"{node.node_id}: node has no visible text")

    roots = [node.node_id for node in parser.nodes if not node.parent]
    if len(roots) != 1:
        errors.append(f"Expected exactly one root, found {roots}")

    current = [node.node_id for node in parser.nodes if node.status == "current"]
    complete = parser.body_attributes.get("data-course-complete") == "true"
    expected_current_count = 0 if complete else 1
    if len(current) != expected_current_count:
        errors.append(
            f"Expected {expected_current_count} current node(s), found {current}"
        )

    aria_current = [
        node.node_id
        for node in parser.nodes
        if node.attributes.get("aria-current") == "step"
    ]
    if is_generated and aria_current != current:
        errors.append(
            f"aria-current nodes {aria_current} do not match current nodes {current}"
        )

    cycles = find_cycles(node_by_id)
    if cycles:
        errors.append(f"Parent cycle detected from: {cycles}")

    if not is_v3:
        for node in parser.nodes:
            if node.status != "mastered":
                continue
            cursor = node.parent
            seen: set[str] = set()
            while cursor and cursor not in seen:
                seen.add(cursor)
                parent = node_by_id.get(cursor)
                if parent is None:
                    break
                if parent.status != "mastered":
                    errors.append(
                        f"{node.node_id}: mastered node has non-mastered ancestor "
                        f"{parent.node_id}"
                    )
                    break
                cursor = parent.parent

    if not parser.has_viewport:
        errors.append("Missing responsive viewport meta")
    if not parser.has_focus_visible:
        warnings.append("No :focus-visible rule detected")
    if not parser.has_reduced_motion:
        warnings.append("No prefers-reduced-motion rule detected")
    if not parser.has_skip_link:
        warnings.append("No skip link detected")

    counts = {
        "nodes": len(parser.nodes),
        "mastered": sum(node.status == "mastered" for node in parser.nodes),
        "current": len(current),
        "future": sum(node.status == "future" for node in parser.nodes),
    }

    if is_generated:
        body_revision = parser.body_attributes.get("data-revision", "")
        if not body_revision.isdigit():
            errors.append(f"Invalid body data-revision: {body_revision!r}")
        if not parser.body_attributes.get("data-course-id"):
            errors.append("Missing body data-course-id")

        progress_values = {
            "data-total": counts["nodes"],
            "data-mastered": counts["mastered"],
            "data-current": counts["current"],
            "data-future": counts["future"],
        }
        for name, expected in progress_values.items():
            actual = int_attribute(parser.progress_attributes, name, errors)
            if actual is not None and actual != expected:
                errors.append(
                    f"Progress {name}={actual} does not match actual count {expected}"
                )

    if is_v3:
        required_views = {"path", "why", "uses"}
        missing_views = sorted(required_views - parser.view_names)
        if missing_views:
            errors.append(f"Missing reasoning views: {missing_views}")
        if "system" in parser.view_names:
            errors.append("Whole-book system graph must not be a default view")
        if not parser.has_problem_index:
            errors.append("Missing stable problem index")
        if not parser.has_reasoning_canvas:
            errors.append("Missing local reasoning canvas")
        if not parser.has_breadcrumb:
            errors.append("Missing reasoning breadcrumb")
        if not parser.has_mobile_reasoning:
            errors.append("Missing mobile textual reasoning path")
        future_without_lock = sorted(
            node.node_id
            for node in parser.nodes
            if node.status == "future"
            and node.attributes.get("data-answer-hidden") != "true"
        )
        if future_without_lock:
            errors.append(
                "Future answers are not marked hidden: "
                f"{future_without_lock}"
            )

        raw_edges = "".join(parser.semantic_edge_text).strip()
        if not raw_edges:
            errors.append("Missing semantic-edge dataset")
        else:
            try:
                semantic_edges = json.loads(raw_edges)
            except json.JSONDecodeError as exc:
                errors.append(f"Invalid semantic-edge JSON: {exc}")
                semantic_edges = []
            if not isinstance(semantic_edges, list):
                errors.append("Semantic-edge dataset must be an array")
                semantic_edges = []

            edge_ids: set[str] = set()
            connected_nodes: set[str] = set()
            required_edge_fields = {
                "id",
                "from",
                "to",
                "relation",
                "label",
                "rationale",
            }
            for index, edge in enumerate(semantic_edges, start=1):
                if not isinstance(edge, dict):
                    errors.append(f"Semantic edge {index} must be an object")
                    continue
                missing_edge_fields = sorted(
                    field
                    for field in required_edge_fields
                    if not edge.get(field)
                )
                if missing_edge_fields:
                    errors.append(
                        f"Semantic edge {index} missing {missing_edge_fields}"
                    )
                    continue
                edge_id = str(edge["id"])
                if edge_id in edge_ids:
                    errors.append(f"Duplicate semantic edge id: {edge_id}")
                edge_ids.add(edge_id)
                source = str(edge["from"])
                target = str(edge["to"])
                if source not in node_by_id:
                    errors.append(f"{edge_id}: missing source node {source}")
                if target not in node_by_id:
                    errors.append(f"{edge_id}: missing target node {target}")
                connected_nodes.update((source, target))

            if len(node_by_id) > 1:
                isolated = sorted(set(node_by_id) - connected_nodes)
                if isolated:
                    errors.append(f"Semantically isolated nodes: {isolated}")

    return errors, warnings, counts


def main() -> int:
    args = parse_args()
    errors, warnings, counts = validate(args.map_path.resolve())

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        return 1

    print(
        "OK: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
        + f", path={args.map_path.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
