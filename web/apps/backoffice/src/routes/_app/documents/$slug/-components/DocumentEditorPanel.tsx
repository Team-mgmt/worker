import { useRef, useState } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { Editor } from "@tiptap/react";
import { SaveIcon } from "lucide-react";
import { toast } from "sonner";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import { AdminUpdateDocumentResponseSchema } from "@shelfalign/schema/dtos/admin/document";

import { ky } from "@/lib/ky";

import { queries } from "@/queries";

import { TiptapEditor } from "@/components/TiptapEditor";
import { Button } from "@/components/ui/button";

interface DocumentEditorPanelProps {
  slug: string;
  initialContent?: unknown;
}

export function DocumentEditorPanel({
  slug,
  initialContent,
}: DocumentEditorPanelProps) {
  const queryClient = useQueryClient();
  const editorRef = useRef<Editor | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const updateMutation = useMutation({
    mutationFn: async () => {
      const editor = editorRef.current;
      if (!editor) throw new Error("Editor not ready");
      const content = editor.getJSON();
      const res = await ky.patch(
        `${import.meta.env.VITE_BASE_URL}/admin/documents/${slug}`,
        { json: { content } },
      );
      const response = await tryJson(
        await res.text(),
        AdminUpdateDocumentResponseSchema,
      );
      return toastParseError(res, response);
    },
    onSuccess: () => {
      toast.success("문서가 저장되었습니다");
      queryClient.invalidateQueries({ queryKey: queries.document._def });
      setHasChanges(false);
    },
  });

  return (
    <div className="space-y-3">
      <TiptapEditor
        content={initialContent}
        editorRef={editorRef}
        onUpdate={() => setHasChanges(true)}
      />
      <div className="flex justify-end">
        <Button
          onClick={() => updateMutation.mutate()}
          disabled={!hasChanges || updateMutation.isPending}
        >
          <SaveIcon size={16} className="mr-1" />
          {updateMutation.isPending ? "저장 중..." : "저장"}
        </Button>
      </div>
    </div>
  );
}
