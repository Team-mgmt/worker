import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

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

const COLORS = {
  navy: "#355070",
  blue: "#4C78A8",
  teal: "#59A14F",
  cyan: "#76B7B2",
  amber: "#F2A65A",
  red: "#E15759",
  violet: "#9C755F",
  grid: "#E5E7EB",
  muted: "#6B7280",
};

function percent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function ChartCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <div className="mb-5">
        <h4 className="font-bold tracking-tight text-zinc-900">{title}</h4>
        <p className="mt-1 text-xs leading-5 text-zinc-500">{description}</p>
      </div>
      {children}
    </article>
  );
}

function DetectionConfusionMatrix({ metrics }: { metrics: DetectionMetrics }) {
  const maximum = Math.max(
    metrics.true_positive,
    metrics.false_positive,
    metrics.false_negative,
    1,
  );
  const cells = [
    {
      label: "TP",
      value: metrics.true_positive,
      color: COLORS.blue,
      tone: metrics.true_positive / maximum,
    },
    {
      label: "FN",
      value: metrics.false_negative,
      color: COLORS.red,
      tone: metrics.false_negative / maximum,
    },
    {
      label: "FP",
      value: metrics.false_positive,
      color: COLORS.amber,
      tone: metrics.false_positive / maximum,
    },
  ];

  return (
    <ChartCard
      title="책등 검출 혼동행렬"
      description="IoU 0.5 이상 연결을 정답 검출로 계산했습니다."
    >
      <div className="mx-auto grid max-w-md grid-cols-[4.75rem_repeat(2,minmax(0,1fr))] gap-1 text-center text-xs">
        <div />
        <div className="pb-2 font-semibold text-zinc-600">예측 책등</div>
        <div className="pb-2 font-semibold text-zinc-600">예측 배경</div>
        <div className="flex items-center justify-end pr-3 font-semibold text-zinc-600">
          실제 책등
        </div>
        {cells.slice(0, 2).map((cell) => (
          <div
            key={cell.label}
            className="flex min-h-24 flex-col items-center justify-center rounded-md border"
            style={{
              backgroundColor: `${cell.color}${Math.round(25 + cell.tone * 80)
                .toString(16)
                .padStart(2, "0")}`,
              borderColor: `${cell.color}55`,
            }}
          >
            <strong className="text-3xl tabular-nums text-zinc-900">
              {cell.value}
            </strong>
            <span className="mt-1 font-semibold text-zinc-600">
              {cell.label}
            </span>
          </div>
        ))}
        <div className="flex items-center justify-end pr-3 font-semibold text-zinc-600">
          실제 배경
        </div>
        <div
          className="flex min-h-24 flex-col items-center justify-center rounded-md border"
          style={{
            backgroundColor: `${cells[2].color}${Math.round(
              25 + cells[2].tone * 80,
            )
              .toString(16)
              .padStart(2, "0")}`,
            borderColor: `${cells[2].color}55`,
          }}
        >
          <strong className="text-3xl tabular-nums text-zinc-900">
            {cells[2].value}
          </strong>
          <span className="mt-1 font-semibold text-zinc-600">FP</span>
        </div>
        <div className="flex min-h-24 flex-col items-center justify-center rounded-md border border-dashed bg-zinc-50 text-zinc-400">
          <strong className="text-2xl">—</strong>
          <span className="mt-1 font-medium">TN 미정의</span>
        </div>
      </div>
      <div className="mt-5 grid grid-cols-4 gap-2 border-t pt-4 text-center">
        {[
          ["Precision", percent(metrics.precision)],
          ["Recall", percent(metrics.recall)],
          ["F1", percent(metrics.f1)],
          ["평균 IoU", percent(metrics.mean_matched_iou)],
        ].map(([label, value]) => (
          <div key={label}>
            <p className="text-[11px] text-zinc-500">{label}</p>
            <p className="mt-1 font-bold tabular-nums text-zinc-800">{value}</p>
          </div>
        ))}
      </div>
    </ChartCard>
  );
}

function StructureChart({ metrics }: { metrics: StructureMetrics }) {
  const data = [
    {
      name: "정상",
      value: metrics.correct_ground_truth_count,
      color: COLORS.teal,
    },
    {
      name: "분할",
      value: metrics.split_ground_truth_count,
      color: COLORS.amber,
    },
    {
      name: "병합 영향",
      value: metrics.merged_ground_truth_count,
      color: COLORS.violet,
    },
    {
      name: "누락",
      value: metrics.missed_ground_truth_count,
      color: COLORS.red,
    },
  ];

  return (
    <ChartCard
      title="검출 구조"
      description="실제 책 한 권을 기준으로 정상·분할·병합·누락을 구분합니다."
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="46%"
              innerRadius={58}
              outerRadius={88}
              paddingAngle={2}
              stroke="white"
              strokeWidth={2}
            >
              {data.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => [`${value}권`, "도서 수"]} />
            <Legend verticalAlign="bottom" iconType="circle" iconSize={9} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function MatchingChart({ metrics }: { metrics: MatchingMetrics }) {
  const top1 = Math.round(metrics.db_evaluated_count * metrics.top1_accuracy);
  const top3 = Math.round(metrics.db_evaluated_count * metrics.top3_accuracy);
  const data = [
    { name: "Top-1 정답", value: top1, color: COLORS.blue },
    { name: "Top-3 추가", value: Math.max(0, top3 - top1), color: COLORS.cyan },
    {
      name: "Top-3 실패",
      value: Math.max(0, metrics.db_evaluated_count - top3),
      color: COLORS.red,
    },
  ];

  return (
    <ChartCard
      title="DB 도서 식별 결과"
      description={`DB 정답이 지정된 ${metrics.db_evaluated_count}권의 후보 순위입니다.`}
    >
      <div className="relative h-64">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="46%"
              innerRadius={58}
              outerRadius={88}
              paddingAngle={2}
              stroke="white"
              strokeWidth={2}
            >
              {data.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip formatter={(value) => [`${value}권`, "도서 수"]} />
            <Legend verticalAlign="bottom" iconType="circle" iconSize={9} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-x-0 top-[6.2rem] text-center">
          <p className="text-2xl font-extrabold tabular-nums text-zinc-900">
            {percent(metrics.top1_accuracy)}
          </p>
          <p className="text-[11px] text-zinc-500">Top-1</p>
        </div>
      </div>
    </ChartCard>
  );
}

function FieldAccuracyChart({ metrics }: { metrics: MatchingMetrics }) {
  const data = [
    { name: "제목", accuracy: metrics.title_normalized_accuracy * 100 },
    { name: "청구기호", accuracy: metrics.call_number_exact_accuracy * 100 },
    { name: "KDC", accuracy: metrics.kdc_accuracy * 100 },
    { name: "도서기호", accuracy: metrics.book_code_accuracy * 100 },
  ];

  return (
    <ChartCard
      title="OCR 필드별 정확도"
      description="GT와 OCR 결과를 필드별로 정규화해 비교했습니다."
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ left: 4, right: 24 }}
          >
            <CartesianGrid
              stroke={COLORS.grid}
              strokeDasharray="3 3"
              horizontal={false}
            />
            <XAxis
              type="number"
              domain={[0, 100]}
              tickFormatter={(value) => `${value}%`}
              tick={{ fill: COLORS.muted, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={62}
              tick={{ fill: "#3F3F46", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: "#F4F4F5" }}
              formatter={(value) => [`${Number(value).toFixed(1)}%`, "정확도"]}
            />
            <Bar
              dataKey="accuracy"
              fill={COLORS.navy}
              radius={[0, 4, 4, 0]}
              maxBarSize={24}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
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
    <section className="mb-4 rounded-xl border border-zinc-200 bg-zinc-50/70 p-4 md:p-6">
      <div className="mb-6 border-b border-zinc-200 pb-4">
        <p className="text-xs font-semibold tracking-widest text-zinc-500 uppercase">
          Ground Truth Evaluation
        </p>
        <h3 className="mt-1 text-xl font-extrabold tracking-tight text-zinc-950">
          평가 결과 시각화
        </h3>
        <p className="mt-1 text-sm text-zinc-500">
          숫자 지표와 동일한 GT 평가 결과를 통계 차트로 표시합니다.
        </p>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <DetectionConfusionMatrix metrics={detectionMetrics} />
        {structureMetrics ? (
          <StructureChart metrics={structureMetrics} />
        ) : null}
        {matchingMetrics ? (
          <>
            <MatchingChart metrics={matchingMetrics} />
            <FieldAccuracyChart metrics={matchingMetrics} />
          </>
        ) : null}
      </div>
    </section>
  );
}
