import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createRouter } from "@tanstack/react-router";

import * as Sentry from "@sentry/react";

import { isSignInRequiredError } from "@shelfalign/client-common/error";

import { GlobalErrorBoundary } from "@/components/GlobalErrorBoundary";

import { routeTree } from "./routeTree.gen";

// TODO: Replace YOUR_SENTRY_DSN with your own DSN from https://sentry.io
Sentry.init({
  dsn: "YOUR_SENTRY_DSN",
  sendDefaultPii: true,
  integrations: [
    Sentry.browserTracingIntegration(),
    Sentry.replayIntegration({
      maskAllText: false,
      blockAllMedia: false,
    }),
  ],
  tracesSampleRate: 1.0,
  tracePropagationTargets: ["localhost", import.meta.env.VITE_BASE_URL],
  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,
  enableLogs: true,
  enabled: import.meta.env.VITE_SENTRY_LOCAL !== "true",
  environment: import.meta.env.MODE,
});

const router = createRouter({
  routeTree,
  defaultErrorComponent: GlobalErrorBoundary,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnMount: true,
      refetchOnReconnect: true,
      refetchOnWindowFocus: true,
      throwOnError: (error) => isSignInRequiredError(error),
    },
    mutations: {
      throwOnError: (error) => isSignInRequiredError(error),
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Sentry.ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </StrictMode>,
);
