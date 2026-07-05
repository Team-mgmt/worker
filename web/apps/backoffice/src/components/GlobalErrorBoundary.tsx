import { useEffect } from "react";

import {
  type ErrorComponentProps,
  Link,
  useRouter,
} from "@tanstack/react-router";

import * as Sentry from "@sentry/react";
import { AlertTriangleIcon, HomeIcon, RefreshCwIcon } from "lucide-react";

import { isSignInRequiredError } from "@shelfalign/client-common/error";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Fallback rendered by TanStack Router when an error escapes a route's
// component tree. Wired in via createRouter({ defaultErrorComponent }).
export function GlobalErrorBoundary({
  error,
  reset,
  info,
}: ErrorComponentProps) {
  const router = useRouter();

  useEffect(() => {
    if (isSignInRequiredError(error)) return;
    Sentry.captureException(error, {
      extra: info ? { componentStack: info.componentStack } : undefined,
    });
  }, [error, info]);

  if (isSignInRequiredError(error)) {
    // Surface to AuthGuard so a Navigate happens instead of showing this UI.
    throw error;
  }

  const message = error instanceof Error ? error.message : String(error);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-lg">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <AlertTriangleIcon className="size-6" />
          </div>
          <CardTitle className="text-xl">문제가 발생했어요</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <p className="text-sm text-muted-foreground">
            요청을 처리하는 도중 오류가 발생했습니다. 잠시 후 다시 시도해
            주세요. 문제가 계속되면 관리자에게 문의해 주세요.
          </p>
          {import.meta.env.MODE !== "production" && (
            <pre className="max-h-48 overflow-auto rounded bg-muted/40 p-3 text-left text-xs">
              {message}
              {info?.componentStack ? `\n${info.componentStack}` : ""}
            </pre>
          )}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                void router.invalidate();
              }}
            >
              <RefreshCwIcon className="size-4 mr-1" />
              다시 시도
            </Button>
            <Button asChild type="button">
              <Link to="/" onClick={reset}>
                <HomeIcon className="size-4 mr-1" />
                홈으로 가기
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
