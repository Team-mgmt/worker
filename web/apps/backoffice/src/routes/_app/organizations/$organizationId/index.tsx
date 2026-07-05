import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { queries } from "@/queries";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/organizations/$organizationId/")({
  component: OrganizationDetailPage,
});

function OrganizationDetailPage() {
  const { organizationId } = Route.useParams();

  const { data: organization } = useSuspenseQuery(
    queries.organization.get(organizationId),
  );

  return (
    <>
      <Breadcrumb
        items={[
          { type: "link", label: "조직 관리", to: "/organizations" },
          { type: "text", label: organization.name },
        ]}
      />
      <h2 className="font-extrabold text-xl my-3">조직 상세</h2>

      <Card>
        <CardHeader>
          <CardTitle>{organization.name}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">ID:</span>{" "}
              <span className="font-mono">{organization.id}</span>
            </div>
            <div>
              <span className="text-muted-foreground">이름:</span>{" "}
              {organization.name}
            </div>
            <div>
              <span className="text-muted-foreground">생성일:</span>{" "}
              {new Date(organization.createdAt).toLocaleString("ko-KR")}
            </div>
            <div>
              <span className="text-muted-foreground">수정일:</span>{" "}
              {new Date(organization.updatedAt).toLocaleString("ko-KR")}
            </div>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
