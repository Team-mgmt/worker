import { Loader2Icon, SparklesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

interface AIGenerateButtonProps {
  onClick: () => void;
  isLoading: boolean;
  disabled?: boolean;
  label?: string;
}

export function AIGenerateButton({
  onClick,
  isLoading,
  disabled = false,
  label = "AI 생성",
}: AIGenerateButtonProps) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onClick}
      disabled={disabled || isLoading}
    >
      {isLoading ? (
        <>
          <Loader2Icon className="mr-1 h-4 w-4 animate-spin" />
          생성 중...
        </>
      ) : (
        <>
          <SparklesIcon className="mr-1 h-4 w-4" />
          {label}
        </>
      )}
    </Button>
  );
}
