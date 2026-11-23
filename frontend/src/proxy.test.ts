// @vitest-environment node
/**
 * The Pages Function that forwards /api/* to the API on Render. It lives in functions/, where
 * every file becomes a route, so its test lives here.
 */
import { describe, expect, it, vi } from "vitest";
import { proxy, RETRY_DELAYS_MS, type Deps } from "../functions/api/[[path]]";

const ENV = { API_ORIGIN: "https://api.example.com" };

function deps(...answers: (Response | Error)[]) {
  const calls: { url: string; init: RequestInit }[] = [];
  const sleeps: number[] = [];
  const fake: Deps = {
    fetch: vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init: init ?? {} });
      const next = answers.length > 1 ? answers.shift()! : answers[0]!;
      if (next instanceof Error) throw next;
      return next.clone();
    }) as Deps["fetch"],
    sleep: async (ms: number) => {
      sleeps.push(ms);
    },
  };
  return { fake, calls, sleeps };
}

const status = (code: number, init: ResponseInit = {}) =>
  new Response(code === 204 ? null : "{}", { status: code, ...init });

describe("proxy", () => {
  it("forwards method, path, query, body and set-cookie", async () => {
    const upstream = new Response('{"access_token":"t"}', {
      status: 200,
      headers: { "Set-Cookie": "refresh_token=abc; Path=/api/v1/auth; HttpOnly; Secure" },
    });
    const { fake, calls } = deps(upstream);
    const request = new Request("https://shortlist.pages.dev/api/v1/auth/login?next=%2Ffeed", {
      method: "POST",
      body: '{"email":"a@b.in"}',
      headers: { "Content-Type": "application/json" },
    });

    const response = await proxy(request, ENV, fake);

    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("https://api.example.com/api/v1/auth/login?next=%2Ffeed");
    expect(calls[0]!.init.method).toBe("POST");
    expect(new TextDecoder().decode(calls[0]!.init.body as ArrayBuffer)).toBe('{"email":"a@b.in"}');
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("refresh_token=abc");
  });

  it("strips host and cf headers", async () => {
    const { fake, calls } = deps(status(200));
    const request = new Request("https://shortlist.pages.dev/api/v1/feed", {
      headers: {
        Host: "shortlist.pages.dev",
        "CF-Connecting-IP": "1.2.3.4",
        "CF-Ray": "abc",
        "X-Forwarded-For": "1.2.3.4",
        "X-Forwarded-Proto": "https",
        Authorization: "Bearer t",
        Accept: "application/json",
      },
    });

    await proxy(request, ENV, fake);

    const sent = new Headers(calls[0]!.init.headers);
    expect([...sent.keys()].sort()).toEqual(["accept", "authorization"]);
  });

  it("passes redirects through instead of following them", async () => {
    const { fake, calls } = deps(status(303, { headers: { Location: "https://jobs.example/1" } }));

    const response = await proxy(new Request("https://s.pages.dev/api/v1/l/tok"), ENV, fake);

    expect(calls[0]!.init.redirect).toBe("manual");
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("https://jobs.example/1");
  });

  it("retries GET through cold start", async () => {
    const { fake, calls, sleeps } = deps(
      new TypeError("connection refused"),
      status(503),
      status(200),
    );

    const response = await proxy(new Request("https://s.pages.dev/api/v1/health"), ENV, fake);

    expect(response.status).toBe(200);
    expect(calls).toHaveLength(3);
    expect(sleeps).toEqual([1000, 2000]);
  });

  it("does not retry POST", async () => {
    const { fake, calls } = deps(status(503));
    const request = new Request("https://s.pages.dev/api/v1/postings/1/feedback", {
      method: "POST",
      body: "{}",
    });

    const response = await proxy(request, ENV, fake);

    expect(response.status).toBe(503);
    expect(calls).toHaveLength(1);
  });

  it("answers 503 problem JSON after about a minute of retries", async () => {
    const { fake, calls, sleeps } = deps(status(502));

    const response = await proxy(new Request("https://s.pages.dev/api/v1/feed"), ENV, fake);

    expect(calls).toHaveLength(RETRY_DELAYS_MS.length + 1);
    expect(sleeps.reduce((a, b) => a + b, 0)).toBe(63_000);
    expect(response.status).toBe(503);
    expect(response.headers.get("content-type")).toBe("application/problem+json");
    expect(await response.json()).toEqual({
      type: "about:blank",
      title: "Server is waking up",
      status: 503,
    });
  });

  it("answers 503 problem JSON when a POST cannot reach the API", async () => {
    const { fake } = deps(new TypeError("connection refused"));
    const request = new Request("https://s.pages.dev/api/v1/auth/login", {
      method: "POST",
      body: "{}",
    });

    const response = await proxy(request, ENV, fake);

    expect(response.status).toBe(503);
  });
});
