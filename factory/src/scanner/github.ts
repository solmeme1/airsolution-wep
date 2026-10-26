import { createLogger, type Logger } from "../core/logger.ts";
import { PermanentError, RetryAfterError, withRetry } from "../core/retry.ts";

const API = "https://api.github.com";

export interface GithubRepo {
  full_name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  license: { spdx_id: string; key: string } | null;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  pushed_at: string;
  archived: boolean;
  fork: boolean;
  default_branch: string;
}

export class GithubClient {
  private readonly log: Logger;

  constructor(private readonly token?: string, log?: Logger) {
    this.log = log ?? createLogger("github");
  }

  private async request<T>(path: string): Promise<T> {
    return withRetry(
      async () => {
        const res = await fetch(`${API}${path}`, {
          headers: {
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ghost-source-factory",
            ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
          },
          signal: AbortSignal.timeout(30_000),
        });
        if (res.ok) return (await res.json()) as T;

        const body = await res.text();
        const remaining = res.headers.get("x-ratelimit-remaining");
        const reset = Number(res.headers.get("x-ratelimit-reset"));
        const retryAfter = Number(res.headers.get("retry-after"));
        if (res.status === 429 || (res.status === 403 && (remaining === "0" || retryAfter))) {
          const waitMs = retryAfter ? retryAfter * 1000 : reset ? Math.max(1000, reset * 1000 - Date.now() + 1000) : 60_000;
          throw new RetryAfterError(`GitHub rate limited on ${path}`, waitMs);
        }
        if (res.status >= 500) throw new Error(`GitHub ${res.status} on ${path}`);
        throw new PermanentError(`GitHub ${res.status} on ${path}: ${body.slice(0, 200)}`);
      },
      {
        onRetry: (err, attempt, waitMs) =>
          this.log.warn("retrying GitHub request", { path, attempt, waitMs: Math.round(waitMs), reason: (err as Error).message }),
      },
    );
  }

  async searchRepos(query: string, perPage: number): Promise<GithubRepo[]> {
    const q = encodeURIComponent(query);
    const data = await this.request<{ items: GithubRepo[] }>(`/search/repositories?q=${q}&sort=stars&order=desc&per_page=${perPage}`);
    return data.items;
  }

  async getRepo(fullName: string): Promise<GithubRepo> {
    return this.request<GithubRepo>(`/repos/${fullName}`);
  }

  async getReadme(fullName: string): Promise<string | null> {
    try {
      const data = await this.request<{ content: string; encoding: string }>(`/repos/${fullName}/readme`);
      return Buffer.from(data.content, data.encoding as BufferEncoding).toString("utf8");
    } catch (err) {
      if (err instanceof PermanentError) return null;
      throw err;
    }
  }

  /** Flat list of file paths on the default branch (truncated by GitHub for huge repos). */
  async getTree(fullName: string, branch: string): Promise<string[]> {
    const data = await this.request<{ tree: { path: string; type: string }[]; truncated: boolean }>(
      `/repos/${fullName}/git/trees/${encodeURIComponent(branch)}?recursive=1`,
    );
    return data.tree.filter((e) => e.type === "blob").map((e) => e.path);
  }
}
