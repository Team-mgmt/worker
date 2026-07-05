import { useMutation } from "@tanstack/react-query";

import { TrashIcon } from "lucide-react";
import { toast } from "sonner";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import { AdminDeleteOrganizationResponseSchema } from "@shelfalign/schema/dtos/admin/organization";

import { ky } from "@/lib/ky";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import type { Organization } from "../-components/OrganizationList/row";

type Props = {
  organization: Organization;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
};

export function DeleteOrganizationDialog({
  organization,
  open,
  onOpenChange,
  onSuccess,
}: Props) {
  const { mutate, isPending } = useMutation({
    mutationFn: async () => {
      const res = await ky.delete(
        `${import.meta.env.VITE_BASE_URL}/admin/organizations/${organization.id}`,
      );
      const response = await tryJson(
        await res.text(),
        AdminDeleteOrganizationResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("조직 삭제 완료");
      onOpenChange(false);
      onSuccess();
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <TrashIcon className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>조직 삭제</DialogTitle>
          <DialogDescription>
            정말로 <strong>{organization.name}</strong> 조직을 삭제하시겠습니까?
            <br />이 작업은 되돌릴 수 없습니다.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              취소
            </Button>
          </DialogClose>
          <Button
            variant="destructive"
            onClick={() => mutate()}
            disabled={isPending}
          >
            {isPending ? "삭제 중..." : "삭제"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
