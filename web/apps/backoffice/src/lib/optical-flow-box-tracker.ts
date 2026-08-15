import cvModule, { type CV, type Mat } from "@techstark/opencv-js";

export type TrackedBox = {
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
};

let openCvPromise: Promise<CV> | null = null;

export function loadOpenCv(): Promise<CV> {
  if (openCvPromise) return openCvPromise;
  openCvPromise = (async () => {
    if (cvModule instanceof Promise) return cvModule;
    const cv = cvModule as CV & {
      calledRun?: boolean;
      onRuntimeInitialized?: () => void;
    };
    if (cv.calledRun) return cv;
    await new Promise<void>((resolve) => {
      cv.onRuntimeInitialized = resolve;
    });
    return cv;
  })();
  return openCvPromise;
}

function median(values: number[]) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export class OpticalFlowBoxTracker {
  private readonly cv: CV;
  private previousGray: Mat | null = null;
  private previousPoints: Mat | null = null;
  private box: TrackedBox;
  private frameCount = 0;

  constructor(
    cv: CV,
    initialFrame: HTMLCanvasElement,
    initialBox: Omit<TrackedBox, "confidence">,
  ) {
    this.cv = cv;
    this.box = { ...initialBox, confidence: 1 };
    this.resetFeatures(initialFrame);
  }

  private frameToGray(frame: HTMLCanvasElement) {
    const rgba = this.cv.imread(frame);
    const gray = new this.cv.Mat();
    this.cv.cvtColor(rgba, gray, this.cv.COLOR_RGBA2GRAY);
    rgba.delete();
    return gray;
  }

  private detectPoints(gray: Mat) {
    const corners = new this.cv.Mat();
    this.cv.goodFeaturesToTrack(gray, corners, 120, 0.01, 4);
    const values: number[] = [];
    const x2 = this.box.x + this.box.width;
    const y2 = this.box.y + this.box.height;
    for (let index = 0; index < corners.rows; index += 1) {
      const x = corners.data32F[index * 2];
      const y = corners.data32F[index * 2 + 1];
      if (x >= this.box.x && x <= x2 && y >= this.box.y && y <= y2) {
        values.push(x, y);
      }
    }
    corners.delete();
    if (values.length < 12) return null;
    return this.cv.matFromArray(values.length / 2, 1, this.cv.CV_32FC2, values);
  }

  private resetFeatures(frame: HTMLCanvasElement) {
    const gray = this.frameToGray(frame);
    const points = this.detectPoints(gray);
    this.previousGray?.delete();
    this.previousPoints?.delete();
    this.previousGray = gray;
    this.previousPoints = points;
  }

  update(frame: HTMLCanvasElement): TrackedBox | null {
    if (!this.previousGray || !this.previousPoints) return null;
    const currentGray = this.frameToGray(frame);
    const nextPoints = new this.cv.Mat();
    const status = new this.cv.Mat();
    const error = new this.cv.Mat();
    this.cv.calcOpticalFlowPyrLK(
      this.previousGray,
      currentGray,
      this.previousPoints,
      nextPoints,
      status,
      error,
      new this.cv.Size(21, 21),
      3,
    );

    const movements: Array<{ dx: number; dy: number; x: number; y: number }> =
      [];
    for (let index = 0; index < status.rows; index += 1) {
      if (status.data[index] !== 1) continue;
      const previousX = this.previousPoints.data32F[index * 2];
      const previousY = this.previousPoints.data32F[index * 2 + 1];
      const x = nextPoints.data32F[index * 2];
      const y = nextPoints.data32F[index * 2 + 1];
      movements.push({ dx: x - previousX, dy: y - previousY, x, y });
    }

    status.delete();
    error.delete();
    nextPoints.delete();
    if (movements.length < 6) {
      currentGray.delete();
      return null;
    }

    const dx = median(movements.map((movement) => movement.dx));
    const dy = median(movements.map((movement) => movement.dy));
    const inliers = movements.filter(
      (movement) =>
        Math.abs(movement.dx - dx) <= 7 && Math.abs(movement.dy - dy) <= 7,
    );
    if (inliers.length < 6) {
      currentGray.delete();
      return null;
    }

    this.box = {
      ...this.box,
      x: Math.max(0, Math.min(frame.width - this.box.width, this.box.x + dx)),
      y: Math.max(0, Math.min(frame.height - this.box.height, this.box.y + dy)),
      confidence: inliers.length / movements.length,
    };
    this.previousGray.delete();
    this.previousPoints.delete();
    this.previousGray = currentGray;
    this.previousPoints = this.cv.matFromArray(
      inliers.length,
      1,
      this.cv.CV_32FC2,
      inliers.flatMap((movement) => [movement.x, movement.y]),
    );
    this.frameCount += 1;

    if (this.frameCount % 20 === 0) {
      const refreshed = this.detectPoints(currentGray);
      if (refreshed) {
        this.previousPoints.delete();
        this.previousPoints = refreshed;
      }
    }
    return { ...this.box };
  }

  dispose() {
    this.previousGray?.delete();
    this.previousPoints?.delete();
    this.previousGray = null;
    this.previousPoints = null;
  }
}
