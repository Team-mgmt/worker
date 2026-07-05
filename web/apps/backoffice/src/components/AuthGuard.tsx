import type { PropsWithChildren } from "react";

import { useSuspenseQuery } from "@tanstack/react-query";
import { Navigate } from "@tanstack/react-router";

import * as Sentry from "@sentry/react";
import { ErrorBoundary } from "react-error-boundary";

import { isSignInRequiredError } from "@shelfalign/client-common/error";

import { queries } from "@/queries";

function AuthGuardContent({ children }: PropsWithChildren) {
  const sessionQuery = useSuspenseQuery(queries.auth.session);

  if (
    sessionQuery.isRefetchError &&
    isSignInRequiredError(sessionQuery.error)
  ) {
    throw sessionQuery.error;
  }

  return children;
}

export function AuthGuard({ children }: PropsWithChildren) {
  return (
    <ErrorBoundary
      fallbackRender={({ error }) => {
        if (
          isSignInRequiredError(error) ||
          error?.constructor?.name === "UnauthorizedError" ||
          String(error).toLowerCase().includes("network") ||
          String(error).toLowerCase().includes("fetch")
        ) {
          return <Navigate to="/auth/signin" />;
        }
        Sentry.captureException(error);
        throw error;
      }}
    >
      <AuthGuardContent>{children}</AuthGuardContent>
    </ErrorBoundary>
  );
}
