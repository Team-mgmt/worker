import { cva } from "class-variance-authority";

export const chipVariants = cva(
  "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-pill px-3 py-2 text-button leading-paragraph font-regular text-center cursor-pointer transition-colors",
  {
    variants: {
      active: {
        true: "bg-primary-black text-primary-white",
        false: "bg-grey-4 text-primary-black",
      },
    },
    defaultVariants: {
      active: false,
    },
  },
);
