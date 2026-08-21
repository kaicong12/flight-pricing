import { AppHeader } from "@/components/app-header";
import { PlanForm } from "@/components/plan-form";

export default function Home() {
  return (
    <div className="min-h-dvh bg-page">
      <AppHeader />
      <PlanForm />
    </div>
  );
}
