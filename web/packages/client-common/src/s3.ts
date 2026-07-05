import ky from "ky";

// S3 caps object tag values at 256 unicode code points. Slice by code points
// (not UTF-16 units) so multi-byte filenames can't land on a surrogate
// boundary, and stay well under the cap. Must match backend truncation in
// upload.service.ts / statistics.service.ts so the wire value matches the
// signed value — a mismatch would fail SigV4 verification.
const TAG_VALUE_MAX = 200;

function truncateTagValue(value: string): string {
  const codePoints = Array.from(value);
  if (codePoints.length <= TAG_VALUE_MAX) return value;
  return codePoints.slice(0, TAG_VALUE_MAX).join("");
}

function serializeTags(tags: Record<string, string>): string {
  return Object.entries(tags)
    .map(
      ([key, value]) =>
        `${encodeURIComponent(key)}=${encodeURIComponent(truncateTagValue(value))}`,
    )
    .join("&");
}

export async function uploadObject(
  url: string,
  file: File,
  tags?: Record<string, string>,
  contentType?: string,
) {
  const headers = new Headers({ "Content-Type": contentType ?? file.type });
  if (tags) {
    headers.set("x-amz-tagging", serializeTags(tags));
  }

  const result = await ky.put(url, {
    body: file,
    headers,
    timeout: false,
    throwHttpErrors: false,
  });

  if (result.status !== 200) {
    const body = await result.text().catch(() => "");
    console.error("S3 upload failed", {
      status: result.status,
      body: body.slice(0, 500),
    });
    return false;
  }

  return true;
}
