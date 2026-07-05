import type { ComponentProps } from "react";

import { cn } from "@/utils";

type TextInputProps = {
  className?: string;
} & Omit<ComponentProps<"input">, "className">;

export function TextInput({ className, ...rest }: TextInputProps) {
  return (
    <input
      className={cn(
        "h-10 w-full max-w-[800px] min-w-[80px] rounded-[4px] border px-4 py-2 text-paragraph leading-paragraph font-regular transition-colors outline-none",
        "bg-grey-5 border-border text-grey-2 placeholder:text-grey-2",
        "hover:bg-background hover:border-border-active",
        "focus:bg-background focus:border-border-active focus:text-primary-black",
        "disabled:bg-surface disabled:border-border disabled:opacity-30",
        className,
      )}
      {...rest}
    />
  );
}
