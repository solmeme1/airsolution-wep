import assert from "node:assert/strict";
import { test } from "node:test";
import { PermanentError, RetryAfterError, withRetry } from "../src/core/retry.ts";

const noSleep = async () => {};

test("retries transient errors then succeeds", async () => {
  let calls = 0;
  const result = await withRetry(async () => {
    if (++calls < 3) throw new Error("flaky");
    return "ok";
  }, { sleepFn: noSleep });
  assert.equal(result, "ok");
  assert.equal(calls, 3);
});

test("stops immediately on PermanentError", async () => {
  let calls = 0;
  await assert.rejects(
    withRetry(async () => {
      calls++;
      throw new PermanentError("nope");
    }, { sleepFn: noSleep }),
    PermanentError,
  );
  assert.equal(calls, 1);
});

test("honours RetryAfterError wait time", async () => {
  const waits: number[] = [];
  let calls = 0;
  await withRetry(async () => {
    if (++calls === 1) throw new RetryAfterError("rate limited", 5000);
    return true;
  }, { sleepFn: async (ms) => waits.push(ms) });
  assert.deepEqual(waits, [5000]);
});

test("gives up instead of sleeping past maxWaitMs", async () => {
  let calls = 0;
  await assert.rejects(
    withRetry(async () => {
      calls++;
      throw new RetryAfterError("rate limited for an hour", 3_600_000);
    }, { sleepFn: noSleep, maxWaitMs: 120_000 }),
    RetryAfterError,
  );
  assert.equal(calls, 1);
});
