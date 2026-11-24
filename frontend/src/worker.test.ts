// @vitest-environment node
/**
 * The Cloudflare Worker that serves the app: /api/* goes through the proxy to Render,
 * everything else is a static asset (with the single-page-app fallback configured in
 * wrangler.json, not in a _redirects file, which Workers reject as an infinite loop).
 */
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import worker from "../worker/index";

const API_ORIGIN = "https://api.example.com";

function env() {
  const assets = { fetch: vi.fn(async () => new Response("<html>app</html>")) };
  return { env: { API_ORIGIN, ASSETS: assets }, assets };
}

describe("worker", () => {
  it("proxies /api requests to the API origin", async () => {
    const upstream = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));
    const { env: e, assets } = env();

    const response = await worker.fetch(new Request("https://app.dev/api/v1/health"), e);

    expect(response.status).toBe(200);
    expect(String(upstream.mock.calls[0]![0])).toBe(`${API_ORIGIN}/api/v1/health`);
    expect(assets.fetch).not.toHaveBeenCalled();
  });

  it("serves everything else from the static assets", async () => {
    const upstream = vi.spyOn(globalThis, "fetch");
    const { env: e, assets } = env();

    const response = await worker.fetch(new Request("https://app.dev/feed"), e);

    expect(await response.text()).toBe("<html>app</html>");
    expect(assets.fetch).toHaveBeenCalledOnce();
    expect(upstream).not.toHaveBeenCalled();
  });
});

describe("deploy config", () => {
  const config = JSON.parse(readFileSync(new URL("../wrangler.json", import.meta.url), "utf8"));

  it("runs the worker first for /api and falls back to index.html for app routes", () => {
    expect(config.main).toBe("worker/index.ts");
    expect(config.assets.directory).toBe("./dist");
    expect(config.assets.run_worker_first).toEqual(["/api/*"]);
    expect(config.assets.not_found_handling).toBe("single-page-application");
    expect(config.vars.API_ORIGIN).toMatch(/^https:\/\/.+\.onrender\.com$/);
  });

  it("has no _redirects file (Workers reject the SPA rule as an infinite loop)", () => {
    expect(existsSync(new URL("../public/_redirects", import.meta.url))).toBe(false);
  });
});
