import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/auth/signin/")({
  component: RouteComponent,
});

function RouteComponent() {
  return <Navigate to="/shelf-ops" replace />;
}
