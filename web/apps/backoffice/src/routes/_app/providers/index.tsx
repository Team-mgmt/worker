import { createFileRoute } from "@tanstack/react-router";

import { z } from "zod";

import { Breadcrumb } from "@/components/Breadcrumb";

import { ProviderList } from "./-components/ProviderList";

const searchSchema = z.object({
  page: z.number().int().min(1).optional().default(1),
});

export const Route = createFileRoute("/_app/providers/")({
  component: ProvidersPage,
  validateSearch: searchSchema,
});

function ProvidersPage() {
  const { page } = Route.useSearch();

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "인증 관리" }]} />
      <h2 className="font-extrabold text-xl my-3">인증 관리</h2>
      <ProviderList page={page} />
    </>
  );
}
