import { useEffect, useState } from "react";
import type { ReactNode } from "react";

const HEALTH_URL = "/api/v1/health";

/**
 * The free API host sleeps when idle and needs about a minute to wake. Until /health answers
 * 200, say so plainly instead of showing a page whose requests all hang.
 */
export function WakeGate({
  children,
  intervalMs = 3000,
}: {
  children: ReactNode;
  intervalMs?: number;
}) {
  const [awake, setAwake] = useState(false);

  useEffect(() => {
    if (awake) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function check() {
      try {
        const response = await fetch(HEALTH_URL);
        if (response.ok) {
          if (!cancelled) setAwake(true);
          return;
        }
      } catch {
        // offline, or the proxy gave up for now: try again
      }
      if (!cancelled) timer = setTimeout(check, intervalMs);
    }
    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [awake, intervalMs]);

  if (!awake) {
    return (
      <div className="wake" role="status">
        <span className="wake__dot" aria-hidden="true" />
        Waking the server, this takes about a minute…
      </div>
    );
  }
  return children;
}
