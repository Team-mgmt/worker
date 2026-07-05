import { createLink } from "@tanstack/react-router";
import type { VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { NavButton } from "./nav-button";
import type { navButtonVariants } from "./variants";

type AnchorNavButtonProps = Omit<ComponentProps<"a">, "children"> &
  VariantProps<typeof navButtonVariants> & {
    icon?: ReactNode;
    children?: ReactNode;
    className?: string;
  };

function AnchorNavButton(props: AnchorNavButtonProps) {
  return <NavButton as="a" {...props} />;
}

export const NavButtonLink = createLink(AnchorNavButton);
