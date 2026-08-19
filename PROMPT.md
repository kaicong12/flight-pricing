# Figma Make prompt — Trip Planner frontend

Paste everything below into Figma Make.

---

## What to design

A web app for planning a city trip with friends. It shortlists places to visit by mining real
YouTube travel videos, then lets the user drag those places into the order they want and draws the
resulting route on a map.

Two things make this product different from every other travel app, and the design must make both
visible:

1. **Every recommendation is traceable.** Each place shows which video recommended it and at what
   timestamp. A person said this out loud; you can go watch them say it.
2. **The app is honest about what it doesn't know.** Opening hours are sometimes unverified. Holiday
   closures months ahead are unknowable. An outdoor stop after sunset is a bad idea. The interface
   states these plainly instead of hiding them.

Design for desktop first at 1440px wide, and include a mobile layout at 390px.

---

## Visual direction

The hardest case this product handles is Helsinki in December, where there are only six hours of
daylight. Let that fact drive the look: Nordic winter light, not warm wanderlust. Cold pale daylight,
deep blue darkness, and the amber of street lighting.

**Palette — use these exact values:**

- `#F2F5F8` — page background, cold pale grey
- `#FFFFFF` — cards and panels
- `#141C2E` — primary text, and the dark end of the daylight gutter
- `#5B6B82` — secondary text and labels
- `#E8862B` — amber accent: after-dark markers, warnings, the active drag state
- `#2E7D8F` — teal: links, timestamps, the route line on the map
- `#B4453C` — closed or blocking problems only. Use sparingly.

**Typography — three roles:**

- **Display**: Archivo, semibold, tight letter-spacing. Screen titles and city names. Used sparingly.
- **Body**: Inter, regular and medium. Place names, descriptions, all prose.
- **Data**: JetBrains Mono. Every clock time, duration, video timestamp and distance. Monospace is
  required here — the interface is full of columns of times that must align, and it echoes video
  timecode.

Set a clear scale: display 32/24, body 16/14, data 13/12. Generous line height on prose, tight on data.

**The signature element: a daylight gutter.**

Down the left edge of the itinerary list runs a narrow vertical strip, roughly 6px wide, representing
the day from 08:00 to 22:00. It is filled as a hard-edged gradient: cold pale `#E4EDF2` between
sunrise and sunset, deep `#141C2E` outside those hours, with a 1px amber line at the exact sunset
time. Each activity block aligns to its real position on this strip. The effect is that a December
day in Helsinki visibly runs out of light halfway down the screen, and the user sees it without
reading a number.

Blocks that fall in the dark section get a small amber dot beside their time. Nothing else changes —
the gutter does the work.

**Restraint:** the gutter is the only bold element. Everything else is quiet — flat white cards, 1px
`#E2E8EF` borders, 8px radius, no shadows beyond a barely-there lift on drag. No gradients anywhere
else. No decorative icons.

**Motion:** one orchestrated moment only. When the user drops a reordered block, three things happen
together over ~250ms: the route on the map redraws along the new order, the daylight gutter re-shades
as times shift, and any newly triggered warning slides down into place. Everything else is static.
Respect reduced-motion.

---

## Screens

### 1. New trip

A single centred column, max 560px. Fields, in this order:

- **Where are you going?** — city text input, placeholder `Helsinki`
- **Arriving** and **Leaving** — two date inputs side by side, plus a time input under each labelled
  `Flight lands` / `Flight departs`
- **Anything we should know?** — a multi-line text area, 3 rows, placeholder:
  `We love food and design, want at least one proper sauna, not big on churches, happy to walk`
- Primary button: **Find places**

Below the button, one line of secondary text: `We read real travel videos, so this takes a couple of
minutes.`

### 2. Finding places

The waiting state. Show what is actually happening rather than a spinner and a lie. Centred, narrow.

A short checklist that fills in progressively, each line in mono with a state marker:

```
Searching travel videos for Helsinki        7 found
Reading transcripts                         4 of 7
Matching places to the map                  ...
```

Below it: `Usually about two minutes. We'll keep going if you close this tab.`

### 3. Itinerary — the main screen

Two panes. Left pane 58% width, scrollable. Right pane 42%, a sticky map. On mobile the map becomes a
collapsed strip at the top that expands to full height when tapped.

**Header of the left pane:** city name in display type, then a mono line of trip facts:

```
HELSINKI
Sun 6 Dec 2026  ·  daylight 09:06–15:17  ·  6h 11m
```

**Day tabs** immediately below: `Day 1  Day 2  Day 3  Day 4`, a simple underlined tab row.

**A provisional-plan banner**, amber left border, no icon:

> **This plan is provisional.** Holiday hours for 6 December aren't published yet — that's
> Independence Day in Finland, so some places may close early. Check again closer to your trip.

**The itinerary list.** Each place is a card. Each card contains, top to bottom:

- Left column, mono: the time range, e.g. `10:00–11:15`. If it starts after sunset, an amber dot
  precedes it.
- A category label in small caps mono, `#5B6B82`: `SEE` / `DO` / `EAT` / `DRINK` / `BUY`
- The place name in body medium, 17px: `Löyly Helsinki`
- One line of why-go text: `Named one of Time's 100 Best Places in the World, with saunas right on
  the ocean and a cold plunge into the Baltic.`
- A provenance row, mono 12px, teal, clickable:
  `▸ Perfect 2 Days in Helsinki · 20:51`
- An hours row, mono 12px: `Open until 21:00` in secondary grey, OR `Hours unverified` in amber, OR
  `Closed on this date` in red.
- A drag handle on the far right — six dots, `#B8C3D0`, cursor grab.

**Travel legs between cards.** Not a card — a thin indented row, mono, secondary grey:

```
      ↓  8 min walk · 624 m
      ↓  11 min · tram 2 · Kauppatori → Lasipalatsi
```

Transit legs name the line and both stops. Walking legs show distance.

**Warnings appear inline, attached to the card they concern**, indented under it, amber left border,
mono label + plain sentence:

```
TOO LATE   Uspenski Cathedral closes at 16:00. You arrive 15:43 and need 75 minutes.
AFTER DARK Löyly starts at 17:41, and the sun set at 15:17.
```

Write warnings as statements of fact with the number that matters. Never "potential timing conflict".

**A mode toggle** at the top of the list: `Walking` / `Transit`, a two-option segmented control.
When Transit is selected and the trip is more than about three months away, show under it:
`Transit times aren't available this far ahead. Showing walking times for now.`

**Footer of the list:** mono summary — `9 stops · 103 min travelling · ends 19:41`

**The map pane.** A city map, muted and desaturated so the route reads clearly. Numbered pins matching
the list order, in teal, with the number in white. The route drawn as a 3px teal line following
streets, not straight lines between pins. Hovering a card highlights its pin and dims the others.
Bottom-right of the map, a small mono scale and a `Walking` / `Transit` label.

### 4. Suggested places drawer

A panel that slides over the left pane, triggered by an **Add places** button. It holds the places we
found that aren't in the itinerary yet — same card layout, each with an **Add** button instead of a
drag handle. At the top, a mono count: `We found 19 places. 9 are in your plan.`

If a city produced few results, show instead: `We only found 6 places for Kotor. Expect a thin plan.`

### 5. Proposed changes — owner view

One person owns each trip; friends can suggest edits but not apply them. Design a review list.

Each proposal is a card: the friend's name and avatar, what they want to change stated as a sentence,
and two buttons, **Approve** and **Decline**.

```
Mei suggested
Add Kotiharjun Sauna to Day 3, after Hakaniemi Market Hall
"the wood-fired one, way better than Löyly"                    [Approve] [Decline]
```

Show a count badge on the nav item: `Proposed changes 3`.

### 6. Shared view

The same itinerary screen, read-only: no drag handles, no Add places button, no warnings panel. A
mono line at the top: `Shared by Kai · view only`.

---

## Rules for the copy

- Sentence case everywhere. No title case headings.
- Buttons name the action and keep the same word through the flow: **Approve** produces "Approved".
- State problems with the number that causes them. `Closes at 16:00. You arrive 15:43.`
- Never apologise, never say "oops", never use exclamation marks.
- Empty states point at the next action, e.g. `No places yet. Add some from the ones we found.`

## Do not

- Do not use a warm cream background with a serif display face and a terracotta accent.
- Do not use hero images of landmarks, stock travel photography, or a full-bleed photo header.
- Do not add gradients, glassmorphism, drop shadows, or rounded corners beyond 8px.
- Do not use emoji, or icons for their own sake. Only the drag handle, the arrows on travel legs, and
  map pins need marks.
- Do not hide the warnings behind a tooltip or an expandable. They belong in the flow of the list.
- Do not number the places `01 / 02 / 03` in the list — the map pins already carry the sequence, and
  the times are the real ordering information.
