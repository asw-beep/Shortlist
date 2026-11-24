/**
 * The Cloudflare Worker that serves Shortlist. Static assets (the built app in dist/) are
 * served by Cloudflare directly, with index.html as the fallback for app routes like /feed;
 * wrangler.json runs this worker first only for /api/*, which goes through the same proxy
 * a Pages deployment uses (functions/api/[[path]].ts): same origin, cold-start retries.
 */
import { proxy, type Env as ProxyEnv } from "../functions/api/[[path]]";

interface Env extends ProxyEnv {
  ASSETS: { fetch: (request: Request) => Promise<Response> };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (new URL(request.url).pathname.startsWith("/api/")) return proxy(request, env);
    return env.ASSETS.fetch(request);
  },
};
