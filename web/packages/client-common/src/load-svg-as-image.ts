interface SvgIntrinsicSize {
  width: number;
  height: number;
}

export interface NormalizedSvg {
  /** SVG markup with explicit width/height matching the viewBox. */
  svgText: string;
  /** SVG-coordinate (viewBox) width — the unit space areas are stored in. */
  width: number;
  /** SVG-coordinate (viewBox) height. */
  height: number;
}

function parseNumber(value: string | null | undefined): number | null {
  if (value == null) return null;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

function isNumberListSeparator(ch: string): boolean {
  return (
    ch === " " ||
    ch === "\t" ||
    ch === "\n" ||
    ch === "\r" ||
    ch === "\f" ||
    ch === ","
  );
}

function tokenizeNumberList(value: string): string[] {
  const tokens: string[] = [];
  let buf = "";
  for (let i = 0; i < value.length; i++) {
    const ch = value[i]!;
    if (isNumberListSeparator(ch)) {
      if (buf) {
        tokens.push(buf);
        buf = "";
      }
    } else {
      buf += ch;
    }
  }
  if (buf) tokens.push(buf);
  return tokens;
}

function parseViewBox(
  value: string | null | undefined,
): SvgIntrinsicSize | null {
  if (value == null) return null;
  const parts = tokenizeNumberList(value);
  if (parts.length !== 4) return null;
  const width = parseNumber(parts[2]);
  const height = parseNumber(parts[3]);
  if (width == null || height == null) return null;
  return { width, height };
}

function readSvgIntrinsicSize(root: Element): SvgIntrinsicSize | null {
  const viewBox = parseViewBox(root.getAttribute("viewBox"));
  if (viewBox) return viewBox;
  const width = parseNumber(root.getAttribute("width"));
  const height = parseNumber(root.getAttribute("height"));
  if (width == null || height == null) return null;
  return { width, height };
}

function parseSvgDocument(svgText: string): Document {
  const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
  if (doc.getElementsByTagName("parsererror").length > 0) {
    throw new Error("Failed to parse SVG markup");
  }
  const root = doc.documentElement;
  if (!root || root.localName.toLowerCase() !== "svg") {
    throw new Error("SVG markup has no <svg> root");
  }
  return doc;
}

export async function fetchAndNormalizeSvg(
  url: string,
): Promise<NormalizedSvg> {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch SVG (${response.status} ${response.statusText})`,
    );
  }
  const text = await response.text();
  const doc = parseSvgDocument(text);
  const root = doc.documentElement;
  const size = readSvgIntrinsicSize(root);
  if (!size) {
    throw new Error("SVG has no intrinsic size");
  }
  // Force the <svg> element to expose explicit width/height matching its
  // viewBox so the browser rasterizes the image at the same coordinate space
  // the detection layout uses. Without this, SVGs that ship only a viewBox are
  // rasterized at the browser default (300x150), making areas appear shifted.
  root.setAttribute("width", String(size.width));
  root.setAttribute("height", String(size.height));
  return {
    svgText: new XMLSerializer().serializeToString(doc),
    width: size.width,
    height: size.height,
  };
}

export interface NormalizedImage {
  /** Blob URL pointing at the (possibly rewritten) image. Caller must revoke. */
  url: string;
  /** Coordinate-space width — viewBox units for SVG, natural pixels for raster. */
  width: number;
  /** Coordinate-space height — viewBox units for SVG, natural pixels for raster. */
  height: number;
}

// Tolerant variant of fetchAndNormalizeSvg used by browser previews, which
// may encounter legacy raster (PNG/JPG) papers from before the SVG-only gate.
// The backoffice editor still uses the strict SVG loaders.
export async function fetchAndNormalizeImage(
  url: string,
): Promise<NormalizedImage> {
  const response = await fetch(url, { credentials: "omit" });
  if (!response.ok) {
    throw new Error(
      `Failed to fetch image (${response.status} ${response.statusText})`,
    );
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";

  if (contentType.includes("svg")) {
    const text = await response.text();
    const doc = parseSvgDocument(text);
    const root = doc.documentElement;
    const size = readSvgIntrinsicSize(root);
    if (!size) throw new Error("SVG has no intrinsic size");
    root.setAttribute("width", String(size.width));
    root.setAttribute("height", String(size.height));
    const svgBlob = new Blob([new XMLSerializer().serializeToString(doc)], {
      type: "image/svg+xml",
    });
    return {
      url: URL.createObjectURL(svgBlob),
      width: size.width,
      height: size.height,
    };
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.src = objectUrl;
    await img.decode();
    return {
      url: objectUrl,
      width: img.naturalWidth,
      height: img.naturalHeight,
    };
  } catch (err) {
    URL.revokeObjectURL(objectUrl);
    throw err;
  }
}

export async function loadSvgAsImage(url: string): Promise<HTMLImageElement> {
  const { svgText } = await fetchAndNormalizeSvg(url);
  const blob = new Blob([svgText], { type: "image/svg+xml" });
  const blobUrl = URL.createObjectURL(blob);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("Failed to decode SVG into Image"));
      img.src = blobUrl;
    });
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}
