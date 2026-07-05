import type { VariantProps } from "class-variance-authority";
import type { ComponentProps, ElementType, PropsWithChildren } from "react";

import { cn } from "@/utils";

import { chipVariants } from "./variants";

type ChipProps<T extends ElementType = "button"> = {
  className?: string;
  as?: T;
} & VariantProps<typeof chipVariants> &
  Omit<ComponentProps<T>, "className" | "children">;

export function Chip<T extends ElementType = "button">({
  className,
  active,
  as,
  children,
  ...rest
}: PropsWithChildren<ChipProps<T>>) {
  const Comp = as ?? "button";

  return (
    <Comp className={cn(chipVariants({ active }), className)} {...rest}>
      {children}
    </Comp>
  );
}
