import type { ComponentProps } from "react";

import { cn } from "@/utils";

type ToggleProps = {
  className?: string;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
} & Omit<ComponentProps<"button">, "className" | "onChange">;

export function Toggle({
  className,
  checked = false,
  onChange,
  ...rest
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={cn(
        "relative inline-flex h-6 w-[42px] shrink-0 cursor-pointer rounded-full transition-colors",
        checked ? "bg-primary-black" : "bg-grey-3",
        className,
      )}
      onClick={() => onChange?.(!checked)}
      {...rest}
    >
      <span
        className={cn(
          "pointer-events-none mt-[3px] inline-block size-[18px] rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-[21px]" : "translate-x-[3px]",
        )}
      />
    </button>
  );
}
