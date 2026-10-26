import type { Config } from "../core/config.ts";

export interface SubscriptionPlan {
  productName: string;
  monthlyPriceKrw: number;
  monthlyPriceUsd: number;
}

export interface BillingProvider {
  readonly name: "stripe" | "toss";
  /** Creates the product + recurring price and returns a checkout URL. */
  createSubscriptionProduct(plan: SubscriptionPlan): Promise<{ productId: string; checkoutUrl: string }>;
}

class NotConfiguredBilling implements BillingProvider {
  constructor(readonly name: "stripe" | "toss") {}

  async createSubscriptionProduct(): Promise<never> {
    throw new Error(`${this.name} billing is not implemented yet (stage 3)`);
  }
}

export function billingFor(cfg: Config): BillingProvider {
  // TODO(stage 3): StripeBilling via the `stripe` SDK, TossBilling via Toss Payments billing-key API.
  return new NotConfiguredBilling(cfg.BILLING_PROVIDER);
}
