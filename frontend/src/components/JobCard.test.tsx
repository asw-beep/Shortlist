import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { RankedJob } from "../api/types";
import { JobCard } from "./JobCard";
import { litSegments } from "./WhyPanel";

const noop = () => undefined;

function job(overrides: Partial<RankedJob> = {}): RankedJob {
  return {
    posting_id: "p1",
    title: "Software Engineer Intern, Platform Infrastructure and Developer Productivity, Summer 2027",
    company: "Atlan",
    city: null,
    remote_scope: "remote_country",
    first_seen_at: new Date().toISOString(),
    matched_skills: ["Python"],
    missing_skills: [],
    factors: {},
    score: 0.87,
    url: "https://example.test/job",
    ...overrides,
  };
}

function renderCard(posting: RankedJob) {
  render(<JobCard job={posting} saved={false} onSave={noop} onDismiss={noop} onOpen={noop} />);
}

test("litSegments rounds to twelfths and clamps", () => {
  expect(litSegments(0)).toBe(0);
  expect(litSegments(0.5)).toBe(6);
  expect(litSegments(0.92)).toBe(11);
  expect(litSegments(1)).toBe(12);
  expect(litSegments(1.4)).toBe(12);
  expect(litSegments(-0.2)).toBe(0);
});

test("score readout is labelled and fits three digits", () => {
  renderCard(job({ score: 1 }));
  expect(screen.getByRole("img", { name: "Match score 100" })).toHaveTextContent("100");
  expect(screen.getByText("Match")).toBeInTheDocument();
});

test("why panel lights segments per factor and survives a missing factor", async () => {
  renderCard(job({ factors: { skill: 0.5 } }));
  await userEvent.click(screen.getByRole("button", { name: "Why" }));

  const skill = screen.getByText("Skills match").closest(".why__factor")!;
  expect(skill.querySelectorAll(".seg")).toHaveLength(12);
  expect(skill.querySelectorAll(".seg.is-on")).toHaveLength(6);

  const taste = screen.getByText("Like jobs you saved").closest(".why__factor")!;
  expect(taste.querySelectorAll(".seg.is-on")).toHaveLength(0);
  expect(taste).toHaveTextContent("0%");
});
