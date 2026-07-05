import { useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import type { z } from "zod";

import type { ProviderSchema } from "@shelfalign/schema/models/provider";

import { queries } from "@/queries";

import { Badge } from "@/components/ui/badge";
import { TableCell, TableRow } from "@/components/ui/table";

import { DeleteProviderDialog } from "../../-dialog/DeleteProviderDialog";
import { ViewProviderDialog } from "../../-dialog/ViewProviderDialog";
import { getProviderType } from "../../-lib/get-provider-type";

export type Provider = z.infer<typeof ProviderSchema>;

type Props = {
  provider: Provider;
};

export function ProviderRow({ provider }: Props) {
  const queryClient = useQueryClient();
  const [viewOpen, setViewOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const createdAt = new Date(provider.createdAt).toLocaleDateString("ko-KR");
  const providerType = getProviderType(provider.config);

  const handleUpdate = () => {
    queryClient.invalidateQueries({
      queryKey: queries.provider.list._def,
    });
  };

  return (
    <TableRow>
      <TableCell className="font-medium">
        <div className="flex items-center gap-2">
          {provider.name}
          <Badge variant="secondary">{providerType}</Badge>
        </div>
      </TableCell>
      <TableCell className="text-muted-foreground">{createdAt}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <ViewProviderDialog
            provider={provider}
            open={viewOpen}
            onOpenChange={setViewOpen}
          />
          <DeleteProviderDialog
            provider={provider}
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            onSuccess={handleUpdate}
          />
        </div>
      </TableCell>
    </TableRow>
  );
}
