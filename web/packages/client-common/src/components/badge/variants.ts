import { cva } from "class-variance-authority";

export const badgeVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1 rounded-[2px] text-paragraph leading-[20px] tracking-[0.17px] font-regular [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      size: {
        lg: "px-3 py-1",
        sm: "px-2 py-0.5",
      },
      variant: {
        default: "bg-grey-4 text-primary-black",
        primary: "text-headline border border-headline",
        danger: "text-accent-red border border-accent-red",
        success: "text-accent-green border border-accent-green",
      },
    },
    defaultVariants: {
      size: "lg",
      variant: "default",
    },
  },
);
