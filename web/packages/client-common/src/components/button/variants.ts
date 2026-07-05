import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-pill px-4.5 text-button leading-paragraph transition-all disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 cursor-pointer",
  {
    variants: {
      variant: {
        primary:
          "bg-primary-black text-primary-white font-bold hover:bg-primary-2 disabled:bg-grey-4 disabled:text-primary-black",
        secondary:
          "bg-background border-primary-1 text-primary-1 font-bold hover:bg-primary-5 disabled:opacity-30",
        ghost:
          "bg-background border-border text-primary-black font-regular hover:bg-grey-4 hover:border-border-active disabled:opacity-30",
        tertiary:
          "bg-grey-4 text-primary-black font-regular hover:bg-grey-3 disabled:opacity-30",
      },
      size: {
        lg: "py-3",
        sm: "py-1.5",
      },
    },
    compoundVariants: [
      {
        variant: ["secondary", "ghost"],
        size: "lg",
        className: "border-[1.75px]",
      },
      {
        variant: ["secondary", "ghost"],
        size: "sm",
        className: "border-[1.2px]",
      },
    ],
    defaultVariants: {
      variant: "primary",
      size: "lg",
    },
  },
);
