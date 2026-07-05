import { useRef, useState } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";

import type { Editor } from "@tiptap/react";
import { toast } from "sonner";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminCreateDocumentResponseSchema,
  DocumentSlugSchema,
} from "@shelfalign/schema/dtos/admin/document";

import { ky } from "@/lib/ky";

import { queries } from "@/queries";

import { Breadcrumb } from "@/components/Breadcrumb";
import { TiptapEditor } from "@/components/TiptapEditor";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export const Route = createFileRoute("/_app/documents/create/")({
  component: CreateDocumentPage,
});

function CreateDocumentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editorRef = useRef<Editor | null>(null);
  const [slug, setSlug] = useState("");
  const [slugError, setSlugError] = useState<string | null>(null);

  const { mutate, isPending } = useMutation({
    mutationFn: async () => {
      const editor = editorRef.current;
      if (!editor) throw new Error("Editor not ready");

      const parsedSlug = DocumentSlugSchema.safeParse(slug);
      if (!parsedSlug.success) {
        const message =
          parsedSlug.error.issues[0]?.message ?? "올바르지 않은 슬러그입니다.";
        setSlugError(message);
        throw new Error(message);
      }
      setSlugError(null);

      const content = editor.getJSON();
      const res = await ky.post(
        `${import.meta.env.VITE_BASE_URL}/admin/documents`,
        { json: { slug: parsedSlug.data, content } },
      );
      const response = await tryJson(
        await res.text(),
        AdminCreateDocumentResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: (data) => {
      toast.success("문서가 생성되었습니다");
      queryClient.invalidateQueries({ queryKey: queries.document._def });
      navigate({
        to: "/documents/$slug",
        params: { slug: data.data.slug },
      });
    },
  });

  return (
    <>
      <Breadcrumb
        items={[
          { type: "link", label: "문서 관리", to: "/documents" },
          { type: "text", label: "새 문서" },
        ]}
      />
      <h2 className="font-extrabold text-xl my-3">새 문서</h2>

      <Card>
        <CardHeader>
          <CardTitle>문서 정보</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="slug">슬러그</Label>
            <Input
              id="slug"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                if (slugError) setSlugError(null);
              }}
              placeholder="예: terms-of-service"
              autoComplete="off"
              className="font-mono"
            />
            <p className="text-xs text-muted-foreground">
              영문, 숫자, 하이픈, 언더스코어만 사용할 수 있습니다.
              <span className="ml-1 font-mono">
                docs/&lt;슬러그&gt;.json
              </span>{" "}
              경로로 저장됩니다.
            </p>
            {slugError && (
              <p className="text-xs text-destructive">{slugError}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label>내용</Label>
            <TiptapEditor
              editorRef={editorRef}
              placeholder="문서 내용을 입력하세요"
            />
          </div>

          <div className="flex gap-2 justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate({ to: "/documents" })}
            >
              취소
            </Button>
            <Button
              type="button"
              disabled={isPending || slug.length === 0}
              onClick={() => mutate()}
            >
              {isPending ? "생성 중..." : "생성"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
