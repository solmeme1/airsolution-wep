import { parseArgs } from "node:util";
import { config } from "./core/config.ts";
import { FactoryDb } from "./core/db.ts";
import { createLogger, errorInfo } from "./core/logger.ts";
import { defaultDeps, drainStage, enqueueTop, runCycle } from "./pipeline/orchestrator.ts";
import { runScan } from "./scanner/index.ts";

const log = createLogger("cli");

const USAGE = `Usage: npm run factory -- <command> [options]

Commands:
  scan                 Search GitHub for abandoned permissive-licensed repos and score them
  top [--limit N]      Show the highest-scoring candidates
  plan [--top N]       Queue the top N candidates and generate modernization plans with Claude
  run [--top N]        Full unattended cycle: scan -> queue -> plan (cron-safe)
  status               Queue and repo counts
`;

async function main(): Promise<number> {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    options: { top: { type: "string", default: "5" }, limit: { type: "string", default: "20" } },
  });
  const [command] = positionals;
  const top = Number(values.top);

  const db = new FactoryDb(config.FACTORY_DB_PATH);
  try {
    switch (command) {
      case "scan":
        console.log(JSON.stringify(await runScan(config, db), null, 2));
        return 0;
      case "top":
        console.table(
          db.topCandidates(Number(values.limit)).map((r) => ({ repo: r.full_name, score: r.score, stars: r.stars, lang: r.language, license: r.license, pushed: r.pushed_at.slice(0, 10) })),
        );
        return 0;
      case "plan": {
        const queued = enqueueTop(db, top);
        const res = await drainStage("plan", db, defaultDeps(config), Math.max(top, queued));
        console.log(JSON.stringify({ queued, ...res }, null, 2));
        return res.failed > 0 && res.done === 0 ? 1 : 0;
      }
      case "run":
        console.log(JSON.stringify(await runCycle(config, db, defaultDeps(config), { top, planLimit: top }), null, 2));
        return 0;
      case "status":
        console.log(JSON.stringify(db.stats(), null, 2));
        return 0;
      default:
        console.log(USAGE);
        return command ? 2 : 0;
    }
  } finally {
    db.close();
  }
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    log.error("fatal", errorInfo(err));
    process.exit(1);
  });
