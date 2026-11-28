import type { CSSProperties } from "react";
import type { RankedJob } from "../api/types";

const LABELS: Record<string, string> = {
  skill: "Skills match",
  rrf: "Search relevance",
  experience: "Experience fit",
  location: "Location fit",
  recency: "Freshness",
  personal: "Like jobs you saved",
};

/** Cells in each factor's meter. */
export const SEGMENTS = 12;

/** How many meter cells a factor value (0 to 1) lights. */
export function litSegments(value: number): number {
  return Math.min(SEGMENTS, Math.max(0, Math.round(value * SEGMENTS)));
}

/** Why a posting ranked where it did: each factor of its score, and the skills behind it. */
export function WhyPanel({ job, id }: { job: RankedJob; id: string }) {
  return (
    <div className="why" id={id}>
      <dl className="why__factors">
        {Object.entries(LABELS).map(([name, label]) => {
          const value = job.factors[name] ?? 0;
          const lit = litSegments(value);
          return (
            <div className="why__factor" key={name}>
              <dt>{label}</dt>
              <dd>
                <span className="segs" aria-hidden="true">
                  {Array.from({ length: SEGMENTS }, (_, cell) => (
                    <span
                      key={cell}
                      className={cell < lit ? "seg is-on" : "seg"}
                      style={{ "--i": cell } as CSSProperties}
                    />
                  ))}
                </span>
                <span className="why__value">{Math.round(value * 100)}%</span>
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="why__skills">
        <strong className="cap">You have:</strong>{" "}
        {job.matched_skills.length ? job.matched_skills.join(", ") : "none of the listed skills"}
      </p>
      {job.missing_skills.length > 0 && (
        <p className="why__skills">
          <strong className="cap">Worth learning:</strong> {job.missing_skills.join(", ")}
        </p>
      )}
    </div>
  );
}
