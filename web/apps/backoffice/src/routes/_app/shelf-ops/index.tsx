import { useMemo, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";

import {
  AlertTriangleIcon,
  BookOpenCheckIcon,
  CheckCircle2Icon,
  FileImageIcon,
  ImageUpIcon,
  Loader2Icon,
  SearchCheckIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export const Route = createFileRoute("/_app/shelf-ops/")({
  component: ShelfOpsPage,
});

type DetectionStatus = "normal" | "misplaced" | "unmatched" | "review";

type Detection = {
  id: string;
  order: number;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  title: string;
  author: string;
  callNumber: string;
  ocrText: string;
  matchMethod: "callNumber" | "fuzzyTitle" | "manualReview";
  matchScore: number;
  status: DetectionStatus;
  reason: string;
  candidates: Array<{
    title: string;
    callNumber: string;
    score: number;
  }>;
};

type WorkerDetection = {
  detected_order: number;
  bbox?: number[] | null;
  ocr_raw_text?: string | null;
  ocr_title?: string | null;
  ocr_author?: string | null;
  ocr_call_number?: string | null;
  matched_book?: string | null;
  matched_call_number?: string | null;
  match_method?: string | null;
  match_score?: number | null;
  decision: string;
  reason?: string | null;
  top_candidates?: Array<{
    title: string;
    author?: string | null;
    call_number: string;
    score: number;
    match_method: string;
  }>;
};

type WorkerMatchResponse = {
  results: WorkerDetection[];
};

const INITIAL_DETECTIONS: Detection[] = [];

const LIBRARIES = [
  {
    code: "111189",
    name: "도봉아이나라도서관",
    roomName: "도봉아이나라도서관",
    scope: "전체 장서",
  },
  {
    code: "111058",
    name: "노원중앙도서관",
    roomName: "노원중앙도서관 종합자료실",
    scope: "종합자료실 · 한국문학 KDC 810-819",
  },
] as const;

const STATUS_META: Record<
  DetectionStatus,
  {
    label: string;
    className: string;
    markerClassName: string;
  }
> = {
  normal: {
    label: "정상",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    markerClassName: "border-emerald-500 bg-emerald-500/10",
  },
  misplaced: {
    label: "오배열",
    className: "bg-red-50 text-red-700 border-red-200",
    markerClassName: "border-red-500 bg-red-500/15",
  },
  unmatched: {
    label: "매칭 실패",
    className: "bg-zinc-100 text-zinc-700 border-zinc-300",
    markerClassName: "border-zinc-500 bg-zinc-500/10",
  },
  review: {
    label: "검수 필요",
    className: "bg-amber-50 text-amber-700 border-amber-200",
    markerClassName: "border-amber-500 bg-amber-500/15",
  },
};

const SPINE_COLORS = [
  "bg-[#5b6472]",
  "bg-[#c37b5a]",
  "bg-[#e8d8b8]",
  "bg-[#6a8b7a]",
  "bg-[#223047]",
  "bg-[#b9a66b]",
  "bg-[#8d4f5f]",
  "bg-[#2f5f73]",
  "bg-[#d9d2c3]",
  "bg-[#465746]",
  "bg-[#6f5d50]",
  "bg-[#394b63]",
];

function statusCounts(detections: Detection[]) {
  return detections.reduce(
    (acc, detection) => {
      acc.total += 1;
      acc[detection.status] += 1;
      return acc;
    },
    { total: 0, normal: 0, misplaced: 0, unmatched: 0, review: 0 },
  );
}

function getMatchMethodLabel(method: Detection["matchMethod"]) {
  switch (method) {
    case "callNumber":
      return "청구기호";
    case "fuzzyTitle":
      return "제목 유사도";
    case "manualReview":
      return "검수 대기";
  }
}

function mapWorkerDecision(decision: string): DetectionStatus {
  switch (decision) {
    case "normal":
      return "normal";
    case "suspected_misplacement":
      return "misplaced";
    case "needs_review":
      return "review";
    default:
      return "unmatched";
  }
}

function mapWorkerMatchMethod(
  method: string | null | undefined,
): Detection["matchMethod"] {
  switch (method) {
    case "call_number":
      return "callNumber";
    case "bibliographic_fuzzy":
      return "fuzzyTitle";
    default:
      return "manualReview";
  }
}

function mapWorkerDetections(
  response: WorkerMatchResponse,
  imageSize: { width: number; height: number },
): Detection[] {
  return response.results.map((result) => {
    const [x1 = 0, y1 = 0, x2 = 0, y2 = 0] = result.bbox ?? [];
    const topCandidate = result.top_candidates?.[0];

    return {
      id: `worker-${result.detected_order}`,
      order: result.detected_order,
      bbox: {
        x: (x1 / imageSize.width) * 100,
        y: (y1 / imageSize.height) * 100,
        width: ((x2 - x1) / imageSize.width) * 100,
        height: ((y2 - y1) / imageSize.height) * 100,
      },
      title:
        result.matched_book ||
        result.ocr_title ||
        topCandidate?.title ||
        "OCR 확인 필요",
      author: result.ocr_author || topCandidate?.author || "-",
      callNumber: result.matched_call_number || result.ocr_call_number || "-",
      ocrText: result.ocr_raw_text ?? "",
      matchMethod: mapWorkerMatchMethod(result.match_method),
      matchScore: result.match_score ?? 0,
      status: mapWorkerDecision(result.decision),
      reason: result.reason ?? "worker 분석 결과",
      candidates:
        result.top_candidates?.map((candidate) => ({
          title: candidate.title,
          callNumber: candidate.call_number,
          score: candidate.score,
        })) ?? [],
    };
  });
}

function ShelfOpsPage() {
  const [selectedLibraryCode, setSelectedLibraryCode] = useState("111189");
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [imageSize, setImageSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [detections, setDetections] = useState<Detection[]>(INITIAL_DETECTIONS);
  const [selectedId, setSelectedId] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const selectedDetection = useMemo(
    () =>
      detections.find((detection) => detection.id === selectedId) ??
      detections[0],
    [detections, selectedId],
  );
  const counts = useMemo(() => statusCounts(detections), [detections]);
  const selectedLibrary =
    LIBRARIES.find((library) => library.code === selectedLibraryCode) ??
    LIBRARIES[0];

  const handleLibraryChange = (libraryCode: string) => {
    setSelectedLibraryCode(libraryCode);
    setDetections([]);
    setSelectedId("");
    setAnalysisError(null);
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        return;
      }

      const image = new Image();
      image.addEventListener("load", () => {
        setImageSize({
          width: image.naturalWidth,
          height: image.naturalHeight,
        });
      });
      image.src = reader.result;

      setSelectedFile(file);
      setImageDataUrl(reader.result);
      setDetections([]);
      setSelectedId("");
      setAnalysisError(null);
    });
    reader.readAsDataURL(file);
  };

  const handleAnalyze = async () => {
    if (!selectedFile || !imageSize) {
      setAnalysisError("분석할 서가 이미지를 먼저 업로드하세요.");
      return;
    }

    setIsAnalyzing(true);
    setAnalysisError(null);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 300_000);
    try {
      const formData = new FormData();
      formData.set("file", selectedFile);

      const workerBaseUrl =
        import.meta.env.VITE_WORKER_BASE_URL ?? "http://localhost:8000";
      const workerUrl = new URL(
        `${workerBaseUrl}/inference/analyze_vision`,
        window.location.origin,
      );
      workerUrl.searchParams.set("library_code", selectedLibrary.code);
      workerUrl.searchParams.set("room_name", selectedLibrary.roomName);
      const response = await fetch(workerUrl, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        throw new Error(
          errorBody?.detail ?? `worker 분석 요청 실패: ${response.status}`,
        );
      }

      const payload = (await response.json()) as WorkerMatchResponse;
      const nextDetections = mapWorkerDetections(payload, imageSize);
      setDetections(nextDetections);
      setSelectedId(nextDetections[0]?.id ?? "");
    } catch (error) {
      setAnalysisError(
        error instanceof DOMException && error.name === "AbortError"
          ? "worker 분석 요청이 60초를 초과했습니다. VLM 응답 지연 또는 외부 API 문제일 수 있습니다."
          : error instanceof Error
          ? error.message
          : "worker 분석 중 오류가 발생했습니다.",
      );
    } finally {
      window.clearTimeout(timeoutId);
      setIsAnalyzing(false);
    }
  };

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "서가 스캔 검수" }]} />
      <div className="my-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="font-extrabold text-xl">서가 스캔 검수</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {selectedLibrary.name} · {selectedLibrary.scope}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={selectedLibraryCode}
            onValueChange={handleLibraryChange}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="도서관 선택" />
            </SelectTrigger>
            <SelectContent>
              {LIBRARIES.map((library) => (
                <SelectItem key={library.code} value={library.code}>
                  {library.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button asChild variant="outline">
            <label className="cursor-pointer">
              <ImageUpIcon className="size-4" />
              이미지 업로드{" "}
              <input
                accept="image/*"
                className="sr-only"
                type="file"
                onChange={handleFileChange}
              />
            </label>
          </Button>
          <Button type="button" onClick={handleAnalyze} disabled={isAnalyzing}>
            {isAnalyzing ? (
              <Loader2Icon className="size-4 animate-spin" />
            ) : (
              <SearchCheckIcon className="size-4" />
            )}
            분석 실행
          </Button>
        </div>
      </div>

      {analysisError ? (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {analysisError}
        </div>
      ) : null}

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SummaryCard
          icon={<BookOpenCheckIcon className="size-4" />}
          label="검출 책등"
          value={`${counts.total}권`}
        />
        <SummaryCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="정상"
          value={`${counts.normal}권`}
        />
        <SummaryCard
          icon={<AlertTriangleIcon className="size-4" />}
          label="오배열"
          value={`${counts.misplaced}권`}
          valueClassName="text-red-600"
        />
        <SummaryCard
          icon={<FileImageIcon className="size-4" />}
          label="검수 대기"
          value={`${counts.review + counts.unmatched}권`}
          valueClassName="text-amber-600"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <Card className="overflow-hidden">
          <CardHeader className="border-b">
            <CardTitle>스캔 이미지</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="relative flex aspect-[16/9] w-full items-center justify-center overflow-hidden bg-zinc-950">
              {imageDataUrl ? (
                <div className="relative w-fit max-h-full max-w-full">
                  <img
                    alt="업로드된 서가"
                    className="block max-h-full max-w-full object-contain"
                    src={imageDataUrl}
                  />
                  <DetectionOverlay
                    detections={detections}
                    selectedId={selectedDetection?.id}
                    onSelect={setSelectedId}
                  />
                </div>
              ) : (
                <DemoShelfImage />
              )}
            </div>
          </CardContent>
        </Card>

        {selectedDetection ? (
          <DetectionDetail detection={selectedDetection} />
        ) : (
          <Card>
            <CardHeader className="border-b">
              <CardTitle>선택 책등</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                검출된 책등이 없습니다.
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      <Card className="mt-4">
        <CardHeader className="border-b">
          <CardTitle>검출 목록</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">순서</TableHead>
                <TableHead>도서</TableHead>
                <TableHead>청구기호</TableHead>
                <TableHead className="text-right">점수</TableHead>
                <TableHead className="w-28 text-center">상태</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detections.map((detection) => (
                <TableRow
                  key={detection.id}
                  className={cn(
                    "cursor-pointer",
                    selectedDetection?.id === detection.id && "bg-muted/70",
                  )}
                  onClick={() => setSelectedId(detection.id)}
                >
                  <TableCell className="font-medium">
                    {detection.order}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{detection.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {detection.author}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {detection.callNumber}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {detection.matchScore.toFixed(1)}
                  </TableCell>
                  <TableCell className="text-center">
                    <StatusBadge status={detection.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}

function DetectionOverlay({
  detections,
  selectedId,
  onSelect,
}: {
  detections: Detection[];
  selectedId?: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="absolute inset-0">
      {detections.map((detection) => {
        const meta = STATUS_META[detection.status];
        const isSelected = detection.id === selectedId;

        return (
          <button
            key={detection.id}
            className={cn(
              "absolute rounded-[4px] border-2 transition",
              meta.markerClassName,
              isSelected && "ring-2 ring-white ring-offset-2 ring-offset-zinc-950",
            )}
            style={{
              left: `${detection.bbox.x}%`,
              top: `${detection.bbox.y}%`,
              width: `${detection.bbox.width}%`,
              height: `${detection.bbox.height}%`,
            }}
            type="button"
            onClick={() => onSelect(detection.id)}
            aria-label={`${detection.order}번 책등 ${STATUS_META[detection.status].label}`}
          >
            <span className="absolute -top-7 left-0 rounded bg-zinc-950/85 px-2 py-0.5 text-xs font-semibold text-white">
              {detection.order}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  valueClassName,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <Card className="gap-3 py-4">
      <CardContent className="flex items-center gap-3 px-4">
        <div className="flex size-9 items-center justify-center rounded-md bg-muted text-muted-foreground">
          {icon}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className={cn("text-xl font-bold", valueClassName)}>{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function DemoShelfImage() {
  return (
    <div className="absolute inset-0 flex items-stretch gap-1 bg-[#202326] px-6 py-8">
      {Array.from({ length: 30 }).map((_, index) => (
        <div
          key={index}
          className={cn(
            "h-full min-w-0 flex-1 rounded-[3px] border border-white/10 shadow-sm",
            SPINE_COLORS[index % SPINE_COLORS.length],
            index % 5 === 0 && "mt-4",
            index % 7 === 0 && "mb-3",
          )}
        >
          <div className="mx-auto mt-4 h-2/3 w-px bg-white/25" />
          <div className="mx-auto mt-3 h-7 w-3/4 rounded-sm bg-white/55" />
        </div>
      ))}
    </div>
  );
}

function DetectionDetail({ detection }: { detection: Detection }) {
  const hasConfirmedMatch =
    detection.status === "normal" || detection.status === "misplaced";

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          <CardTitle>선택 책등</CardTitle>
          <StatusBadge status={detection.status} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <section>
          <p className="text-xs text-muted-foreground">
            {hasConfirmedMatch ? "확정 매칭 도서" : "OCR 인식 도서"}
          </p>
          <h3 className="mt-1 text-lg font-bold leading-snug">
            {detection.title}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {detection.author}
          </p>
        </section>

        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">
              {hasConfirmedMatch ? "확정 청구기호" : "인식 청구기호"}
            </dt>
            <dd className="mt-1 font-mono font-semibold">
              {detection.callNumber}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">
              {hasConfirmedMatch ? "매칭 방식" : "후보 산출 방식"}
            </dt>
            <dd className="mt-1 font-semibold">
              {getMatchMethodLabel(detection.matchMethod)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">
              {hasConfirmedMatch ? "매칭 점수" : "후보 최고 점수"}
            </dt>
            <dd className="mt-1 font-semibold tabular-nums">
              {detection.matchScore.toFixed(1)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">BBox</dt>
            <dd className="mt-1 font-mono text-xs">
              {detection.bbox.x}, {detection.bbox.y}, {detection.bbox.width},{" "}
              {detection.bbox.height}
            </dd>
          </div>
        </dl>

        <section>
          <p className="text-xs text-muted-foreground">OCR 원문</p>
          <p className="mt-1 rounded-md border bg-muted/40 px-3 py-2 font-mono text-sm">
            {detection.ocrText}
          </p>
        </section>

        <section>
          <p className="text-xs text-muted-foreground">판정 사유</p>
          <p className="mt-1 text-sm">{detection.reason}</p>
        </section>

        <section>
          <p className="text-xs text-muted-foreground">DB 후보</p>
          <div className="mt-2 flex flex-col gap-2">
            {detection.candidates.length > 0 ? (
              detection.candidates.map((candidate) => (
                <div
                  key={`${candidate.title}-${candidate.callNumber}`}
                  className="rounded-md border px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="truncate text-sm font-medium">
                      {candidate.title}
                    </p>
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {candidate.score.toFixed(1)}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {candidate.callNumber}
                  </p>
                </div>
              ))
            ) : (
              <p className="rounded-md border px-3 py-2 text-sm text-muted-foreground">
                후보 없음
              </p>
            )}
          </div>
        </section>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: DetectionStatus }) {
  const meta = STATUS_META[status];

  return (
    <Badge
      variant="outline"
      className={cn("whitespace-nowrap", meta.className)}
    >
      {meta.label}
    </Badge>
  );
}
