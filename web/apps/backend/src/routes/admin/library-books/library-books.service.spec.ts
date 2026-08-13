import { buildLibraryBookSearchWhere } from "./library-books.service";

describe("buildLibraryBookSearchWhere", () => {
  it("searches normalized bibliographic fields for a plain text query", () => {
    expect(buildLibraryBookSearchWhere("  어리석은  ")).toEqual({
      book: {
        OR: [
          { normalizedBookname: { contains: "어리석은" } },
          { normalizedAuthors: { contains: "어리석은" } },
        ],
      },
    });
  });

  it("uses an ISBN prefix query for a long numeric value", () => {
    expect(buildLibraryBookSearchWhere("9791171831708")).toEqual({
      book: { isbn13: { startsWith: "9791171831708" } },
    });
  });

  it("searches holding identifiers for a call-number-like query", () => {
    expect(buildLibraryBookSearchWhere("813.6 김12ㄱ")).toEqual({
      OR: [
        { normalizedCallNumber: { contains: "813.6 김12ㄱ".normalize("NFKC") } },
        { bookCode: { contains: "813.6 김12ㄱ", mode: "insensitive" } },
      ],
    });
  });

  it("returns no search filter for a blank query", () => {
    expect(buildLibraryBookSearchWhere("   ")).toBeUndefined();
  });
});
