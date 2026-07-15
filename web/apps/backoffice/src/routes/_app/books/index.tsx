import { FormEvent, useEffect, useMemo, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";
import { ChevronLeftIcon, ChevronRightIcon, SearchIcon } from "lucide-react";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ky } from "@/lib/ky";
import { LIBRARIES } from "@/lib/libraries";

export const Route = createFileRoute("/_app/books/")({
  component: LibraryBooksPage,
});

type Holding = {
  id: string;
  callNumber: string | null;
  shelfLocName: string | null;
  copyCode: string | null;
  library: { code: string; name: string };
  book: {
    id: string;
    isbn13: string | null;
    bookname: string;
    authors: string | null;
    publisher: string | null;
    publicationYear: string | null;
  } | null;
};

type ListResponse = {
  result: boolean;
  data: Holding[];
  count: number;
  page: number;
  pageSize: number;
};

const PAGE_SIZE = 25;

function LibraryBooksPage() {
  const [libraryCode, setLibraryCode] = useState<string>(LIBRARIES[0].code);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [payload, setPayload] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    ky.get(`${import.meta.env.VITE_BASE_URL}/admin/library-books`, {
      searchParams: {
        libraryCode,
        query,
        page: page.toString(),
        pageSize: PAGE_SIZE.toString(),
      },
      signal: controller.signal,
    })
      .json<ListResponse>()
      .then(setPayload)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "조회에 실패했습니다.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [libraryCode, query, page]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((payload?.count ?? 0) / PAGE_SIZE)),
    [payload?.count],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setQuery(input.trim());
  };

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "도서 데이터셋" }]} />
      <div className="my-4 flex flex-col gap-1">
        <h2 className="text-xl font-extrabold">도서 데이터셋</h2>
        <p className="text-sm text-muted-foreground">
          도서관 소장 도서와 청구기호를 조회합니다.
        </p>
      </div>

      <form className="mb-4 flex flex-col gap-3 border bg-white p-4 md:flex-row md:items-end" onSubmit={submit}>
        <div className="w-full md:w-64">
          <Label className="mb-1.5 block">도서관</Label>
          <Select value={libraryCode} onValueChange={(value) => { setLibraryCode(value); setPage(1); }}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {LIBRARIES.map((library) => (
                <SelectItem key={library.code} value={library.code}>{library.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-0 flex-1">
          <Label htmlFor="book-search" className="mb-1.5 block">검색</Label>
          <Input id="book-search" value={input} onChange={(event) => setInput(event.target.value)} placeholder="제목, 저자, ISBN, 청구기호" />
        </div>
        <Button type="submit" disabled={loading}>
          <SearchIcon className="size-4" /> 검색
        </Button>
      </form>

      <div className="overflow-hidden border bg-white">
        <div className="flex items-center justify-between border-b px-4 py-3 text-sm">
          <span className="font-semibold">{loading ? "조회 중" : `총 ${(payload?.count ?? 0).toLocaleString()}건`}</span>
          {query ? <span className="text-muted-foreground">검색어: {query}</span> : null}
        </div>
        {error ? <div className="p-6 text-sm text-red-700">{error}</div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-zinc-50 text-xs text-muted-foreground">
                <tr><th className="px-4 py-3">도서</th><th className="px-4 py-3">저자</th><th className="px-4 py-3">청구기호</th><th className="px-4 py-3">자료실</th><th className="px-4 py-3">ISBN</th><th className="px-4 py-3">출판 정보</th></tr>
              </thead>
              <tbody className="divide-y">
                {(payload?.data ?? []).map((holding) => (
                  <tr key={holding.id} className="hover:bg-zinc-50">
                    <td className="max-w-80 px-4 py-3 font-medium">{holding.book?.bookname ?? "도서 정보 없음"}</td>
                    <td className="max-w-56 px-4 py-3 text-muted-foreground">{holding.book?.authors ?? "-"}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono">{holding.callNumber ?? "-"}</td>
                    <td className="px-4 py-3">{holding.shelfLocName ?? "-"}</td>
                    <td className="whitespace-nowrap px-4 py-3">{holding.book?.isbn13 ?? "-"}</td>
                    <td className="px-4 py-3 text-muted-foreground">{[holding.book?.publisher, holding.book?.publicationYear].filter(Boolean).join(" · ") || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !payload?.data.length ? <div className="p-8 text-center text-sm text-muted-foreground">조회된 도서가 없습니다.</div> : null}
          </div>
        )}
        <div className="flex items-center justify-between border-t px-4 py-3">
          <span className="text-sm text-muted-foreground">{page} / {totalPages} 페이지</span>
          <div className="flex gap-1">
            <Button type="button" variant="outline" size="icon" title="이전 페이지" disabled={loading || page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeftIcon className="size-4" /></Button>
            <Button type="button" variant="outline" size="icon" title="다음 페이지" disabled={loading || page >= totalPages} onClick={() => setPage((value) => value + 1)}><ChevronRightIcon className="size-4" /></Button>
          </div>
        </div>
      </div>
    </>
  );
}
