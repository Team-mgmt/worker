import z from "zod";

// Inner nodes (attrs, marks, nested content) are passed through as opaque JSON.
// Tiptap is the source of truth for node validity, and Zod's z.json() rejects
// `undefined` values that some Tiptap node attrs include.
export const TiptapContentSchema = z
  .object({
    type: z.string().min(1),
    content: z.array(z.unknown()).optional(),
    text: z.string().optional(),
  })
  .catchall(z.unknown());

export const NonEmptyTiptapContentSchema = TiptapContentSchema;

export type TiptapContent = z.infer<typeof TiptapContentSchema>;
