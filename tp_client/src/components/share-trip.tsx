"use client";

// Sharing one trip. Used from the trips list and from the plan screen, so the trigger has two
// shapes but the dialog is the same.

import { Avatar } from "@base-ui/react/avatar";
import { Check, Link2, LogOut, Users, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { Member, TripRole, User } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 250;
const SHAREABLE: TripRole[] = ["editor", "viewer"];

const ROLE_NOTE: Record<TripRole, string> = {
  owner: "renames, shares and deletes",
  editor: "can change the plan",
  viewer: "can look, not touch",
};

function initials(user: { name: string | null; email: string }): string {
  const source = user.name?.trim() || user.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase();
}

function Face({ user }: { user: { name: string | null; email: string; picture: string | null } }) {
  return (
    <Avatar.Root className="grid size-8 shrink-0 place-items-center overflow-hidden rounded-full bg-[#d7cfba] text-[11px] font-semibold text-ink-soft select-none">
      {/* Chrome ORB-blocks a Google avatar when the request carries a referrer. */}
      {user.picture ? (
        <Avatar.Image
          src={user.picture}
          alt=""
          referrerPolicy="no-referrer"
          className="size-full object-cover"
        />
      ) : null}
      <Avatar.Fallback>{initials(user)}</Avatar.Fallback>
    </Avatar.Root>
  );
}

/** Bold name over the email, which is what makes two people called Bo tellable apart. */
function Who({ user }: { user: User }) {
  return (
    <span className="min-w-0 flex-1 text-left">
      <span className="block truncate text-[13.5px] font-semibold text-ink">
        {user.name?.trim() || user.email}
      </span>
      <span className="block truncate text-[12px] text-muted-foreground">{user.email}</span>
    </span>
  );
}

export function ShareTrip({
  tripId,
  yourRole,
  meId,
  variant = "pill",
}: {
  tripId: string;
  yourRole: TripRole;
  meId: string;
  variant?: "pill" | "icon";
}) {
  const router = useRouter();
  const owns = yourRole === "owner";

  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ q: string; items: User[] }>({ q: "", items: [] });
  const [role, setRole] = useState<TripRole>("editor");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const q = query.trim();

  async function loadMembers() {
    const r = await fetch(`/api/trips/${tripId}/members`);
    if (r.ok) setMembers((await r.json()) as Member[]);
  }

  /** Opening is an event, not synchronisation, so the member list loads here and not in an effect. */
  function toggle(next: boolean) {
    setOpen(next);
    setError(null);
    if (next) void loadMembers();
  }

  useEffect(() => {
    if (!open || !owns) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      if (q.length < 2) {
        setFound({ q, items: [] });
        return;
      }
      try {
        const r = await fetch(`/api/users/search?q=${encodeURIComponent(q)}`, {
          signal: controller.signal,
        });
        setFound({ q, items: r.ok ? ((await r.json()) as User[]) : [] });
      } catch {
        // An aborted keystroke is not a failure; the next one owns the result.
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q, open, owns]);

  /** Every mutation reports tp_api's own message, so a 403 or 409 does not fail silently. */
  async function send(path: string, init: RequestInit): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(path, init);
      if (r.ok) return true;
      const body = (await r.json().catch(() => null)) as { detail?: string } | null;
      setError(body?.detail ?? "That did not work. Try again.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function share(user: User, as: TripRole) {
    const ok = await send(`/api/trips/${tripId}/members`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_id: user.user_id, role: as }),
    });
    if (!ok) return;
    setQuery("");
    setFound({ q: "", items: [] });
    await loadMembers();
    router.refresh();
  }

  async function unshare(userId: string) {
    if (!(await send(`/api/trips/${tripId}/members/${userId}`, { method: "DELETE" }))) return;
    if (userId === meId) {
      setOpen(false);
      router.push("/trips");
      return;
    }
    await loadMembers();
    router.refresh();
  }

  async function copyLink() {
    await navigator.clipboard.writeText(`${window.location.origin}/trip/${tripId}/plan`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  const alreadyIn = new Set(members.map((m) => m.user_id));
  const suggestions = found.q === q ? found.items.filter((u) => !alreadyIn.has(u.user_id)) : [];

  return (
    <Dialog open={open} onOpenChange={toggle}>
      <DialogTrigger
        aria-label="Share this trip"
        className={cn(
          "flex items-center gap-1.5 rounded-full border border-border bg-surface font-medium text-ink transition-colors hover:border-[#c6bda4] outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          variant === "pill" ? "h-9 px-3.5 text-[13px]" : "size-8 justify-center",
        )}
      >
        <Users className="size-3.5" />
        {variant === "pill" ? "Share" : null}
      </DialogTrigger>

      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{owns ? "Share this trip" : "Who is on this trip"}</DialogTitle>
          <DialogDescription>
            {owns
              ? "A link on its own grants nothing — add someone here and it opens for them."
              : "Only the owner can change who is on it."}
          </DialogDescription>
        </DialogHeader>

        {owns ? (
          <div>
            {/* autoComplete off: Chrome offers to autofill an address over the dialog otherwise. */}
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name or email"
                aria-label="Search for someone to share with"
                autoComplete="off"
                spellCheck={false}
                className="h-9 w-full min-w-40 flex-1 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
              <div className="flex h-9 shrink-0 items-center rounded-full bg-page p-0.5">
                {SHAREABLE.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    aria-pressed={role === r}
                    className={cn(
                      "flex h-8 items-center rounded-full px-2.5 text-[12.5px] font-medium capitalize transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      role === r
                        ? "bg-surface text-ink shadow-card"
                        : "text-muted-foreground hover:text-ink",
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <p className="mt-1.5 text-[12px] text-faint">
              Added as {role} — {ROLE_NOTE[role]}.
            </p>

            {q.length >= 2 ? (
              <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-border">
                {suggestions.length === 0 ? (
                  <p className="px-3 py-3 text-[13px] text-muted-foreground">
                    Nobody matches. They have to have signed in here at least once.
                  </p>
                ) : (
                  suggestions.map((u) => (
                    <button
                      key={u.user_id}
                      type="button"
                      disabled={busy}
                      onClick={() => void share(u, role)}
                      className="flex w-full items-center gap-2.5 border-b border-hairline px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-page disabled:opacity-60 outline-none focus-visible:bg-page focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      <Face user={u} />
                      <Who user={u} />
                    </button>
                  ))
                )}
              </div>
            ) : null}
          </div>
        ) : null}

        {error ? (
          <p role="alert" className="text-[13px] text-alert">
            {error}
          </p>
        ) : null}

        <div>
          <p className="font-mono text-[10.5px] tracking-[0.05em] text-faint uppercase">
            On this trip
          </p>
          <div className="mt-1.5">
            {members.map((m) => (
              <div key={m.user_id} className="flex items-center gap-2.5 border-b border-hairline py-2.5 last:border-b-0">
                <Face user={m} />
                <Who user={m} />
                {owns && m.role !== "owner" ? (
                  <select
                    value={m.role}
                    disabled={busy}
                    onChange={(e) => void share(m, e.target.value as TripRole)}
                    aria-label={`Role for ${m.email}`}
                    className="h-7 rounded-md border border-input bg-transparent px-1.5 text-[12.5px] capitalize outline-none focus-visible:border-ring"
                  >
                    {SHAREABLE.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="shrink-0 font-mono text-[11px] text-faint">{m.role}</span>
                )}
                {owns && m.role !== "owner" ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void unshare(m.user_id)}
                    aria-label={`Remove ${m.email}`}
                    className="grid size-6 shrink-0 place-items-center rounded-full text-faint transition-colors hover:bg-alert-bg hover:text-alert disabled:opacity-60 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <X className="size-3.5" />
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => void copyLink()}
            className="flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-3 text-[12.5px] font-medium text-ink transition-colors hover:border-[#c6bda4] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {copied ? <Check className="size-3.5 text-ok" /> : <Link2 className="size-3.5" />}
            {copied ? "Copied" : "Copy link"}
          </button>
          {owns ? null : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void unshare(meId)}
              className="flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-medium text-alert transition-colors hover:bg-alert-bg disabled:opacity-60 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <LogOut className="size-3.5" />
              Leave this trip
            </button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
