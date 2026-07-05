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
    await new Promise((r) => setTimeout(r, 600));
    if (email === "admin@shelfalign.kr" && password === "1234") {
      localStorage.setItem("accessToken", "test-token");
      navigate({ to: "/" });
    } else {
      toast.error("이메일 또는 비밀번호가 올바르지 않습니다.");
    }
    setIsLoading(false);
  };

  return (
    <main className="flex items-center justify-center min-h-screen bg-muted px-4 sm:px-6 lg:px-8 py-12">
      <div className="w-full max-w-md">
        <Card className="rounded-2xl shadow-xl">
          <CardHeader className="text-center">
            <CardTitle className="text-3xl sm:text-4xl">ShelfAlign 백오피스</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="이메일"
                className="w-full border border-input rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                required
              />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="비밀번호"
                className="w-full border border-input rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                required
              />
              <Button type="submit" className="w-full" size="lg" disabled={isLoading}>
                {isLoading ? "로그인 중..." : "ShelfAlign Login"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
