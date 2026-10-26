import assert from "node:assert/strict";
import { test } from "node:test";
import { scoreRepo, type ScoreInput } from "../src/scanner/scoring.ts";

const now = new Date("2026-10-01T00:00:00Z");
const base: ScoreInput = {
  stars: 5000,
  forks: 400,
  openIssues: 80,
  pushedAt: new Date("2022-01-01T00:00:00Z"),
  archived: false,
  language: "JavaScript",
  hasDescription: true,
};

test("actively maintained repos get no abandonment credit", () => {
  const active = scoreRepo({ ...base, pushedAt: new Date("2026-09-01T00:00:00Z") }, now);
  const abandoned = scoreRepo(base, now);
  assert.ok(abandoned - active >= 19, `${abandoned} vs ${active}`);
});

test("more demand scores higher", () => {
  assert.ok(scoreRepo({ ...base, stars: 20000 }, now) > scoreRepo({ ...base, stars: 300 }, now));
});

test("score stays within 0..100", () => {
  const max = scoreRepo({ ...base, stars: 1e7, forks: 1e6, openIssues: 1e5, archived: true, language: "CoffeeScript" }, now);
  const min = scoreRepo({ ...base, stars: 0, forks: 0, openIssues: 0, pushedAt: now, language: null, hasDescription: false }, now);
  assert.ok(max <= 100 && min >= 0, `${min}..${max}`);
});
