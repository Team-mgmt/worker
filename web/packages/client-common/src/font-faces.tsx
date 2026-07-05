import { useQueries } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";

export type FontFaceSpec = {
  family: string;
  weight?: string;
  style?: string;
};

export type FontUrlResolver = (spec: FontFaceSpec) => Promise<string | null>;

export type FontFacesProps = {
  specs: FontFaceSpec[];
  resolveUrl: FontUrlResolver;
  /**
   * Extra query key segments to disambiguate resolvers that share a
   * `(family, weight, style)` but resolve to different URLs (e.g. per
   * tenant / organization). Without this, two tenants would collide on
   * the same Tanstack Query cache entry.
   */
  queryKey?: readonly unknown[];
};

function cssWeight(weight: string | undefined): string {
  return weight === "bold" ? "700" : "400";
}

function specKey(spec: FontFaceSpec): string {
  return `${spec.family}|${spec.weight ?? "normal"}|${spec.style ?? "normal"}`;
}

function fontKey(spec: FontFaceSpec, url: string): string {
  return `${specKey(spec)}|${url}`;
}

function escapeCssString(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function fontFaceRule(spec: FontFaceSpec, url: string): string {
  const safeFamily = escapeCssString(spec.family);
  const safeUrl = escapeCssString(url);
  return `@font-face {
  font-family: "${safeFamily}";
  src: url("${safeUrl}");
  font-weight: ${cssWeight(spec.weight)};
  font-style: ${spec.style ?? "normal"};
  font-display: swap;
}`;
}

// Renders one <style> per unique (family, weight, style). React 19 hoists
// these into <head> and dedupes by `href` across the tree, so the browser
// fetches each font file at most once via CSS even if multiple components
// mount the same spec. Failed URL resolutions render nothing — text falls
// back to the inherited font stack.
export function FontFaces({
  specs,
  resolveUrl,
  queryKey: extraQueryKey,
}: FontFacesProps): ReactNode {
  const uniqueSpecs = useMemo(() => {
    const seen = new Map<string, FontFaceSpec>();
    for (const spec of specs) {
      if (!spec.family) continue;
      const key = specKey(spec);
      if (!seen.has(key)) seen.set(key, spec);
    }
    return Array.from(seen.values());
  }, [specs]);

  const results = useQueries({
    queries: uniqueSpecs.map((spec) => ({
      queryKey: [
        "client-common",
        "FontFaces",
        ...(extraQueryKey ?? []),
        specKey(spec),
      ],
      queryFn: () => resolveUrl(spec),
      staleTime: Infinity,
      gcTime: Infinity,
      retry: false,
    })),
  });

  return (
    <>
      {uniqueSpecs.map((spec, i) => {
        const url = results[i]?.data;
        if (!url) return null;
        const key = fontKey(spec, url);
        return (
          <style key={key} href={key} precedence="default">
            {fontFaceRule(spec, url)}
          </style>
        );
      })}
    </>
  );
}
