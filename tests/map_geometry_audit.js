#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const htmlPath = path.resolve(
  process.argv[2] || "map.html"
);
const html = fs.readFileSync(htmlPath, "utf8");
const graphData = html.match(
  /<script type="application\/json" id="graph-data">([\s\S]*?)<\/script>/
)?.[1];
if (!graphData) throw new Error("Map is missing graph data");
const snapshot = JSON.parse(graphData);
const atlas = snapshot.argument_atlas;
const nodeIds = new Set(snapshot.nodes.map((node) => node.id));
const inferencesByMap = new Map();
for (const inference of atlas.inferences) {
  if (!inferencesByMap.has(inference.map_id)) {
    inferencesByMap.set(inference.map_id, []);
  }
  inferencesByMap.get(inference.map_id).push(inference);
}

let checkedMaps = 0;
for (const argumentMap of atlas.maps) {
  if (argumentMap.status === "future") {
    if (argumentMap.node_ids.length || argumentMap.conclusion_id) {
      throw new Error(`${argumentMap.id}: future proof leaks its answer`);
    }
    continue;
  }
  if (!argumentMap.node_ids.length) continue;
  checkedMaps += 1;
  if (argumentMap.node_ids.length > 12) {
    throw new Error(`${argumentMap.id}: local proof exceeds 12 propositions`);
  }
  if (!argumentMap.node_ids.includes(argumentMap.conclusion_id)) {
    throw new Error(`${argumentMap.id}: conclusion is outside the local proof`);
  }
  if (!argumentMap.node_ids.every((id) => nodeIds.has(id))) {
    throw new Error(`${argumentMap.id}: local proof references a missing proposition`);
  }
  const reachable = new Set([argumentMap.conclusion_id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const inference of inferencesByMap.get(argumentMap.id) || []) {
      if (!reachable.has(inference.conclusion_id)) continue;
      for (const premise of inference.premise_ids) {
        if (!reachable.has(premise)) {
          reachable.add(premise);
          changed = true;
        }
      }
    }
  }
  const unreachable = argumentMap.node_ids.filter((id) => !reachable.has(id));
  if (unreachable.length) {
    throw new Error(
      `${argumentMap.id}: propositions do not support the top conclusion: ` +
      unreachable.join(", ")
    );
  }
}

for (const token of [
  ".proof-tree",
  ".premise-row",
  ".proof-arrow",
  "renderReasoning(argumentMap.conclusion_id",
  'aria-hidden="true">↑</div>',
  '<details class="deeper-proof">',
  "depth >= 1"
]) {
  if (!html.includes(token)) {
    throw new Error(`Missing bottom-to-top proof contract: ${token}`);
  }
}
for (const token of ["<svg id=\"graph-svg\"", "argumentLayout(", "setZoomAt("]) {
  if (html.includes(token)) {
    throw new Error(`Free-canvas geometry remains: ${token}`);
  }
}

console.log(`OK proof-pages maps=${checkedMaps} direction=bottom-to-top`);
