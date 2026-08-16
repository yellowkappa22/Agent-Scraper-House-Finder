import assert from "node:assert/strict";
import test from "node:test";

import { getProperties, setStatus } from "../src/index.js";

test("properties merge Gold with persistent D1 status", async () => {
  const env = {
    GOLD: {
      get: async () => ({
        json: async () => ({
          generated_at: "2026-08-16T12:00:00Z",
          properties: [{ id: "spareroom:1", rent: 700 }],
        }),
      }),
    },
    DB: {
      prepare: () => ({
        all: async () => ({
          results: [{
            property_id: "spareroom:1",
            status: "in_process",
            updated_at: "2026-08-16T12:01:00Z",
          }],
        }),
      }),
    },
  };

  const result = await getProperties(env);
  assert.equal(result.properties[0].status, "in_process");
  assert.equal(result.properties[0].rent, 700);
});

test("invalid statuses are rejected before writing to D1", async () => {
  const request = new Request("https://example.test", {
    method: "PUT",
    body: JSON.stringify({ status: "deleted" }),
  });
  const response = await setStatus(request, {}, "spareroom:1");
  assert.equal(response.status, 400);
});
