import type { VariantProps } from "class-variance-authority";
import type { ComponentProps, ElementType, PropsWithChildren } from "react";

import { cn } from "@/utils";

import { navButtonVariants } from "./variants";

type NavButtonProps<T extends ElementType = "button"> = {
  className?: string;
  icon?: React.ReactNode;
  as?: T;
} & VariantProps<typeof navButtonVariants> &
  Omit<ComponentProps<T>, "className" | "children">;

export function NavButton<T extends ElementType = "button">({
  className,
  icon,
  active,
  as,
  children,
  ...rest
}: PropsWithChildren<NavButtonProps<T>>) {
  const Comp = as ?? "button";

  return (
    <Comp className={cn(navButtonVariants({ active }), className)} {...rest}>
      {icon && <span className="size-4.5 *:size-full">{icon}</span>}
      <p>{children}</p>
    </Comp>
  );
}
