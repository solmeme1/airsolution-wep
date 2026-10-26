import type { ModernizationPlan } from "../refactor/planner.ts";
import { createLogger } from "../core/logger.ts";

const log = createLogger("publisher");

export interface PublishTarget {
  readonly name: string;
  publish(repo: string, plan: ModernizationPlan): Promise<{ url: string | null }>;
}

/**
 * Stage 3 placeholder. Real targets (Vercel deploy, Product Hunt / dev.to posts)
 * plug in behind this interface. Until PUBLISH_DRY_RUN=false and a target is
 * implemented, nothing leaves the machine.
 */
export class DryRunPublisher implements PublishTarget {
  readonly name = "dry-run";

  async publish(repo: string, plan: ModernizationPlan) {
    log.info("dry-run publish", { repo, product: plan.product_name, type: plan.product_type });
    return { url: null };
  }
}
