import { existsSync } from "node:fs";
import { z } from "zod";

if (existsSync(".env")) process.loadEnvFile(".env");

const csv = z
  .string()
  .transform((s) => s.split(",").map((x) => x.trim()).filter(Boolean));

const schema = z.object({
  ANTHROPIC_API_KEY: z.string().optional(),
  FACTORY_MODEL: z.string().default("claude-opus-5-5"),
  FACTORY_GITHUB_TOKEN: z.string().optional(),
  SCAN_MIN_STARS: z.coerce.number().int().positive().default(300),
  SCAN_ABANDONED_MONTHS: z.coerce.number().int().positive().default(24),
  SCAN_LANGUAGES: csv.default(["JavaScript", "Python", "TypeScript", "Go", "Ruby", "PHP"]),
  SCAN_MAX_RESULTS_PER_LANGUAGE: z.coerce.number().int().min(1).max(100).default(30),
  FACTORY_DB_PATH: z.string().default("./data/factory.db"),
  BILLING_PROVIDER: z.enum(["stripe", "toss"]).default("stripe"),
  STRIPE_SECRET_KEY: z.string().optional(),
  TOSS_SECRET_KEY: z.string().optional(),
  PUBLISH_DRY_RUN: z
    .string()
    .default("true")
    .transform((v) => v.toLowerCase() !== "false"),
});

export type Config = z.infer<typeof schema>;

// Empty strings in .env mean "unset".
const env = Object.fromEntries(
  Object.entries(process.env).filter(([, v]) => v !== undefined && v !== ""),
);

export const config: Config = schema.parse(env);
