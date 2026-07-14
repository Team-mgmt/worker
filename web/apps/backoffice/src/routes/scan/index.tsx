import { useMemo, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";

import {
  CameraIcon,
  ImagesIcon,
  Loader2Icon,
  RotateCcwIcon,
  SearchCheckIcon,
} from "lucide-react";

import { LIBRARIES } from "@/lib/libraries";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/scan/")({
  component: ScanPage,
});

type WorkerDetection = {
  detected_order: number;
  bbox?: number[] | null;
  ocr_raw_text?: string | null;
  ocr_title?: string | null;
  ocr_author?: string | null;
  ocr_call_number?: string | null;
  matched_book?: string | null;
  matched_call_number?: string | null;
  match_score?: number | null;
  decision: string;
  reason?: string | null;
};

type WorkerResponse = {
  results: WorkerDetection[];
};

type ScanResult = {
  order: number;
  bbox: { x: number; y: number; width: number; height: number };
  title: string;
  author: string;
  callNumber: string;
  score: number;
  decision: string;
  reason: string;
};

const DECISION_META: Record<
  string,
  { label: string; badge: string; marker: string }
> = {
  normal: {
    label: "정상",
    badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
    marker: "border-emerald-400 bg-emerald-400/10",
  },
  suspected_misplacement: {
    label: "오배열 의심",
    badge: "border-red-200 bg-red-50 text-red-700",
    marker: "border-red-500 bg-red-500/15",
  },
  needs_review: {
    label: "확인 필요",
    badge: "border-amber-200 bg-amber-50 text-amber-700",
    marker: "border-amber-400 bg-amber-400/10",
  },
  unmatched: {
    label: "인식 실패",
    badge: "border-zinc-300 bg-zinc-100 text-zinc-700",
    marker: "border-zinc-400 bg-zinc-400/10",
  },
};

function getDecisionMeta(decision: string) {
  return DECISION_META[decision] ?? DECISION_META.unmatched;
}

function readImage(file: File) {
  return new Promise<{
    dataUrl: string;
    width: number;
    height: number;
  }>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("error", () =>
      reject(new Error("이미지를 읽지 못했습니다.")),
    );
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        reject(new Error("이미지를 읽지 못했습니다."));
        return;
      }

      const image = new Image();
      image.addEventListener("error", () =>
        reject(new Error("이미지를 열지 못했습니다.")),
      );
      image.addEventListener("load", () =>
        resolve({
          dataUrl: reader.result as string,
          width: image.naturalWidth,
          height: image.naturalHeight,
        }),
      );
      image.src = reader.result;
    });
    reader.readAsDataURL(file);
  });
}

function mapResults(
  response: WorkerResponse,
  imageSize: { width: number; height: number },
): ScanResult[] {
  return response.results.map((result) => {
    const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = result.bbox ?? [];
    return {
      order: result.detected_order,
      bbox: {
        x: (x1 / imageSize.width) * 100,
        y: (y1 / imageSize.height) * 100,
        width: ((x2 - x1) / imageSize.width) * 100,
        height: ((y2 - y1) / imageSize.height) * 100,
      },
      title: result.matched_book || result.ocr_title || "도서 확인 필요",
      author: result.ocr_author || "",
      callNumber: result.matched_call_number || result.ocr_call_number || "-",
      score: result.match_score ?? 0,
      decision: result.decision,
      reason: result.reason || "",
    };
  });
}

function ScanPage() {
  const [libraryCode, setLibraryCode] = useState("111189");
  const [preview, setPreview] = useState<string | null>(null);
  const [results, setResults] = useState<ScanResult[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const library =
    LIBRARIES.find((item) => item.code === libraryCode) ?? LIBRARIES[0];
  const counts = useMemo(
    () => ({
      total: results.length,
      normal: results.filter((item) => item.decision === "normal").length,
      misplaced: results.filter(
        (item) => item.decision === "suspected_misplacement",
      ).length,
      review: results.filter(
        (item) =>
          item.decision !== "normal" &&
          item.decision !== "suspected_misplacement",
      ).length,
    }),
    [results],
  );

  const analyzeFile = async (file: File) => {
    setError(null);
    setResults([]);
    setIsAnalyzing(true);

    try {
      const image = await readImage(file);
      setPreview(image.dataUrl);

      const formData = new FormData();
      formData.set("file", file);

      const workerBaseUrl =
        import.meta.env.VITE_WORKER_BASE_URL ??
        (import.meta.env.DEV ? "http://localhost:8000" : "/worker");
      const workerUrl = new URL(
        `${workerBaseUrl}/inference/analyze_vision`,
        window.location.origin,
      );
      workerUrl.searchParams.set("library_code", library.code);
      workerUrl.searchParams.set("room_name", library.roomName);

      const response = await fetch(workerUrl, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `분석 요청 실패: ${response.status}`);
      }

      const payload = (await response.json()) as WorkerResponse;
      setResults(mapResults(payload, image));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "분석 중 오류가 발생했습니다.",
      );
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) {
      void analyzeFile(file);
    }
  };

  const reset = () => {
    setPreview(null);
    setResults([]);
    setError(null);
  };

  return (
    <div className="min-h-dvh w-full bg-zinc-100 text-zinc-950">
      <header className="border-b bg-white">
        <div className="mx-auto flex min-h-16 max-w-2xl items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="text-lg font-bold">ShelfAlign Scan</h1>
            <p className="text-xs text-zinc-500">{library.name}</p>
          </div>
          <Select
            value={libraryCode}
            onValueChange={(value) => {
              setLibraryCode(value);
              reset();
            }}
            disabled={isAnalyzing}
          >
            <SelectTrigger className="w-[180px] bg-white">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LIBRARIES.map((item) => (
                <SelectItem key={item.code} value={item.code}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-4 pb-10">
        <section className="overflow-hidden border bg-zinc-950">
          <div className="relative flex min-h-[46vh] items-center justify-center">
            {preview ? (
              <div className="relative w-fit max-w-full">
                <img
                  src={preview}
                  alt="촬영된 서가"
                  className="block max-h-[62vh] max-w-full object-contain"
                />
                <div className="absolute inset-0">
                  {results.map((result) => {
                    const meta = getDecisionMeta(result.decision);
                    return (
                      <div
                        key={result.order}
                        className={cn("absolute border-2", meta.marker)}
                        style={{
                          left: `${result.bbox.x}%`,
                          top: `${result.bbox.y}%`,
                          width: `${result.bbox.width}%`,
                          height: `${result.bbox.height}%`,
                        }}
                      >
                        <span className="absolute -top-6 left-0 bg-zinc-950 px-1.5 py-0.5 text-[11px] font-bold text-white">
                          {result.order}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <CameraIcon className="size-12 text-zinc-600" />
            )}

            {isAnalyzing ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-zinc-950/75 text-white">
                <Loader2Icon className="size-8 animate-spin" />
                <p className="text-sm font-semibold">책등 분석 중</p>
              </div>
            ) : null}
          </div>
        </section>

        <div className="grid grid-cols-2 gap-3">
          <Button asChild size="lg" disabled={isAnalyzing}>
            <label className="cursor-pointer">
              <CameraIcon className="size-5" />
              카메라 촬영
              <input
                type="file"
                accept="image/*"
                capture="environment"
                className="sr-only"
                disabled={isAnalyzing}
                onChange={handleFileInput}
              />
            </label>
          </Button>
          <Button asChild size="lg" variant="outline" disabled={isAnalyzing}>
            <label className="cursor-pointer bg-white">
              <ImagesIcon className="size-5" />
              갤러리 선택
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                disabled={isAnalyzing}
                onChange={handleFileInput}
              />
            </label>
          </Button>
        </div>

        {error ? (
          <div className="border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}

        {results.length > 0 ? (
          <>
            <section className="grid grid-cols-4 border bg-white text-center">
              <Count label="검출" value={counts.total} />
              <Count
                label="정상"
                value={counts.normal}
                tone="text-emerald-700"
              />
              <Count
                label="오배열"
                value={counts.misplaced}
                tone="text-red-700"
              />
              <Count label="확인" value={counts.review} tone="text-amber-700" />
            </section>

            <section className="overflow-hidden border bg-white">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <h2 className="font-bold">분석 결과</h2>
                <Button size="sm" variant="ghost" onClick={reset}>
                  <RotateCcwIcon className="size-4" />
                  다시 촬영
                </Button>
              </div>
              <div className="divide-y">
                {results.map((result) => {
                  const meta = getDecisionMeta(result.decision);
                  return (
                    <article
                      key={result.order}
                      className="flex gap-3 px-4 py-4"
                    >
                      <div className="flex size-8 shrink-0 items-center justify-center bg-zinc-100 text-sm font-bold">
                        {result.order}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <h3 className="font-semibold leading-snug">
                              {result.title}
                            </h3>
                            {result.author ? (
                              <p className="mt-0.5 text-sm text-zinc-500">
                                {result.author}
                              </p>
                            ) : null}
                          </div>
                          <Badge
                            variant="outline"
                            className={cn("shrink-0", meta.badge)}
                          >
                            {meta.label}
                          </Badge>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 text-sm">
                          <span className="font-mono">{result.callNumber}</span>
                          <span className="tabular-nums text-zinc-500">
                            {result.score.toFixed(1)}
                          </span>
                        </div>
                        {result.reason ? (
                          <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                            {result.reason}
                          </p>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          </>
        ) : null}

        {!preview && !isAnalyzing ? (
          <div className="flex items-center justify-center gap-2 py-2 text-xs text-zinc-500">
            <SearchCheckIcon className="size-4" />
            <span>{library.scope}</span>
          </div>
        ) : null}
      </main>
    </div>
  );
}

function Count({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: string;
}) {
  return (
    <div className="border-r px-2 py-3 last:border-r-0">
      <p className="text-[11px] text-zinc-500">{label}</p>
      <p className={cn("mt-1 text-xl font-bold tabular-nums", tone)}>{value}</p>
    </div>
  );
}
