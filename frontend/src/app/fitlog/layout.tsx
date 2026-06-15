import RequireAuth from "@/components/RequireAuth";

export default function FitlogLayout({ children }: { children: React.ReactNode }) {
  return <RequireAuth>{children}</RequireAuth>;
}
