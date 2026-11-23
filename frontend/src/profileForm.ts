/** Turning the profile form's text boxes into the API's lists, and back. */
import type { ProfileDraft, ProfileIn, ProfileOut, SkillIn } from "./api/types";

export interface ProfileForm {
  target_roles: string[];
  seniority_ok: string[];
  years_experience: string;
  locations: string;
  open_to_relocate: boolean;
  remote_ok: boolean;
  skills: string;
  avoid_companies: string;
  notes: string;
  digest_opt_in: boolean;
}

export const EMPTY_FORM: ProfileForm = {
  target_roles: ["software"],
  seniority_ok: ["intern", "new_grad", "entry"],
  years_experience: "0",
  locations: "",
  open_to_relocate: true,
  remote_ok: true,
  skills: "",
  avoid_companies: "",
  notes: "",
  digest_opt_in: true,
};

export function splitList(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[,\n]/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ];
}

/** "Python:3, SQL" → [{name: "Python", level: 3}, {name: "SQL", level: 2}] */
export function parseSkills(text: string): SkillIn[] {
  return splitList(text).map((entry) => {
    const match = /^(.*?)\s*:\s*([123])$/.exec(entry);
    return match ? { name: match[1]!, level: Number(match[2]) } : { name: entry, level: 2 };
  });
}

export function formatSkills(skills: { name: string; level: number }[]): string {
  return skills.map((skill) => `${skill.name}:${skill.level}`).join(", ");
}

export function fromProfile(profile: ProfileOut): ProfileForm {
  return {
    target_roles: profile.target_roles,
    seniority_ok: profile.seniority_ok,
    years_experience: String(profile.years_experience),
    locations: profile.locations.join(", "),
    open_to_relocate: profile.open_to_relocate,
    remote_ok: profile.remote_ok,
    skills: formatSkills(profile.skills),
    avoid_companies: profile.avoid_companies.join(", "),
    notes: profile.notes,
    digest_opt_in: profile.digest_opt_in,
  };
}

/** A résumé draft fills what it found and leaves the rest of the form alone. */
export function withDraft(form: ProfileForm, draft: ProfileDraft): ProfileForm {
  return {
    ...form,
    target_roles: draft.target_roles.length ? draft.target_roles : form.target_roles,
    years_experience:
      draft.years_experience === null ? form.years_experience : String(draft.years_experience),
    locations: draft.locations.length ? draft.locations.join(", ") : form.locations,
    skills: draft.skills.length ? formatSkills(draft.skills) : form.skills,
  };
}

export function toProfileIn(form: ProfileForm): ProfileIn {
  return {
    target_roles: form.target_roles as ProfileIn["target_roles"],
    seniority_ok: form.seniority_ok as ProfileIn["seniority_ok"],
    years_experience: Number(form.years_experience) || 0,
    locations: splitList(form.locations),
    open_to_relocate: form.open_to_relocate,
    remote_ok: form.remote_ok,
    skills: parseSkills(form.skills),
    avoid_companies: splitList(form.avoid_companies),
    notes: form.notes,
    digest_opt_in: form.digest_opt_in,
  };
}
