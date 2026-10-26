import type { Config } from "../core/config.ts";
import type { FactoryDb, JobStage } from "../core/db.ts";
import { createLogger, errorInfo } from "../core/logger.ts";
import { PermanentError } from "../core/retry.ts";
import { DryRunPublisher, type PublishTarget } from "../publisher/index.ts";
import { ClaudeEngine } from "../refactor/claude.ts";
import { ModernizationPlan, planRepo } from "../refactor/planner.ts";
import { GithubClient } from "../scanner/github.ts";
import { runScan } from "../scanner/index.ts";

const log = createLogger("pipeline");
const MAX_ATTEMPTS = 3;

export interface PipelineDeps {
  gh: GithubClient;
  claude: ClaudeEngine;
  publisher: PublishTarget;
}

export function defaultDeps(cfg: Config): PipelineDeps {
  return {
    gh: new GithubClient(cfg.FACTORY_GITHUB_TOKEN),
    claude: new ClaudeEngine(cfg.FACTORY_MODEL, cfg.ANTHROPIC_API_KEY),
    publisher: new DryRunPublisher(),
  };
}

/** Queue the top-N scored repos for planning. */
export function enqueueTop(db: FactoryDb, n: number): number {
  const repos = db.topCandidates(n);
  for (const r of repos) {
    db.enqueue(r.full_name, "plan");
    db.setRepoStatus(r.full_name, "queued");
  }
  return repos.length;
}

/** Drain one stage's queue. Each job is isolated: a failure is recorded, never thrown. */
export async function drainStage(stage: JobStage, db: FactoryDb, deps: PipelineDeps, limit: number): Promise<{ done: number; failed: number }> {
  let done = 0;
  let failed = 0;
  for (let i = 0; i < limit; i++) {
    const job = db.claimNext(stage, MAX_ATTEMPTS);
    if (!job) break;
    try {
      const output = await runJob(stage, job.repo, db, deps);
      db.finishJob(job.id, output);
      done++;
      log.info("job done", { stage, repo: job.repo, attempt: job.attempts });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      db.failJob(job.id, msg, { permanent: err instanceof PermanentError, maxAttempts: MAX_ATTEMPTS });
      failed++;
      log.error("job failed", { stage, repo: job.repo, attempt: job.attempts, permanent: err instanceof PermanentError, ...errorInfo(err) });
    }
  }
  return { done, failed };
}

async function runJob(stage: JobStage, repo: string, db: FactoryDb, deps: PipelineDeps): Promise<string> {
  switch (stage) {
    case "plan": {
      const row = db.getRepo(repo);
      if (!row) throw new PermanentError(`unknown repo ${repo}`);
      const plan = await planRepo(row, deps.gh, deps.claude);
      db.setRepoStatus(repo, plan.viable ? "planned" : "rejected");
      if (plan.viable) db.enqueue(repo, "build");
      return JSON.stringify(plan);
    }
    case "build":
      // TODO(stage 2): clone into ./workspace, run the Claude Agent SDK / Claude Code headless
      // against the plan, run tests, push to a new repo. Kept as an explicit no-op for now.
      throw new PermanentError("build stage not implemented yet");
    case "publish": {
      const planJson = db.getJobOutput(repo, "plan");
      if (!planJson) throw new PermanentError(`no plan for ${repo}`);
      const res = await deps.publisher.publish(repo, ModernizationPlan.parse(JSON.parse(planJson)));
      return JSON.stringify(res);
    }
  }
}

/** One full unattended cycle: scan -> queue -> plan. Safe to run from cron. */
export async function runCycle(cfg: Config, db: FactoryDb, deps: PipelineDeps, opts: { top: number; planLimit: number }) {
  const recovered = db.recoverStale();
  if (recovered) log.warn("recovered stale jobs", { recovered });
  const scan = await runScan(cfg, db, deps.gh);
  const queued = enqueueTop(db, opts.top);
  const plan = await drainStage("plan", db, deps, opts.planLimit);
  return { scan, queued, plan };
}
