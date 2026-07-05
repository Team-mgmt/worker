import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
} from "lucide-react";

import { cn } from "@/utils";

type PaginationProps = {
  className?: string;
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  maxVisiblePages?: number;
};

function getPageNumbers(
  currentPage: number,
  totalPages: number,
  maxVisible: number,
) {
  const pages: (number | "ellipsis")[] = [];

  if (totalPages <= maxVisible) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
    return pages;
  }

  const half = Math.floor(maxVisible / 2);
  let start = Math.max(1, currentPage - half);
  const end = Math.min(totalPages, start + maxVisible - 1);

  if (end - start + 1 < maxVisible) {
    start = Math.max(1, end - maxVisible + 1);
  }

  if (start > 1) {
    pages.push(1);
    if (start > 2) pages.push("ellipsis");
  }

  for (let i = start; i <= end; i++) {
    if (!pages.includes(i)) pages.push(i);
  }

  if (end < totalPages) {
    if (end < totalPages - 1) pages.push("ellipsis");
    pages.push(totalPages);
  }

  return pages;
}

const navButtonClass =
  "flex items-center justify-center size-8 rounded-full bg-primary-white border border-border cursor-pointer transition-colors hover:bg-grey-4 disabled:opacity-30 disabled:cursor-not-allowed";

export function Pagination({
  className,
  currentPage,
  totalPages,
  onPageChange,
  maxVisiblePages = 5,
}: PaginationProps) {
  const pageNumbers = getPageNumbers(currentPage, totalPages, maxVisiblePages);

  return (
    <nav
      className={cn(
        "flex items-center justify-center gap-3 px-4 pt-4 pb-6",
        className,
      )}
    >
      <button
        className={navButtonClass}
        onClick={() => onPageChange(1)}
        disabled={currentPage === 1}
      >
        <ChevronsLeftIcon className="size-4" />
      </button>
      <button
        className={navButtonClass}
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage === 1}
      >
        <ChevronLeftIcon className="size-4" />
      </button>

      {pageNumbers.map((page, i) =>
        page === "ellipsis" ? (
          <span
            key={`ellipsis-${i}`}
            className="flex items-center justify-center size-8 rounded-full bg-primary-white text-primary-black text-[12px]"
          >
            ...
          </span>
        ) : (
          <button
            key={page}
            onClick={() => onPageChange(page)}
            className={cn(
              "flex items-center justify-center size-8 rounded-full text-[12px] cursor-pointer transition-colors",
              page === currentPage
                ? "bg-primary-black text-primary-white"
                : "border border-border bg-primary-white text-primary-black hover:bg-grey-4",
            )}
          >
            {page}
          </button>
        ),
      )}

      <button
        className={navButtonClass}
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage === totalPages}
      >
        <ChevronRightIcon className="size-4" />
      </button>
      <button
        className={navButtonClass}
        onClick={() => onPageChange(totalPages)}
        disabled={currentPage === totalPages}
      >
        <ChevronsRightIcon className="size-4" />
      </button>
    </nav>
  );
}
