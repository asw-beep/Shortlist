import type { RankedJob } from "../api/types";

const LABELS: Record<string, string> = {
  skill: "Skills match",
  rrf: "Search relevance",
  experience: "Experience fit",
  location: "Location fit",
  recency: "Freshness",
  personal: "Like jobs you saved",
};

/** Why a posting ranked where it did: each factor of its score, and the skills behind it. */
export function WhyPanel({ job, id }: { job: RankedJob; id: string }) {
  return (
    <div className="why" id={id}>
      <dl className="why__factors">
        {Object.entries(LABELS).map(([name, label]) => {
          const value = job.factors[name] ?? 0;
          const percent = Math.round(value * 100);
          return (
            <div className="why__factor" key={name}>
              <dt>{label}</dt>
              <dd>
                <span className="bar" aria-hidden="true">
                  <span className="bar__fill" style={{ width: `${percent}%` }} />
                </span>
                <span className="why__value">{percent}%</span>
              </dd>
            </div>
          );
        })}
      </dl>
      <p className="why__skills">
        <strong>You have:</strong>{" "}
        {job.matched_skills.length ? job.matched_skills.join(", ") : "none of the listed skills"}
      </p>
      {job.missing_skills.length > 0 && (
        <p className="why__skills">
          <strong>Worth learning:</strong> {job.missing_skills.join(", ")}
        </p>
      )}
    </div>
  );
}
