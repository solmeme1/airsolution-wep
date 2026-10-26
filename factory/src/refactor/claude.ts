import Anthropic from "@anthropic-ai/sdk";
import type { z } from "zod";
import { createLogger } from "../core/logger.ts";
import { PermanentError } from "../core/retry.ts";

const log = createLogger("claude");

export interface StructuredRequest<T> {
  system: string;
  prompt: string;
  schema: z.ZodType<T>;
  jsonSchema: Record<string, unknown>;
  effort?: "low" | "medium" | "high" | "xhigh" | "max";
  maxTokens?: number;
}

/**
 * Thin wrapper over the Messages API for headless structured generation.
 * The SDK already retries 408/409/429/5xx and connection errors (maxRetries).
 */
export class ClaudeEngine {
  private readonly client: Anthropic;

  constructor(private readonly model: string, apiKey?: string) {
    this.client = new Anthropic({ ...(apiKey ? { apiKey } : {}), maxRetries: 4 });
  }

  async structured<T>(req: StructuredRequest<T>): Promise<T> {
    let message;
    try {
      const stream = this.client.beta.messages.stream({
        model: this.model,
        max_tokens: req.maxTokens ?? 32000,
        betas: ["server-side-fallback-2026-07-01"],
        fallbacks: "default", // on a safety refusal the API retries on a fallback model in the same call
        output_config: {
          effort: req.effort ?? "high",
          format: { type: "json_schema", schema: req.jsonSchema },
        },
        system: req.system,
        messages: [{ role: "user", content: req.prompt }],
      });
      message = await stream.finalMessage();
    } catch (err) {
      if (err instanceof Anthropic.AuthenticationError || err instanceof Anthropic.PermissionDeniedError) {
        throw new PermanentError(`Claude auth failed: ${err.message}`);
      }
      if (err instanceof Anthropic.BadRequestError || err instanceof Anthropic.NotFoundError) {
        throw new PermanentError(`Claude rejected request: ${err.message}`);
      }
      throw err; // rate limit / 5xx / network after SDK retries: let the job queue retry later
    }

    log.info("claude call finished", {
      model: message.model,
      stop_reason: message.stop_reason,
      input_tokens: message.usage.input_tokens,
      output_tokens: message.usage.output_tokens,
    });

    if (message.stop_reason === "refusal") {
      throw new PermanentError(`Claude declined (${message.stop_details?.category ?? "unknown"})`);
    }
    if (message.stop_reason === "max_tokens") {
      throw new Error("Claude output hit max_tokens; increase maxTokens");
    }

    const text = message.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join("");
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error("Claude returned non-JSON output");
    }
    const result = req.schema.safeParse(parsed);
    if (!result.success) throw new Error(`Claude output failed schema validation: ${result.error.message}`);
    return result.data;
  }
}
