import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { ChevronDownIcon } from "lucide-react";

import { queries } from "@/queries";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

export function Header() {
  const { data: session } = useSuspenseQuery(queries.auth.session);
  const displayName = session.membership[0]?.name || "관리자";

  return (
    <header className="w-full h-16 flex justify-between items-center overflow-visible pt-4">
      <Link to="/" className="font-semibold font-mono text-2xl leading-11 h-12">
        ShelfAlign
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex items-center relative outline-none"
          aria-label="메뉴 열기"
        >
          <p className="hidden sm:block">
            안녕하세요, <span className="font-bold">{displayName}</span>님
          </p>
          <ChevronDownIcon className="ml-2 w-4 h-4 mb-1" />
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem className="block sm:hidden">
            안녕하세요, <span className="font-bold">{displayName}</span>님
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
