import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import * as Sentry from "@sentry/nestjs";

// Sentry v10 owns the OTel TracerProvider. To also ship spans to our collector
// sidecar (then to S3), register an extra BatchSpanProcessor + OTLP exporter
// alongside Sentry's own processor. Gated on the OTLP endpoint env vars so
// local dev without a collector doesn't retry exports forever. Honors either
// the base endpoint or the traces-specific override per the OTel spec.
const tracesEnabled = Boolean(
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT ||
  process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
);
const openTelemetrySpanProcessors = tracesEnabled
  ? [new BatchSpanProcessor(new OTLPTraceExporter())]
  : undefined;

// TODO: Replace YOUR_SENTRY_DSN with your own DSN from https://sentry.io
// Create a new project at sentry.io and get your DSN from Project Settings > Client Keys
Sentry.init({
  dsn: "YOUR_SENTRY_DSN",
  // Send structured logs to Sentry
  enableLogs: true,
  // tracesSampleRate stays at 1.0 so spans are recorded and our OTLP processor
  // sees them; the transaction envelope is dropped below before upload, so
  // Sentry never ingests transactions and billing stays flat.
  tracesSampleRate: 1.0,
  // Setting this option to true will send default PII data to Sentry.
  // For example, automatic IP address collection on events
  sendDefaultPii: true,
  environment: process.env.NODE_ENV ?? "development",
  enabled: process.env.SENTRY_LOCAL !== "true",
  openTelemetrySpanProcessors,
  beforeSendTransaction: () => null,
});
