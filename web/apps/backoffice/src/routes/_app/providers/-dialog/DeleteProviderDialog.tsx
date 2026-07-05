import { useMutation } from "@tanstack/react-query";

import { TrashIcon } from "lucide-react";
import { toast } from "sonner";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import { AdminDeleteProviderResponseSchema } from "@shelfalign/schema/dtos/admin/provider";

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

import type { Provider } from "../-components/ProviderList/row";

type Props = {
  provider: Provider;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
};

export function DeleteProviderDialog({
  provider,
  open,
  onOpenChange,
  onSuccess,
}: Props) {
  const { mutate, isPending } = useMutation({
    mutationFn: async () => {
      const res = await ky.delete(
        `${import.meta.env.VITE_BASE_URL}/admin/providers/${provider.id}`,
      );
      const response = await tryJson(
        await res.text(),
        AdminDeleteProviderResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("인증 제공자 삭제 완료");
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
          <DialogTitle>인증 제공자 삭제</DialogTitle>
          <DialogDescription>
            정말로 <strong>{provider.name}</strong> 인증 제공자를
            삭제하시겠습니까?
            <br />이 작업은 되돌릴 수 없으며, 이 제공자를 사용하는 모든
            사용자에게 영향을 줄 수 있습니다.
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
