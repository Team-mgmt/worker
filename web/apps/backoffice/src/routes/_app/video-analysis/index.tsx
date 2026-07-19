import { useMemo, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";
import {
  CheckCircle2Icon,
  FilmIcon,
  Loader2Icon,
  UploadIcon,
} from "lucide-react";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { LIBRARIES } from "@/lib/libraries";

export const Route = createFileRoute("/_app/video-analysis/")({
  component: VideoAnalysisPage,
});

type FrameQuality = {
  frame_index: number;
  timestamp_seconds: number;
  width: number;
  height: number;
  sharpness: number;
  brightness: number;
  contrast: number;
  quality_score: number;
  selected: boolean;
};

type Detection = {
  detected_order: number;
  bbox?: number[] | null;
  ocr_title?: string | null;
  ocr_author?: string | null;
  ocr_call_number?: string | null;
  matched_book?: string | null;
  matched_call_number?: string | null;
  match_score?: number | null;
  decision: string;
};

type VideoAnalysisResponse = {
  video_run_id: string;
  source_name: string;
  duration_seconds: number;
  sample_interval_seconds: number;
  frame_candidates: FrameQuality[];
  selected_frame_data_url: string;
  frame_selection_seconds: number;
  total_seconds: number;
  analysis: { results: Detection[]; artifact_run_id?: string | null };
};

function decisionLabel(decision: string) {
  if (decision === "normal") return "정상";
  if (decision === "suspected_misplacement") return "오배열";
  return "검수 필요";
}

function VideoAnalysisPage() {
  const [libraryCode, setLibraryCode] = useState("111189");
  const [interval, setInterval] = useState("1");
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [result, setResult] = useState<VideoAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const library = LIBRARIES.find((item) => item.code === libraryCode) ?? LIBRARIES[0];

  const counts = useMemo(() => {
    const detections = result?.analysis.results ?? [];
    return {
      total: detections.length,
      normal: detections.filter((item) => item.decision === "normal").length,
      misplaced: detections.filter((item) => item.decision === "suspected_misplacement").length,
      review: detections.filter((item) => !["normal", "suspected_misplacement"].includes(item.decision)).length,
    };
  }, [result]);

  const selectVideo = (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0];
    if (!next) return;
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setFile(next);
    setVideoUrl(URL.createObjectURL(next));
    setResult(null);
    setError("");
  };

  const analyze = async () => {
    if (!file) {
      setError("분석할 동영상을 먼저 선택하세요.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 600_000);
    try {
      const workerBase = import.meta.env.VITE_WORKER_BASE_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "/worker");
      const url = new URL(`${workerBase}/inference/analyze_video`, window.location.origin);
      url.searchParams.set("library_code", library.code);
      url.searchParams.set("room_name", library.roomName);
      url.searchParams.set("sample_interval_seconds", interval);
      const body = new FormData();
      body.set("file", file);
      const response = await fetch(url, { method: "POST", body, signal: controller.signal });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail ?? `동영상 분석 요청 실패: ${response.status}`);
      }
      setResult((await response.json()) as VideoAnalysisResponse);
    } catch (cause) {
      setError(
        cause instanceof DOMException && cause.name === "AbortError"
          ? "동영상 분석이 10분을 초과했습니다."
          : cause instanceof Error
            ? cause.message
            : "동영상 분석 중 오류가 발생했습니다.",
      );
    } finally {
      window.clearTimeout(timeout);
      setLoading(false);
    }
  };

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "동영상 서가 분석" }]} />
      <div className="my-4">
        <h2 className="text-xl font-extrabold">동영상 서가 분석</h2>
        <p className="mt-1 text-sm text-muted-foreground">짧은 서가 영상에서 품질이 가장 좋은 프레임을 선택해 분석합니다.</p>
      </div>

      <div className="mb-5 grid gap-3 border bg-white p-4 md:grid-cols-[240px_180px_1fr_auto] md:items-end">
        <div>
          <Label className="mb-1.5 block">도서관</Label>
          <Select value={libraryCode} onValueChange={setLibraryCode}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>{LIBRARIES.map((item) => <SelectItem key={item.code} value={item.code}>{item.name}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div>
          <Label className="mb-1.5 block">프레임 간격</Label>
          <Select value={interval} onValueChange={setInterval}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="0.5">0.5초</SelectItem>
              <SelectItem value="1">1초</SelectItem>
              <SelectItem value="2">2초</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button asChild variant="outline">
          <label className="cursor-pointer overflow-hidden">
            <UploadIcon className="size-4 shrink-0" />
            <span className="truncate">{file?.name ?? "동영상 선택"}</span>
            <input className="sr-only" type="file" accept="video/mp4,video/quicktime,video/webm,.m4v" onChange={selectVideo} />
          </label>
        </Button>
        <Button onClick={analyze} disabled={!file || loading}>
          {loading ? <Loader2Icon className="size-4 animate-spin" /> : <FilmIcon className="size-4" />}
          {loading ? "분석 중" : "분석 실행"}
        </Button>
      </div>

      {error ? <div className="mb-5 border-l-4 border-red-600 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}

      <div className="grid gap-5 xl:grid-cols-2">
        <section>
          <h3 className="mb-2 text-sm font-bold">업로드 영상</h3>
          <div className="flex aspect-video items-center justify-center overflow-hidden bg-zinc-950">
            {videoUrl ? <video className="h-full w-full object-contain" src={videoUrl} controls /> : <FilmIcon className="size-10 text-zinc-600" />}
          </div>
        </section>
        <section>
          <h3 className="mb-2 text-sm font-bold">선택된 최적 프레임</h3>
          <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-zinc-100">
            {result ? (
              <>
                <img className="h-full w-full object-contain" src={result.selected_frame_data_url} alt="선택된 최적 프레임" />
                <div className="absolute left-3 top-3 bg-zinc-950 px-2 py-1 text-xs text-white">품질 기반 선택</div>
              </>
            ) : <span className="text-sm text-muted-foreground">분석 후 선택 프레임이 표시됩니다.</span>}
          </div>
        </section>
      </div>

      {result ? (
        <>
          <div className="my-5 grid grid-cols-2 border bg-white md:grid-cols-4">
            {[['검출 책등', counts.total], ['정상', counts.normal], ['오배열', counts.misplaced], ['검수 대기', counts.review]].map(([label, value]) => (
              <div key={label} className="border-b px-4 py-3 last:border-b-0 md:border-b-0 md:border-r md:last:border-r-0"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-bold">{value}권</p></div>
            ))}
          </div>

          <section className="mb-5">
            <div className="mb-2 flex items-end justify-between"><h3 className="text-sm font-bold">프레임 품질 평가</h3><p className="text-xs text-muted-foreground">영상 {result.duration_seconds.toFixed(1)}초 · 전체 {result.total_seconds.toFixed(1)}초</p></div>
            <div className="overflow-x-auto border bg-white">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-zinc-50 text-left text-xs text-muted-foreground"><tr><th className="px-4 py-3">시점</th><th className="px-4 py-3">선명도</th><th className="px-4 py-3">밝기</th><th className="px-4 py-3">대비</th><th className="px-4 py-3">종합 점수</th><th className="px-4 py-3">선택</th></tr></thead>
                <tbody className="divide-y">{result.frame_candidates.map((frame) => <tr key={frame.frame_index} className={frame.selected ? "bg-emerald-50" : undefined}><td className="px-4 py-3">{frame.timestamp_seconds.toFixed(1)}초</td><td className="px-4 py-3">{(frame.sharpness * 100).toFixed(1)}</td><td className="px-4 py-3">{(frame.brightness * 100).toFixed(1)}</td><td className="px-4 py-3">{(frame.contrast * 100).toFixed(1)}</td><td className="px-4 py-3 font-semibold">{(frame.quality_score * 100).toFixed(1)}</td><td className="px-4 py-3">{frame.selected ? <CheckCircle2Icon className="size-4 text-emerald-600" /> : "-"}</td></tr>)}</tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-bold">책등 분석 결과</h3>
            <div className="divide-y border bg-white">{result.analysis.results.map((item) => <div key={item.detected_order} className="grid gap-2 px-4 py-3 md:grid-cols-[48px_1fr_180px_100px] md:items-center"><span className="font-mono text-sm">{item.detected_order}</span><div><p className="font-semibold">{item.matched_book || item.ocr_title || "OCR 확인 필요"}</p><p className="text-xs text-muted-foreground">{item.ocr_author || "저자 미확인"}</p></div><span className="font-mono text-sm">{item.matched_call_number || item.ocr_call_number || "-"}</span><Badge variant="outline">{decisionLabel(item.decision)}</Badge></div>)}</div>
          </section>
        </>
      ) : null}
    </>
  );
}
