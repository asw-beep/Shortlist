import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, test, vi } from "vitest";
import { AuthProvider } from "../auth/AuthProvider";
import { ForgotPasswordPage } from "./ForgotPasswordPage";
import { ResetPasswordPage } from "./ResetPasswordPage";

type Call = { url: string; body: unknown };

/** The API as these pages see it: no session to restore, reset endpoints answer as given. */
function fakeApi(answers: Record<string, number>): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(String(input));
    const path = new URL(request.url, "http://localhost").pathname;
    const text = await request.text();
    calls.push({ url: path, body: text ? JSON.parse(text) : null });
    const status = answers[path] ?? 401;
    const body =
      status === 204 || status === 202
        ? null
        : JSON.stringify({ type: "about:blank", title: "No", status });
    return new Response(body, { status, headers: { "Content-Type": "application/problem+json" } });
  });
  return calls;
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <Routes>
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/login" element={<p>Login page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("forgot password sends the email and gives the same answer either way", async () => {
  const calls = fakeApi({ "/api/v1/auth/password-reset/request": 202 });
  renderAt("/forgot-password");

  await userEvent.type(await screen.findByLabelText("Email"), "student@iiitkottayam.ac.in");
  await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));

  expect(await screen.findByText(/If an account uses that email/)).toBeInTheDocument();
  expect(calls.find((c) => c.url.endsWith("/password-reset/request"))?.body).toEqual({
    email: "student@iiitkottayam.ac.in",
  });
});

test("reset password sends the token from the link and goes to log in", async () => {
  const calls = fakeApi({ "/api/v1/auth/password-reset/confirm": 204 });
  renderAt("/reset-password#token=abc123");

  await userEvent.type(await screen.findByLabelText("New password"), "a long new passphrase");
  await userEvent.click(screen.getByRole("button", { name: "Save new password" }));

  expect(await screen.findByText("Login page")).toBeInTheDocument();
  await waitFor(() =>
    expect(calls.find((c) => c.url.endsWith("/password-reset/confirm"))?.body).toEqual({
      token: "abc123",
      new_password: "a long new passphrase",
    }),
  );
});

test("reset password without a token explains where the link comes from", async () => {
  fakeApi({});
  renderAt("/reset-password");

  expect(await screen.findByText(/needs the link from your reset email/)).toBeInTheDocument();
});
