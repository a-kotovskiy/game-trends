/**
 * Cloudflare Worker — Game Trends trigger & status proxy
 *
 * Env vars (set via wrangler.toml or Cloudflare dashboard):
 *   GITHUB_TOKEN  — Personal access token with repo/actions:write scope
 *   REPO          — "owner/repo", e.g. "a-kotovskiy/game-trends"
 *
 * Endpoints:
 *   POST /trigger  — Dispatch workflow_dispatch for update.yml
 *   GET  /status   — Read status.json from raw.githubusercontent.com
 */

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const RATE_LIMIT_MINUTES = 10;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

async function handleTrigger(env) {
  const repo = env.REPO || "a-kotovskiy/game-trends";
  const token = env.GITHUB_TOKEN;

  if (!token) {
    return json({ error: "GITHUB_TOKEN not configured" }, 500);
  }

  // Fetch current status to enforce rate limit
  const statusUrl = `https://raw.githubusercontent.com/${repo}/main/status.json`;
  try {
    const statusRes = await fetch(statusUrl, { cf: { cacheTtl: 0 } });
    if (statusRes.ok) {
      const status = await statusRes.json();

      if (status.running) {
        return json({ error: "Already running", running: true }, 429);
      }

      if (status.last_run) {
        const lastRun = new Date(status.last_run);
        const minutesAgo = (Date.now() - lastRun.getTime()) / 60000;
        if (minutesAgo < RATE_LIMIT_MINUTES) {
          const waitMin = Math.ceil(RATE_LIMIT_MINUTES - minutesAgo);
          return json(
            { error: `Rate limited. Try again in ${waitMin} min`, wait_minutes: waitMin },
            429
          );
        }
      }
    }
  } catch (_) {
    // If we can't read status, allow trigger anyway
  }

  // Dispatch workflow_dispatch
  const apiUrl = `https://api.github.com/repos/${repo}/actions/workflows/update.yml/dispatches`;
  const res = await fetch(apiUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "game-trends-worker",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  if (res.status === 204) {
    return json({ ok: true, message: "Workflow triggered" });
  }

  const body = await res.text();
  return json({ error: "GitHub API error", status: res.status, body }, 502);
}

async function handleStatus(env) {
  const repo = env.REPO || "a-kotovskiy/game-trends";
  const statusUrl = `https://raw.githubusercontent.com/${repo}/main/status.json`;

  try {
    const res = await fetch(statusUrl, {
      cf: { cacheTtl: 30, cacheEverything: true },
    });
    if (!res.ok) {
      return json({ error: "Failed to fetch status", status: res.status }, 502);
    }
    const data = await res.json();
    return json(data);
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method.toUpperCase();

    // CORS preflight
    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (url.pathname === "/trigger" && method === "POST") {
      return handleTrigger(env);
    }

    if (url.pathname === "/status" && method === "GET") {
      return handleStatus(env);
    }

    return json({ error: "Not found" }, 404);
  },
};
