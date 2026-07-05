import { createLink } from "@tanstack/react-router";
import type { VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { Chip } from "./chip";
import type { chipVariants } from "./variants";

type AnchorChipProps = Omit<ComponentProps<"a">, "children"> &
  VariantProps<typeof chipVariants> & {
    children?: ReactNode;
    className?: string;
  };

function AnchorChip(props: AnchorChipProps) {
  return <Chip as="a" {...props} />;
}

export const ChipLink = createLink(AnchorChip);
