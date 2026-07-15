import { useState } from "react";

import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { Loader2Icon, LockKeyholeIcon } from "lucide-react";

import { ADMIN_ORGANIZATION_ID } from "@/lib/constants";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/auth/signin/")({
  component: SignInPage,
});

type SignInResponse = {
  result: true;
  data: {
    accessToken: string;
    organizations: Array<{
      organizationId: string;
      type: "ADMIN" | "LIBRARIAN";
    }>;
  };
};

function SignInPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@shelfaligner.com");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const response = await fetch(
        `${import.meta.env.VITE_BASE_URL}/auth/signin`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ email: email.trim(), password }),
        },
      );
      if (!response.ok) {
        throw new Error(
          response.status === 400
            ? "이메일 또는 비밀번호가 올바르지 않습니다."
            : `로그인 실패: ${response.status}`,
        );
      }

      const payload = (await response.json()) as SignInResponse;
      const organization =
        payload.data.organizations.find(
          (item) => item.organizationId === ADMIN_ORGANIZATION_ID,
        ) ?? payload.data.organizations.find((item) => item.type === "ADMIN");
      if (!organization) throw new Error("관리자 조직 권한이 없습니다.");

      localStorage.setItem("accessToken", payload.data.accessToken);
      localStorage.setItem("organization", organization.organizationId);
      await navigate({ to: "/shelf-ops", replace: true });
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "로그인 중 오류가 발생했습니다.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-dvh items-center justify-center bg-zinc-100 px-4 py-10">
      <section className="w-full max-w-sm border bg-white p-6 shadow-sm">
        <div className="mb-6">
          <div className="mb-4 flex size-10 items-center justify-center bg-zinc-900 text-white">
            <LockKeyholeIcon className="size-5" />
          </div>
          <p className="font-mono text-sm font-semibold">ShelfAlign</p>
          <h1 className="mt-1 text-xl font-extrabold">관리자 로그인</h1>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <Label htmlFor="email">이메일</Label>
            <Input
              id="email"
              className="mt-1.5"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="password">비밀번호</Label>
            <Input
              id="password"
              className="mt-1.5"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          {error ? (
            <p className="border-l-4 border-red-600 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          ) : null}
          <Button className="w-full" type="submit" disabled={isSubmitting}>
            {isSubmitting ? (
              <Loader2Icon className="size-4 animate-spin" />
            ) : (
              <LockKeyholeIcon className="size-4" />
            )}
            로그인
          </Button>
        </form>
      </section>
    </main>
  );
}
