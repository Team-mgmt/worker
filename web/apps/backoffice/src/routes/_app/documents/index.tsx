import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";

import { FileTextIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { z } from "zod";

import { queries } from "@/queries";
import { formatBytes } from "@/routes/_app/documents/-lib/format";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const searchSchema = z.object({
  includeDeleted: z.boolean().optional().default(false),
});

export const Route = createFileRoute("/_app/documents/")({
  component: DocumentsPage,
  validateSearch: searchSchema,
});

function DocumentsPage() {
  const { includeDeleted } = Route.useSearch();
  const navigate = useNavigate();
  const { data: documents } = useSuspenseQuery(
    queries.document.list(includeDeleted),
  );

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "문서 관리" }]} />
      <div className="flex items-center justify-between my-3">
        <h2 className="font-extrabold text-xl">문서 관리</h2>
        <Button asChild>
          <Link to="/documents/create">
            <PlusIcon size={16} className="mr-1" />새 문서
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>S3 문서 목록</CardTitle>
          <Label className="flex items-center gap-2 text-sm font-normal cursor-pointer">
            <Checkbox
              checked={includeDeleted}
              onCheckedChange={(checked) =>
                navigate({
                  to: "/documents",
                  search: { includeDeleted: checked === true },
                })
              }
            />
            삭제된 문서 포함
          </Label>
        </CardHeader>
        <CardContent>
          {documents.length === 0 ? (
            <div className="text-center py-12 text-gray-500">
              <FileTextIcon className="mx-auto mb-2 size-8 opacity-50" />
              등록된 문서가 없습니다
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>슬러그</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>크기</TableHead>
                  <TableHead>최종 수정일</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.slug} className="relative">
                    <TableCell>
                      <Link
                        to="/documents/$slug"
                        params={{ slug: doc.slug }}
                        className="before:absolute before:inset-0 before:content-[''] font-mono"
                      >
                        {doc.slug}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {doc.isDeleted ? (
                        <Badge variant="destructive">
                          <Trash2Icon size={12} className="mr-1" />
                          삭제됨
                        </Badge>
                      ) : (
                        <Badge variant="secondary">활성</Badge>
                      )}
                    </TableCell>
                    <TableCell>{formatBytes(doc.size)}</TableCell>
                    <TableCell>
                      {doc.lastModified
                        ? new Date(doc.lastModified).toLocaleString()
                        : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
