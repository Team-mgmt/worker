import { lazy } from "react";

import { Outlet, createRootRoute } from "@tanstack/react-router";

const TanStackRouterDevtools =
  import.meta.env.MODE === "production"
    ? () => null
    : lazy(() =>
        import("@tanstack/react-router-devtools").then((res) => ({
          default: res.TanStackRouterDevtools,
        })),
      );

const ReactQueryDevtools =
  import.meta.env.MODE === "production"
    ? () => null
    : lazy(() =>
        import("@tanstack/react-query-devtools/build/modern/production.js").then(
          (res) => ({
            default: res.ReactQueryDevtools,
          }),
        ),
      );

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  return (
    <>
      <Outlet />
      <TanStackRouterDevtools />
      <ReactQueryDevtools initialIsOpen={false} />
    </>
  );
}
