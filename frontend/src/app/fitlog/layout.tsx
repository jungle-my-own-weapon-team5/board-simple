import RequireAuth from "@/components/RequireAuth";
import FitlogCoachButton from "@/components/FitlogCoachButton";

export default function FitlogLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      {children}
      <FitlogCoachButton />
    </RequireAuth>
  );
}
