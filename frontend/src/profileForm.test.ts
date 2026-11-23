import { expect, test } from "vitest";
import { EMPTY_FORM, parseSkills, splitList, toProfileIn, withDraft } from "./profileForm";

test("skills parse with an optional level, defaulting to 2", () => {
  expect(parseSkills("Python:3, SQL ,Docker : 1, , Python:3")).toEqual([
    { name: "Python", level: 3 },
    { name: "SQL", level: 2 },
    { name: "Docker", level: 1 },
  ]);
});

test("lists split on commas and new lines, trimmed and deduplicated", () => {
  expect(splitList("Bengaluru,\n Pune, Bengaluru")).toEqual(["Bengaluru", "Pune"]);
});

test("a résumé draft fills only what it found", () => {
  const form = { ...EMPTY_FORM, locations: "Kochi", skills: "Go:2" };
  const next = withDraft(form, {
    target_roles: ["ml"],
    years_experience: null,
    locations: [],
    skills: [{ name: "PyTorch", level: 3 }],
    unrecognized_skills: [],
  });
  expect(next.target_roles).toEqual(["ml"]);
  expect(next.locations).toBe("Kochi");
  expect(next.years_experience).toBe("0");
  expect(next.skills).toBe("PyTorch:3");
});

test("the form becomes the API's profile body", () => {
  const body = toProfileIn({ ...EMPTY_FORM, years_experience: "1.5", locations: "Kochi, Pune" });
  expect(body.years_experience).toBe(1.5);
  expect(body.locations).toEqual(["Kochi", "Pune"]);
});
