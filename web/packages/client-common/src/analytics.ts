import type { AnyRouter } from "@tanstack/react-router";

type DataLayerEvent = Record<string, unknown> & { event: string };

declare global {
  interface Window {
    dataLayer?: Array<DataLayerEvent | Record<string, unknown>>;
  }
}

export function pushDataLayerEvent(
  event: string,
  params?: Record<string, unknown>,
) {
  if (typeof window === "undefined") return;
  window.dataLayer = window.dataLayer ?? [];
  window.dataLayer.push({ event, ...params });
}

export function trackPageViews(router: AnyRouter) {
  return router.subscribe("onResolved", ({ toLocation }) => {
    if (typeof window === "undefined") return;
    pushDataLayerEvent("page_view", {
      page_path: toLocation.pathname,
      page_location: window.location.href,
      page_title: document.title,
    });
  });
}

const DEFAULT_CLICK_SELECTOR =
  "button, [role='button'], a, [data-gtm-event], [data-gtm]";

const TEXT_TRUNCATE_LIMIT = 120;

function readGtmDataset(dataset: DOMStringMap) {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(dataset)) {
    if (value === undefined) continue;
    if (key === "gtmEvent" || key === "gtm") continue;
    if (!key.startsWith("gtm")) continue;
    const paramKey = key
      .slice(3)
      .replace(/^./, (c) => c.toLowerCase())
      .replace(/([A-Z])/g, "_$1")
      .toLowerCase();
    params[paramKey] = value;
  }
  return params;
}

export function enableAutoClickTracking(options?: { selector?: string }) {
  if (typeof document === "undefined") return () => {};
  const selector = options?.selector ?? DEFAULT_CLICK_SELECTOR;
  const handler = (event: Event) => {
    const origin = event.target;
    if (!(origin instanceof Element)) return;
    const target = origin.closest(selector);
    if (!(target instanceof HTMLElement)) return;
    const datasetParams = readGtmDataset(target.dataset);
    const explicitName = target.dataset.gtmEvent ?? target.dataset.gtm;
    const text = (target.textContent ?? "").trim();
    pushDataLayerEvent(explicitName ?? "interaction_click", {
      element_tag: target.tagName.toLowerCase(),
      element_text: text ? text.slice(0, TEXT_TRUNCATE_LIMIT) : undefined,
      element_id: target.id || undefined,
      element_role: target.getAttribute("role") || undefined,
      element_href:
        target instanceof HTMLAnchorElement ? target.href : undefined,
      element_name:
        target.getAttribute("aria-label") ||
        target.getAttribute("name") ||
        undefined,
      page_path: window.location.pathname,
      ...datasetParams,
    });
  };
  document.addEventListener("click", handler, true);
  return () => document.removeEventListener("click", handler, true);
}

export function enableAutoFormTracking() {
  if (typeof document === "undefined") return () => {};
  const handler = (event: Event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const datasetParams = readGtmDataset(form.dataset);
    const explicitName = form.dataset.gtmEvent ?? form.dataset.gtm;
    pushDataLayerEvent(explicitName ?? "form_submit", {
      form_id: form.id || undefined,
      form_name: form.getAttribute("name") || undefined,
      form_action: form.action || undefined,
      page_path: window.location.pathname,
      ...datasetParams,
    });
  };
  document.addEventListener("submit", handler, true);
  return () => document.removeEventListener("submit", handler, true);
}

let autoEventTrackingDisposer: (() => void) | null = null;

export function enableAutoEventTracking() {
  if (autoEventTrackingDisposer) return autoEventTrackingDisposer;
  const offClick = enableAutoClickTracking();
  const offForm = enableAutoFormTracking();
  autoEventTrackingDisposer = () => {
    offClick();
    offForm();
    autoEventTrackingDisposer = null;
  };
  return autoEventTrackingDisposer;
}
