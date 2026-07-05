import { useCallback, type DependencyList } from "react";
import { useErrorBoundary } from "react-error-boundary";

import { isSignInRequiredError } from "../error";

type RequestCallback<TArgs extends unknown[], TResult> = (
  ...args: TArgs
) => TResult | Promise<TResult>;

/**
 * Wraps async request callbacks and forwards sign-in-required errors
 * to the nearest ErrorBoundary.
 */
export function useRequestCallback<TArgs extends unknown[], TResult>(
  callback: RequestCallback<TArgs, TResult>,
  deps: DependencyList,
): (...args: TArgs) => Promise<TResult | undefined> {
  const { showBoundary } = useErrorBoundary();

  return useCallback(
    async (...args: TArgs): Promise<TResult | undefined> => {
      try {
        return await callback(...args);
      } catch (error) {
        if (isSignInRequiredError(error)) {
          showBoundary(error);
          return undefined;
        }

        throw error;
      }
    },
    [callback, showBoundary, ...deps],
  );
}
