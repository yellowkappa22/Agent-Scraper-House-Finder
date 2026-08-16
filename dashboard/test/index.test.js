import assert from "node:assert/strict";
import test from "node:test";

import { generateMessage, getProperties, messageInstructions, setStatus } from "../src/index.js";

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

test("couples metadata takes precedence over self-contained messaging", () => {
  const instructions = messageInstructions({ couples_supported: true, self_contained: true });
  assert.match(instructions, /partner will move in/);
});

test("self-contained messaging does not mention a partner", () => {
  const instructions = messageInstructions({ couples_supported: false, self_contained: true });
  assert.match(instructions, /Do not mention a partner/);
});

test("message generation sends trusted Gold content to GPT-5.6 Luna", async () => {
  const env = {
    OPENAI_API_KEY: "test-secret",
    GOLD: {
      get: async () => ({
        json: async () => ({
          generated_at: "2026-08-16T12:00:00Z",
          properties: [{
            id: "spareroom:1",
            address: "Room in Headington",
            description: "Sunny room near the park.",
            couples_supported: true,
            self_contained: false,
          }],
        }),
      }),
    },
  };
  let request;
  const response = await generateMessage(env, "spareroom:1", async (url, init) => {
    request = { url, init, body: JSON.parse(init.body) };
    return Response.json({ output_text: "Hello, is this still available?" });
  });
  assert.equal(response.status, 200);
  assert.equal(request.url, "https://api.openai.com/v1/responses");
  assert.equal(request.body.model, "gpt-5.6-luna");
  assert.match(request.body.input, /Room in Headington/);
  assert.match(request.body.input, /Sunny room near the park/);
  assert.equal(request.init.headers.authorization, "Bearer test-secret");
  assert.deepEqual(await response.json(), { message: "Hello, is this still available?" });
});

test("message generation rejects unknown properties before calling OpenAI", async () => {
  const env = {
    OPENAI_API_KEY: "test-secret",
    GOLD: {
      get: async () => ({
        json: async () => ({ generated_at: "2026-08-16T12:00:00Z", properties: [] }),
      }),
    },
  };
  const response = await generateMessage(env, "missing", async () => {
    throw new Error("OpenAI should not be called");
  });
  assert.equal(response.status, 404);
});
