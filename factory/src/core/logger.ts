// Structured JSON-lines logger so headless runs can be grepped / shipped to a log sink.
type Level = "debug" | "info" | "warn" | "error";

const order: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };
const threshold = order[(process.env.LOG_LEVEL as Level) ?? "info"] ?? order.info;

function emit(level: Level, scope: string, msg: string, data?: Record<string, unknown>) {
  if (order[level] < threshold) return;
  const line = JSON.stringify({ ts: new Date().toISOString(), level, scope, msg, ...data });
  (level === "error" || level === "warn" ? process.stderr : process.stdout).write(line + "\n");
}

export function createLogger(scope: string) {
  return {
    debug: (msg: string, data?: Record<string, unknown>) => emit("debug", scope, msg, data),
    info: (msg: string, data?: Record<string, unknown>) => emit("info", scope, msg, data),
    warn: (msg: string, data?: Record<string, unknown>) => emit("warn", scope, msg, data),
    error: (msg: string, data?: Record<string, unknown>) => emit("error", scope, msg, data),
  };
}

export type Logger = ReturnType<typeof createLogger>;

export function errorInfo(err: unknown): Record<string, unknown> {
  return err instanceof Error ? { error: err.message, name: err.name } : { error: String(err) };
}
