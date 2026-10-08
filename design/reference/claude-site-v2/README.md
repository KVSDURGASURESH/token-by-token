# Handoff: Token by Token — public site shell v2

## Read this first — implementation rule
Build **exactly what `Token by Token Site v2.dc.html` shows**. Don't redesign anything, and don't "improve" spacing, copy, colours, type or behaviour. Where this README and the prototype disagree, the prototype wins. Where the prototype is silent, ask before inventing.

- Repo: `KVSDURGASURESH/token-by-token`, branch `codex/episode-1-local-prep` (see `/github.md` in the design project).
- Target app: the existing `dashboard/` front end. Recreate the design with that codebase's own component patterns and tooling. **Do not ship the HTML file.** It is a design reference: a self-running prototype that loads `support.js`. Open it in a browser from this folder's root.
- Fidelity: **high fidelity.** Final colours, type, spacing, copy and interactions.

## Files
| File | Role |
|---|---|
| `Token by Token Site v2.dc.html` | **Source of truth.** Template markup (all styles inline) and a `<script data-dc-script>` logic class that holds the data, routing and state. |
| `token-by-token.svg` | Site-bar mark, 22×22. |
| `support.js` | Prototype runtime only. Not for production. |
| `reference/Token by Token Site (v1 baseline).dc.html` | The previous version. Diff it against v2 to see each change precisely. |
| `reference/Episode 01 Redesign (canvas + behaviour spec).dc.html` | Review canvas. The "Behaviour specification" block at the bottom (URL state, history, invalid links, keyboard, live region, responsive, privacy) applies to v2 unchanged. Its iframes point at the root filenames, so it is for reading the spec text only. |

Data in the prototype (`EPS`, `D1`, `WL`, `FNS`, `SOAK` …) is lifted from `dashboard/src/data/*.json`. Wire the real JSON; don't hard-code the numbers.

---

## Part A — The v1 shell (already designed; implement as is)
Everything in v2 that isn't listed in Part B is unchanged from v1. In summary:

- **Site bar:** wordmark (`TOKEN BY TOKEN / INFERENCE LAB` at ≥981px, `TOKEN BY TOKEN` below 981px) · Episodes · Methodology · Field notes · Lab tools ▾ (local-only list, no links) · **[new: external links]** · Light/Dark.
- **Rail:** shown at ≥981px, 220px wide, sticky, with two lists: Episodes and "On this page". Below 981px it becomes one episode-menu button in the site bar.
- **Study page order:** label → H1 → deck question → qualifiers (mono, separated by rules) → the sticky selector (the only sticky element) → 01 Brief → "Open evidence lab ↓" → 02 Method · 03 Evidence · 04 Boundaries · 05 Source → pager.
- **Evidence states:** ✓ ✕ ≈ ≥/≤ </> △ ∅ ⚠ ≠ =. Each has one symbol and one wording, decided by a single function.
- **Routing:** hash routes `#episodes`, `#episode-N`, `#methodology`, `#field-notes`, plus query params. See Part C.

## Part B — Changes in v2 (pinpoint list)

### B1. Planned episode numbers are greyed out
- **Where:** the rail "Episodes" list and the narrow episode menu.
- **Rule:** an episode number uses `var(--ink)` if the episode is recorded **or** is the current page. Otherwise it uses `var(--line-strong)` (light `#98a8a2`, dark `#4a5659`). In practice, 00 and 01 are ink and 02–16 are grey.
- **Only the number changes colour.** The title keeps its existing colour: `var(--copy)` for planned episodes, `var(--ink)` for recorded ones or the current page.
- **Number type:** rail `500 .9375rem/1.3 Oswald`; menu `500 1rem/1 Oswald`.

### B2. Chapter numbers use a single accent colour (dusky yellow / bronze)
One colour for **all** five chapters. Never multi-colour.

| Token | Light | Dark |
|---|---|---|
| `--chapter` (prototype: `--c1`…`--c5`, all set to the same value) | `#6e5f12` | `#d4c26a` |

In the real code, use a single token, `--chapter`.

The accent is applied in exactly these places:

1. **Study chapter headings** "01 Brief", "02 Method", "03 Evidence", "04 Boundaries", "05 Source":
   - Label text colour is `--chapter`. The type is unchanged: `600 .6875rem/1.3 Avenir Next`, `letter-spacing .16em`, uppercase.
   - The label becomes `display:flex; align-items:center; gap:10px`.
   - Before the text, add a decorative bar: `24px × 3px`, `background: --chapter`, `aria-hidden="true"`, `flex: 0 0 auto`.
   - The large heading under each label (Oswald) stays `--ink`.
2. **Planned-episode page chapter headings** (01 Brief … 05 Source): same treatment as item 1.
3. **Rail and episode-menu "On this page" numbers:**
   - Colour is `--chapter`, weight 600, mono at `.75rem`.
   - The current chapter's 2px left bar changes from `--ink` to `--chapter`.
   - Labels stay ink/600 when current and ink/400 otherwise.
4. **Methodology and Episodes index sub-chapters** (Definitions, Evidence states, …) are **not** five-chapter pages. Their numbers stay `var(--muted)` and their current bar stays `--ink`.

Don't use `--chapter` anywhere else. It must never colour data, plots or evidence states. Outcome colours stay reserved: better `#006d45`/`#4bdcaf`, worse `#b22f18`/`#ff7a4d`, band `#8a5b00`/`#f0ba4b`.

### B3. Landing hero on `#episodes` (home)
This replaces the old index header (eyebrow "Token by Token · Inference lab", H1 "Episodes", one paragraph). The Recorded / Field notes / Planned lists below it are unchanged.

`<header data-screen-label="Landing">`:
- **Container:** `display:grid; gap:24px; padding: clamp(8px,2vw,28px) 0 clamp(32px,5vw,60px); border-bottom:1px solid var(--ink)`.
- **Contents, in order:**
  1. **Eyebrow:** "Token by Token · an open inference lab". `600 .6875rem/1.3 Avenir`, `.16em`, uppercase, `--muted`.
  2. **H1** (`id="page-title"`): "Every token is a measurement." `600 clamp(3rem,9.5vw,7.75rem)/.86 Oswald`, `letter-spacing:-.01em`, uppercase, `text-wrap:balance`.
  3. **Deck:** "We run open model-serving engines under recorded load and read the results one claim at a time — what a user waits for, what the hardware does, and where the evidence stops."
     - `clamp(1.125rem,1.9vw,1.4375rem)/1.4`, `--copy`, `max-width:34em`.
  4. **Token strip** (`<figure>`, `margin-top:6px`, `gap:10px`):
     - **Row:** `aria-hidden="true"`, `display:flex; flex-wrap:wrap; border-left:1px solid var(--line)`.
     - **Tokens:** ten cells holding `Time`, `·to`, `·first`, `·token`, `·is`, `·the`, `·wait`, `·a`, `·user`, `·feels.`. The "·" is literal.
     - **Cell:** `display:grid; gap:6px; padding:10px 12px 8px; border-right:1px solid var(--line)`.
     - **Cell top border:** cell 0 uses `3px solid var(--ink)`; all other cells use `1px dashed var(--line-strong)`.
     - **Token text:** `500 clamp(1rem,1.8vw,1.375rem)/1 mono`, `white-space:pre`.
     - **Index label** under each token: `t00`…`t09`, `.625rem mono`, `--muted`.
     - **Figcaption** (flex, `gap:6px 22px`, `.75rem`, `--muted`), two legend items, each with a 22px swatch:
       - "First token — TTFT", swatch `3px solid --ink`
       - "Every token after — TPOT", swatch `1px dashed --line-strong`
  5. **CTA row** (flex wrap, `gap:10px 12px`). All three links are `.8125rem/600`, `.12em`, uppercase, `min-height:48px`:
     - **Primary:** "Start with Episode 00 →" links to `#episode-0`. `background:--ink; color:--paper; padding:0 20px`.
     - **Secondary:** "Episode 01 · Measure what matters" links to `#episode-1`. `border:1px solid --ink; padding:0 20px`.
     - **Tertiary:** "How the lab measures" links to `#methodology`. Underlined text link, `padding:0 6px`.
  6. **Counts line:** `.75rem/1.5 mono`, `--copy`. Reads "2 recorded episodes │ 1 field note │ 15 planned".
     - Separators are `border-left:1px solid --line-strong` with 12px padding.
     - **Derive the counts from the catalog. Don't hard-code them.**

### B4. Episode 01 selector becomes a measured-load track
This replaces the segmented 12 | 16 | 24 buttons. It still sits in the same sticky selector bar: `position:sticky; top:0; z-index:6; padding:10px 0; border-block:1px solid --line-strong; flex-wrap; gap:8px 24px`.

- **Label** "Measured load" (unchanged style).
- **Track** (`role="group"`, `aria-labelledby="sel-label"`, `data-track`):
  - Container: `position:relative; flex:1 1 18rem; min-width:min(100%,15rem); max-width:30rem; height:62px; margin:0 24px; touch-action:none; user-select:none; cursor:pointer`.
  - **Scale:** linear from 10 to 26 users, so `pos(v) = (v−10)/16 × 100%`. That puts 12 at 12.5%, 16 at 37.5% and 24 at 87.5%.
  - **Unmeasured rail:** `1px dashed --line-strong` at `top:15px`, extending 24px past both ends (`left:-24px; right:-24px`).
  - **Measured fill:**
    - Size and position: `3px` high at `top:14px`, `background:--ink`, starting at `pos(12)` with `width:(L−12)/16 × 100%`.
    - Animation: `transition: width .3s cubic-bezier(.3,.7,.2,1)`.
  - **Point buttons:** one per recorded load. Keep the existing roving tabindex, `aria-pressed`, `data-seg="load"` and `data-val`.
    - Button box: absolutely positioned at `left:pos(v)` with `translateX(-50%)`, `min-width:52px`, `height:62px`, no border or background. Its content is a centred grid:
      - **Dot:** 9×9, `margin-top:11px`, `border:1.5px solid --ink`, `background:--paper`, round.
      - **Value:** `margin-top:10px`, `500 1.125rem/1 Oswald`. Colour is `--ink` when selected and `--muted` otherwise.
      - **Sub-label:** "USERS" (or "USERS · PARTIAL" when that point is partial), `margin-top:3px`, `.625rem`, `.1em`, uppercase, `--muted`.
  - **Thumb:**
    - Shape: `aria-hidden`, 22×22, `top:4px`, `left:pos(L)`, `margin-left:-11px`, round, `background:--ink`, `box-shadow:0 0 0 4px --paper`, `cursor:grab`.
    - Animation: `transition:left .3s cubic-bezier(.3,.7,.2,1)`.
    - Order: render it **after** the buttons so it sits on top.
- **Interaction:**
  - **Click or tap** a point: select it (push a history entry).
  - **Pointer down** on the track or thumb (not on a button): snap to the **nearest recorded load**, push one history entry and capture the pointer.
  - **Pointer move:** re-snap. Each change **replaces** the history entry instead of pushing a new one.
  - **Pointer up or cancel:** release.
  - **Never emit an unrecorded value.**
  - **Keyboard** is unchanged: ←/→/↑/↓/Home/End on the group move the selection and focus.
  - **Reduced motion:** transitions off.
- **Note text** (replaces the old note): "Drag, tap or use ← →. Snaps to recorded loads only — the dashed rail between them was never measured." `.75rem`, `--muted`, `max-width:24rem`.

### B5. Episode 00 selector becomes a categorical workload strip
**Not a slider.** These are six separate workloads, and a slider would suggest a sweep.

- **Layout:** `flex:1 1 100%; display:flex; gap:6px; align-items:stretch`. The order is ← button, strip, → button.
- **Arrow buttons:**
  - Style: `flex:0 0 40px; border:1px solid --line-strong; background:none; font-size:1.125rem`.
  - Labels: `aria-label` "Previous workload" / "Next workload".
  - At the ends they are `disabled` with `opacity:.35`.
  - Each press selects the neighbouring workload and pushes a history entry.
- **Strip** (`role="group"`, `aria-labelledby="sel-label"`, `data-strip`):
  - `position:relative; flex:1 1 auto; min-width:0; display:flex; overflow-x:auto; scroll-snap-type:x mandatory; scrollbar-width:none; border:1px solid --line-strong`.
- **Card buttons** (keep roving tabindex, `aria-pressed`, `data-seg="wl"`, `data-val`):
  - Box: `flex:0 0 auto; scroll-snap-align:start; width:12.5rem; max-width:68vw; padding:9px 14px 10px; border-right:1px solid --line-strong; display:grid; gap:3px; text-align:left`.
  - Colours: selected is `bg --ink / fg --paper`; otherwise `transparent / --ink`. `transition: background .2s, color .2s`.
  - Lines, in order:
    1. `{Tier} · {i} of 6`, e.g. "STRESS · 4 of 6". `.625rem/1.3`, `.12em`, uppercase.
    2. `{n}-token input`, e.g. "2,048-token input". `500 1.0625rem/1.15 Oswald`.
    3. `{c} concurrent request(s)`. `.6875rem/1.3`.
    4. `= equal work` or `≠ unequal work — not compared` (from the existing `unequalWL` rule). `.6875rem/1.3 mono`, `margin-top:2px`.
- **Auto-scroll:**
  - When the selected workload changes, scroll the strip horizontally so the selected card is centred: `left = card.offsetLeft − (strip.clientWidth − card.offsetWidth)/2`.
  - Use `smooth` unless reduced motion is set; the first paint uses `auto`.
  - **Don't use `scrollIntoView`.**
- **Note text** is unchanged: "Input length and concurrency change together. These are six separate workloads, not a sweep."
- **Field note:** still has no page-level selector. Its Evidence sweep control is unchanged.

### B6. Episode header — two versions behind one config flag (`headline`)
- **Default:** `headline = "title"`, which is identical to v1.
- **`headline = "question"`:**
  1. **Label row** (flex wrap, `gap:4px 12px`, baseline):
     - "Episode 01" in `600 .6875rem` uppercase `--ink`
     - The episode name "Measure what matters" in `500 1rem/1 Oswald`, `.02em`, `--ink`
     - "Recorded study" after a `1px --line-strong` left rule, `--muted`
  2. **H1:** the news question, in sentence case (**not** uppercase). `500 clamp(2.125rem,4.6vw,3.875rem)/1.02 Oswald`, `max-width:15em`, `margin-top:4px`, `text-wrap:balance`.
  3. **Deck:** the existing precise question (unchanged).
  4. **Qualifiers:** unchanged.
- **Copy:**

| Page | Kicker | Kind | H1 (question mode) |
|---|---|---|---|
| Episode 01 | Episode 01 | Recorded study | What breaks first when two inference engines meet the same H200 workload? |
| Episode 00 | Episode 00 | Recorded study · Exploratory | What happens to one request as prompts grow longer and the queue gets busier? |
| Field note | Field note | Recorded study | How many conversations can one deployment hold before the first token stalls? |

The Episode 00 and Field note headlines are drafts. Confirm them with the owner before shipping. Preview either mode with `head=title|question` in the hash. This is a preview-only override, like `theme`.

### B7. External links: GitHub and live Grafana dashboard
- **Wide (≥981px):** a flex group (`gap:18px`) in the site bar, placed between the site nav and the Light/Dark toggle.
  - Link style: `min-height:44px; gap:7px; .75rem/600; .12em; uppercase; color:--muted`, hover `--ink`, no underline.
  - Each link is: 16px icon, label, then a small `↗` (`.625rem`, `aria-hidden`).
- **Narrow (<981px):** the same two links appear at the top of the "Menu" panel, above "Lab tools · local only".
  - Row style: `min-height:48px; border-bottom:1px solid --line; gap:10px; .8125rem/600; uppercase`, with `↗` pushed right in `--muted`.
- **Links:**
  - **GitHub:** label "GitHub", `aria-label` "Source on GitHub (opens in a new tab)". Links to `https://github.com/KVSDURGASURESH/token-by-token`.
  - **Dashboard:** label "Live dashboard", `aria-label` "Live Grafana dashboard, hosted separately (opens in a new tab)".
    - **Set its URL with a config value (`GRAFANA_URL`).** The prototype uses a placeholder, `https://grafana.example.com/d/token-by-token`.
    - Must be the public, read-only dashboard URL. No credentials, org IDs or internal hostnames.
  - **Both links:** `target="_blank" rel="noopener noreferrer"`.
- **Icons** (16×16, `currentColor`, `aria-hidden`):
  - **GitHub:** the standard GitHub mark (Octicon `mark-github`, path in the prototype).
  - **Dashboard:** a generic chart glyph, not the Grafana logo. A 13×12 frame (`stroke 1.4`) with four bars: `M4 11V8.5 M7 11V5.5 M10 11V7 M13 11V4`.

## Part C — State, routing, behaviour (unchanged from v1, still required)
- **Hash state:**
  - `#episode-1?load=12|16|24&mode=engines|loads&base=…&depth=brief|lab|ledger&ch=brief…source&metric=id`
  - Episode 00: `wl=128-c1…8192-c32`. Field note: `users=2…100`.
  - Preview-only: `theme`, `text`, `head`.
- **History:** load, workload, mode, baseline, depth and route changes push an entry; metric and chapter changes replace it. Track dragging pushes once and then replaces.
- **Invalid values:** fall back to the default and show the "Link adjusted" notice.
- **Missing data:** a missing manifest fails closed.
- **Keyboard and live region:** one polite live region announces "selection + qualified finding". Esc closes menus and plot explanations and returns focus.
- **Privacy:** public copy names vLLM and SGLang only. No versions, serving profiles, flags, endpoints, org names, recipes, payloads or configs.

## Design tokens (complete)
| Token | Light | Dark |
|---|---|---|
| paper | `#fbfaf5` | `#0e1112` |
| panel | `#f1f0e9` | `#171c1d` |
| ink | `#172f2d` | `#eef1ec` |
| copy | `#455a56` | `#c3cac7` |
| muted | `#5a6966` | `#9aa4a1` |
| line | `#d6dad2` | `#283133` |
| line-strong | `#98a8a2` | `#4a5659` |
| better | `#006d45` | `#4bdcaf` |
| worse | `#b22f18` | `#ff7a4d` |
| neutral (band) | `#8a5b00` | `#f0ba4b` |
| **chapter (new)** | **`#6e5f12`** | **`#d4c26a`** |

- **Fonts:** display Oswald 400–700 (Google Fonts); text "Avenir Next", Avenir, "Helvetica Neue", Helvetica, Arial; mono ui-monospace, SFMono-Regular, Menlo, Consolas.
- **Shape:** no border radius except round dots and the thumb. No shadows except the thumb's 4px paper ring. Focus: `2px solid --ink`, offset 3px.
- **Breakpoints:** 981px (rail vs menu). Plot columns are 3/2/1 by main width (≥860 / ≥520). The main column is at most 1040px; the page is at most 1360px.

## Acceptance checklist
- [ ] Rail: 00 and 01 numbers are ink, 02–16 are grey, and titles are unchanged.
- [ ] All five chapter numbers, bars and the current rail bar use `#6e5f12` / `#d4c26a`, and only those elements use it.
- [ ] Home shows the hero exactly per B3, with counts derived from data.
- [ ] Ep 01 track snaps only to 12/16/24 when dragged, tapped or keyed; the thumb animates; history is pushed once per drag.
- [ ] Ep 00 strip snaps, the arrows disable at the ends, the selected card is centred, and the ≠/= line matches the Evidence chapter.
- [ ] The `headline` flag switches the header; the default is title.
- [ ] GitHub and Live dashboard links appear in the bar (wide) and the Menu (narrow), open in a new tab, and the dashboard URL comes from config.
- [ ] Checked at 1440, 768, 542, 390 and 320px, in light and dark, and at 200% text with no horizontal page scroll.
