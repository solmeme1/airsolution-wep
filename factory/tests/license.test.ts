import assert from "node:assert/strict";
import { test } from "node:test";
import { isCommerciallyReusable, requiresAttribution } from "../src/scanner/license.ts";

test("permissive licenses pass, copyleft and missing licenses fail", () => {
  for (const ok of ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC", "Unlicense"]) assert.equal(isCommerciallyReusable(ok), true, ok);
  for (const bad of ["GPL-3.0", "AGPL-3.0", "LGPL-2.1", "MPL-2.0", "NOASSERTION", null, undefined, ""]) {
    assert.equal(isCommerciallyReusable(bad), false, String(bad));
  }
});

test("attribution flags", () => {
  assert.equal(requiresAttribution("MIT"), true);
  assert.equal(requiresAttribution("Unlicense"), false);
});
