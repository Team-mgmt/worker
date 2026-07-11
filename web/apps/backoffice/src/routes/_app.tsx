import { Suspense } from "react";

import { createFileRoute, Outlet } from "@tanstack/react-router";

import { Header } from "@/components/Header";

export const Route = createFileRoute("/_app")({
  component: RouteComponent,
});

function RouteComponent() {
  return (
    <div className="flex-1 flex flex-col">
        <div className="container mx-auto">
          <Header />
        </div>
        <Suspense>
          <div className="w-full h-full overflow-auto flex-1">
            <div className="container mx-auto mt-6 pb-24">
              <Outlet />
            </div>
          </div>
        </Suspense>
    </div>
  );
}
