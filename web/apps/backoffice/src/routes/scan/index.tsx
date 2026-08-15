import { useCallback, useEffect, useRef, useState } from "react";

import { createFileRoute } from "@tanstack/react-router";

import {
  CameraIcon,
  ImagesIcon,
  Loader2Icon,
  ScanSearchIcon,
  SearchIcon,
  SquareIcon,
  VideoIcon,
} from "lucide-react";

import { LIBRARIES } from "@/lib/libraries";
import type {
  OpticalFlowBoxTracker,
  TrackedBox,
} from "@/lib/optical-flow-box-tracker";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export const Route = createFileRoute("/scan/")({ component: PatronBookFinder });

type Holding = {
  id: string;
  callNumber?: string | null;
  shelfLocName?: string | null;
  book?: {
    isbn13?: string | null;
    bookname: string;
    authors?: string | null;
  } | null;
};

type TargetResult = {
  status: "found" | "possible" | "not_found";
  calibration_status: "uncalibrated";
  location_hint?: string | null;
  score_margin?: number | null;
  best_detection?: {
    detected_order: number;
    bbox?: number[] | null;
    score: number;
    ocr_raw_text?: string | null;
  } | null;
  candidate_detections: Array<{
    detected_order: number;
    bbox?: number[] | null;
    score: number;
    ocr_title?: string | null;
    ocr_call_number?: string | null;
  }>;
};

type TargetVideoResult = {
  video_run_id: string;
  duration_seconds: number;
  analyzed_frame_count: number;
  selected_timestamp_seconds: number;
  selected_frame_data_url: string;
  target_search: TargetResult;
};

function apiUrl(path: string) {
  const base = import.meta.env.VITE_BASE_URL || "/api";
  return new URL(
    `${base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`,
    window.location.origin,
  );
}

function workerUrl(path: string) {
  const base =
    import.meta.env.VITE_WORKER_BASE_URL ??
    (import.meta.env.DEV ? "http://localhost:8000" : "/worker");
  return new URL(
    `${base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`,
    window.location.origin,
  );
}

function PatronBookFinder() {
  const [libraryCode, setLibraryCode] = useState("111058");
  const [query, setQuery] = useState("");
  const [books, setBooks] = useState<Holding[]>([]);
  const [target, setTarget] = useState<Holding | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [result, setResult] = useState<TargetResult | null>(null);
  const [videoResult, setVideoResult] = useState<TargetVideoResult | null>(
    null,
  );
  const [liveActive, setLiveActive] = useState(false);
  const [liveStatus, setLiveStatus] = useState("");
  const [liveResult, setLiveResult] = useState<TargetResult | null>(null);
  const [liveFrameSize, setLiveFrameSize] = useState({ width: 1, height: 1 });
  const [trackedBox, setTrackedBox] = useState<TrackedBox | null>(null);
  const liveVideoRef = useRef<HTMLVideoElement | null>(null);
  const liveStreamRef = useRef<MediaStream | null>(null);
  const liveSessionRef = useRef(0);
  const trackerRef = useRef<OpticalFlowBoxTracker | null>(null);
  const trackerCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const trackerAnimationRef = useRef<number | null>(null);
  const trackedBoxElementRef = useRef<HTMLDivElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const stopLiveCamera = useCallback((message?: string) => {
    liveSessionRef.current += 1;
    liveStreamRef.current?.getTracks().forEach((track) => track.stop());
    liveStreamRef.current = null;
    if (trackerAnimationRef.current !== null)
      cancelAnimationFrame(trackerAnimationRef.current);
    trackerAnimationRef.current = null;
    trackerRef.current?.dispose();
    trackerRef.current = null;
    trackerCanvasRef.current = null;
    setLiveActive(false);
    setLiveResult(null);
    setTrackedBox(null);
    setBusy(false);
    if (message !== undefined) setLiveStatus(message);
  }, []);

  useEffect(() => () => stopLiveCamera(), [stopLiveCamera]);

  const startOpticalFlowTracking = async (
    sourceFrame: HTMLCanvasElement,
    bbox: number[],
    sessionId: number,
  ) => {
    if (bbox.length !== 4 || liveSessionRef.current !== sessionId) return false;
    const { loadOpenCv, OpticalFlowBoxTracker: Tracker } =
      await import("@/lib/optical-flow-box-tracker");
    const cv = await loadOpenCv();
    if (liveSessionRef.current !== sessionId) return false;

    // Optical flow runs locally for every rendered frame. Keeping the working
    // image small gives mobile browsers a realistic chance of sustaining 30 FPS.
    const trackerWidth = Math.min(480, sourceFrame.width);
    const trackerHeight = Math.round(
      sourceFrame.height * (trackerWidth / sourceFrame.width),
    );
    const trackerCanvas = document.createElement("canvas");
    trackerCanvas.width = trackerWidth;
    trackerCanvas.height = trackerHeight;
    trackerCanvas
      .getContext("2d", { willReadFrequently: true })
      ?.drawImage(sourceFrame, 0, 0, trackerWidth, trackerHeight);
    const scaleX = trackerWidth / sourceFrame.width;
    const scaleY = trackerHeight / sourceFrame.height;
    const initialBox = {
      x: bbox[0] * scaleX,
      y: bbox[1] * scaleY,
      width: (bbox[2] - bbox[0]) * scaleX,
      height: (bbox[3] - bbox[1]) * scaleY,
    };

    trackerRef.current?.dispose();
    trackerRef.current = new Tracker(cv, trackerCanvas, initialBox);
    trackerCanvasRef.current = trackerCanvas;
    setTrackedBox({ ...initialBox, confidence: 1 });
    setLiveFrameSize({ width: trackerWidth, height: trackerHeight });

    if (trackerAnimationRef.current !== null)
      cancelAnimationFrame(trackerAnimationRef.current);
    const trackFrame = () => {
      if (liveSessionRef.current !== sessionId) return;
      const video = liveVideoRef.current;
      const canvas = trackerCanvasRef.current;
      const tracker = trackerRef.current;
      if (!video || !canvas || !tracker) return;
      canvas
        .getContext("2d", { willReadFrequently: true })
        ?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const nextBox = tracker.update(canvas);
      if (!nextBox || nextBox.confidence < 0.35) {
        tracker.dispose();
        trackerRef.current = null;
        setTrackedBox(null);
        setLiveStatus(
          "추적 대상을 놓쳤습니다. 중지 후 라이브 탐색을 다시 시작해주세요.",
        );
        return;
      }
      const boxElement = trackedBoxElementRef.current;
      if (boxElement) {
        boxElement.style.left = `${(nextBox.x / canvas.width) * 100}%`;
        boxElement.style.top = `${(nextBox.y / canvas.height) * 100}%`;
        boxElement.style.width = `${(nextBox.width / canvas.width) * 100}%`;
        boxElement.style.height = `${(nextBox.height / canvas.height) * 100}%`;
      }
      trackerAnimationRef.current = requestAnimationFrame(trackFrame);
    };
    trackerAnimationRef.current = requestAnimationFrame(trackFrame);
    return true;
  };

  const targetBody = (
    file: File,
    saveArtifacts = true,
    allowLocalFallback = true,
  ) => {
    if (!target?.book) return null;
    const body = new FormData();
    body.set("file", file);
    body.set("holding_id", target.id);
    body.set("library_code", libraryCode);
    body.set("target_title", target.book.bookname);
    if (target.book.authors) body.set("target_author", target.book.authors);
    if (target.callNumber) body.set("target_call_number", target.callNumber);
    if (target.book.isbn13) body.set("target_isbn13", target.book.isbn13);
    body.set("save_artifacts", saveArtifacts ? "true" : "false");
    body.set("allow_local_fallback", allowLocalFallback ? "true" : "false");
    return body;
  };

  const search = async () => {
    if (query.trim().length < 2)
      return setError("검색어를 두 글자 이상 입력하세요.");
    setBusy(true);
    setError("");
    try {
      const url = apiUrl("public/library-books");
      url.searchParams.set("libraryCode", libraryCode);
      url.searchParams.set("query", query.trim());
      const response = await fetch(url);
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload?.message || "도서 검색에 실패했습니다.");
      setBooks(payload.data ?? []);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "도서 검색에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };

  const analyze = async (file: File) => {
    if (!target?.book) return;
    setBusy(true);
    setError("");
    setResult(null);
    setVideoResult(null);
    const objectUrl = URL.createObjectURL(file);
    setPreview(objectUrl);
    const image = new Image();
    image.src = objectUrl;
    await image.decode();
    setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
    try {
      const body = targetBody(file);
      if (!body) return;
      const response = await fetch(workerUrl("inference/find_target_book"), {
        method: "POST",
        body,
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload?.detail || "책 찾기에 실패했습니다.");
      setResult(payload as TargetResult);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "책 찾기에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };

  const startLiveSearch = async () => {
    if (!target?.book || liveActive) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(
        "이 브라우저에서는 실시간 카메라를 사용할 수 없습니다. HTTPS 접속인지 확인하세요.",
      );
      return;
    }

    const sessionId = liveSessionRef.current + 1;
    liveSessionRef.current = sessionId;
    setBusy(true);
    setError("");
    setResult(null);
    setVideoResult(null);
    setPreview(null);
    setLiveResult(null);
    setLiveStatus("카메라 권한을 확인하고 있습니다.");

    try {
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: { exact: "environment" },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            frameRate: { ideal: 30, max: 30 },
          },
        });
      } catch (cameraError) {
        if (
          cameraError instanceof DOMException &&
          cameraError.name !== "OverconstrainedError" &&
          cameraError.name !== "NotFoundError"
        ) {
          throw cameraError;
        }
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            frameRate: { ideal: 30, max: 30 },
          },
        });
      }
      if (liveSessionRef.current !== sessionId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      liveStreamRef.current = stream;
      setLiveActive(true);
      setLiveStatus("후면 카메라가 연결되었습니다. 분석 0/4 대기 중");
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve()),
      );
      const video = liveVideoRef.current;
      if (!video) throw new Error("카메라 화면을 초기화하지 못했습니다.");
      video.srcObject = stream;
      await video.play();

      let bestPossible:
        | {
            result: TargetResult;
            dataUrl: string;
            width: number;
            height: number;
          }
        | undefined;
      let lastAttempt:
        | {
            result: TargetResult;
            dataUrl: string;
            width: number;
            height: number;
          }
        | undefined;

      for (let frameNumber = 1; frameNumber <= 4; frameNumber += 1) {
        if (liveSessionRef.current !== sessionId) return;
        if (!video.videoWidth || !video.videoHeight) {
          await new Promise((resolve) => setTimeout(resolve, 300));
          frameNumber -= 1;
          continue;
        }

        setLiveResult(null);
        setLiveStatus(
          `프레임 ${frameNumber}/4 분석 중 · 카메라를 잠시 고정해주세요`,
        );
        const scale = Math.min(1, 1280 / video.videoWidth);
        const width = Math.round(video.videoWidth * scale);
        const height = Math.round(video.videoHeight * scale);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        setLiveFrameSize({ width, height });
        canvas.getContext("2d")?.drawImage(video, 0, 0, width, height);
        const blob = await new Promise<Blob | null>((resolve) =>
          canvas.toBlob(resolve, "image/jpeg", 0.8),
        );
        if (!blob) throw new Error("카메라 프레임을 생성하지 못했습니다.");
        const frameFile = new File([blob], `live-frame-${frameNumber}.jpg`, {
          type: "image/jpeg",
        });
        const body = targetBody(frameFile, false, false);
        if (!body) return;
        const response = await fetch(workerUrl("inference/find_target_book"), {
          method: "POST",
          body,
        });
        const payload = await response.json();
        if (!response.ok)
          throw new Error(
            payload?.detail || "실시간 프레임 분석에 실패했습니다.",
          );
        if (liveSessionRef.current !== sessionId) return;

        const frameResult = payload as TargetResult;
        const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
        lastAttempt = { result: frameResult, dataUrl, width, height };
        setLiveResult(frameResult);
        const trackingBbox = frameResult.best_detection?.bbox;
        if (trackingBbox) {
          await startOpticalFlowTracking(canvas, trackingBbox, sessionId);
        }
        if (
          frameResult.status === "possible" &&
          (!bestPossible ||
            (frameResult.best_detection?.score ?? 0) >
              (bestPossible.result.best_detection?.score ?? 0))
        ) {
          bestPossible = lastAttempt;
        }
        if (frameResult.status === "found") {
          setResult(frameResult);
          if (trackerRef.current) {
            setLiveStatus(
              "목표 도서를 찾았습니다. 브라우저가 최대 30FPS로 추적 중입니다.",
            );
            setBusy(true);
            return;
          }
          setPreview(dataUrl);
          setImageSize({ width, height });
          stopLiveCamera(
            "목표 도서를 발견했지만 추적 특징이 부족해 정확한 프레임에서 멈췄습니다.",
          );
          return;
        }
        setLiveStatus(
          frameResult.status === "possible"
            ? `프레임 ${frameNumber}/4 · 유사 후보 발견, 계속 확인 중`
            : `프레임 ${frameNumber}/4 · 아직 목표 도서를 찾지 못했습니다`,
        );
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }

      const finalAttempt = bestPossible ?? lastAttempt;
      if (finalAttempt) {
        setPreview(finalAttempt.dataUrl);
        setImageSize({
          width: finalAttempt.width,
          height: finalAttempt.height,
        });
        setResult(finalAttempt.result);
      }
      stopLiveCamera("라이브 탐색이 끝났습니다. 필요하면 다시 시작하세요.");
    } catch (cause) {
      stopLiveCamera("");
      setError(
        cause instanceof Error
          ? cause.message
          : "실시간 카메라를 시작하지 못했습니다.",
      );
    }
  };

  const analyzeVideo = async (file: File) => {
    if (!target?.book) return;
    setBusy(true);
    setError("");
    setResult(null);
    setVideoResult(null);
    setPreview(null);
    try {
      const body = new FormData();
      body.set("file", file);
      body.set("holding_id", target.id);
      body.set("library_code", libraryCode);
      body.set("target_title", target.book.bookname);
      if (target.book.authors) body.set("target_author", target.book.authors);
      if (target.callNumber) body.set("target_call_number", target.callNumber);
      if (target.book.isbn13) body.set("target_isbn13", target.book.isbn13);
      body.set("sample_interval_seconds", "1");
      body.set("max_analyzed_frames", "3");

      const response = await fetch(
        workerUrl("inference/find_target_book_video"),
        { method: "POST", body },
      );
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload?.detail || "동영상에서 책을 찾지 못했습니다.");

      const videoPayload = payload as TargetVideoResult;
      const selectedImage = new Image();
      selectedImage.src = videoPayload.selected_frame_data_url;
      await selectedImage.decode();
      setImageSize({
        width: selectedImage.naturalWidth,
        height: selectedImage.naturalHeight,
      });
      setPreview(videoPayload.selected_frame_data_url);
      setVideoResult(videoPayload);
      setResult(videoPayload.target_search);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "동영상에서 책을 찾지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };

  const highlightedDetections = result?.candidate_detections ?? [];
  const resultText =
    result?.status === "found"
      ? `찾았습니다. ${result.location_hint ?? "표시된 책을 확인하세요."}`
      : result?.status === "possible"
        ? "후보가 2권 있습니다. 노란색으로 표시된 책의 제목을 확인하거나 가까이에서 다시 촬영하세요."
        : result
          ? "현재 사진에서는 목표 책을 찾지 못했습니다."
          : null;

  return (
    <main className="mx-auto min-h-dvh max-w-2xl bg-zinc-50 px-4 py-6 text-zinc-950">
      <h1 className="text-2xl font-black">ShelfAlign 책 찾기</h1>
      <p className="mt-1 text-sm text-zinc-600">
        찾을 책을 선택하고 서가를 촬영하세요.
      </p>

      <section className="mt-5 space-y-3 border bg-white p-4">
        <Select
          value={libraryCode}
          onValueChange={(value) => {
            setLibraryCode(value);
            setBooks([]);
            setTarget(null);
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
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void search();
            }}
            placeholder="제목, 저자, ISBN, 청구기호"
          />
          <Button onClick={() => void search()} disabled={busy}>
            <SearchIcon className="size-4" />
            검색
          </Button>
        </div>
        {books.length ? (
          <div className="divide-y border">
            {books.map((holding) => (
              <button
                key={holding.id}
                type="button"
                className="block w-full px-3 py-3 text-left hover:bg-zinc-50"
                onClick={() => {
                  setTarget(holding);
                  setBooks([]);
                  setResult(null);
                }}
              >
                <p className="font-semibold">
                  {holding.book?.bookname ?? "도서 정보 없음"}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  {holding.book?.authors || "저자 미상"} ·{" "}
                  {holding.callNumber || "청구기호 없음"}
                </p>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {target?.book ? (
        <section className="mt-4 border border-blue-200 bg-blue-50 p-4">
          <p className="text-xs font-bold text-blue-700">찾을 책</p>
          <p className="mt-1 font-bold">{target.book.bookname}</p>
          <p className="text-sm text-zinc-600">
            {target.book.authors || "저자 미상"} ·{" "}
            {target.callNumber || "청구기호 없음"}
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            {target.shelfLocName || "자료실 위치 미확인"}
          </p>
        </section>
      ) : null}

      {target ? (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <Button asChild size="lg" disabled={busy}>
            <label className="cursor-pointer">
              {busy ? (
                <Loader2Icon className="size-5 animate-spin" />
              ) : (
                <CameraIcon className="size-5" />
              )}
              카메라 촬영
              <input
                className="sr-only"
                type="file"
                accept="image/*"
                capture="environment"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void analyze(file);
                  event.target.value = "";
                }}
              />
            </label>
          </Button>
          <Button asChild size="lg" variant="outline" disabled={busy}>
            <label className="cursor-pointer bg-white">
              <ImagesIcon className="size-5" />
              갤러리 선택
              <input
                className="sr-only"
                type="file"
                accept="image/*"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void analyze(file);
                  event.target.value = "";
                }}
              />
            </label>
          </Button>
          <Button
            asChild
            size="lg"
            variant="secondary"
            disabled={busy}
            className="col-span-2"
          >
            <label className="cursor-pointer">
              {busy ? (
                <Loader2Icon className="size-5 animate-spin" />
              ) : (
                <VideoIcon className="size-5" />
              )}
              동영상으로 찾기 (최대 30초)
              <input
                className="sr-only"
                type="file"
                accept="video/mp4,video/quicktime,video/webm,.m4v"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void analyzeVideo(file);
                  event.target.value = "";
                }}
              />
            </label>
          </Button>
          <Button
            size="lg"
            variant="default"
            disabled={busy && !liveActive}
            className="col-span-2"
            onClick={() => void startLiveSearch()}
          >
            <ScanSearchIcon className="size-5" />
            실시간 카메라로 찾기
          </Button>
        </div>
      ) : null}

      {liveActive ? (
        <section className="mt-4 overflow-hidden border bg-zinc-950 text-white">
          <div className="relative">
            <video
              ref={liveVideoRef}
              autoPlay
              muted
              playsInline
              className="block w-full"
            />
            <div className="pointer-events-none absolute inset-3 border-2 border-dashed border-white/50" />
            {trackedBox ? (
              <div
                ref={trackedBoxElementRef}
                className="pointer-events-none absolute border-4 border-green-400 bg-green-400/10"
                style={{
                  left: `${(trackedBox.x / liveFrameSize.width) * 100}%`,
                  top: `${(trackedBox.y / liveFrameSize.height) * 100}%`,
                  width: `${(trackedBox.width / liveFrameSize.width) * 100}%`,
                  height: `${(trackedBox.height / liveFrameSize.height) * 100}%`,
                }}
              >
                <span className="absolute -top-7 left-0 whitespace-nowrap bg-green-600 px-2 py-1 text-xs font-bold">
                  목표 도서 추적 중
                </span>
              </div>
            ) : null}
            {!trackedBox
              ? (liveResult?.candidate_detections ?? []).map(
                  (detection, index) => {
                    const bbox = detection.bbox;
                    if (!bbox || bbox.length !== 4) return null;
                    return (
                      <div
                        key={detection.detected_order}
                        className="pointer-events-none absolute border-4 border-amber-400 bg-amber-400/10"
                        style={{
                          left: `${(bbox[0] / liveFrameSize.width) * 100}%`,
                          top: `${(bbox[1] / liveFrameSize.height) * 100}%`,
                          width: `${((bbox[2] - bbox[0]) / liveFrameSize.width) * 100}%`,
                          height: `${((bbox[3] - bbox[1]) / liveFrameSize.height) * 100}%`,
                        }}
                      >
                        <span className="absolute -top-7 left-0 bg-amber-500 px-2 py-1 text-xs font-bold">
                          최근 후보 {index + 1}
                        </span>
                      </div>
                    );
                  },
                )
              : null}
          </div>
          <div className="flex items-center justify-between gap-3 p-3">
            <p className="text-sm">{liveStatus}</p>
            <Button
              size="sm"
              variant="destructive"
              onClick={() =>
                stopLiveCamera("사용자가 라이브 탐색을 중지했습니다.")
              }
            >
              <SquareIcon className="size-4" />
              중지
            </Button>
          </div>
          <p className="px-3 pb-3 text-xs text-zinc-400">
            서버 분석 결과가 도착할 때마다 최근 후보가 표시됩니다. 정확한 위치
            확인을 위해 카메라를 천천히 움직이세요.
          </p>
        </section>
      ) : liveStatus ? (
        <p className="mt-4 border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          {liveStatus}
        </p>
      ) : null}

      {error ? (
        <p className="mt-4 border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      ) : null}
      {preview ? (
        <section className="relative mt-4 overflow-hidden bg-zinc-950">
          <img
            src={preview}
            alt="촬영한 서가"
            className="block max-h-[60vh] w-full object-contain"
          />
          {highlightedDetections.map((detection, index) => {
            const bbox = detection.bbox;
            if (!bbox || bbox.length !== 4) return null;
            const isPossible = result?.status === "possible";
            return (
              <div
                key={detection.detected_order}
                className={`absolute border-4 ${isPossible ? "border-amber-400 bg-amber-400/10" : "border-red-500 bg-red-500/10"}`}
                style={{
                  left: `${(bbox[0] / imageSize.width) * 100}%`,
                  top: `${(bbox[1] / imageSize.height) * 100}%`,
                  width: `${((bbox[2] - bbox[0]) / imageSize.width) * 100}%`,
                  height: `${((bbox[3] - bbox[1]) / imageSize.height) * 100}%`,
                }}
              >
                <span
                  className={`absolute -top-7 left-0 px-2 py-1 text-xs font-bold text-white ${isPossible ? "bg-amber-500" : "bg-red-600"}`}
                >
                  후보 {index + 1}
                </span>
              </div>
            );
          })}
        </section>
      ) : null}
      {resultText ? (
        <section className="mt-4 border bg-white p-4">
          <p className="text-lg font-bold">{resultText}</p>
          {videoResult ? (
            <p className="mt-2 text-sm font-medium text-blue-700">
              영상 {videoResult.selected_timestamp_seconds.toFixed(1)}초 지점 ·{" "}
              {videoResult.analyzed_frame_count}개 프레임 분석
            </p>
          ) : null}
          {result?.best_detection ? (
            <p className="mt-2 text-sm text-zinc-600">
              일치 점수 {result.best_detection.score.toFixed(1)} · 후보 차이{" "}
              {(result.score_margin ?? 0).toFixed(1)}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-amber-700">
            현재 판정 기준은 GT 평가 전 임시 기준입니다.
          </p>
        </section>
      ) : null}
    </main>
  );
}
