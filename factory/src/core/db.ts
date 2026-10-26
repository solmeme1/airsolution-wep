import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

export type JobStage = "plan" | "build" | "publish";
export type JobStatus = "pending" | "running" | "done" | "failed";

export interface RepoRow {
  full_name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  license: string | null;
  stars: number;
  forks: number;
  open_issues: number;
  pushed_at: string;
  archived: number;
  score: number;
  status: string;
}

export interface JobRow {
  id: number;
  repo: string;
  stage: JobStage;
  status: JobStatus;
  attempts: number;
  last_error: string | null;
  output: string | null;
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS repos (
  full_name    TEXT PRIMARY KEY,
  html_url     TEXT NOT NULL,
  description  TEXT,
  language     TEXT,
  license      TEXT,
  stars        INTEGER NOT NULL,
  forks        INTEGER NOT NULL,
  open_issues  INTEGER NOT NULL,
  pushed_at    TEXT NOT NULL,
  archived     INTEGER NOT NULL DEFAULT 0,
  score        REAL NOT NULL,
  status       TEXT NOT NULL DEFAULT 'discovered',
  discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo        TEXT NOT NULL REFERENCES repos(full_name),
  stage       TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending',
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_error  TEXT,
  output      TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (repo, stage)
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (stage, status);
`;

export class FactoryDb {
  readonly db: DatabaseSync;

  constructor(path: string) {
    if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
    this.db.exec(SCHEMA);
  }

  upsertRepo(r: Omit<RepoRow, "status">): void {
    this.db
      .prepare(
        `INSERT INTO repos (full_name, html_url, description, language, license, stars, forks, open_issues, pushed_at, archived, score)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(full_name) DO UPDATE SET
           description = excluded.description, stars = excluded.stars, forks = excluded.forks,
           open_issues = excluded.open_issues, pushed_at = excluded.pushed_at, archived = excluded.archived,
           license = excluded.license, score = excluded.score, updated_at = datetime('now')`,
      )
      .run(r.full_name, r.html_url, r.description, r.language, r.license, r.stars, r.forks, r.open_issues, r.pushed_at, r.archived, r.score);
  }

  topCandidates(limit: number, status = "discovered"): RepoRow[] {
    return this.db
      .prepare("SELECT * FROM repos WHERE status = ? ORDER BY score DESC LIMIT ?")
      .all(status, limit) as unknown as RepoRow[];
  }

  setRepoStatus(fullName: string, status: string): void {
    this.db.prepare("UPDATE repos SET status = ?, updated_at = datetime('now') WHERE full_name = ?").run(status, fullName);
  }

  enqueue(repo: string, stage: JobStage): void {
    this.db.prepare("INSERT OR IGNORE INTO jobs (repo, stage) VALUES (?, ?)").run(repo, stage);
  }

  /** Atomically claim the next pending job for a stage (safe across concurrent workers). */
  claimNext(stage: JobStage, maxAttempts: number): JobRow | undefined {
    return this.db
      .prepare(
        `UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = datetime('now')
         WHERE id = (
           SELECT id FROM jobs WHERE stage = ? AND status IN ('pending', 'failed') AND attempts < ?
           ORDER BY id LIMIT 1
         )
         RETURNING *`,
      )
      .get(stage, maxAttempts) as JobRow | undefined;
  }

  finishJob(id: number, output: string): void {
    this.db.prepare("UPDATE jobs SET status = 'done', output = ?, last_error = NULL, updated_at = datetime('now') WHERE id = ?").run(output, id);
  }

  /** A permanent failure exhausts the job's attempts so it is never claimed again. */
  failJob(id: number, error: string, opts: { permanent?: boolean; maxAttempts?: number } = {}): void {
    this.db
      .prepare(
        `UPDATE jobs SET status = 'failed', last_error = ?, attempts = CASE WHEN ? THEN max(attempts, ?) ELSE attempts END,
           updated_at = datetime('now') WHERE id = ?`,
      )
      .run(error, opts.permanent ? 1 : 0, opts.maxAttempts ?? 0, id);
  }

  getRepo(fullName: string): RepoRow | undefined {
    return this.db.prepare("SELECT * FROM repos WHERE full_name = ?").get(fullName) as RepoRow | undefined;
  }

  getJobOutput(repo: string, stage: JobStage): string | null {
    const row = this.db.prepare("SELECT output FROM jobs WHERE repo = ? AND stage = ? AND status = 'done'").get(repo, stage) as
      | { output: string | null }
      | undefined;
    return row?.output ?? null;
  }

  /** Jobs left 'running' by a crashed process go back to the queue. */
  recoverStale(minutes = 30): number {
    const res = this.db
      .prepare(`UPDATE jobs SET status = 'pending' WHERE status = 'running' AND updated_at < datetime('now', ?)`)
      .run(`-${minutes} minutes`);
    return Number(res.changes);
  }

  stats(): Record<string, unknown> {
    const repos = this.db.prepare("SELECT status, COUNT(*) AS n FROM repos GROUP BY status").all();
    const jobs = this.db.prepare("SELECT stage, status, COUNT(*) AS n FROM jobs GROUP BY stage, status").all();
    return { repos, jobs };
  }

  close(): void {
    this.db.close();
  }
}
