import { Link, useNavigate } from "@tanstack/react-router";

import { ChevronDownIcon, LogOutIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

export function Header() {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("organization");
    void navigate({ to: "/auth/signin", replace: true });
  };

  return (
    <header className="flex h-16 w-full items-center justify-between overflow-visible pt-4">
      <div className="flex items-center gap-6">
        <Link
          to="/"
          className="h-12 font-mono text-2xl font-semibold leading-11"
        >
          ShelfAlign
        </Link>
        <nav className="hidden items-center gap-4 text-sm font-medium md:flex">
          <Link to="/books" activeProps={{ className: "font-bold" }}>
            도서 데이터셋
          </Link>
          <Link to="/shelf-ops" activeProps={{ className: "font-bold" }}>
            서가 검수
          </Link>
          <Link to="/video-analysis" activeProps={{ className: "font-bold" }}>
            동영상 분석
          </Link>
          <Link to="/evaluation" activeProps={{ className: "font-bold" }}>
            GT 라벨 검수
          </Link>
        </nav>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="relative flex items-center outline-none"
          aria-label="사용자 메뉴 열기"
        >
          <p className="hidden sm:block">
            안녕하세요, <span className="font-bold">관리자</span>님
          </p>
          <ChevronDownIcon className="mb-1 ml-2 size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem className="block sm:hidden">
            안녕하세요, <span className="font-bold">관리자</span>님
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={handleLogout}>
            <LogOutIcon className="size-4" />
            로그아웃
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
