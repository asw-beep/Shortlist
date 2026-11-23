/**
 * Cloudflare Pages Function: forwards every /api/* request to the API on Render, so the
 * browser sees one origin for pages and API. That keeps the SameSite=Strict refresh cookie
 * first-party and the API free of CORS.
 *
 * Render's free tier sleeps after 15 idle minutes and takes about a minute to wake. While it
 * wakes, GET and HEAD requests are retried with backoff (1, 2, 4, 8, 16, 32 s); after that the
 * proxy answers a 503 problem the app understands. Other methods are never retried: a POST
 * that reached the API once must not run twice.
 */

export interface Env {
  API_ORIGIN: string;
}

export interface Deps {
  fetch: typeof fetch;
  sleep: (ms: number) => Promise<void>;
}

export const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 16000, 32000];

const IDEMPOTENT = new Set(["GET", "HEAD"]);
const RETRYABLE_STATUS = new Set([502, 503]);

const defaultDeps: Deps = {
  fetch: (input, init) => fetch(input, init),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

/** Headers that describe the hop to Cloudflare, not the request itself. */
function forwardable(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower !== "host" &&
    lower !== "x-real-ip" &&
    !lower.startsWith("cf-") &&
    !lower.startsWith("x-forwarded-")
  );
}

function wakingUp(): Response {
  return new Response(
    JSON.stringify({ type: "about:blank", title: "Server is waking up", status: 503 }),
    { status: 503, headers: { "Content-Type": "application/problem+json", "Retry-After": "5" } },
  );
}

export async function proxy(
  request: Request,
  env: Env,
  deps: Deps = defaultDeps,
): Promise<Response> {
  const url = new URL(request.url);
  const target = `${env.API_ORIGIN.replace(/\/+$/, "")}${url.pathname}${url.search}`;
  const headers = new Headers();
  request.headers.forEach((value, name) => {
    if (forwardable(name)) headers.set(name, value);
  });
  const idempotent = IDEMPOTENT.has(request.method);
  const init: RequestInit = {
    method: request.method,
    headers,
    body: idempotent ? undefined : await request.arrayBuffer(),
    redirect: "manual", // the signed-link route answers 303; the browser must follow it
  };

  for (let attempt = 0; ; attempt++) {
    let response: Response | null;
    try {
      response = await deps.fetch(target, init);
    } catch {
      response = null; // the API is unreachable: asleep, or restarting
    }
    if (!idempotent) return response ?? wakingUp();
    if (response && !RETRYABLE_STATUS.has(response.status)) return response;
    const delay = RETRY_DELAYS_MS[attempt];
    if (delay === undefined) return wakingUp();
    response?.body?.cancel().catch(() => undefined); // free the connection; don't wait
    await deps.sleep(delay);
  }
}

export const onRequest = (context: { request: Request; env: Env }): Promise<Response> =>
  proxy(context.request, context.env);
