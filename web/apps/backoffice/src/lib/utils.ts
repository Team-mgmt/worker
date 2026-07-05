export { cn } from "@shelfalign/client-common/utils";

export function isSvgFile(file: File): boolean {
  return (
    file.type === "image/svg+xml" || file.name.toLowerCase().endsWith(".svg")
  );
}

export function getLogLevelVariant(logLevel: string) {
  switch (logLevel.toUpperCase()) {
    case "ERROR":
      return "destructive" as const;
    case "WARN":
    case "WARNING":
      return "secondary" as const;
    case "INFO":
      return "default" as const;
    default:
      return "outline" as const;
  }
}
