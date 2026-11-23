import { useId, useState } from "react";
import type { RankedJob } from "../api/types";
import { WhyPanel } from "./WhyPanel";

const REMOTE: Record<string, string> = {
  remote_country: "Remote (India)",
  remote_global: "Remote",
};

export function place(city: string | null | undefined, remoteScope: string): string {
  return city ?? REMOTE[remoteScope] ?? "India";
}

export function daysAgo(iso: string, now = Date.now()): string {
  const days = Math.floor((now - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  return days === 1 ? "yesterday" : `${days} days ago`;
}

interface JobCardProps {
  job: RankedJob;
  saved: boolean;
  onSave: () => void;
  onDismiss: () => void;
  onOpen: () => void;
}

export function JobCard({ job, saved, onSave, onDismiss, onOpen }: JobCardProps) {
  const [showWhy, setShowWhy] = useState(false);
  const whyId = useId();
  return (
    <article className="job">
      <header className="job__head">
        <h2 className="job__title">{job.title}</h2>
        <span className="job__score" title="Match score">
          {Math.round(job.score * 100)}
        </span>
      </header>
      <p className="job__meta">
        {job.company} · {place(job.city, job.remote_scope)} · seen {daysAgo(job.first_seen_at)}
      </p>
      {job.matched_skills.length > 0 && (
        <ul className="chips" aria-label="Skills you have">
          {job.matched_skills.slice(0, 6).map((skill) => (
            <li key={skill}>{skill}</li>
          ))}
        </ul>
      )}
      <div className="job__actions">
        <a
          className="button"
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={onOpen}
        >
          Open
        </a>
        <button type="button" className="button button--quiet" onClick={onSave} disabled={saved}>
          {saved ? "Saved" : "Save"}
        </button>
        <button type="button" className="button button--quiet" onClick={onDismiss}>
          Not for me
        </button>
        <button
          type="button"
          className="link-button"
          aria-expanded={showWhy}
          aria-controls={whyId}
          onClick={() => setShowWhy((open) => !open)}
        >
          {showWhy ? "Hide why" : "Why"}
        </button>
      </div>
      {showWhy && <WhyPanel job={job} id={whyId} />}
    </article>
  );
}
