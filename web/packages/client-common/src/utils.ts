import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: [
        "display",
        "heading-1",
        "heading-2",
        "heading-3",
        "heading-4",
        "heading-5",
        "paragraph",
        "captions",
        "link",
        "button",
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
