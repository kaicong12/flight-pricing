// THROWAWAY SPIKE fixture. Real Tromsø places, real cached hours, plausible walking legs, so the
// prototype is judged against the shape of real data rather than round numbers.

export type Candidate = {
  id: string;
  name: string;
  category: string;
  openFrom?: number | null;
  openTo?: number | null;
  outdoor?: boolean;
  km: [number, number];
};

const at = (h: number, m = 0) => h * 60 + m;

export const DAY_START = at(8);
export const DAY_END = at(23);
export const SUNSET = at(19, 14);
export const DAY_LABEL = "Day 2 · Sun 20 Sep";

export const CANDIDATES: Candidate[] = [
  { id: "polar", name: "The Polar Museum", category: "see", openFrom: at(10), openTo: at(18), km: [0.3, 0.3] },
  { id: "raketten", name: "Raketten Bar & Pølse", category: "eat", openFrom: at(12), openTo: at(19), km: [0.1, 0.2] },
  { id: "fjell", name: "Fjellheisen", category: "do", openFrom: at(9), openTo: at(24), outdoor: true, km: [1.2, -0.9] },
  { id: "sauna", name: "Sauna Pust Tromsø", category: "do", openFrom: at(6), openTo: at(23), km: [0.3, 0.2] },
  { id: "cathedral", name: "Tromsø Cathedral", category: "see", openFrom: at(11), openTo: at(13), km: [0.1, -0.1] },
  { id: "polaria", name: "Polaria", category: "see", openFrom: at(10), openTo: at(17), km: [-0.2, -0.6] },
  { id: "riso", name: "Risø mat og kaffebar", category: "drink", openFrom: null, openTo: null, km: [0, -0.1] },
  { id: "olhallen", name: "Ølhallen", category: "drink", openFrom: at(12), openTo: at(24), km: [-0.2, -0.4] },
  { id: "telegraf", name: "Telegrafbukta", category: "do", outdoor: true, km: [-1.9, -1.9] },
  { id: "skirri", name: "Restaurant Skirri", category: "eat", openFrom: at(11), openTo: at(17), km: [0.2, 0.2] },
];

export const BY_ID = new Map(CANDIDATES.map((c) => [c.id, c]));

/** Crow-flies km at 4.5 km/h, floored at 5 min. Stands in for one computeRoutes leg. */
export function travelMin(fromId: string, toId: string): number {
  const a = BY_ID.get(fromId)?.km;
  const b = BY_ID.get(toId)?.km;
  if (!a || !b) return 0;
  const km = Math.hypot(b[0] - a[0], b[1] - a[1]);
  return Math.max(5, Math.round((km / 4.5) * 60));
}
