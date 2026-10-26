# Ghost Source Factory (project #3)

An unattended pipeline that finds **abandoned, permissively licensed** open-source projects, scores how much they're worth, and has Claude plan how to rebuild each one as a modern SaaS product, developer API, CLI or library.

```
 ┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐
 │ 1. scan  │──▶│ value score  │──▶│ 2. plan      │──▶│ 2. build │──▶│ 3. publish + │
 │ GitHub   │   │ + license    │   │ (Claude,     │   │ (TODO)   │   │    billing   │
 │ search   │   │   filter     │   │  structured) │   │          │   │ (dry-run)    │
 └──────────┘   └──────────────┘   └──────────────┘   └──────────┘   └──────────────┘
        all state in SQLite (repos + jobs queue) → crash-safe, cron-safe
```

| Stage | Status | Code |
|---|---|---|
| Scan GitHub, filter licenses, score value | ✅ working | `src/scanner/` |
| Modernization plan with Claude (JSON schema output) | ✅ working (needs API key) | `src/refactor/` |
| Build: clone and refactor with Claude Code running headless | ⏳ stub | `src/pipeline/orchestrator.ts` (`build`) |
| Publish (Vercel, Product Hunt, dev.to) | ⏳ dry-run only | `src/publisher/` |
| Billing (Stripe / Toss Payments) | ⏳ interface only | `src/billing/` |

## Quick start

```bash
cd factory
npm install
cp .env.example .env        # fill in keys (or set them as environment secrets)
npm run scan                # discover + score candidates
npm run factory -- top      # show the best candidates
npm run plan -- --top 3     # Claude writes modernization plans for the top 3
npm run status
npm run run:pipeline        # full cycle (scan → queue → plan); put this in cron
```

Checks: `npm run typecheck` and `npm test`.

## How it stays safe to run with nobody watching

- **Job queue in SQLite**: `claimNext` claims a job atomically, failures are recorded per job and retried up to 3 times, and jobs left `running` by a crashed process are put back in the queue (`recoverStale`).
- **Error types**: `PermanentError` (bad credentials, 4xx, a Claude refusal) is never retried. Transient errors back off exponentially, and GitHub rate limits wait until the reset time.
- **One failure doesn't stop the run**: a language that fails to scan or a repo that fails to plan is logged and skipped.
- **JSON-lines logs** on stdout/stderr, ready for any log collector. Set the level with `LOG_LEVEL`.
- **Untrusted input**: README text and file lists are passed to Claude as data inside tags, and the system prompt tells it never to follow instructions found in them.

## License policy

Only these licenses pass: MIT, Apache-2.0, BSD-2/3, ISC, 0BSD, Unlicense, Zlib and CC0. GPL, AGPL, LGPL, MPL and repos with no license are rejected automatically. For MIT, Apache and BSD, `requiresAttribution()` flags that the shipped product must keep the original copyright notice.

## Scoring (0–100)

`demand` (stars, 35) + `adoption` (forks, 15) + `unmet need` (open issues, 15) + `abandonment` (peaks 3–6 years idle, 20) + `modernization upside` (legacy stack, 10) + description (5). Claude's plan then makes the business call and sets `viable=false` when a maintained competitor already exists.
