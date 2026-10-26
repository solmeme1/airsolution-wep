export interface ScoreInput {
  stars: number;
  forks: number;
  openIssues: number;
  pushedAt: Date;
  archived: boolean;
  language: string | null;
  hasDescription: boolean;
}

// Stacks where a rewrite to modern TS/Next.js/Python adds the most value.
const MODERNIZATION_BONUS: Record<string, number> = {
  JavaScript: 1.0,
  PHP: 1.0,
  CoffeeScript: 1.2,
  Ruby: 0.8,
  Python: 0.6,
  Java: 0.6,
  Go: 0.3,
  TypeScript: 0.2,
};

/**
 * Value score 0..100. Rewards proven demand (stars, forks, people still filing
 * issues) on a project nobody maintains anymore.
 */
export function scoreRepo(r: ScoreInput, now = new Date()): number {
  const monthsIdle = Math.max(0, (now.getTime() - r.pushedAt.getTime()) / (30.44 * 24 * 3600 * 1000));

  const demand = Math.min(1, Math.log10(r.stars + 1) / 4.5); // ~31k stars saturates
  const adoption = Math.min(1, Math.log10(r.forks + 1) / 3.5);
  const unmetNeed = Math.min(1, Math.log10(r.openIssues + 1) / 2.5); // open issues nobody answers
  // Peaks around 3-6 years idle; very old projects often solve obsolete problems.
  const abandonment = monthsIdle < 12 ? 0 : monthsIdle <= 72 ? Math.min(1, (monthsIdle - 12) / 24) : Math.max(0.4, 1 - (monthsIdle - 72) / 120);
  const modernization = Math.min(1, (r.language ? MODERNIZATION_BONUS[r.language] : undefined) ?? 0.4);

  let score =
    demand * 35 +
    adoption * 15 +
    unmetNeed * 15 +
    abandonment * 20 +
    modernization * 10 +
    (r.hasDescription ? 5 : 0);

  if (r.archived) score += 2; // explicit "no longer maintained" signal
  return Math.round(Math.min(100, score) * 10) / 10;
}
