import type { ComponentProps } from "react";

import { cn } from "@/utils";

export function Table({ className, ...rest }: ComponentProps<"table">) {
  return (
    <div className="overflow-x-auto rounded-[8px] border border-border">
      <table
        className={cn("w-full border-collapse whitespace-nowrap", className)}
        {...rest}
      />
    </div>
  );
}

export function TableHeader({ className, ...rest }: ComponentProps<"thead">) {
  return <thead className={cn("bg-grey-5", className)} {...rest} />;
}

export function TableBody({ className, ...rest }: ComponentProps<"tbody">) {
  return (
    <tbody
      className={cn(
        "[&_tr]:border-b [&_tr]:border-border [&_tr:last-child]:border-0",
        className,
      )}
      {...rest}
    />
  );
}

export function TableRow({ className, ...rest }: ComponentProps<"tr">) {
  return <tr className={cn("", className)} {...rest} />;
}

export function TableHeaderCell({ className, ...rest }: ComponentProps<"th">) {
  return (
    <th
      className={cn(
        "h-14 min-w-[80px] px-6 py-2 text-left text-paragraph leading-paragraph font-bold text-primary-black",
        className,
      )}
      {...rest}
    />
  );
}

export function TableCell({ className, ...rest }: ComponentProps<"td">) {
  return (
    <td
      className={cn(
        "h-14 min-w-[80px] bg-background px-6 py-2 text-paragraph leading-paragraph font-regular text-primary-black",
        className,
      )}
      {...rest}
    />
  );
}
