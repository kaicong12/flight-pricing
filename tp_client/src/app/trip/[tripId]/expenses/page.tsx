// The Expenses tab: what the trip has cost, and who owes whom once it is split.

import { notFound, redirect } from "next/navigation";

import { AppHeader } from "@/components/app-header";
import { ExpensesView } from "@/components/expenses/expenses-view";
import { TripTabs } from "@/components/trip-tabs";
import type { TripStatus } from "@/lib/api-types";
import type { ExpenseTab } from "@/lib/expense-types";
import { currentUser } from "@/lib/session";
import { getJson } from "@/lib/tp-api";
import { cityNames } from "@/lib/trips";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PageProps<"/trip/[tripId]/expenses">) {
  const { tripId } = await params;
  const trip = await getJson<TripStatus>(`/trips/${encodeURIComponent(tripId)}`);
  return { title: trip ? `${cityNames(trip)} expenses` : "Expenses" };
}

export default async function ExpensesPage({ params }: PageProps<"/trip/[tripId]/expenses">) {
  const { tripId } = await params;
  const id = encodeURIComponent(tripId);

  const user = await currentUser();
  if (!user) redirect("/login");

  const [trip, tab] = await Promise.all([
    getJson<TripStatus>(`/trips/${id}`),
    getJson<ExpenseTab>(`/trips/${id}/expenses`),
  ]);
  if (!trip || !tab) notFound();

  return (
    <div className="min-h-dvh bg-page pb-24">
      <AppHeader user={user} />
      <main className="mx-auto w-full max-w-[980px] px-7 pt-9">
        <TripTabs tripId={trip.trip_id} />

        <div className="mt-6">
          <h1 className="text-2xl font-semibold tracking-[-0.015em]">Expenses</h1>
        </div>

        <div className="mt-5">
          <ExpensesView
            tripId={trip.trip_id}
            initial={tab}
            meId={user.user_id}
            canEdit={trip.your_role !== "viewer"}
            defaultDate={trip.arrive_date}
          />
        </div>
      </main>
    </div>
  );
}
