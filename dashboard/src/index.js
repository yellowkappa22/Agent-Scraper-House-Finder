import {
  couplesExamples,
  couplesPrompt,
  selfContainedExamples,
  selfContainedPrompt,
} from "./prompts.js";

const ALLOWED_STATUSES = new Set([
  "new", "in_process", "contacted", "viewing_confirmed",
  "waiting_for_selection", "failed", "ignored",
]);

function json(data, init = {}) {
  return Response.json(data, {
    ...init,
    headers: { "cache-control": "no-store", ...init.headers },
  });
}

async function readProperties(env) {
  const object = await env.GOLD.get("current.json");
  if (!object) {
    throw new Error("Gold snapshot current.json was not found");
  }
  const snapshot = await object.json();
  if (
    !snapshot ||
    typeof snapshot.generated_at !== "string" ||
    !Array.isArray(snapshot.properties)
  ) {
    throw new Error("Gold snapshot has an invalid schema");
  }
  return snapshot;
}

async function readStatuses(env) {
  const result = await env.DB.prepare(
    "SELECT property_id, status, updated_at FROM property_status",
  ).all();
  return new Map(
    result.results.map((row) => [
      row.property_id,
      { status: row.status, updated_at: row.updated_at },
    ]),
  );
}

async function getProperties(env) {
  const [snapshot, statuses] = await Promise.all([
    readProperties(env),
    readStatuses(env),
  ]);
  return {
    generated_at: snapshot.generated_at,
    properties: snapshot.properties.map((property) => {
      const saved = statuses.get(property.id);
      return {
        ...property,
        status: saved?.status ?? "new",
        status_updated_at: saved?.updated_at ?? null,
      };
    }),
  };
}

async function setStatus(request, env, propertyId) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Request body must be JSON" }, { status: 400 });
  }
  if (!ALLOWED_STATUSES.has(body?.status)) {
    return json(
      { error: "Invalid property status" },
      { status: 400 },
    );
  }
  const updatedAt = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO property_status (property_id, status, updated_at)
     VALUES (?, ?, ?)
     ON CONFLICT(property_id) DO UPDATE SET
       status = excluded.status,
       updated_at = excluded.updated_at`,
  )
    .bind(propertyId, body.status, updatedAt)
    .run();
  return json({ id: propertyId, status: body.status, updated_at: updatedAt });
}

const SIGNATURE = "Best regards,\nKasper Pettersson";

function ensureSignature(message) {
  const body = message
    .trim()
    .replace(/\n*Best regards,?\s*(?:\n[^\n]+)?\s*$/i, "")
    .trimEnd();
  return `${body}\n\n${SIGNATURE}`;
}

function responseText(response) {
  if (typeof response.output_text === "string" && response.output_text.trim()) {
    return response.output_text.trim();
  }
  return (response.output ?? [])
    .flatMap((item) => item.content ?? [])
    .filter((item) => item.type === "output_text")
    .map((item) => item.text)
    .join("\n")
    .trim();
}

function messageInstructions(property) {
  const couples = property.couples_supported === true;
  const selfContained = property.self_contained === true;
  if (!couples && !selfContained) return null;
  const prompt = couples ? couplesPrompt : selfContainedPrompt;
  const examples = couples ? couplesExamples : selfContainedExamples;
  if (!examples.length) return prompt;
  return `${prompt}\n\nExamples of the desired style:\n${examples
    .map((example, index) => `Example ${index + 1}:\n${example}`)
    .join("\n\n")}`;
}

async function generateMessage(env, propertyId, fetchImpl = fetch) {
  if (!env.OPENAI_API_KEY) {
    return json({ error: "Message generation is not configured" }, { status: 503 });
  }
  const snapshot = await readProperties(env);
  const property = snapshot.properties.find((item) => item.id === propertyId);
  if (!property) return json({ error: "Property not found" }, { status: 404 });
  const instructions = messageInstructions(property);
  if (!instructions) {
    return json({ error: "Property is not eligible for message generation" }, { status: 400 });
  }

  const listing = [
    `Listing heading/address: ${String(property.address ?? "").slice(0, 1000)}`,
    `Listing description: ${String(property.description ?? "").slice(0, 12000)}`,
  ].join("\n\n");
  const openaiResponse = await fetchImpl("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-5.6-luna",
      reasoning: { effort: "low" },
      max_output_tokens: 350,
      instructions,
      input: listing,
    }),
  });
  if (!openaiResponse.ok) throw new Error(`OpenAI request failed: ${openaiResponse.status}`);
  const message = responseText(await openaiResponse.json());
  if (!message) throw new Error("OpenAI returned an empty message");
  return json({ message: ensureSignature(message) });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/api/health") {
      return json({ status: "ok" });
    }

    if (request.method === "GET" && url.pathname === "/api/properties") {
      try {
        return json(await getProperties(env));
      } catch (error) {
        console.error("Unable to load dashboard properties", error);
        return json({ error: "Unable to load properties" }, { status: 503 });
      }
    }

    const statusMatch = url.pathname.match(/^\/api\/properties\/([^/]+)\/status$/);
    if (request.method === "PUT" && statusMatch) {
      try {
        return await setStatus(request, env, decodeURIComponent(statusMatch[1]));
      } catch (error) {
        console.error("Unable to update property status", error);
        return json({ error: "Unable to update status" }, { status: 503 });
      }
    }

    const messageMatch = url.pathname.match(/^\/api\/properties\/([^/]+)\/message$/);
    if (request.method === "POST" && messageMatch) {
      try {
        return await generateMessage(env, decodeURIComponent(messageMatch[1]));
      } catch (error) {
        console.error("Unable to generate property message", error);
        return json({ error: "Unable to generate message" }, { status: 503 });
      }
    }

    if (url.pathname.startsWith("/api/")) {
      return json({ error: "Not found" }, { status: 404 });
    }

    return env.ASSETS.fetch(request);
  },
};

export { generateMessage, getProperties, messageInstructions, setStatus };
