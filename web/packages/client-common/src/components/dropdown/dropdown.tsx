import { ChevronDownIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/utils";

import { dropdownItemVariants, dropdownTriggerVariants } from "./variants";

export type DropdownOption = {
  label: string;
  value: string;
  disabled?: boolean;
};

type DropdownProps = {
  className?: string;
  options: DropdownOption[];
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  direction?: "top" | "bottom";
};

export function Dropdown({
  className,
  options,
  value,
  onChange,
  placeholder = "Placeholder",
  disabled = false,
  direction = "bottom",
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selectedOption = options.find((o) => o.value === value);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const triggerState = disabled
    ? "disabled"
    : open
      ? "open"
      : selectedOption
        ? "selected"
        : "default";

  return (
    <div ref={ref} className={cn("relative w-full", className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className={cn(
          dropdownTriggerVariants({ state: triggerState }),
          !disabled &&
            !open &&
            !selectedOption &&
            "hover:bg-background hover:border-border-active",
        )}
      >
        <span className="min-w-0 flex-1 truncate">
          {selectedOption ? selectedOption.label : placeholder}
        </span>
        <ChevronDownIcon
          className={cn(
            "size-6 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div
          className={cn(
            "absolute left-0 right-0 z-50 mt-1 max-h-60 overflow-y-auto rounded-[4px] border border-border bg-white shadow-lg",
            direction === "top" && "bottom-full top-auto",
          )}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={option.disabled}
              onClick={() => {
                onChange?.(option.value);
                setOpen(false);
              }}
              className={dropdownItemVariants({
                selected: option.value === value,
                disabled: !!option.disabled,
              })}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
