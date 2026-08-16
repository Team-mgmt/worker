type DetectionMetrics = {
  ground_truth_count: number;
  prediction_count: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  precision: number;
  recall: number;
  f1: number;
  mean_matched_iou: number;
};

type StructureMetrics = {
  correct_ground_truth_count: number;
  split_ground_truth_count: number;
  merged_ground_truth_count: number;
  missed_ground_truth_count: number;
};

type MatchingMetrics = {
  title_normalized_accuracy: number;
  call_number_exact_accuracy: number;
  kdc_accuracy: number;
  book_code_accuracy: number;
  db_evaluated_count: number;
  top1_accuracy: number;
  top3_accuracy: number;
};

function percentage(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function AccuracyBar({
  label,
  value,
  color = "bg-sky-600",
}: {
  label: string;
  value: number;
  color?: string;
}) {
  const width = Math.max(0, Math.min(100, value * 100));

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="font-bold tabular-nums">{percentage(value)}</span>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-zinc-100">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

function DetectionConfusionMatrix({ metrics }: { metrics: DetectionMetrics }) {
  return (
    <div>
      <div className="mb-3">
        <h4 className="font-bold">책등 검출 혼동행렬</h4>
        <p className="mt-1 text-xs text-muted-foreground">
          IoU 기준을 통과한 책등 연결 결과입니다.
        </p>
      </div>
      <div className="grid grid-cols-[5.5rem_repeat(2,minmax(0,1fr))] overflow-hidden rounded-lg border text-center text-sm">
        <div className="bg-zinc-50 p-2 text-xs text-muted-foreground">
          실제 ＼ 예측
        </div>
        <div className="border-l bg-zinc-50 p-2 font-medium">책등</div>
        <div className="border-l bg-zinc-50 p-2 font-medium">배경</div>

        <div className="border-t bg-zinc-50 p-3 font-medium">책등</div>
        <div className="border-l border-t bg-emerald-100 p-3">
          <strong className="block text-2xl tabular-nums text-emerald-800">
            {metrics.true_positive}
          </strong>
          <span className="text-xs text-emerald-700">TP</span>
        </div>
        <div className="border-l border-t bg-red-50 p-3">
          <strong className="block text-2xl tabular-nums text-red-700">
            {metrics.false_negative}
          </strong>
          <span className="text-xs text-red-600">FN</span>
        </div>

        <div className="border-t bg-zinc-50 p-3 font-medium">배경</div>
        <div className="border-l border-t bg-amber-100 p-3">
          <strong className="block text-2xl tabular-nums text-amber-800">
            {metrics.false_positive}
          </strong>
          <span className="text-xs text-amber-700">FP</span>
        </div>
        <div className="border-l border-t bg-zinc-100 p-3 text-muted-foreground">
          <strong className="block text-2xl">—</strong>
          <span className="text-xs">TN 미정의</span>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        객체 검출에서는 가능한 모든 배경 영역의 수를 정의할 수 없어 TN을
        계산하지 않습니다.
      </p>
    </div>
  );
}

function StructureSummary({ metrics }: { metrics: StructureMetrics }) {
  const total =
    metrics.correct_ground_truth_count +
    metrics.split_ground_truth_count +
    metrics.merged_ground_truth_count +
    metrics.missed_ground_truth_count;
  const segments = [
    {
      label: "정상",
      value: metrics.correct_ground_truth_count,
      color: "bg-emerald-500",
    },
    {
      label: "분할",
      value: metrics.split_ground_truth_count,
      color: "bg-amber-500",
    },
    {
      label: "병합 영향",
      value: metrics.merged_ground_truth_count,
      color: "bg-violet-500",
    },
    {
      label: "누락",
      value: metrics.missed_ground_truth_count,
      color: "bg-red-500",
    },
  ];

  return (
    <div>
      <h4 className="font-bold">검출 구조</h4>
      <p className="mt-1 text-xs text-muted-foreground">
        GT 한 권을 기준으로 정상·분할·병합·누락을 구분합니다.
      </p>
      <div className="mt-5 flex h-5 overflow-hidden rounded-full bg-zinc-100">
        {segments.map((segment) =>
          segment.value ? (
            <div
              key={segment.label}
              className={segment.color}
              style={{ width: `${(segment.value / total) * 100}%` }}
              title={`${segment.label} ${segment.value}권`}
            />
          ) : null,
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        {segments.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${segment.color}`} />
            <span className="text-muted-foreground">{segment.label}</span>
            <strong className="ml-auto tabular-nums">{segment.value}권</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function MatchingSummary({ metrics }: { metrics: MatchingMetrics }) {
  const top1Correct = Math.round(
    metrics.db_evaluated_count * metrics.top1_accuracy,
  );
  const top3Correct = Math.round(
    metrics.db_evaluated_count * metrics.top3_accuracy,
  );
  const top3Added = Math.max(0, top3Correct - top1Correct);
  const failed = Math.max(0, metrics.db_evaluated_count - top3Correct);

  return (
    <div>
      <h4 className="font-bold">DB 도서 식별 결과</h4>
      <p className="mt-1 text-xs text-muted-foreground">
        정답 도서가 후보 순위에 포함된 결과입니다.
      </p>
      <div className="mt-4 grid grid-cols-3 overflow-hidden rounded-lg border text-center">
        <div className="bg-emerald-50 px-2 py-4">
          <strong className="block text-2xl tabular-nums text-emerald-800">
            {top1Correct}
          </strong>
          <span className="text-xs text-emerald-700">Top-1 정답</span>
        </div>
        <div className="border-l bg-sky-50 px-2 py-4">
          <strong className="block text-2xl tabular-nums text-sky-800">
            {top3Added}
          </strong>
          <span className="text-xs text-sky-700">Top-3 추가</span>
        </div>
        <div className="border-l bg-red-50 px-2 py-4">
          <strong className="block text-2xl tabular-nums text-red-700">
            {failed}
          </strong>
          <span className="text-xs text-red-600">Top-3 실패</span>
        </div>
      </div>
      <div className="mt-4 space-y-4">
        <AccuracyBar label="DB Top-1" value={metrics.top1_accuracy} />
        <AccuracyBar
          label="DB Top-3"
          value={metrics.top3_accuracy}
          color="bg-indigo-600"
        />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        DB GT {metrics.db_evaluated_count}권 기준
      </p>
    </div>
  );
}

function OcrFieldAccuracy({ metrics }: { metrics: MatchingMetrics }) {
  return (
    <div>
      <h4 className="font-bold">OCR 필드별 정확도</h4>
      <p className="mt-1 text-xs text-muted-foreground">
        GT와 연결된 책등의 정규화 필드 비교 결과입니다.
      </p>
      <div className="mt-4 space-y-4">
        <AccuracyBar
          label="제목"
          value={metrics.title_normalized_accuracy}
          color="bg-cyan-600"
        />
        <AccuracyBar
          label="청구기호"
          value={metrics.call_number_exact_accuracy}
          color="bg-amber-500"
        />
        <AccuracyBar
          label="KDC"
          value={metrics.kdc_accuracy}
          color="bg-emerald-600"
        />
        <AccuracyBar
          label="도서기호"
          value={metrics.book_code_accuracy}
          color="bg-violet-600"
        />
      </div>
    </div>
  );
}

export function EvaluationCharts({
  detectionMetrics,
  structureMetrics,
  matchingMetrics,
}: {
  detectionMetrics: DetectionMetrics;
  structureMetrics?: StructureMetrics | null;
  matchingMetrics?: MatchingMetrics | null;
}) {
  return (
    <section className="mb-4 border bg-white p-4 shadow-sm">
      <div className="mb-4">
        <h3 className="text-lg font-extrabold">평가 결과 시각화</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          숫자 지표와 동일한 GT 평가 결과를 차트로 표시합니다.
        </p>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-xl border p-4">
          <DetectionConfusionMatrix metrics={detectionMetrics} />
        </div>
        {structureMetrics ? (
          <div className="rounded-xl border p-4">
            <StructureSummary metrics={structureMetrics} />
          </div>
        ) : null}
        {matchingMetrics ? (
          <>
            <div className="rounded-xl border p-4">
              <MatchingSummary metrics={matchingMetrics} />
            </div>
            <div className="rounded-xl border p-4">
              <OcrFieldAccuracy metrics={matchingMetrics} />
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}
