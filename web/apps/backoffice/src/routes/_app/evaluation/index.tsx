import { useEffect, useMemo, useRef, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";

import type { KonvaEventObject } from "konva/lib/Node";
import {
  CheckIcon,
  Loader2Icon,
  MousePointer2Icon,
  PlusIcon,
  RotateCcwIcon,
  SaveIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react";
import {
  Circle,
  Image as KonvaImage,
  Layer,
  Line,
  Stage,
  Text,
} from "react-konva";

import { LIBRARIES } from "@/lib/libraries";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/_app/evaluation/")({
  component: EvaluationPage,
});

type Point = [number, number];
type Annotation = {
  id: string;
  class: "book_spine";
  polygon: Point[];
  title?: string | null;
  author?: string | null;
  call_number?: string | null;
  holding_id?: string | null;
  book_id?: string | null;
  placement_status?: "normal" | "misplaced" | null;
};
type DetectionMetrics = {
  iou_threshold: number;
  ground_truth_count: number;
  prediction_count: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  precision: number;
  recall: number;
  f1: number;
  ap50: number;
  mean_matched_iou: number;
  count_error: number;
};
type DetectionMatch = {
  status: "matched" | "false_positive" | "missed";
  ground_truth_index?: number | null;
  ground_truth_id?: string | null;
  prediction_index?: number | null;
  iou: number;
  confidence: number;
  ground_truth_polygon?: Point[] | null;
  prediction_polygon?: Point[] | null;
};
type DetectionStructureMetrics = {
  ground_truth_count: number;
  prediction_count: number;
  correct_ground_truth_count: number;
  split_ground_truth_count: number;
  merged_ground_truth_count: number;
  missed_ground_truth_count: number;
  merged_prediction_count: number;
  false_positive_prediction_count: number;
  split_rate: number;
  merge_rate: number;
};
type PlacementMetrics = {
  evaluated_count: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  true_negative: number;
  precision: number;
  recall: number;
  f1: number;
};
type MatchingMetrics = {
  polygon_matched_count: number;
  title_evaluated_count: number;
  title_normalized_accuracy: number;
  author_evaluated_count: number;
  author_normalized_accuracy: number;
  call_number_evaluated_count: number;
  call_number_exact_accuracy: number;
  kdc_evaluated_count: number;
  kdc_accuracy: number;
  book_code_evaluated_count: number;
  book_code_accuracy: number;
  db_evaluated_count: number;
  top1_accuracy: number;
  top3_accuracy: number;
  confirmed_count: number;
  wrong_confirmation_count: number;
  false_confirmation_rate: number;
};
type ArtifactRun = {
  run_id: string;
  library_code: string;
  created_at: string;
  prefix: string;
  has_ground_truth: boolean;
};
type PredictionResult = {
  detected_order: number;
  bbox?: number[] | null;
  obb_polygon?: number[][] | null;
  ocr_title?: string | null;
  ocr_author?: string | null;
  ocr_call_number?: string | null;
  matched_holding_id?: string | null;
  matched_book_id?: string | null;
};
type ArtifactDetail = {
  run_id: string;
  prefix: string;
  result: { inference?: { results?: PredictionResult[] } };
  ground_truth?: {
    annotations?: Annotation[];
    metrics?: DetectionMetrics;
    detection_matches?: DetectionMatch[];
    structure_metrics?: DetectionStructureMetrics;
    placement_metrics?: PlacementMetrics | null;
    matching_metrics?: MatchingMetrics | null;
  } | null;
  image_width: number;
  image_height: number;
  original_url: string;
};

type CatalogHolding = {
  id: string;
  callNumber?: string | null;
  shelfLocName?: string | null;
  book?: {
    id: string;
    bookname: string;
    authors?: string | null;
    isbn13?: string | null;
  } | null;
};

function apiUrl(path: string) {
  const configured = import.meta.env.VITE_BASE_URL || "/api";
  const base = new URL(
    configured.endsWith("/") ? configured : `${configured}/`,
    window.location.origin,
  );
  return new URL(path.replace(/^\//, ""), base).toString();
}

function workerUrl(path: string) {
  const configured =
    import.meta.env.VITE_WORKER_BASE_URL ??
    (import.meta.env.DEV ? "http://localhost:8000" : "/worker");
  const base = new URL(
    configured.endsWith("/") ? configured : `${configured}/`,
    window.location.origin,
  );
  return new URL(path.replace(/^\//, ""), base).toString();
}

function predictionAnnotations(detail: ArtifactDetail): Annotation[] {
  return (detail.result.inference?.results ?? []).flatMap((result) => {
    let polygon = result.obb_polygon as Point[] | null | undefined;
    if ((!polygon || polygon.length !== 4) && result.bbox?.length === 4) {
      const [left, top, right, bottom] = result.bbox;
      polygon = [
        [left, top],
        [right, top],
        [right, bottom],
        [left, bottom],
      ];
    }
    if (!polygon || polygon.length !== 4) return [];
    return [
      {
        id: `spine-${result.detected_order}`,
        class: "book_spine" as const,
        polygon,
        title: result.ocr_title,
        author: result.ocr_author,
        call_number: result.ocr_call_number,
        // Model output is a hypothesis, not reviewed ground truth. Catalog IDs
        // are populated only after a reviewer selects the actual book.
        holding_id: null,
        book_id: null,
        placement_status: "normal" as const,
      },
    ];
  });
}

function useHtmlImage(source: string | null) {
  const [loaded, setLoaded] = useState<{
    source: string;
    image: HTMLImageElement;
  } | null>(null);
  useEffect(() => {
    if (!source) return;
    const nextImage = new Image();
    nextImage.addEventListener("load", () =>
      setLoaded({ source, image: nextImage }),
    );
    nextImage.src = source;
    return () => {
      nextImage.src = "";
    };
  }, [source]);
  return loaded?.source === source ? loaded.image : null;
}

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function EvaluationPage() {
  const [libraryCode, setLibraryCode] = useState("111058");
  const [runs, setRuns] = useState<ArtifactRun[]>([]);
  const [runId, setRunId] = useState("");
  const [detail, setDetail] = useState<ArtifactDetail | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftPoints, setDraftPoints] = useState<Point[]>([]);
  const [mode, setMode] = useState<"select" | "add">("select");
  const [metrics, setMetrics] = useState<DetectionMetrics | null>(null);
  const [detectionMatches, setDetectionMatches] = useState<DetectionMatch[]>(
    [],
  );
  const [showIouOverlay, setShowIouOverlay] = useState(true);
  const [structureMetrics, setStructureMetrics] =
    useState<DetectionStructureMetrics | null>(null);
  const [placementMetrics, setPlacementMetrics] =
    useState<PlacementMetrics | null>(null);
  const [matchingMetrics, setMatchingMetrics] =
    useState<MatchingMetrics | null>(null);
  const [message, setMessage] = useState("");
  const [isBusy, setIsBusy] = useState(true);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogResults, setCatalogResults] = useState<CatalogHolding[]>([]);
  const [isCatalogSearching, setIsCatalogSearching] = useState(false);
  const [catalogMessage, setCatalogMessage] = useState("");
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasWidth, setCanvasWidth] = useState(900);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setCanvasWidth(Math.max(320, entry.contentRect.width)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    fetch(
      workerUrl(`/inference/artifacts?library_code=${libraryCode}&limit=100`),
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`실행 목록 조회 실패: ${response.status}`);
        return (await response.json()) as ArtifactRun[];
      })
      .then((payload) => {
        setRuns(payload);
        setMessage(payload.length ? "" : "저장된 분석 실행이 없습니다.");
      })
      .catch((error: unknown) =>
        setMessage(
          error instanceof Error ? error.message : "실행 목록 조회 실패",
        ),
      )
      .finally(() => setIsBusy(false));
  }, [libraryCode]);

  const loadRun = async (nextRunId = runId) => {
    if (!nextRunId) return;
    setIsBusy(true);
    setMessage("");
    try {
      const response = await fetch(
        workerUrl(
          `/inference/artifacts/${nextRunId}?library_code=${libraryCode}`,
        ),
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `실행 조회 실패: ${response.status}`);
      }
      const payload = (await response.json()) as ArtifactDetail;
      const loadedAnnotations = payload.ground_truth?.annotations?.length
        ? payload.ground_truth.annotations
        : predictionAnnotations(payload);
      const initial = loadedAnnotations.map((annotation) => ({
        ...annotation,
        placement_status: annotation.placement_status ?? ("normal" as const),
      }));
      setRunId(nextRunId);
      setDetail(payload);
      setAnnotations(initial);
      setMetrics(payload.ground_truth?.metrics ?? null);
      setDetectionMatches(payload.ground_truth?.detection_matches ?? []);
      setStructureMetrics(payload.ground_truth?.structure_metrics ?? null);
      setPlacementMetrics(payload.ground_truth?.placement_metrics ?? null);
      setMatchingMetrics(payload.ground_truth?.matching_metrics ?? null);
      setSelectedId(initial[0]?.id ?? null);
      setCatalogQuery("");
      setCatalogResults([]);
      setCatalogMessage("");
      setDraftPoints([]);
      setMode("select");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "실행 조회 실패");
    } finally {
      setIsBusy(false);
    }
  };

  const image = useHtmlImage(detail ? workerUrl(detail.original_url) : null);
  const scale = detail ? canvasWidth / detail.image_width : 1;
  const canvasHeight = detail ? detail.image_height * scale : 520;
  const selected =
    annotations.find((annotation) => annotation.id === selectedId) ?? null;
  const selectedDetectionMatches = useMemo(
    () =>
      detectionMatches.filter(
        (match) =>
          match.ground_truth_id && match.ground_truth_id === selectedId,
      ),
    [detectionMatches, selectedId],
  );
  const selectedDetectionMatch =
    selectedDetectionMatches.find((match) => match.status === "matched") ??
    null;
  const selectedFalsePositives = selectedDetectionMatches.filter(
    (match) => match.status === "false_positive",
  );
  const selectedComparisonViewBox = useMemo(() => {
    if (!detail || !selected) return null;
    const points = [
      ...selected.polygon,
      ...selectedDetectionMatches.flatMap(
        (match) => match.prediction_polygon ?? [],
      ),
    ];
    if (!points.length) return null;
    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);
    const left = Math.max(0, Math.min(...xs));
    const top = Math.max(0, Math.min(...ys));
    const right = Math.min(detail.image_width, Math.max(...xs));
    const bottom = Math.min(detail.image_height, Math.max(...ys));
    const paddingX = Math.max(20, (right - left) * 0.35);
    const paddingY = Math.max(20, (bottom - top) * 0.05);
    const x = Math.max(0, left - paddingX);
    const y = Math.max(0, top - paddingY);
    const width = Math.min(detail.image_width - x, right - left + paddingX * 2);
    const height = Math.min(
      detail.image_height - y,
      bottom - top + paddingY * 2,
    );
    return `${x} ${y} ${width} ${height}`;
  }, [detail, selected, selectedDetectionMatches]);

  const updateAnnotation = (id: string, update: Partial<Annotation>) => {
    setAnnotations((current) =>
      current.map((item) => (item.id === id ? { ...item, ...update } : item)),
    );
  };
  const selectAnnotation = (id: string | null) => {
    setSelectedId(id);
    setCatalogQuery("");
    setCatalogResults([]);
    setCatalogMessage("");
  };
  const searchCatalog = async () => {
    const query = catalogQuery.trim() || selected?.title?.trim() || "";
    if (query.length < 2) {
      setCatalogMessage("검색어를 두 글자 이상 입력하세요.");
      return;
    }
    setCatalogQuery(query);
    setCatalogMessage("");
    setIsCatalogSearching(true);
    try {
      const url = new URL(apiUrl("public/library-books"));
      url.searchParams.set("libraryCode", libraryCode);
      url.searchParams.set("query", query);
      const response = await fetch(url);
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(
          payload?.message ?? `도서 검색 실패: ${response.status}`,
        );
      }
      const byBookId = new Map<string, CatalogHolding>();
      for (const holding of (payload?.data ?? []) as CatalogHolding[]) {
        if (holding.book?.id && !byBookId.has(holding.book.id)) {
          byBookId.set(holding.book.id, holding);
        }
      }
      const nextResults = [...byBookId.values()];
      setCatalogResults(nextResults);
      setCatalogMessage(nextResults.length ? "" : "검색 결과가 없습니다.");
    } catch (error) {
      setCatalogResults([]);
      setCatalogMessage(
        error instanceof Error ? error.message : "도서 검색에 실패했습니다.",
      );
    } finally {
      setIsCatalogSearching(false);
    }
  };
  const selectCatalogBook = (holding: CatalogHolding) => {
    if (!selected || !holding.book) return;
    updateAnnotation(selected.id, {
      title: holding.book.bookname,
      author: holding.book.authors ?? null,
      call_number: holding.callNumber ?? null,
      book_id: holding.book.id,
      holding_id: null,
    });
    setCatalogMessage(`정답 도서로 선택: ${holding.book.bookname}`);
  };
  const resetToPrediction = () => {
    if (!detail) return;
    const next = predictionAnnotations(detail);
    setAnnotations(next);
    setSelectedId(next[0]?.id ?? null);
    setMetrics(null);
    setDetectionMatches([]);
    setStructureMetrics(null);
    setPlacementMetrics(null);
    setMatchingMetrics(null);
  };
  const handleStageClick = (event: KonvaEventObject<MouseEvent>) => {
    if (mode !== "add" || !detail) return;
    const pointer = event.target.getStage()?.getPointerPosition();
    if (!pointer) return;
    const point: Point = [
      Math.max(0, Math.min(detail.image_width, pointer.x / scale)),
      Math.max(0, Math.min(detail.image_height, pointer.y / scale)),
    ];
    const next = [...draftPoints, point];
    if (next.length === 4) {
      const id = `spine-manual-${Date.now()}`;
      setAnnotations((current) => [
        ...current,
        {
          id,
          class: "book_spine",
          polygon: next,
          placement_status: "normal",
        },
      ]);
      setSelectedId(id);
      setDraftPoints([]);
      setMode("select");
    } else setDraftPoints(next);
  };
  const saveGroundTruth = async () => {
    if (!detail) return;
    setIsBusy(true);
    setMessage("");
    try {
      const response = await fetch(
        workerUrl(
          `/inference/artifacts/${detail.run_id}/ground-truth?library_code=${libraryCode}`,
        ),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewer: "admin", annotations }),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `GT 저장 실패: ${response.status}`);
      }
      const payload = (await response.json()) as {
        metrics: DetectionMetrics;
        detection_matches: DetectionMatch[];
        structure_metrics: DetectionStructureMetrics;
        placement_metrics?: PlacementMetrics | null;
        matching_metrics?: MatchingMetrics | null;
      };
      setMetrics(payload.metrics);
      setDetectionMatches(payload.detection_matches);
      setStructureMetrics(payload.structure_metrics);
      setPlacementMetrics(payload.placement_metrics ?? null);
      setMatchingMetrics(payload.matching_metrics ?? null);
      setMessage("ground-truth.json 저장과 평가가 완료되었습니다.");
      setRuns((current) =>
        current.map((run) =>
          run.run_id === detail.run_id
            ? { ...run, has_ground_truth: true }
            : run,
        ),
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "GT 저장 실패");
    } finally {
      setIsBusy(false);
    }
  };

  const metricItems = useMemo(
    () =>
      metrics
        ? [
            ["Precision", percent(metrics.precision)],
            ["Recall", percent(metrics.recall)],
            ["F1", percent(metrics.f1)],
            ["AP50", percent(metrics.ap50)],
            ["평균 IoU", percent(metrics.mean_matched_iou)],
            [
              "TP / FP / FN",
              `${metrics.true_positive} / ${metrics.false_positive} / ${metrics.false_negative}`,
            ],
          ]
        : [],
    [metrics],
  );

  return (
    <>
      <Breadcrumb items={[{ type: "text", label: "GT 라벨 검수" }]} />
      <div className="my-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-extrabold">책등 정답 라벨 편집</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            예측 OBB를 교정하고 IoU 0.5 기준 검출 지표를 산출합니다.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-52">
            <Label className="mb-1.5 block">도서관</Label>
            <Select
              value={libraryCode}
              onValueChange={(value) => {
                setIsBusy(true);
                setLibraryCode(value);
                setDetail(null);
                setRunId("");
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LIBRARIES.map((library) => (
                  <SelectItem key={library.code} value={library.code}>
                    {library.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-80 max-w-full">
            <Label className="mb-1.5 block">S3 분석 실행</Label>
            <Select
              value={runId}
              onValueChange={(value) => void loadRun(value)}
            >
              <SelectTrigger>
                <SelectValue
                  placeholder={isBusy ? "조회 중" : "실행 ID 선택"}
                />
              </SelectTrigger>
              <SelectContent>
                {runs.map((run) => (
                  <SelectItem key={run.run_id} value={run.run_id}>
                    {new Date(run.created_at).toLocaleString("ko-KR")}{" "}
                    {run.has_ground_truth ? "· GT" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      {message ? (
        <div className="mb-4 border-l-4 border-zinc-700 bg-white px-4 py-3 text-sm">
          {message}
        </div>
      ) : null}
      {metrics ? (
        <div className="mb-4 grid grid-cols-2 border bg-white md:grid-cols-3 xl:grid-cols-6">
          {metricItems.map(([label, value]) => (
            <div
              key={label}
              className="border-b border-r px-4 py-3 last:border-r-0 md:border-b-0"
            >
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-bold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      ) : null}
      {structureMetrics ? (
        <div className="mb-4 grid grid-cols-2 border bg-white md:grid-cols-4 xl:grid-cols-7">
          {[
            ["정상 연결", `${structureMetrics.correct_ground_truth_count}권`],
            ["분할 검출", `${structureMetrics.split_ground_truth_count}권`],
            ["병합 영향 GT", `${structureMetrics.merged_ground_truth_count}권`],
            ["누락", `${structureMetrics.missed_ground_truth_count}권`],
            ["병합 예측", `${structureMetrics.merged_prediction_count}개`],
            ["오검출", `${structureMetrics.false_positive_prediction_count}개`],
            [
              "Split / Merge",
              `${percent(structureMetrics.split_rate)} / ${percent(structureMetrics.merge_rate)}`,
            ],
          ].map(([label, value]) => (
            <div
              key={label}
              className="border-b border-r px-4 py-3 xl:border-b-0"
            >
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-bold tabular-nums">{value}</p>
            </div>
          ))}
          <div className="col-span-2 border-t px-4 py-2 text-xs text-muted-foreground md:col-span-4 xl:col-span-7">
            GT {structureMetrics.ground_truth_count}권 · 예측{" "}
            {structureMetrics.prediction_count}개 · 한 GT에 예측 여러 개면 분할,
            한 예측이 여러 GT를 덮으면 병합으로 계산합니다.
          </div>
        </div>
      ) : null}
      {placementMetrics ? (
        <div className="mb-4 grid grid-cols-2 border bg-white md:grid-cols-4">
          {[
            ["오배열 Precision", percent(placementMetrics.precision)],
            ["오배열 Recall", percent(placementMetrics.recall)],
            ["오배열 F1", percent(placementMetrics.f1)],
            [
              "배치 TP / FP / FN / TN",
              `${placementMetrics.true_positive} / ${placementMetrics.false_positive} / ${placementMetrics.false_negative} / ${placementMetrics.true_negative}`,
            ],
          ].map(([label, value]) => (
            <div key={label} className="border-r px-4 py-3 last:border-r-0">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-bold tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      ) : null}
      {matchingMetrics ? (
        <div className="mb-4 grid grid-cols-2 border bg-white md:grid-cols-4 xl:grid-cols-7">
          {[
            ["제목 정확도", percent(matchingMetrics.title_normalized_accuracy)],
            [
              "청구기호 정확도",
              percent(matchingMetrics.call_number_exact_accuracy),
            ],
            ["KDC 정확도", percent(matchingMetrics.kdc_accuracy)],
            ["도서기호 정확도", percent(matchingMetrics.book_code_accuracy)],
            ["DB Top-1", percent(matchingMetrics.top1_accuracy)],
            ["DB Top-3", percent(matchingMetrics.top3_accuracy)],
            ["오확정률", percent(matchingMetrics.false_confirmation_rate)],
          ].map(([label, value]) => (
            <div
              key={label}
              className="border-b border-r px-4 py-3 xl:border-b-0"
            >
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-bold tabular-nums">{value}</p>
            </div>
          ))}
          <div className="col-span-2 border-t px-4 py-2 text-xs text-muted-foreground md:col-span-4 xl:col-span-7">
            Polygon 연결 {matchingMetrics.polygon_matched_count}권 · DB GT{" "}
            {matchingMetrics.db_evaluated_count}권 · 자동 확정{" "}
            {matchingMetrics.confirmed_count}권 중 오확정{" "}
            {matchingMetrics.wrong_confirmation_count}권
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="overflow-hidden border bg-zinc-950">
          <div className="flex min-h-14 flex-wrap items-center justify-between gap-2 border-b border-zinc-700 bg-zinc-900 px-3 py-2 text-white">
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={mode === "select" ? "secondary" : "ghost"}
                onClick={() => {
                  setMode("select");
                  setDraftPoints([]);
                }}
              >
                <MousePointer2Icon className="size-4" />
                선택
              </Button>
              <Button
                size="sm"
                variant={mode === "add" ? "secondary" : "ghost"}
                onClick={() => {
                  setMode("add");
                  setDraftPoints([]);
                }}
              >
                <PlusIcon className="size-4" />
                책등 추가
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={resetToPrediction}
                disabled={!detail}
              >
                <RotateCcwIcon className="size-4" />
                예측 복원
              </Button>
              <Button
                size="sm"
                variant={showIouOverlay ? "secondary" : "ghost"}
                onClick={() => setShowIouOverlay((current) => !current)}
                disabled={!detectionMatches.length}
              >
                IoU 비교
              </Button>
            </div>
            <span className="text-xs text-zinc-300">
              GT {annotations.length}개{" "}
              {mode === "add" ? `· 꼭짓점 ${draftPoints.length}/4` : ""}
            </span>
          </div>
          <div ref={canvasRef} className="w-full overflow-auto">
            {detail && image ? (
              <Stage
                width={canvasWidth}
                height={canvasHeight}
                onClick={handleStageClick}
              >
                <Layer scaleX={scale} scaleY={scale}>
                  <KonvaImage
                    image={image}
                    width={detail.image_width}
                    height={detail.image_height}
                  />
                  {showIouOverlay
                    ? detectionMatches
                        .filter(
                          (match) =>
                            !selectedId || match.ground_truth_id === selectedId,
                        )
                        .map((match, index) => {
                          if (!match.prediction_polygon) return null;
                          const isFalsePositive =
                            match.status === "false_positive";
                          return (
                            <Line
                              key={`prediction-${match.prediction_index ?? index}`}
                              points={match.prediction_polygon.flat()}
                              closed
                              stroke={isFalsePositive ? "#ef4444" : "#38bdf8"}
                              strokeWidth={3 / scale}
                              dash={[10 / scale, 7 / scale]}
                              fill={
                                isFalsePositive
                                  ? "rgba(239,68,68,0.10)"
                                  : "rgba(56,189,248,0.06)"
                              }
                              listening={false}
                            />
                          );
                        })
                    : null}
                  {annotations.map((annotation) => {
                    const active = annotation.id === selectedId;
                    return (
                      <Line
                        key={annotation.id}
                        points={annotation.polygon.flat()}
                        closed
                        fill={
                          active
                            ? "rgba(245,158,11,0.18)"
                            : "rgba(34,197,94,0.10)"
                        }
                        stroke={active ? "#f59e0b" : "#22c55e"}
                        strokeWidth={active ? 4 / scale : 2 / scale}
                        draggable={mode === "select"}
                        onClick={(event) => {
                          event.cancelBubble = true;
                          selectAnnotation(annotation.id);
                        }}
                        onDragEnd={(event) => {
                          const offsetX = event.target.x();
                          const offsetY = event.target.y();
                          event.target.position({ x: 0, y: 0 });
                          updateAnnotation(annotation.id, {
                            polygon: annotation.polygon.map(([x, y]) => [
                              x + offsetX,
                              y + offsetY,
                            ]),
                          });
                        }}
                      />
                    );
                  })}
                  {annotations.map((annotation, index) => {
                    const [x, y] = annotation.polygon[0];
                    const match = detectionMatches.find(
                      (item) => item.ground_truth_id === annotation.id,
                    );
                    return (
                      <Text
                        key={`label-${annotation.id}`}
                        x={x}
                        y={y - 24 / scale}
                        text={`${index + 1}${
                          showIouOverlay && match
                            ? match.status === "matched"
                              ? ` · IoU ${(match.iou * 100).toFixed(1)}%`
                              : " · 누락"
                            : ""
                        }`}
                        fill="white"
                        fontSize={18 / scale}
                      />
                    );
                  })}
                  {selected?.polygon.map(([x, y], pointIndex) => (
                    <Circle
                      key={`${selected.id}-${pointIndex}`}
                      x={x}
                      y={y}
                      radius={8 / scale}
                      fill="#f59e0b"
                      stroke="white"
                      strokeWidth={2 / scale}
                      draggable
                      onDragMove={(event) => {
                        const polygon = selected.polygon.map((point, index) =>
                          index === pointIndex
                            ? ([event.target.x(), event.target.y()] as Point)
                            : point,
                        );
                        updateAnnotation(selected.id, { polygon });
                      }}
                    />
                  ))}
                  {draftPoints.length ? (
                    <Line
                      points={draftPoints.flat()}
                      stroke="#38bdf8"
                      strokeWidth={3 / scale}
                    />
                  ) : null}
                  {draftPoints.map(([x, y], index) => (
                    <Circle
                      key={`draft-${index}`}
                      x={x}
                      y={y}
                      radius={7 / scale}
                      fill="#38bdf8"
                    />
                  ))}
                </Layer>
              </Stage>
            ) : (
              <div className="flex h-[520px] items-center justify-center text-sm text-zinc-400">
                분석 실행을 선택하세요.
              </div>
            )}
          </div>
        </section>
        <aside className="border bg-white">
          <div className="border-b px-4 py-3">
            <h3 className="font-bold">선택 라벨</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              영역 이동 또는 꼭짓점 드래그로 보정
            </p>
          </div>
          {selected ? (
            <div className="space-y-4 p-4">
              {detectionMatches.length ? (
                <div className="border bg-slate-50 p-3 text-sm">
                  <p className="font-semibold">개별 검출 비교</p>
                  {detail && selectedComparisonViewBox ? (
                    <svg
                      className="mt-2 h-72 w-full bg-zinc-900"
                      viewBox={selectedComparisonViewBox}
                      preserveAspectRatio="xMidYMid meet"
                      aria-label="선택한 책등의 GT와 예측 비교"
                    >
                      <image
                        href={workerUrl(detail.original_url)}
                        x="0"
                        y="0"
                        width={detail.image_width}
                        height={detail.image_height}
                      />
                      {selectedDetectionMatches.map((match, index) =>
                        match.prediction_polygon ? (
                          <polygon
                            key={`preview-${match.prediction_index ?? index}`}
                            points={match.prediction_polygon
                              .map(([x, y]) => `${x},${y}`)
                              .join(" ")}
                            fill={
                              match.status === "false_positive"
                                ? "rgba(239,68,68,0.15)"
                                : "rgba(56,189,248,0.12)"
                            }
                            stroke={
                              match.status === "false_positive"
                                ? "#ef4444"
                                : "#38bdf8"
                            }
                            strokeWidth="4"
                            strokeDasharray="12 8"
                            vectorEffect="non-scaling-stroke"
                          />
                        ) : null,
                      )}
                      <polygon
                        points={selected.polygon
                          .map(([x, y]) => `${x},${y}`)
                          .join(" ")}
                        fill="rgba(34,197,94,0.10)"
                        stroke="#22c55e"
                        strokeWidth="4"
                        vectorEffect="non-scaling-stroke"
                      />
                    </svg>
                  ) : null}
                  {selectedDetectionMatch?.status === "matched" ? (
                    <>
                      <p className="mt-1">
                        IoU {percent(selectedDetectionMatch.iou)} · 예측 신뢰도{" "}
                        {percent(selectedDetectionMatch.confidence)}
                      </p>
                      {selectedFalsePositives.length ? (
                        <p className="mt-1 font-semibold text-red-600">
                          이 책과 겹치는 중복·오검출{" "}
                          {selectedFalsePositives.length}개
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="mt-1 text-red-600">대응 예측 없음(FN)</p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    초록 실선은 GT, 파란 점선은 연결된 예측, 빨간 점선은 이 책과
                    겹치는 중복·오검출입니다.
                  </p>
                </div>
              ) : null}
              <div>
                <Label>제목</Label>
                <Input
                  className="mt-1"
                  value={selected.title ?? ""}
                  onChange={(event) =>
                    updateAnnotation(selected.id, { title: event.target.value })
                  }
                />
              </div>
              <div>
                <Label>저자</Label>
                <Input
                  className="mt-1"
                  value={selected.author ?? ""}
                  onChange={(event) =>
                    updateAnnotation(selected.id, {
                      author: event.target.value,
                    })
                  }
                />
              </div>
              <div>
                <Label>청구기호</Label>
                <Input
                  className="mt-1"
                  value={selected.call_number ?? ""}
                  onChange={(event) =>
                    updateAnnotation(selected.id, {
                      call_number: event.target.value,
                    })
                  }
                />
              </div>
              <div>
                <Label>DB 정답 도서 검색</Label>
                <div className="mt-1 flex gap-2">
                  <Input
                    value={catalogQuery}
                    placeholder={selected.title || "제목 또는 저자"}
                    onChange={(event) => setCatalogQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void searchCatalog();
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void searchCatalog()}
                    disabled={isCatalogSearching}
                  >
                    {isCatalogSearching ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <SearchIcon className="size-4" />
                    )}
                    검색
                  </Button>
                </div>
                {catalogMessage ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {catalogMessage}
                  </p>
                ) : null}
                {catalogResults.length ? (
                  <div className="mt-2 max-h-64 space-y-2 overflow-y-auto">
                    {catalogResults.map((holding) => {
                      if (!holding.book) return null;
                      const isSelected = selected.book_id === holding.book.id;
                      return (
                        <button
                          key={holding.book.id}
                          type="button"
                          className={`w-full border p-3 text-left text-sm transition-colors ${
                            isSelected
                              ? "border-blue-500 bg-blue-50"
                              : "hover:bg-muted"
                          }`}
                          onClick={() => selectCatalogBook(holding)}
                        >
                          <span className="block font-semibold">
                            {holding.book.bookname}
                          </span>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {holding.book.authors || "저자 미상"} ·{" "}
                            {holding.callNumber || "청구기호 없음"}
                          </span>
                          {holding.shelfLocName ? (
                            <span className="mt-1 block text-xs text-muted-foreground">
                              {holding.shelfLocName}
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </div>
              <div>
                <Label>정답 도서 ID (book_id)</Label>
                <Input
                  className="mt-1 font-mono text-xs"
                  placeholder="위 검색 결과에서 실제 책을 선택하세요"
                  value={selected.book_id ?? ""}
                  readOnly
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  같은 책의 여러 복본은 하나의 book_id 정답으로 평가합니다.
                </p>
                {selected.book_id || selected.holding_id ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-2 w-full"
                    onClick={() => {
                      updateAnnotation(selected.id, {
                        book_id: null,
                        holding_id: null,
                      });
                      setCatalogMessage("정답 도서 선택을 해제했습니다.");
                    }}
                  >
                    정답 선택 해제
                  </Button>
                ) : null}
              </div>
              <div>
                <Label>정답 소장 ID (holding_id, 선택 사항)</Label>
                <Input
                  className="mt-1 font-mono text-xs"
                  placeholder="가능하면 RDS LibraryHolding.id 입력"
                  value={selected.holding_id ?? ""}
                  onChange={(event) =>
                    updateAnnotation(selected.id, {
                      holding_id: event.target.value || null,
                    })
                  }
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  입력하면 제목 유사도가 아니라 실제 소장자료 ID로 Top-1/Top-3를
                  평가합니다.
                </p>
              </div>
              <div>
                <Label>배치 정답</Label>
                <Select
                  value={selected.placement_status ?? "normal"}
                  onValueChange={(value: "normal" | "misplaced") =>
                    updateAnnotation(selected.id, { placement_status: value })
                  }
                >
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="normal">정상</SelectItem>
                    <SelectItem value="misplaced">오배열</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="text-xs text-muted-foreground">
                {selected.polygon
                  .map(([x, y]) => `${x.toFixed(1)}, ${y.toFixed(1)}`)
                  .join(" · ")}
              </div>
              <Button
                variant="destructive"
                className="w-full"
                onClick={() => {
                  setAnnotations((current) =>
                    current.filter((item) => item.id !== selected.id),
                  );
                  selectAnnotation(null);
                }}
              >
                <Trash2Icon className="size-4" />
                잘못된 검출 삭제
              </Button>
            </div>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">
              라벨을 선택하세요.
            </p>
          )}
          <div className="border-t p-4">
            <Button
              className="w-full"
              onClick={() => void saveGroundTruth()}
              disabled={!detail || isBusy || annotations.length === 0}
            >
              {isBusy ? (
                <CheckIcon className="size-4 animate-pulse" />
              ) : (
                <SaveIcon className="size-4" />
              )}
              GT 저장 및 평가
            </Button>
          </div>
        </aside>
      </div>
    </>
  );
}
