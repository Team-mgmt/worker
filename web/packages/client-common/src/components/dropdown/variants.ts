import { cva } from "class-variance-authority";

export const dropdownTriggerVariants = cva(
  "flex w-full items-center gap-2 rounded-[4px] border px-4 py-2 text-left text-paragraph leading-paragraph font-regular transition-colors",
  {
    variants: {
      state: {
        default: "bg-grey-5 border-border text-grey-2",
        open: "bg-background border-primary-1",
        selected: "bg-background border-border-active text-primary-black",
        disabled: "bg-background border-border opacity-30 cursor-not-allowed",
      },
    },
    defaultVariants: {
      state: "default",
    },
  },
);

export const dropdownItemVariants = cva(
  "flex w-full items-center p-3 text-paragraph leading-paragraph font-regular text-primary-black transition-colors",
  {
    variants: {
      selected: {
        true: "bg-primary-5",
        false: "hover:bg-grey-5",
      },
      disabled: {
        true: "opacity-30 text-grey-2 cursor-not-allowed",
        false: "",
      },
    },
    defaultVariants: {
      selected: false,
      disabled: false,
    },
  },
);
