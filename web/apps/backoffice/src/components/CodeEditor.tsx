import Editor from "@monaco-editor/react";

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  language: "javascript" | "python";
  height?: string;
  readOnly?: boolean;
  placeholder?: string;
}

export function CodeEditor({
  value,
  onChange,
  language,
  height = "150px",
  readOnly = false,
}: CodeEditorProps) {
  return (
    <div className="border rounded-md overflow-hidden">
      <Editor
        height={height}
        language={language}
        theme="vs-dark"
        value={value}
        onChange={(newValue: string | undefined) => onChange(newValue ?? "")}
        options={{
          minimap: { enabled: false },
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          fontSize: 14,
          readOnly,
          tabSize: language === "python" ? 4 : 2,
          insertSpaces: true,
          wordWrap: "on",
        }}
      />
    </div>
  );
}
