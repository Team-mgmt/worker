import { useState } from "react";

import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/auth/signin/")({
  component: RouteComponent,
});

function RouteComponent() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const response = await fetch(
        `${import.meta.env.VITE_BASE_URL}/auth/signin`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-turnstile-token": "dummy",
          },
          credentials: "include",
          body: JSON.stringify({ email, password }),
        },
      );

      if (!response.ok) {
        toast.error("Login failed.");
        return;
      }

      const result = (await response.json()) as {
        result: true;
        data: { accessToken: string };
      };

      localStorage.setItem("accessToken", result.data.accessToken);
      navigate({ to: "/" });
    } catch {
      toast.error("Login failed.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md">
        <Card className="rounded-2xl shadow-xl">
          <CardHeader className="text-center">
            <CardTitle className="text-3xl sm:text-4xl">
              ShelfAlign Backoffice
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                required
              />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                required
              />
              <Button
                type="submit"
                className="w-full"
                size="lg"
                disabled={isLoading}
              >
                {isLoading ? "Signing in..." : "ShelfAlign Login"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
