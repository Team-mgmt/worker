import { createFileRoute } from "@tanstack/react-router";

import { z } from "zod";

import { Breadcrumb } from "@/components/Breadcrumb";

import { OrganizationList } from "./-components/OrganizationList";

const searchSchema = z.object({
  page: z.number().int().min(1).optional().default(1),
});

export const Route = createFileRoute("/_app/organizations/")({
  component: OrganizationsPage,
  validateSearch: searchSchema,
});

function OrganizationsPage() {
  const { page } = Route.useSearch();

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "조직 관리" }]} />
      <h2 className="font-extrabold text-xl my-3">조직 관리</h2>
      <OrganizationList page={page} />
    </>
  );
}
