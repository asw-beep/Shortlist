# Instrument theme for the web app

Date: 2026-11-28. Status: approved direction (option A of three), design below awaiting sign-off.

## Why

The web app looks generic: system fonts, a blue accent, grey cards. Shortlist's real difference
from a job board is the explained score, six ranking factors per posting, and today that sits
behind a "Why" link as thin blue bars. The restyle should make the app look like it was made on
purpose, and make the score the thing you notice first. The README will show it off with
screenshots and GIFs, so it has to look good in both light and dark.

## Approaches considered

Three directions were mocked up side by side on the real Feed page, in light and dark:

- **A · Instrument panel (picked).** Every posting gets a dot-matrix match readout. The six
  factors become segmented meters, the buttons look like hardware keys, and the palette is warm
  grey with signal orange. Picked because it puts the explained score at the centre.
- **B · Departure board.** A timetable of rows with split-flap score tiles and status lamps. It
  scans fastest, but it's cramped on phones, and the forms don't fit the metaphor.
- **C · Sticker pop.** Neo-brutalist: ink outlines, hard shadows, score stickers. The most
  energetic, but the least ownable and the hardest to keep calm on the Profile form.

## Goals

- Every page restyled in the Instrument look: Feed, Saved, Profile, Log in, Register, Forgot
  password, Reset password, Thanks, Not found, Can't reach Shortlist, and the waking-server
  screen.
- Light (aluminium) and dark (anodised black) from `prefers-color-scheme`, as today.
- Deployed to the live Cloudflare Worker.
- The README gets a screenshot of every page and GIFs of the interactive flows.

## Non-goals

- No new features: no theme toggle, no new data on screen, no backend changes.
- No copy changes, apart from a small "Match" label on the score readout.
- No new JavaScript dependencies. Plain CSS in `frontend/src/styles.css` stays the approach.

## Anti-goals

- A toy. Key-style buttons and screws are accents. The long Profile form must stay calm and
  readable.
- Lost accessibility. Keep the skip link, labelled fields, aria wiring, visible focus and
  reduced motion. The tests query by role and text, and they must still pass unchanged.

## Design

**Tokens** (in `:root`, redefined under `prefers-color-scheme: dark`), as in the mockup:

| Token | Light | Dark | Use |
|---|---|---|---|
| `--chassis` | `#E2E2DC` | `#0E0E0D` | page background |
| `--plate` | `#F3F3EE` | `#191918` | cards, panels |
| `--ink` / `--muted` | `#151515` / `#66665F` | `#EBEBE5` / `#8B8B84` | text |
| `--rule` | `#C9C9C1` | `#2D2D2A` | borders, screws, dashed dividers |
| `--slot` | `#E9E9E3` | `#121211` | inset inputs |
| `--key` / `--key-edge` | `#FBFBF8` / `#B4B4AC` | `#252523` / `#050505` | buttons |
| `--signal` / `--signal-edge` / `--signal-ink` | `#FF4F12` / `#B83A0C` / `#160803` | `#FF5A1F` / `#9E3510` / `#160803` | the one primary action, wordmark LED |
| `--lcd` / `--lcd-text` | `#141413` / `#FF6328` | `#050505` / `#FF7034` | score readout |
| `--unlit` | `#D3D3CB` | `#2C2C29` | meter segments that are off |
| `--ok` / `--error` | green / red, tuned per mode | | messages, closed badge, danger key |

Orange is reserved for the score readout, the wordmark LED and one primary key per screen
(Save on a card; the submit button on a form). Everything else stays grey and ink.

**Type.** Geist for text, Geist Mono (uppercase, letter-spaced) for labels, captions and meta
lines, and Doto (dot matrix) only for the score number. All three load from Google Fonts in
`index.html` with `preconnect`, `display=swap` and system fallbacks.

**Components**

- *Masthead:* an orange LED square plus SHORTLIST in mono. The nav becomes a segmented control:
  the active NavLink is the raised segment, and Log out is the last segment.
- *Job card:* a plate with four screw dots. A mono caption line (company · place · seen …) sits
  above the title, and an LCD window on the right shows MATCH and the score in Doto. Skills are
  mono chips. Open, Save, Not for me and Why are keys; Save is the orange key, and Why looks
  pressed while open. Open stays a link.
- *Why panel:* each factor is a 12-segment meter with its percentage, in two columns on wide
  screens and one on narrow. Labels stay as they are. Segments light up in a short stagger when
  the panel opens. "You have" and "Worth learning" get mono captions.
- *Forms:* labels are mono uppercase captions, inputs are inset slots, checkboxes are native
  with `accent-color: var(--signal)`, and submit is the orange key. The résumé `<details>` and
  the Delete account area sit on plates, with a red danger key.
- *Narrow pages* (Log in, Register, password pages, Thanks, Not found, Can't reach): a centred
  plate with screws.
- *Saved:* rows on plates, with the title, mono meta and a "Closed" badge as a grey LED and
  caption.
- *Messages:* an error shows a red LED and border, a notice a green one.
- *Waking server:* a blinking orange LED with mono status text, centred.
- *Favicon:* the existing mark, recoloured to the orange LED look.

**Motion.** Only key press travel and the meter light-up. Both are off under
`prefers-reduced-motion`.

## Media for the README (my calls)

- A test student account on the live site, with a filled profile and a few saved postings, so
  the signed-in pages show real data.
- Captured with Playwright driving the installed Chrome, at 1280×800, light and dark. GIFs are
  made with ffmpeg at about 10 fps and 900 px wide, and kept short to keep the repo small. The
  capture script stays outside the repo.
- Files go in `docs/media/`. The README gets a "Screens" section with a light/dark screenshot of
  every page and GIFs for Feed (search, Why, save), Saved, Profile, and Log in / Register.

## Left to the builder

Exact spacing, the chip and key sizes on phones, the layout of the dark-mode screenshots in the
README, and the favicon details.
