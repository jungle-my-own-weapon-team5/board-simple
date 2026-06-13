import { Suspense } from "react";

import LoginPage from "@/screens/LoginPage";

export default function LoginRoute() {
  return (
    <Suspense>
      <LoginPage />
    </Suspense>
  );
}
