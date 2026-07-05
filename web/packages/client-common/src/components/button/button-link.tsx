import { createLink } from "@tanstack/react-router";
import type { VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { Button } from "./button";
import type { buttonVariants } from "./variants";

type AnchorButtonProps = Omit<ComponentProps<"a">, "children"> &
  VariantProps<typeof buttonVariants> & {
    iconLeft?: ReactNode;
    iconRight?: ReactNode;
    children?: ReactNode;
    className?: string;
  };

function AnchorButton(props: AnchorButtonProps) {
  return <Button as="a" {...props} />;
}

export const ButtonLink = createLink(AnchorButton);
