const configuredBaseUrl = import.meta.env.VITE_BASE_URL || "/api";

export const apiBaseUrl = new URL(
  configuredBaseUrl.endsWith("/") ? configuredBaseUrl : `${configuredBaseUrl}/`,
  window.location.origin,
)
  .toString()
  .replace(/\/$/, "");
