import { AppHeader } from "@/components/app-header";
import { PlanForm } from "@/components/plan-form";
import { currentUser } from "@/lib/session";

export default async function Home() {
  return (
    <div className="min-h-dvh bg-page">
      <AppHeader user={await currentUser()} />
      <PlanForm />
    </div>
  );
}
