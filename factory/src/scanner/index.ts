import type { Config } from "../core/config.ts";
import type { FactoryDb } from "../core/db.ts";
import { createLogger, errorInfo } from "../core/logger.ts";
import { GithubClient } from "./github.ts";
import { isCommerciallyReusable } from "./license.ts";
import { scoreRepo } from "./scoring.ts";

const log = createLogger("scanner");

export interface ScanResult {
  seen: number;
  stored: number;
  rejectedLicense: number;
  failedLanguages: string[];
}

export function abandonedBefore(months: number, now = new Date()): string {
  const d = new Date(now);
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

export async function runScan(cfg: Config, db: FactoryDb, gh = new GithubClient(cfg.FACTORY_GITHUB_TOKEN)): Promise<ScanResult> {
  const cutoff = abandonedBefore(cfg.SCAN_ABANDONED_MONTHS);
  const result: ScanResult = { seen: 0, stored: 0, rejectedLicense: 0, failedLanguages: [] };

  for (const language of cfg.SCAN_LANGUAGES) {
    const query = `stars:>=${cfg.SCAN_MIN_STARS} pushed:<${cutoff} language:"${language}" fork:false`;
    try {
      const repos = await gh.searchRepos(query, cfg.SCAN_MAX_RESULTS_PER_LANGUAGE);
      for (const r of repos) {
        result.seen++;
        const spdx = r.license?.spdx_id ?? null;
        if (!isCommerciallyReusable(spdx)) {
          result.rejectedLicense++;
          continue;
        }
        const score = scoreRepo({
          stars: r.stargazers_count,
          forks: r.forks_count,
          openIssues: r.open_issues_count,
          pushedAt: new Date(r.pushed_at),
          archived: r.archived,
          language: r.language,
          hasDescription: !!r.description,
        });
        db.upsertRepo({
          full_name: r.full_name,
          html_url: r.html_url,
          description: r.description,
          language: r.language,
          license: spdx,
          stars: r.stargazers_count,
          forks: r.forks_count,
          open_issues: r.open_issues_count,
          pushed_at: r.pushed_at,
          archived: r.archived ? 1 : 0,
          score,
        });
        result.stored++;
      }
      log.info("language scanned", { language, found: repos.length });
    } catch (err) {
      // One failing language must not kill the whole headless run.
      result.failedLanguages.push(language);
      log.error("language scan failed", { language, ...errorInfo(err) });
    }
  }
  log.info("scan complete", { ...result });
  return result;
}
