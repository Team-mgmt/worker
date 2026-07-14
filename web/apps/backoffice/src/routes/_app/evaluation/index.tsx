import { useEffect, useMemo, useRef, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";

import type { KonvaEventObject } from "konva/lib/Node";
import {
  CheckIcon,
  MousePointer2Icon,
  PlusIcon,
  RotateCcwIcon,
  SaveIcon,
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
};
type ArtifactDetail = {
  run_id: string;
  prefix: string;
  result: { inference?: { results?: PredictionResult[] } };
  ground_truth?: {
    annotations?: Annotation[];
    metrics?: DetectionMetrics;
  } | null;
  image_width: number;
  image_height: number;
  original_url: string;
};

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
  const [message, setMessage] = useState("");
  const [isBusy, setIsBusy] = useState(true);
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
      const initial = payload.ground_truth?.annotations?.length
        ? payload.ground_truth.annotations
        : predictionAnnotations(payload);
      setRunId(nextRunId);
      setDetail(payload);
      setAnnotations(initial);
      setMetrics(payload.ground_truth?.metrics ?? null);
      setSelectedId(initial[0]?.id ?? null);
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

  const updateAnnotation = (id: string, update: Partial<Annotation>) => {
    setAnnotations((current) =>
      current.map((item) => (item.id === id ? { ...item, ...update } : item)),
    );
  };
  const resetToPrediction = () => {
    if (!detail) return;
    const next = predictionAnnotations(detail);
    setAnnotations(next);
    setSelectedId(next[0]?.id ?? null);
    setMetrics(null);
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
        { id, class: "book_spine", polygon: next },
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
      const payload = (await response.json()) as { metrics: DetectionMetrics };
      setMetrics(payload.metrics);
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
                          setSelectedId(annotation.id);
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
                    return (
                      <Text
                        key={`label-${annotation.id}`}
                        x={x}
                        y={y - 24 / scale}
                        text={`${index + 1}`}
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
                  setSelectedId(null);
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
