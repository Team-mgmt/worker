import Placeholder from "@tiptap/extension-placeholder";
import { TableKit } from "@tiptap/extension-table";
import { type Editor, EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  BetweenHorizontalStartIcon,
  BetweenVerticalStartIcon,
  BoldIcon,
  Heading2Icon,
  Heading3Icon,
  ItalicIcon,
  ListIcon,
  ListOrderedIcon,
  Quote,
  RowsIcon,
  StrikethroughIcon,
  TableIcon,
  Trash2Icon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { Button } from "@/components/ui/button";

interface TiptapEditorProps {
  content?: unknown;
  onUpdate?: (editor: Editor) => void;
  editorRef?: { current: Editor | null };
  placeholder?: string;
  editable?: boolean;
  className?: string;
}

export function TiptapEditor({
  content,
  onUpdate,
  editorRef,
  placeholder = "내용을 입력하세요...",
  editable = true,
  className,
}: TiptapEditorProps) {
  type EditorContentValue = NonNullable<
    Parameters<typeof useEditor>[0]
  >["content"];

  const editor = useEditor({
    extensions: [StarterKit, TableKit, Placeholder.configure({ placeholder })],
    content: (content ?? "") as EditorContentValue,
    editable,
    onCreate: ({ editor: e }) => {
      if (editorRef) {
        editorRef.current = e;
      }
    },
    onUpdate: ({ editor: e }) => {
      onUpdate?.(e);
    },
    onDestroy: () => {
      if (editorRef) {
        editorRef.current = null;
      }
    },
  });

  if (!editor) return null;

  return (
    <div
      className={cn(
        "rounded-md border border-input bg-background",
        !editable && "bg-muted/30",
        className,
      )}
    >
      {editable && (
        <div className="flex flex-wrap items-center gap-1 border-b border-input p-1">
          <ToolbarButton
            active={editor.isActive("bold")}
            onClick={() => editor.chain().focus().toggleBold().run()}
            label="굵게"
          >
            <BoldIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("italic")}
            onClick={() => editor.chain().focus().toggleItalic().run()}
            label="기울임"
          >
            <ItalicIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("strike")}
            onClick={() => editor.chain().focus().toggleStrike().run()}
            label="취소선"
          >
            <StrikethroughIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("heading", { level: 2 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
            label="제목 2"
          >
            <Heading2Icon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("heading", { level: 3 })}
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 3 }).run()
            }
            label="제목 3"
          >
            <Heading3Icon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("bulletList")}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            label="목록"
          >
            <ListIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("orderedList")}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            label="번호 목록"
          >
            <ListOrderedIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("blockquote")}
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
            label="인용"
          >
            <Quote className="size-4" />
          </ToolbarButton>
          <TableToolbarButtons editor={editor} />
        </div>
      )}

      <EditorContent
        editor={editor}
        className="prose prose-sm max-w-none p-3 min-h-[240px] focus-within:outline-none [&_.tiptap]:outline-none [&_.tiptap.ProseMirror_p.is-editor-empty:first-child::before]:text-muted-foreground [&_.tiptap.ProseMirror_p.is-editor-empty:first-child::before]:content-[attr(data-placeholder)] [&_.tiptap.ProseMirror_p.is-editor-empty:first-child::before]:float-left [&_.tiptap.ProseMirror_p.is-editor-empty:first-child::before]:h-0 [&_.tiptap.ProseMirror_p.is-editor-empty:first-child::before]:pointer-events-none"
      />
    </div>
  );
}

interface ToolbarButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}

function ToolbarButton({
  active,
  onClick,
  label,
  children,
}: ToolbarButtonProps) {
  return (
    <Button
      type="button"
      size="sm"
      variant={active ? "secondary" : "ghost"}
      onClick={onClick}
      title={label}
      aria-label={label}
      className="h-8 w-8 p-0"
    >
      {children}
    </Button>
  );
}

function TableToolbarButtons({ editor }: { editor: Editor }) {
  const inTable = editor.isActive("table");

  return (
    <>
      <ToolbarButton
        active={false}
        onClick={() =>
          editor
            .chain()
            .focus()
            .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
            .run()
        }
        label="표 삽입"
      >
        <TableIcon className="size-4" />
      </ToolbarButton>
      {inTable && (
        <>
          <ToolbarButton
            active={false}
            onClick={() => editor.chain().focus().addRowAfter().run()}
            label="행 추가"
          >
            <BetweenHorizontalStartIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={false}
            onClick={() => editor.chain().focus().addColumnAfter().run()}
            label="열 추가"
          >
            <BetweenVerticalStartIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={false}
            onClick={() => editor.chain().focus().deleteRow().run()}
            label="행 삭제"
          >
            <RowsIcon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={false}
            onClick={() => editor.chain().focus().deleteColumn().run()}
            label="열 삭제"
          >
            <Trash2Icon className="size-4" />
          </ToolbarButton>
          <ToolbarButton
            active={false}
            onClick={() => editor.chain().focus().deleteTable().run()}
            label="표 삭제"
          >
            <Trash2Icon className="size-4 text-destructive" />
          </ToolbarButton>
        </>
      )}
    </>
  );
}
