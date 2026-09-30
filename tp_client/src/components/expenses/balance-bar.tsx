// One currency's pile: what it came to, a diverging bar per person, and the payments that clear it.
//
// The bar is centred on zero — owed-to-them grows right, owes grows left — because the question the
// tab answers is which side of nothing each person is on, not how much was spent.

import { Button } from "@/components/ui/button";
import type { Member } from "@/lib/api-types";
import { type CurrencyBalance, firstName, forReading, money, widest } from "@/lib/expense-types";
import { cn } from "@/lib/utils";

export function BalanceBar({
  balance,
  members,
  meId,
  busy,
  canEdit,
  onSettle,
}: {
  balance: CurrencyBalance;
  members: Member[];
  meId: string;
  busy: boolean;
  canEdit: boolean;
  onSettle: (fromUserId: string, toUserId: string, amountCents: number) => void;
}) {
  const scale = widest(balance);
  const who = (userId: string) => {
    const member = members.find((m) => m.user_id === userId);
    return member ? firstName(member) : "Someone";
  };

  return (
    <section className="rounded-card border border-border surface p-5 shadow-card">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em]">
          {money(balance.total_cents, balance.currency)}
        </h2>
        <p className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase">
          {balance.currency} · {balance.members.length} people
        </p>
      </header>

      <ul className="mt-4 space-y-2.5">
        {forReading(balance, meId).map((m) => {
          const owes = m.net_cents < 0;
          const width = `${Math.round((Math.abs(m.net_cents) / scale) * 100)}%`;
          return (
            <li
              key={m.user_id}
              className="grid grid-cols-[minmax(0,84px)_minmax(0,1fr)_minmax(0,auto)] items-center gap-3"
            >
              <span className="truncate text-[13px] font-medium">
                {m.user_id === meId ? "You" : who(m.user_id)}
              </span>

              <span className="flex h-5 items-stretch" aria-hidden="true">
                <span className="flex w-1/2 justify-end">
                  <span
                    className="rounded-l-full bg-alert/55"
                    style={{ width: owes ? width : 0 }}
                  />
                </span>
                <span className="w-px bg-hairline" />
                <span className="flex w-1/2">
                  <span className="rounded-r-full bg-ok/55" style={{ width: owes ? 0 : width }} />
                </span>
              </span>

              <span
                className={cn(
                  "text-right font-mono text-[12px] tabular-nums",
                  m.net_cents === 0 ? "text-faint" : owes ? "text-alert" : "text-ok",
                )}
                title={[
                  `paid ${money(m.paid_cents, balance.currency)}`,
                  `share ${money(m.share_cents, balance.currency)}`,
                  m.settled_cents
                    ? `settled ${money(m.settled_cents, balance.currency)}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(", ")}
              >
                {money(m.net_cents, balance.currency)}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-5 border-t border-hairline pt-4">
        {balance.transfers.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">Settled — nobody owes anybody.</p>
        ) : (
          <>
            <h3 className="font-mono text-[11px] tracking-[0.04em] text-faint uppercase">
              To settle up
            </h3>
            <ul className="mt-2.5 space-y-2">
              {balance.transfers.map((t) => (
                <li
                  key={`${t.from_user_id}-${t.to_user_id}`}
                  className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5"
                >
                  <p className="text-[13.5px]">
                    <span className="font-semibold">
                      {t.from_user_id === meId ? "You" : who(t.from_user_id)}
                    </span>{" "}
                    <span className="text-muted-foreground">pays</span>{" "}
                    <span className="font-semibold">
                      {t.to_user_id === meId ? "you" : who(t.to_user_id)}
                    </span>{" "}
                    <span className="font-mono tabular-nums">
                      {money(t.amount_cents, balance.currency)}
                    </span>
                  </p>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => onSettle(t.from_user_id, t.to_user_id, t.amount_cents)}
                    >
                      Mark paid
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
