# Instrument Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle every page of the web app in the Instrument look, ship it, and put screenshots and GIFs of every page in the README.

**Architecture:** One rewritten `frontend/src/styles.css` built on colour tokens (light in `:root`, dark under
`prefers-color-scheme`). Small markup changes in `Layout`, `JobCard`, `WhyPanel` and `SavedPage` add the hooks the look needs
(LED, LCD readout, meter segments). The media is captured from the local stack (Docker Postgres, uvicorn, Vite) with
Playwright driving the installed Chrome.

**Tech Stack:** React 19, Vite 8, plain CSS, Vitest + Testing Library; Google Fonts (Geist, Geist Mono, Doto); Playwright (ad hoc, via npx) and ffmpeg for media.

**Spec:** `docs/superpowers/specs/2026-11-28-instrument-theme-design.md`

## Global Constraints

- Token values exactly as in the spec's table; orange (`--signal`) only on the score readout, the wordmark LED and one primary key per screen.
- No new entries in `frontend/package.json`. Playwright runs from a scratch folder, never from the repo.
- No copy changes, except a "Match" caption on the score readout.
- The existing tests query by role and text. They must pass unchanged.
- Key travel and meter light-up are the only motion, and both stop under `prefers-reduced-motion: reduce`.
- No AI attribution anywhere committed (no co-author trailer, no tool names, no claude.ai links).

## Review Focus

- A long title (90+ characters) or company name at 360 px wide must wrap, never push the score readout off the card.
- A score of 100 (three digits) or under 10 must fit the readout without changing the card's layout.
- A factor missing from `job.factors` must show zero lit segments and "0%", not crash.
- Keyboard focus must be visible on every key, nav segment, input and checkbox in both themes.
- Muted text on plates must stay readable in dark mode (no grey-on-grey below about 4.5:1 for body-size text).

---

### Task 1: Tokens, fonts, base styles and masthead

**Files:**
- Modify: `frontend/index.html` (font preconnect and stylesheet link)
- Modify: `frontend/src/styles.css` (rewrite: tokens, base, masthead, keys, plates, forms, messages, wake screen, saved, profile)
- Modify: `frontend/src/components/Layout.tsx` (LED mark, segmented nav)
- Modify: `frontend/public/favicon.svg`

**Interfaces:**
- Produces CSS classes the later tasks use: `.plate` (card surface with screws), `.cap` (mono uppercase caption),
  `.key`, `.key--signal`, `.key--danger` (buttons; `.button` stays as an alias so pages need no edits),
  `.led`, `.led--ok`, `.led--error`, `.led--off`.

- [ ] **Step 1:** Add `<link rel="preconnect">` for fonts.googleapis.com and fonts.gstatic.com, then the stylesheet
  `family=Doto:wght@900&family=Geist+Mono:wght@400;500;600&family=Geist:wght@400;500;600&display=swap` to `index.html`.
- [ ] **Step 2:** Rewrite `styles.css` with the spec's tokens. Every existing class name used by the pages keeps working
  (`.panel`, `.button`, `.button--quiet`, `.button--danger`, `.link-button`, `.field*`, `.check`, `.message*`, `.wake*`,
  `.saved*`, `.resume`, `.danger`, `.empty`, `.muted`). Field labels and legends become `.cap` style, inputs become inset
  slots, and checkboxes get `accent-color: var(--signal)`.
- [ ] **Step 3:** In `Layout.tsx`, replace the SVG mark with `<span className="led" aria-hidden="true" />` and the
  wordmark text "SHORTLIST" styled in mono. Wrap the nav links in `.segments`, where the active NavLink is the raised segment
  and Log out is the last segment. Keep `aria-label="Shortlist home"` and the skip link.
- [ ] **Step 4:** Recolour `favicon.svg`: a `#141413` rounded square with an orange `#FF4F12` LED square.
- [ ] **Step 5:** Run `cd frontend && npm run typecheck && npm run lint && npm test`. Expected: all pass, with no test edits.
- [ ] **Step 6:** Commit: `style: instrument theme tokens, fonts and masthead`.

### Task 2: Job card readout and Why meters

**Files:**
- Modify: `frontend/src/components/JobCard.tsx`, `frontend/src/components/WhyPanel.tsx`, `frontend/src/styles.css`
- Test: `frontend/src/components/JobCard.test.tsx` (new)

**Interfaces:**
- Produces `export const SEGMENTS = 12` and `export function litSegments(value: number): number` in `WhyPanel.tsx`
  (round(value × 12), clamped to 0–12).

- [ ] **Step 1: Write the failing tests** in `JobCard.test.tsx`:

```tsx
test("litSegments rounds to twelfths and clamps", () => {
  expect(litSegments(0)).toBe(0);
  expect(litSegments(0.5)).toBe(6);
  expect(litSegments(0.92)).toBe(11);
  expect(litSegments(1)).toBe(12);
  expect(litSegments(1.4)).toBe(12);
  expect(litSegments(-0.2)).toBe(0);
});
test("score readout is labelled and fits three digits", () => {
  render(<JobCard job={job({ score: 1 })} saved={false} onSave={noop} onDismiss={noop} onOpen={noop} />);
  expect(screen.getByLabelText("Match score 100")).toHaveTextContent("100");
  expect(screen.getByText("Match")).toBeInTheDocument();
});
test("why panel lights segments per factor and survives a missing factor", async () => {
  render(<JobCard job={job({ factors: { skill: 0.5 } })} saved={false} onSave={noop} onDismiss={noop} onOpen={noop} />);
  await userEvent.click(screen.getByRole("button", { name: "Why" }));
  const skill = screen.getByText("Skills match").closest(".why__factor")!;
  expect(skill.querySelectorAll(".seg.is-on")).toHaveLength(6);
  const taste = screen.getByText("Like jobs you saved").closest(".why__factor")!;
  expect(taste.querySelectorAll(".seg.is-on")).toHaveLength(0);
  expect(taste).toHaveTextContent("0%");
});
```

  `job(overrides)` builds a full `RankedJob` (title with 95 characters, `company: "Atlan"`, `city: null`,
  `remote_scope: "remote_country"`, `first_seen_at` = now, `matched_skills: ["Python"]`, `missing_skills: []`,
  `factors: {}`, `score: 0.87`).
- [ ] **Step 2:** Run `npx vitest run src/components/JobCard.test.tsx`. Expected: FAIL (`litSegments` not exported, no "Match").
- [ ] **Step 3:** In `JobCard`, add the caption line `company · place · seen …` (`.cap`) above the `h2`, and replace the score
  span with `<span className="lcd" role="img" aria-label={`Match score ${n}`}><span className="lcd__cap">Match</span><span className="lcd__num">{n}</span></span>`
  (`role="img"` makes the label the whole accessible name, so screen readers hear "Match score 87" once).
  The actions become keys: Open (`.key`, still an `<a>`), Save (`.key key--signal`), Not for me (`.key`), Why (`.key key--toggle`, pressed while `aria-expanded`).
- [ ] **Step 4:** In `WhyPanel`, render each factor's bar as `SEGMENTS` `<span className="seg">` elements (`is-on` for the
  first `litSegments(value)`, each with `--i` for the stagger) inside `aria-hidden` `.segs`. Keep `dt` labels, the `%` value
  text, and the "You have" / "Worth learning" lines as they are.
- [ ] **Step 5:** Style `.job` as a plate with screws, `.lcd` (Doto 900, `--lcd-text`, inset shadow, `min-width` fits three
  digits), `.segs`/`.seg` (12 equal cells, light-up keyframe gated by reduced motion), and two meter columns above 640 px wide.
  The title area gets `min-width: 0` so long titles wrap.
- [ ] **Step 6:** Run `npm test`. Expected: all pass.
- [ ] **Step 7:** Commit: `style: score readout and segmented why meters`.

### Task 3: Remaining page hooks

**Files:**
- Modify: `frontend/src/pages/SavedPage.tsx` (closed badge becomes LED + caption; meta line `.cap`), `frontend/src/components/WakeGate.tsx` (LED dot class), `frontend/src/styles.css`

- [ ] **Step 1:** In SavedPage, render `{item.status === "closed" && <span className="badge"><span className="led led--off" aria-hidden="true" />Closed</span>}`.
  The text stays "Closed". Turn the Open and Remove actions into `.key` styles.
- [ ] **Step 2:** In WakeGate, change the dot to `className="led wake__led"` and keep the `role="status"` text unchanged.
- [ ] **Step 3:** Run `npm test && npm run build`. Expected: all pass, build succeeds.
- [ ] **Step 4:** Commit: `style: saved list, wake screen and forms in the instrument theme`.

### Task 4: Local stack and visual pass

- [ ] **Step 1:** `docker compose up -d db`, then in `backend` run `uv sync`, `uv run alembic upgrade head` and
  `uv run python -m app.cli seed-skills`. If the volume has no postings, run `uv run python -m app.cli pipeline` (rules-only, no keys).
- [ ] **Step 2:** `uv run uvicorn app.main:app` on :8000, then `npm run dev` on :5173.
- [ ] **Step 3:** Create an invite (`uv run python -m app.cli invite-create`), then register "Demo Student" (demo@example.test).
  Fill the profile (software + ml; intern + new_grad; Python:3, SQL:2, PyTorch:2, React:1, Docker:1; Bengaluru; remote on) and save 3 postings.
- [ ] **Step 4:** Look at every page at 1280 px and 390 px wide, in light and dark. Check the Review Focus items. Fix what's off in `styles.css`, rerun `npm test`, and commit.

### Task 5: README media

**Files:**
- Create: `docs/media/*.png`, `docs/media/*.gif`
- Modify: `README.md` (new "Screens" section after the intro)

- [ ] **Step 1:** In the scratchpad, write a Playwright script (`npm i playwright` there, `chromium.launch({ channel: "chrome" })`)
  that logs in as the demo student and saves a 1280×800 PNG of every page in light and dark (`colorScheme`). It also records
  videos of the flows: Feed (search, open Why, Save), Saved, Profile (scroll, save), Log in → Feed.
- [ ] **Step 2:** Convert each video with ffmpeg (palettegen/paletteuse, 10 fps, 900 px wide), keeping each GIF under about 3 MB.
- [ ] **Step 3:** Add the "Screens" section to the README: GIFs for the flows, then a table of light | dark screenshots per page.
- [ ] **Step 4:** Commit: `docs: screenshots and GIFs of every page`.

### Task 6: Deploy

- [ ] **Step 1:** Run `npm run format:check && npm run lint && npm test && npm run build` in `frontend`. Expected: clean.
- [ ] **Step 2:** `git push origin main`. Cloudflare Workers Builds deploys the `shortlist` Worker.
- [ ] **Step 3:** `gh api repos/asw-beep/Shortlist/commits/HEAD/check-runs` shows "Workers Builds: shortlist" with conclusion `success`.
