import type { VariantProps } from "class-variance-authority";
import type {
  ComponentProps,
  ElementType,
  PropsWithChildren,
  ReactNode,
} from "react";

import { cn } from "@/utils";

import { buttonVariants } from "./variants";

type ButtonProps<T extends ElementType = "button"> = {
  className?: string;
  as?: T;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
} & VariantProps<typeof buttonVariants> &
  Omit<ComponentProps<T>, "className" | "children">;

export function Button<T extends ElementType = "button">({
  className,
  variant,
  size,
  as,
  iconLeft,
  iconRight,
  children,
  ...rest
}: PropsWithChildren<ButtonProps<T>>) {
  const Comp = as ?? "button";

  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...rest}
    >
      {iconLeft && <span className="size-4 *:size-full">{iconLeft}</span>}
      {children}
      {iconRight && <span className="size-4 *:size-full">{iconRight}</span>}
    </Comp>
  );
}
