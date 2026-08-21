# Design system

Source: Claude Design project **"Flight Pricing App Design"** (`Trip Planner.dc.html` + `design.md`).

It uses **no packaged design system** — not Modernist, not Kekal UI. The artboards hard-code every
value and `design.md` names the direction **"Organic Biophilic"**: warm sand paper, sage and moss,
clay for what is broken, dusty sky reserved for water. The shadcn `base-nova` structure stays; only
the palette, type and shape change.

**Light only.** The design defines no dark theme, and nothing in the app sets `.dark`, so the shadcn
dark block in `globals.css` is inert.

## Colour

Tokens live in `src/app/globals.css`. Design-doc names differ where shadcn already owns one: its
`--accent` is a neutral surface, so the state accent is `--brand` here.

| Token | Hex | Use |
|---|---|---|
| `--page` / `--background` | `#f3f0e6` | warm sand, never a card. Carries two radial washes on `body` — sage top-left, sky top-right |
| `--surface` / `--card` | `#fdfbf3` | cards. The `surface` utility adds `linear-gradient(168deg,#fefdf7,#fbf6ea)` — paper, not glass |
| `--border` | `#e3ddcb` | 1px hairlines |
| `--hairline` | `#ece7d9` | dividers inside a card |
| `--input` | `#e0dac9` | field borders |
| `--ink` / `--foreground` / `--primary` | `#252b20` | text and the primary button fill. Dark bark green |
| `--ink-hover` | `#39412f` | primary button hover |
| `--ink-soft` | `#4b5344` | secondary text |
| `--muted-foreground` | `#6a7263` | supporting copy |
| `--faint` | `#98a08d` | metadata, mono captions. 12px+ only |
| `--brand` / `--ring` | `#2c6b64` | in progress, links, focus ring — deep lake teal |
| `--brand-bg` | `#e5efec` | |
| `--ok` / `--ok-bg` | `#4e7a45` / `#e9f0e0` | task complete — moss |
| `--warn` / `--warn-bg` / `--warn-border` | `#8a6524` / `#f6ebd4` / `#ebdbba` | provisional plan |
| `--alert` / `--alert-bg` | `#8b4526` / `#f8e7dc` | one block that does not work — clay |
| `--land` | `#e8e7d6` | map land. Water is the `water` utility, `linear-gradient(180deg,#bfd2de,#adc3d2)` |

Rules: warm neutrals carry the UI, colour only carries state. The primary button stays ink so
`--brand` keeps meaning *in progress*. Blue is a material, not an accent — water and nothing else.
`--alert` is per-block, `--warn` is whole-plan.

## Type

**Karla** for anything a human wrote, **IBM Plex Mono** for anything a machine produced — times,
task kinds, ids, counts. Both via `next/font/google` in `layout.tsx`; Karla binds `--font-sans`
(shadcn resolves `font-sans` through it), Plex Mono binds `--font-plex-mono`.

| Role | Size / weight |
|---|---|
| Page title | 26–32 / 600, `-0.015em` |
| Section title | 14 / 600 |
| Body | 13.5–14.5 / 400, line-height 1.55 |
| Label | 13 / 600 |
| Meta | 12–12.5 / 400, `--faint` |
| Mono eyebrow | 10.5–11 / 400, `0.05em`, uppercase |

## Space, radius, elevation

4px base. Card padding 18–28px, page gutter 28px, max width 1180px (lists), 1060px (plan), 700px
(status).

Cards use **asymmetric radii** — `--radius-card` `26px 20px 24px 22px`, `--radius-card-sm`
`20px 16px 18px 17px` — which reads hand-drawn and still crops predictably. Buttons and chips are
full pills. Inputs stay at 14px: a pill-shaped 44px text field makes the caret ambiguous. Blobs
(`46% 54% 38% 62% / 60% 40% 56% 44%`) only where the thing is a picture, not a box.

Depth is one hairline plus `--shadow-card` `0 1px 2px rgba(37,43,32,0.04)`, hover `--shadow-lift`
`0 6px 20px rgba(37,43,32,0.08)`. No coloured shadows.

A fixed `feTurbulence` grain sits over the whole app in `layout.tsx` (`mix-blend-multiply`,
`pointer-events-none`) so cards, chips and the map share one paper surface.

Motion is state feedback only: `tp-spin` 0.9s, `tp-pulse` 1.4s, 150ms hovers. No entrance
animation — content arriving by polling must not also fade in.

## Patterns in use

`AppHeader` leaf mark (`999px 4px 999px 4px`, moss→teal) with pill nav · `TripCard` topographic
thumbnail with a water blob and one status chip · `TripProgress` checklist rows (moss tick, spinner,
dashed ring; `blocked` renders as waiting, not an error) · plan form card beside a mono-eyebrow
"what happens next" rail.

Not built yet, designed: itinerary + map, block detail, share + proposals, the standalone ingesting
and blocked pages. See `design.md` in the design project.
