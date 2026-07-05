import { EyeIcon } from "lucide-react";

import { ProviderConfigSchema } from "@shelfalign/schema/auth/providers/base";

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
import { maskSecrets } from "../-lib/mask-secrets";

type Props = {
  provider: Provider;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ViewProviderDialog({ provider, open, onOpenChange }: Props) {
  const parsed = ProviderConfigSchema.safeParse(provider.config);
  const configWithoutSecret = parsed.success ? maskSecrets(parsed.data) : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <EyeIcon className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>인증 제공자 정보</DialogTitle>
          <DialogDescription>{provider.name}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 overflow-hidden">
          <div className="overflow-hidden">
            <h4 className="text-sm font-medium mb-2">설정</h4>
            <pre className="text-xs bg-muted p-4 rounded-md overflow-auto max-h-80">
              {JSON.stringify(configWithoutSecret, null, 2)}
            </pre>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">생성일:</span>{" "}
              {new Date(provider.createdAt).toLocaleString("ko-KR")}
            </div>
            <div>
              <span className="text-muted-foreground">수정일:</span>{" "}
              {new Date(provider.updatedAt).toLocaleString("ko-KR")}
            </div>
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">닫기</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
