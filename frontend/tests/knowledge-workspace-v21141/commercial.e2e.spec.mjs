import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { test } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const fixtureRoot = join(
  here,
  "../../../tests/fixtures/knowledge_workspace_v21141",
);
const cases = JSON.parse(
  readFileSync(join(fixtureRoot, "e2e-skeleton.json"), "utf8"),
).cases;

for (const contract of cases) {
  test(`${contract.id}: ${contract.name}`, async () => {
    test.skip(
      contract.status === "blocked",
      contract.evidence[0],
    );
    throw new Error(
      `${contract.id} cannot pass until production-equivalent evidence replaces ${contract.status}`,
    );
  });
}
