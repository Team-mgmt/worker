import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { HistoryIcon, RotateCcwIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminDeleteDocumentResponseSchema,
  AdminRestoreDocumentVersionResponseSchema,
} from "@shelfalign/schema/dtos/admin/document";

import { ky } from "@/lib/ky";

import { queries } from "@/queries";
import { DocumentEditorPanel } from "@/routes/_app/documents/$slug/-components/DocumentEditorPanel";
import { VersionHistorySidebar } from "@/routes/_app/documents/$slug/-components/VersionHistorySidebar";

import { Breadcrumb } from "@/components/Breadcrumb";
import { TiptapEditor } from "@/components/TiptapEditor";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const searchSchema = z.object({
  versionId: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/_app/documents/$slug/")({
  component: DocumentDetailPage,
  validateSearch: searchSchema,
});

function DocumentDetailPage() {
  const { slug } = Route.useParams();
  const { versionId } = Route.useSearch();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const isViewingVersion = Boolean(versionId);
  const { data: document } = useSuspenseQuery(
    queries.document.get(slug, versionId),
  );

  const deleteMutation = useMutation({
    mutationFn: async () => {
      const res = await ky.delete(
        `${import.meta.env.VITE_BASE_URL}/admin/documents/${slug}`,
      );
      const response = await tryJson(
        await res.text(),
        AdminDeleteDocumentResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("문서가 삭제되었습니다");
      queryClient.invalidateQueries({ queryKey: queries.document._def });
      navigate({ to: "/documents" });
    },
  });

  const restoreMutation = useMutation({
    mutationFn: async (targetVersionId: string) => {
      const res = await ky.post(
        `${import.meta.env.VITE_BASE_URL}/admin/documents/${slug}/restore`,
        { json: { versionId: targetVersionId } },
      );
      const response = await tryJson(
        await res.text(),
        AdminRestoreDocumentVersionResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("이전 버전으로 복원되었습니다");
      queryClient.invalidateQueries({ queryKey: queries.document._def });
      navigate({ to: "/documents/$slug", params: { slug }, search: {} });
    },
  });

  return (
    <>
      <Breadcrumb
        items={[
          { type: "link", label: "문서 관리", to: "/documents" },
          { type: "text", label: slug },
        ]}
      />

      <div className="flex items-center justify-between my-3 gap-2">
        <div className="flex items-center gap-2">
          <h2 className="font-extrabold text-xl font-mono">{slug}</h2>
          {document.isDeleted && (
            <Badge variant="destructive">
              <Trash2Icon size={12} className="mr-1" />
              삭제됨
            </Badge>
          )}
          {isViewingVersion && (
            <Badge variant="outline">
              <HistoryIcon size={12} className="mr-1" />
              과거 버전
            </Badge>
          )}
        </div>

        <div className="flex gap-2">
          {isViewingVersion ? (
            <>
              <Button
                variant="outline"
                onClick={() =>
                  navigate({
                    to: "/documents/$slug",
                    params: { slug },
                    search: {},
                  })
                }
              >
                최신 버전으로
              </Button>
              {versionId && !document.isDeleted && (
                <Button
                  onClick={() => restoreMutation.mutate(versionId)}
                  disabled={restoreMutation.isPending}
                >
                  <RotateCcwIcon size={16} className="mr-1" />
                  {restoreMutation.isPending
                    ? "복원 중..."
                    : "이 버전으로 복원"}
                </Button>
              )}
            </>
          ) : (
            !document.isDeleted && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="destructive">
                    <Trash2Icon size={16} className="mr-1" />
                    삭제
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>문서 삭제</AlertDialogTitle>
                    <AlertDialogDescription>
                      문서를 삭제하시겠습니까? S3 객체 버전 관리가 활성화되어
                      있어 이전 버전을 통해 복원할 수 있습니다.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>취소</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={() => deleteMutation.mutate()}
                      className="bg-destructive text-white hover:bg-destructive/90"
                    >
                      삭제
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4">
        <Card>
          <CardHeader>
            <CardTitle>
              {isViewingVersion ? "과거 버전 미리보기" : "내용"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {document.isDeleted && document.content === null ? (
              <div className="text-center py-12 text-muted-foreground">
                이 버전은 삭제 마커입니다. 본문이 없습니다.
              </div>
            ) : isViewingVersion ? (
              <TiptapEditor
                key={`${slug}:${document.versionId ?? "preview"}`}
                content={document.content ?? undefined}
                editable={false}
              />
            ) : (
              <DocumentEditorPanel
                key={`${slug}:${document.lastModified ?? "init"}`}
                slug={slug}
                initialContent={document.content ?? undefined}
              />
            )}
          </CardContent>
        </Card>

        <VersionHistorySidebar slug={slug} activeVersionId={versionId} />
      </div>
    </>
  );
}
