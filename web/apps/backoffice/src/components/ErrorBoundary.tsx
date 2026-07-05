import type { ReactNode } from "react";

import * as Sentry from "@sentry/react";
import { AlertCircleIcon, RefreshCwIcon } from "lucide-react";
import {
  ErrorBoundary as ReactErrorBoundary,
  type ErrorBoundaryProps,
  type FallbackProps,
} from "react-error-boundary";

import { isSignInRequiredError } from "@shelfalign/client-common/error";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryWrapperProps extends Omit<
  ErrorBoundaryProps,
  "fallback" | "fallbackRender" | "FallbackComponent"
> {
  children: ReactNode;
  // Optional override for the fallback rendered when an error is caught.
  fallback?: (props: FallbackProps) => ReactNode;
}

export function ErrorBoundary({
  children,
  fallback,
  onError,
  ...rest
}: ErrorBoundaryWrapperProps) {
  return (
    <ReactErrorBoundary
      {...rest}
      onError={(error, info) => {
        // Auth errors are surfaced through Navigate by AuthGuard — don't drown
        // them in noise here.
        if (!isSignInRequiredError(error)) {
          Sentry.captureException(error);
        }
        onError?.(error, info);
      }}
      fallbackRender={(fallbackProps) => {
        // Re-throw signin-required errors so an upstream AuthGuard can redirect.
        if (isSignInRequiredError(fallbackProps.error)) {
          throw fallbackProps.error;
        }
        if (fallback) return fallback(fallbackProps);
        return <ErrorBoundaryFallback {...fallbackProps} />;
      }}
    >
      {children}
    </ReactErrorBoundary>
  );
}

function ErrorBoundaryFallback({ error, resetErrorBoundary }: FallbackProps) {
  const message = error instanceof Error ? error.message : String(error);

  return (
    <Alert variant="destructive" className="my-4">
      <AlertCircleIcon className="size-4" />
      <AlertTitle>문제가 발생했어요</AlertTitle>
      <AlertDescription className="space-y-3">
        <p className="text-sm text-muted-foreground">
          요청을 처리하는 도중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.
        </p>
        {import.meta.env.MODE !== "production" && (
          <pre className="max-h-40 overflow-auto rounded bg-muted/40 p-2 text-xs">
            {message}
          </pre>
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={resetErrorBoundary}
        >
          <RefreshCwIcon className="size-4 mr-1" />
          다시 시도
        </Button>
      </AlertDescription>
    </Alert>
  );
}
