import { setTimeout as sleep } from "node:timers/promises";

/** Thrown to stop retrying immediately (e.g. 4xx that will never succeed). */
export class PermanentError extends Error {
  override name = "PermanentError";
}

/** Thrown when the caller knows exactly how long to wait (e.g. rate-limit reset). */
export class RetryAfterError extends Error {
  override name = "RetryAfterError";
  constructor(message: string, readonly waitMs: number) {
    super(message);
  }
}

export interface RetryOptions {
  attempts?: number;
  baseMs?: number;
  maxMs?: number;
  /** A RetryAfterError asking to wait longer than this gives up now; the job queue retries later. */
  maxWaitMs?: number;
  onRetry?: (err: unknown, attempt: number, waitMs: number) => void;
  sleepFn?: (ms: number) => Promise<unknown>;
}

export async function withRetry<T>(fn: (attempt: number) => Promise<T>, opts: RetryOptions = {}): Promise<T> {
  const { attempts = 4, baseMs = 1000, maxMs = 60_000, maxWaitMs = 120_000, onRetry, sleepFn = sleep } = opts;
  let lastErr: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await fn(attempt);
    } catch (err) {
      lastErr = err;
      if (err instanceof PermanentError || attempt === attempts) break;
      if (err instanceof RetryAfterError && err.waitMs > maxWaitMs) break;
      const backoff = Math.min(maxMs, baseMs * 2 ** (attempt - 1));
      const jitter = Math.random() * backoff * 0.2;
      const waitMs = err instanceof RetryAfterError ? err.waitMs : backoff + jitter;
      onRetry?.(err, attempt, waitMs);
      await sleepFn(waitMs);
    }
  }
  throw lastErr;
}
