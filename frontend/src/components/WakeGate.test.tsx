import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { WakeGate } from "./WakeGate";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

test("WakeGate shows waking message until health is 200", async () => {
  const answers = [503, 503, 200];
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("{}", { status: answers.shift() ?? 200 }));

  render(
    <WakeGate>
      <p>The app</p>
    </WakeGate>,
  );

  expect(screen.getByRole("status")).toHaveTextContent(
    "Waking the server, this takes about a minute",
  );
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(screen.queryByText("The app")).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(3000));

  expect(screen.getByText("The app")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(String(fetchMock.mock.calls[0]![0])).toContain("/api/v1/health");
});

test("WakeGate keeps polling when the network fails", async () => {
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValue(new Response("{}", { status: 200 }));

  render(
    <WakeGate>
      <p>The app</p>
    </WakeGate>,
  );
  await act(() => vi.advanceTimersByTimeAsync(3000));

  expect(screen.getByText("The app")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
