import { SearchIcon, XIcon } from "lucide-react";
import { type ComponentProps, useState } from "react";

import { cn } from "@/utils";

type SearchBarProps = {
  className?: string;
  value?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onClear?: () => void;
} & Omit<ComponentProps<"input">, "className" | "type">;

export function SearchBar({
  className,
  value,
  onChange,
  onClear,
  ...rest
}: SearchBarProps) {
  const [internalValue, setInternalValue] = useState("");
  const isControlled = value !== undefined;
  const currentValue = isControlled ? value : internalValue;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!isControlled) setInternalValue(e.target.value);
    onChange?.(e);
  };

  const handleClear = () => {
    if (!isControlled) setInternalValue("");
    onClear?.();
  };

  return (
    <div
      className={cn(
        "group relative w-full max-w-[800px] min-w-[240px]",
        className,
      )}
    >
      <SearchIcon className="absolute left-3 top-1/2 size-5 -translate-y-1/2 text-grey-2 transition-colors group-focus-within:text-primary-1" />
      <input
        type="search"
        value={currentValue}
        onChange={handleChange}
        className={cn(
          "h-[42px] w-full rounded-[4px] border py-3 pl-10 pr-4 text-paragraph leading-paragraph font-regular transition-colors outline-none",
          "border-border bg-grey-5 text-grey-2 placeholder:text-grey-2",
          "hover:border-border-active hover:bg-background",
          "focus:border-primary-1 focus:bg-background focus:text-primary-black",
          "disabled:border-border disabled:bg-surface disabled:opacity-30",
          "[&::-webkit-search-cancel-button]:hidden",
        )}
        {...rest}
      />
      {currentValue && (
        <button
          type="button"
          onClick={handleClear}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-grey-2 transition-colors hover:text-primary-black"
        >
          <XIcon className="size-4" />
        </button>
      )}
    </div>
  );
}
