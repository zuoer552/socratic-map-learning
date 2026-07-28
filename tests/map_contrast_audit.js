#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const requireCompound = process.argv.includes("--require-compound");
const htmlArgument = process.argv
  .slice(2)
  .find((argument) => !argument.startsWith("--"));
const htmlPath = path.resolve(
  htmlArgument || "map.html"
);
const html = fs.readFileSync(htmlPath, "utf8");
const style = html.match(/<style>([\s\S]*?)<\/style>/)?.[1] || "";

function variablesFrom(block) {
  return new Map(
    [...block.matchAll(/(--[\w-]+)\s*:\s*(#[\da-fA-F]{6})\s*;/g)].map(
      ([, name, value]) => [name, value.toLowerCase()]
    )
  );
}

const lightBlock = style.match(/:root\s*\{([\s\S]*?)\}/)?.[1] || "";
const darkBlock = style.match(
  /@media\s*\(prefers-color-scheme:\s*dark\)\s*\{[\s\S]*?:root\s*\{([\s\S]*?)\}/
)?.[1] || "";
const themes = {
  light: variablesFrom(lightBlock),
  dark: new Map([
    ...variablesFrom(lightBlock),
    ...variablesFrom(darkBlock)
  ])
};

function rgb(hex) {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function luminance(hex) {
  const channels = rgb(hex).map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * channels[0] +
    0.7152 * channels[1] +
    0.0722 * channels[2]
  );
}

function contrast(foreground, background) {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const surfaces = [
  "default",
  "conclusion",
  "objection",
  "boundary",
  "junction",
  "junction-objection",
  "junction-boundary"
];
const failures = [];
let minimumTextRatio = Number.POSITIVE_INFINITY;
let minimumTextPair = "";

for (const [themeName, tokens] of Object.entries(themes)) {
  for (const surface of surfaces) {
    const backgroundName = `--${surface}-bg`;
    const foregroundName = `--${surface}-fg`;
    const mutedName = `--${surface}-muted`;
    const borderName = `--${surface}-border`;
    for (const name of [
      backgroundName,
      foregroundName,
      mutedName,
      borderName
    ]) {
      if (!tokens.has(name)) {
        failures.push(`${themeName}: missing semantic token ${name}`);
      }
    }
    if (
      tokens.has(backgroundName) &&
      tokens.has(foregroundName) &&
      contrast(tokens.get(foregroundName), tokens.get(backgroundName)) < 4.5
    ) {
      failures.push(
        `${themeName}: ${surface} primary text contrast is ` +
        `${contrast(tokens.get(foregroundName), tokens.get(backgroundName)).toFixed(2)}:1`
      );
    }
    if (tokens.has(backgroundName) && tokens.has(foregroundName)) {
      const ratio = contrast(
        tokens.get(foregroundName),
        tokens.get(backgroundName)
      );
      if (ratio < minimumTextRatio) {
        minimumTextRatio = ratio;
        minimumTextPair = `${themeName}/${surface}/primary`;
      }
    }
    if (
      tokens.has(backgroundName) &&
      tokens.has(mutedName) &&
      contrast(tokens.get(mutedName), tokens.get(backgroundName)) < 4.5
    ) {
      failures.push(
        `${themeName}: ${surface} secondary text contrast is ` +
        `${contrast(tokens.get(mutedName), tokens.get(backgroundName)).toFixed(2)}:1`
      );
    }
    if (tokens.has(backgroundName) && tokens.has(mutedName)) {
      const ratio = contrast(
        tokens.get(mutedName),
        tokens.get(backgroundName)
      );
      if (ratio < minimumTextRatio) {
        minimumTextRatio = ratio;
        minimumTextPair = `${themeName}/${surface}/secondary`;
      }
    }
    if (
      tokens.has("--page") &&
      tokens.has(backgroundName) &&
      tokens.has(borderName)
    ) {
      const boundaryContrast = Math.max(
        contrast(tokens.get(backgroundName), tokens.get("--page")),
        contrast(tokens.get(borderName), tokens.get("--page"))
      );
      if (boundaryContrast < 3) {
        failures.push(
          `${themeName}: ${surface} surface boundary contrast is ` +
          `${boundaryContrast.toFixed(2)}:1`
        );
      }
    }
  }
}

const contracts = [
  [
    /\.proposition\s*\{[\s\S]*?background:\s*var\(--default-bg\)/,
    "proposition surfaces must consume --default-bg"
  ],
  [
    /\.proposition\s*\{[\s\S]*?color:\s*var\(--default-fg\)/,
    "proposition text must consume --default-fg"
  ],
  [
    /\.proposition\.conclusion\s*\{[\s\S]*?background:\s*var\(--conclusion-bg\)/,
    "conclusions must consume conclusion tokens"
  ],
  [
    /\.proposition\.objection\s*\{[\s\S]*?background:\s*var\(--objection-bg\)/,
    "objections must consume objection tokens"
  ],
  [
    /\.inference-card\s*\{[\s\S]*?background:\s*var\(--junction-bg\)/,
    "inference bridges must consume semantic junction tokens"
  ]
];
for (const [pattern, message] of contracts) {
  if (!pattern.test(style)) failures.push(message);
}

const graphData = html.match(
  /<script type="application\/json" id="graph-data">([\s\S]*?)<\/script>/
)?.[1];
if (graphData) {
  const data = JSON.parse(graphData);
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));
  const compoundConclusions = data.argument_atlas.maps
    .filter((map) => map.status !== "future")
    .map((map) => nodeById.get(map.conclusion_id))
    .filter(
      (node) => node && ["boundary", "objection"].includes(node.node_type)
    );
  if (requireCompound && !compoundConclusions.length) {
    failures.push(
      "contrast fixture does not exercise a conclusion + semantic-type combination"
    );
  }
}

if (failures.length) {
  throw new Error(
    `Contrast audit failed for ${htmlPath}:\n- ${failures.join("\n- ")}`
  );
}

console.log(
  `OK contrast themes=${Object.keys(themes).length} surfaces=${surfaces.length} ` +
  `minimum-text=${minimumTextRatio.toFixed(2)}:1 (${minimumTextPair})`
);
