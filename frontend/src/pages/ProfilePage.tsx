import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { api, unwrap } from "../api/client";
import { ApiError } from "../api/problem";
import type { ProfileDraft, ProfileOut } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { setLoginNotice } from "../auth/loginNotice";
import { FormError, Notice, SubmitButton } from "../components/Form";
import { EMPTY_FORM, fromProfile, toProfileIn, withDraft, type ProfileForm } from "../profileForm";

const ROLES = [
  ["software", "Software engineering"],
  ["ml", "Machine learning"],
  ["data", "Data"],
] as const;
const SENIORITY = [
  ["intern", "Internships"],
  ["new_grad", "New-grad roles"],
  ["entry", "Entry level"],
  ["mid", "Mid level"],
] as const;

async function loadProfile(): Promise<ProfileOut | null> {
  try {
    return await unwrap(api.GET("/api/v1/profile"));
  } catch (error) {
    if (error instanceof ApiError && error.code === "profile-missing") return null;
    throw error;
  }
}

async function draftFromResume(file: File | null, text: string): Promise<ProfileDraft> {
  const body = new FormData();
  if (file) body.append("file", file);
  else body.append("text", text);
  return unwrap(
    api.POST("/api/v1/profile/resume", {
      body: body as never, // multipart: sent as FormData, not JSON
      bodySerializer: (value) => value as FormData,
    }),
  );
}

function Checkboxes({
  legend,
  options,
  selected,
  onChange,
}: {
  legend: string;
  options: readonly (readonly [string, string])[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <fieldset className="field">
      <legend>{legend}</legend>
      {options.map(([value, label]) => (
        <label key={value} className="check">
          <input
            type="checkbox"
            checked={selected.includes(value)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...selected, value]
                  : selected.filter((item) => item !== value),
              )
            }
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="check">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

export function ProfilePage() {
  const notice = (useLocation().state as { notice?: string } | null)?.notice;
  const profile = useQuery({ queryKey: ["profile"], queryFn: loadProfile });
  if (profile.isPending) return <p className="muted">Loading your profile…</p>;
  if (profile.isError) return <FormError error={profile.error} />;
  return <ProfileEditor initial={profile.data} notice={profile.data ? undefined : notice} />;
}

function ProfileEditor({ initial, notice }: { initial: ProfileOut | null; notice?: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { forget } = useAuth();
  const [form, setForm] = useState<ProfileForm>(() =>
    initial ? fromProfile(initial) : EMPTY_FORM,
  );
  const [resumeText, setResumeText] = useState("");
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/profile", { body: toProfileIn(form) })),
    onSuccess: (saved) => {
      queryClient.setQueryData(["profile"], saved);
      void queryClient.invalidateQueries({ queryKey: ["feed"] });
    },
  });
  const draft = useMutation({
    mutationFn: () => draftFromResume(resumeFile, resumeText),
    onSuccess: (result) => setForm((current) => withDraft(current, result)),
  });
  const deleteAccount = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/users/me")),
    onSuccess: () => {
      setLoginNotice("Your account and everything in it are deleted.");
      forget();
      navigate("/login", { replace: true });
    },
  });

  const set =
    <K extends keyof ProfileForm>(key: K) =>
    (value: ProfileForm[K]) =>
      setForm((current) => ({ ...current, [key]: value }));

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate();
  }

  const unrecognized = save.data?.unrecognized_skills ?? draft.data?.unrecognized_skills ?? [];

  return (
    <section className="panel">
      <h1>Your profile</h1>
      {notice && <Notice>{notice}</Notice>}

      <details className="resume" open={!initial}>
        <summary>Fill it in from your résumé</summary>
        <p className="muted">
          Your résumé is read once to suggest roles and skills. It is not stored.
        </p>
        <input
          type="file"
          accept="application/pdf"
          aria-label="Résumé PDF"
          onChange={(event) => setResumeFile(event.target.files?.[0] ?? null)}
        />
        <textarea
          aria-label="Or paste your résumé text"
          placeholder="…or paste the text here"
          rows={4}
          value={resumeText}
          onChange={(event) => setResumeText(event.target.value)}
        />
        <FormError error={draft.error} />
        <button
          type="button"
          className="button button--quiet"
          disabled={draft.isPending || (!resumeFile && !resumeText.trim())}
          onClick={() => draft.mutate()}
        >
          {draft.isPending ? "Reading…" : "Suggest from résumé"}
        </button>
      </details>

      <form onSubmit={handleSubmit}>
        <Checkboxes
          legend="Roles you want"
          options={ROLES}
          selected={form.target_roles}
          onChange={set("target_roles")}
        />
        <Checkboxes
          legend="Levels"
          options={SENIORITY}
          selected={form.seniority_ok}
          onChange={set("seniority_ok")}
        />
        <div className="field">
          <label htmlFor="years">Years of experience (internships count)</label>
          <input
            id="years"
            type="number"
            min={0}
            max={10}
            step={0.5}
            value={form.years_experience}
            onChange={(event) => set("years_experience")(event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="skills">Skills</label>
          <textarea
            id="skills"
            rows={3}
            value={form.skills}
            onChange={(event) => set("skills")(event.target.value)}
          />
          <p className="field__hint">
            Comma-separated. Add :1, :2 or :3 for how well you know it, e.g. Python:3, SQL:2.
          </p>
          {unrecognized.length > 0 && (
            <p className="field__hint">
              Not recognised (kept out of matching): {unrecognized.join(", ")}
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor="locations">Cities in India</label>
          <input
            id="locations"
            value={form.locations}
            onChange={(event) => set("locations")(event.target.value)}
          />
          <p className="field__hint">
            Comma-separated, e.g. Bengaluru, Kochi. Leave empty for anywhere in India.
          </p>
        </div>
        <Toggle
          label="Open to relocating within India"
          checked={form.open_to_relocate}
          onChange={set("open_to_relocate")}
        />
        <Toggle label="Open to remote roles" checked={form.remote_ok} onChange={set("remote_ok")} />
        <div className="field">
          <label htmlFor="avoid">Companies to hide</label>
          <input
            id="avoid"
            value={form.avoid_companies}
            onChange={(event) => set("avoid_companies")(event.target.value)}
          />
        </div>
        <Toggle
          label="Email me a weekly digest of new matches"
          checked={form.digest_opt_in}
          onChange={set("digest_opt_in")}
        />
        <FormError error={save.error} />
        {save.isSuccess && <Notice>Saved. Your feed now uses this profile.</Notice>}
        <div className="actions">
          <SubmitButton pending={save.isPending}>Save profile</SubmitButton>
          {save.isSuccess && (
            <button
              type="button"
              className="button button--quiet"
              onClick={() => navigate("/feed")}
            >
              See your feed
            </button>
          )}
        </div>
      </form>

      <div className="danger">
        <h2>Delete account</h2>
        <p className="muted">
          Removes your profile, saved postings and history. This can't be undone.
        </p>
        <FormError error={deleteAccount.error} />
        {confirmDelete ? (
          <div className="actions">
            <button
              type="button"
              className="button button--danger"
              onClick={() => deleteAccount.mutate()}
            >
              Yes, delete everything
            </button>
            <button type="button" className="link-button" onClick={() => setConfirmDelete(false)}>
              Keep my account
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="button button--quiet"
            onClick={() => setConfirmDelete(true)}
          >
            Delete my account
          </button>
        )}
      </div>
    </section>
  );
}
