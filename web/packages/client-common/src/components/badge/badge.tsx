import type { VariantProps } from "class-variance-authority";
import type { PropsWithChildren } from "react";

import { cn } from "@/utils";

import { badgeVariants } from "./variants";

type BadgeProps = {
  className?: string;
} & VariantProps<typeof badgeVariants>;

export function Badge({
  className,
  size,
  variant,
  children,
}: PropsWithChildren<BadgeProps>) {
  return (
    <span className={cn(badgeVariants({ size, variant }), className)}>
      {children}
    </span>
  );
}
