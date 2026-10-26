// Only licenses that allow commercial reuse of a modified version without forcing
// the derived SaaS to be open-sourced. Copyleft (GPL/AGPL/LGPL/MPL/EUPL) and repos
// with no license (all rights reserved) are rejected.
const PERMISSIVE = new Set([
  "mit",
  "apache-2.0",
  "bsd-2-clause",
  "bsd-3-clause",
  "isc",
  "0bsd",
  "unlicense",
  "zlib",
  "cc0-1.0",
]);

/** Licenses that require keeping the original notice in the shipped product. */
const ATTRIBUTION_REQUIRED = new Set(["mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "zlib"]);

export function isCommerciallyReusable(spdxKey: string | null | undefined): boolean {
  return !!spdxKey && PERMISSIVE.has(spdxKey.toLowerCase());
}

export function requiresAttribution(spdxKey: string | null | undefined): boolean {
  return !!spdxKey && ATTRIBUTION_REQUIRED.has(spdxKey.toLowerCase());
}
