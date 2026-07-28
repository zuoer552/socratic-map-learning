#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const htmlPath = path.resolve(
  process.argv[2] || "map.html"
);
const html = fs.readFileSync(htmlPath, "utf8");
if (!html.includes('data-sml-version="7"')) {
  throw new Error("Expected a v7 source-guided question reader");
}

for (const id of [
  "source-sidebar",
  "source-panel",
  "spine-panel",
  "main-content",
  "content",
  "current-link",
  "graph-data"
]) {
  if (!html.includes(`id="${id}"`)) {
    throw new Error(`Missing v7 interface element: ${id}`);
  }
}

for (const forbidden of [
  'id="graph-viewport"',
  'id="graph-svg"',
  "function setZoomAt(",
  "function systemLayout(",
  "function argumentLayout(",
  '"pointerdown"',
  '"wheel"',
  "左边是结论",
  "右边是理由",
  "查看本单元导读",
  "unit-overview-link",
  "SOURCE-GROUNDED READING",
  "阅读入口",
  "先找到原书位置",
  "章节负责告诉你",
  "从哪个部分进入",
  "点击原书单元",
  "本单元的问题",
  "理解这一部分必须回答什么",
  "下级结构",
  "继续进入哪一部分",
  "局部关系图",
  "这个回答凭什么成立",
  "阅读规则",
  "本问说明",
  "它在原书中处理什么",
  "学习状态被保留",
  "为了不提前泄露",
  "问题链起点",
  "问题链终点"
]) {
  if (html.includes(forbidden)) {
    throw new Error(`Obsolete free-canvas behavior remains: ${forbidden}`);
  }
}

for (const [pattern, message] of [
  [/function renderSourceNavigation\(/, "Missing source navigation"],
  [/function renderContentsPage\(/, "Missing source contents"],
  [/function renderUnitPage\(/, "Missing source-unit page"],
  [/function renderQuestionPage\(/, "Missing unique question page"],
  [/function resolvedMovesMarkup\(/, "Missing resolved-move renderer"],
  [/function activeMoveMarkup\(/, "Missing active-move renderer"],
  [/function renderProofFor\(/, "Missing local proof renderer"],
  [/function renderReasoning\(/, "Missing recursive proof disclosure"],
  [/function routeFromHash\(/, "Missing stable hash routing"],
  [/window\.addEventListener\("hashchange"/, "Missing deep-link updates"],
  [/<div class="proof-arrow" aria-hidden="true">↑<\/div>/, "Missing upward proof arrows"],
  [/<div class="premise-row">/, "Missing proof premise rows"],
  [/const modeCopyByMode = \{/, "Missing work-mode copy routing"],
  [/deeper: "展开/, "Missing progressive disclosure"],
  [/>上一问</, "Missing previous-question context"],
  [/>下一问</, "Missing next-question context"]
]) {
  if (!pattern.test(html)) throw new Error(message);
}

const questionRenderer = html.match(
  /function renderQuestionPage\([\s\S]*?\n    function closeSidebar\(/
)?.[0] || "";
const resolvedPosition = questionRenderer.indexOf("${resolvedMovesMarkup(stage)}");
const activeMovePosition = questionRenderer.indexOf("${activeMoveMarkup(stage)}");
const proofPosition = questionRenderer.indexOf("${renderProofFor(stage)}");
const contextPosition = questionRenderer.indexOf('<section class="question-context"');
const chainPosition = questionRenderer.indexOf("${chainContext(stage)}");
if (
  proofPosition < 0 ||
  resolvedPosition < 0 ||
  activeMovePosition < 0 ||
  contextPosition < 0 ||
  chainPosition < 0 ||
  !(
    resolvedPosition < activeMovePosition &&
    activeMovePosition < proofPosition &&
    proofPosition < contextPosition &&
    contextPosition < chainPosition
  )
) {
  throw new Error(
    "Question pages must show closure, active move, proof, source, then chain"
  );
}

const dataMatch = html.match(
  /<script type="application\/json" id="graph-data">([\s\S]*?)<\/script>/
);
if (!dataMatch) throw new Error("Missing graph-data JSON");
const snapshot = JSON.parse(dataMatch[1]);
if (snapshot.schema_version !== 7) {
  throw new Error(`Expected schema 7, got ${snapshot.schema_version}`);
}
const atlas = snapshot.argument_atlas;
const learningCycle = snapshot.learning_cycle || {};
const activeMove = learningCycle.active_move || {};
for (const forbiddenField of [
  "expected_answer",
  "required_premises",
  "learner_response",
  "attempts"
]) {
  if (Object.hasOwn(activeMove, forbiddenField)) {
    throw new Error(`Public active move leaks ${forbiddenField}`);
  }
}
for (const move of learningCycle.resolved_moves || []) {
  if (!move.resolved_statement) {
    throw new Error("Resolved move lacks its canonical statement");
  }
  if (
    Object.hasOwn(move, "expected_answer") ||
    Object.hasOwn(move, "learner_response") ||
    Object.hasOwn(move, "attempts")
  ) {
    throw new Error("Public resolved move leaks teacher-only history");
  }
}
const spine = atlas?.system_spine;
const structure = atlas?.source_structure;
if (!atlas?.maps?.length || !Array.isArray(atlas.inferences)) {
  throw new Error("Argument atlas is incomplete");
}
if (!spine?.stages?.length || spine.transitions.length !== spine.stages.length - 1) {
  throw new Error("Whole-book problem chain is incomplete");
}
if (!structure?.units?.length) {
  throw new Error("Source structure is incomplete");
}
const unitIds = new Set(structure.units.map((unit) => unit.id));
if (unitIds.size !== structure.units.length) {
  throw new Error("Source units are not unique");
}
for (const stage of spine.stages) {
  if (!unitIds.has(stage.primary_unit_id)) {
    throw new Error(`${stage.id} lacks one primary source unit`);
  }
  if (!(stage.related_unit_ids || []).every((id) => unitIds.has(id))) {
    throw new Error(`${stage.id} points to an unknown related source unit`);
  }
}
for (let index = 0; index < spine.stages.length - 1; index += 1) {
  const current = spine.stages[index];
  const next = spine.stages[index + 1];
  const transition = spine.transitions[index];
  if (
    transition.from_stage_id !== current.id ||
    transition.to_stage_id !== next.id ||
    transition.label !== "因此必须追问" ||
    !transition.bridge
  ) {
    throw new Error(`Broken problem transition at ${index + 1}`);
  }
}
if (!spine.stages
  .filter((stage) => stage.status === "future")
  .every((stage) => !stage.answer_id)) {
  throw new Error("A future question exposes its answer");
}

const runtimeMatches = [...html.matchAll(/<script(?:\s[^>]*)?>\s*([\s\S]*?)<\/script>/g)];
const runtime = runtimeMatches
  .map((match) => match[1])
  .find((source) => source.includes('"use strict"'));
if (!runtime) throw new Error("Missing executable runtime script");
new vm.Script(runtime, { filename: `${htmlPath}:runtime` });

console.log(
  `OK v7 units=${structure.units.length} stages=${spine.stages.length} ` +
  `maps=${atlas.maps.length} inferences=${atlas.inferences.length}`
);
