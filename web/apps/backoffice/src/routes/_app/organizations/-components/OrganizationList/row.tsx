import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { PencilIcon } from "lucide-react";

import { ADMIN_ORGANIZATION_ID } from "@/lib/constants";

import { queries } from "@/queries";

import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";

import { DeleteOrganizationDialog } from "../../-dialog/DeleteOrganizationDialog";

export type Organization = {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  deletedAt: string | null;
};

type Props = {
  organization: Organization;
};

export function OrganizationRow({ organization }: Props) {
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const isAdminOrganization = organization.id === ADMIN_ORGANIZATION_ID;

  const createdAt = new Date(organization.createdAt).toLocaleDateString(
    "ko-KR",
  );

  const handleUpdate = () => {
    queryClient.invalidateQueries({
      queryKey: queries.organization.list._def,
    });
  };

  return (
    <TableRow>
      <TableCell className="font-medium">{organization.name}</TableCell>
      <TableCell className="text-muted-foreground">{createdAt}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" asChild>
            <Link
              to="/organizations/$organizationId/edit"
              params={{ organizationId: organization.id }}
            >
              <PencilIcon className="size-4" />
            </Link>
          </Button>
          {!isAdminOrganization && (
            <DeleteOrganizationDialog
              organization={organization}
              open={deleteOpen}
              onOpenChange={setDeleteOpen}
              onSuccess={handleUpdate}
            />
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}
