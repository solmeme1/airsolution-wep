import assert from "node:assert/strict";
import { test } from "node:test";
import { FactoryDb } from "../src/core/db.ts";

function seed(db: FactoryDb, name: string, score: number) {
  db.upsertRepo({
    full_name: name, html_url: `https://github.com/${name}`, description: null, language: "JavaScript",
    license: "MIT", stars: 1000, forks: 10, open_issues: 5, pushed_at: "2021-01-01T00:00:00Z", archived: 0, score,
  });
}

test("candidates come back ordered by score", () => {
  const db = new FactoryDb(":memory:");
  seed(db, "a/low", 10);
  seed(db, "b/high", 90);
  assert.deepEqual(db.topCandidates(5).map((r) => r.full_name), ["b/high", "a/low"]);
});

test("job queue: claim, fail, retry, permanent failure", () => {
  const db = new FactoryDb(":memory:");
  seed(db, "a/repo", 50);
  db.enqueue("a/repo", "plan");
  db.enqueue("a/repo", "plan"); // idempotent

  const first = db.claimNext("plan", 3);
  assert.equal(first?.attempts, 1);
  assert.equal(db.claimNext("plan", 3), undefined, "running job is not claimable twice");

  db.failJob(first!.id, "transient");
  const second = db.claimNext("plan", 3);
  assert.equal(second?.attempts, 2);

  db.failJob(second!.id, "fatal", { permanent: true, maxAttempts: 3 });
  assert.equal(db.claimNext("plan", 3), undefined, "permanent failure is not retried");
});

test("finished job output is retrievable", () => {
  const db = new FactoryDb(":memory:");
  seed(db, "a/repo", 50);
  db.enqueue("a/repo", "plan");
  const job = db.claimNext("plan", 3)!;
  db.finishJob(job.id, '{"ok":true}');
  assert.equal(db.getJobOutput("a/repo", "plan"), '{"ok":true}');
});
