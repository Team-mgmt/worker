import { cn } from "@/utils";

type SegmentedToggleOption<TValue extends string> = {
  value: TValue;
  label: string;
};

type SegmentedToggleProps<TValue extends string> = {
  value: TValue;
  options: ReadonlyArray<SegmentedToggleOption<TValue>>;
  onChange: (value: TValue) => void;
  className?: string;
};

export function SegmentedToggle<TValue extends string>({
  value,
  options,
  onChange,
  className,
}: SegmentedToggleProps<TValue>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-start gap-0 rounded-[4px] bg-grey-5 p-[6px]",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[2px] px-2 py-[6px] text-[14px] leading-[18px] font-bold transition-colors",
              active
                ? "bg-background text-primary-black shadow-[0_1px_3px_0_rgba(0,0,0,0.1),0_1px_2px_0_rgba(0,0,0,0.1)]"
                : "text-grey-2 hover:text-primary-black",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
