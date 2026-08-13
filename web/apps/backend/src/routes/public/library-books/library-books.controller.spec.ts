import { BadRequestException } from "@nestjs/common";

import { PublicLibraryBooksController } from "./library-books.controller";

describe("PublicLibraryBooksController", () => {
  const list = jest.fn();
  const controller = new PublicLibraryBooksController({ list } as never);

  beforeEach(() => list.mockReset());

  it("rejects unsupported libraries and short queries", async () => {
    await expect(controller.search("999999", "환한 숨")).rejects.toBeInstanceOf(BadRequestException);
    await expect(controller.search("111058", "환")).rejects.toBeInstanceOf(BadRequestException);
  });

  it("returns only the public holding fields", async () => {
    list.mockResolvedValue({
      holdings: [
        {
          id: "holding-1",
          libraryCode: "111058",
          callNumber: "813.6 조92ㅎ",
          shelfLocName: "종합자료실",
          raw: { secret: true },
          book: {
            id: "book-1",
            isbn13: "9780000000000",
            bookname: "환한 숨",
            authors: "조해진",
            bookImageUrl: null,
            publisher: "비공개 필드",
          },
        },
      ],
      count: 1,
    });

    const response = await controller.search("111058", "환한 숨");

    expect(list).toHaveBeenCalledWith({ libraryCode: "111058", query: "환한 숨", page: 1, pageSize: 10 });
    expect(response.data[0]).toEqual({
      id: "holding-1",
      libraryCode: "111058",
      callNumber: "813.6 조92ㅎ",
      shelfLocName: "종합자료실",
      book: {
        id: "book-1",
        isbn13: "9780000000000",
        bookname: "환한 숨",
        authors: "조해진",
        bookImageUrl: null,
      },
    });
  });
});
