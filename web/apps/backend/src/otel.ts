import { metrics } from "@opentelemetry/api";
import { OTLPMetricExporter } from "@opentelemetry/exporter-metrics-otlp-proto";
import {
  defaultResource,
  detectResources,
  envDetector,
  hostDetector,
  processDetector,
  serviceInstanceIdDetector,
} from "@opentelemetry/resources";
import {
  MeterProvider,
  PeriodicExportingMetricReader,
} from "@opentelemetry/sdk-metrics";
import * as Sentry from "@sentry/nestjs";

// OTel spec allows either a base OTLP endpoint or per-signal overrides; honor
// both so deployments using only signal-specific env vars still light up.
const tracesEnabled = Boolean(
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT ||
  process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
);
const metricsEnabled = Boolean(
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT ||
  process.env.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
);

let meterProvider: MeterProvider | undefined;

if (metricsEnabled) {
  const resource = defaultResource().merge(
    detectResources({
      detectors: [
        envDetector,
        hostDetector,
        processDetector,
        serviceInstanceIdDetector,
      ],
    }),
  );

  meterProvider = new MeterProvider({
    resource,
    readers: [
      new PeriodicExportingMetricReader({
        exporter: new OTLPMetricExporter(),
        exportIntervalMillis: 60_000,
      }),
    ],
  });

  metrics.setGlobalMeterProvider(meterProvider);
}

if (tracesEnabled || metricsEnabled) {
  // Flush buffered telemetry on SIGTERM and exit. `Sentry.close` drains both
  // Sentry's own transport and the BatchSpanProcessor registered via
  // `openTelemetrySpanProcessors` in instrument.ts. `once` so a second SIGTERM
  // falls through to Node's default exit. `process.exit` is required because
  // main.ts does not yet enable Nest shutdown hooks — without it the process
  // would hang on the HTTP server until ECS SIGKILLs at 30s.
  process.once("SIGTERM", () => {
    void Promise.allSettled([
      meterProvider?.shutdown(),
      Sentry.close(2000),
    ]).finally(() => process.exit(0));
  });
}
