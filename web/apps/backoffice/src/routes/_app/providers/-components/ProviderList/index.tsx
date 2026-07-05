import { useSuspenseQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { queries } from "@/queries";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { ProviderRow } from "./row";

type Props = {
  page: number;
};

export function ProviderList({ page }: Props) {
  const navigate = useNavigate();
  const { data } = useSuspenseQuery(queries.provider.list(page));

  const pageSize = 10;
  const lastPage = Math.max(Math.ceil(data.count / pageSize), 1);

  const handlePageChange = (newPage: number) => {
    navigate({
      to: "/providers",
      search: { page: newPage },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          인증 관리{" "}
          <span className="text-sm text-muted-foreground font-normal">
            (총 {data.count}개)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead className="w-32">생성일</TableHead>
              <TableHead className="w-24 text-right">작업</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.data.map((provider) => (
              <ProviderRow key={provider.id} provider={provider} />
            ))}
            {data.data.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="text-center text-muted-foreground py-8"
                >
                  인증 제공자가 없습니다
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        {lastPage > 1 && (
          <div className="flex justify-center gap-2 mt-6">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => handlePageChange(page - 1)}
            >
              이전
            </Button>
            <span className="flex items-center px-3 text-sm text-muted-foreground">
              {page} / {lastPage}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= lastPage}
              onClick={() => handlePageChange(page + 1)}
            >
              다음
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
