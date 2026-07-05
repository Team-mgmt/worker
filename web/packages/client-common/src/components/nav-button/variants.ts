import { cva } from "class-variance-authority";

export const navButtonVariants = cva(
  "flex h-12 w-full items-center gap-3 pl-4 font-base text-button leading-paragraph [&_svg]:text-current",
  {
    variants: {
      active: {
        false: "rounded-card-sm text-primary-black font-regular",
        true: "rounded-nav bg-primary-1 text-primary-white font-bold",
      },
    },
    defaultVariants: {
      active: false,
    },
  },
);
