import { skipToken, useQuery, useSuspenseQuery } from "@tanstack/react-query";

type UseImageSizeOptions = {
  crossOrigin?: boolean;
  queryKey?: readonly unknown[];
};

export function useImageSize(
  url: string | undefined,
  options?: UseImageSizeOptions,
) {
  const { crossOrigin = false, queryKey } = options ?? {};
  return useQuery({
    queryKey: queryKey
      ? ["hooks", "useImageSize", ...queryKey]
      : ["hooks", "useImageSize", url, crossOrigin],
    queryFn: url
      ? () =>
          new Promise<[number, number]>((resolve, reject) => {
            const image = new Image();
            if (crossOrigin) {
              image.crossOrigin = "anonymous";
            }
            image.src = url;
            image.onload = () => {
              resolve([image.width, image.height]);
            };
            image.onerror = (err) => {
              reject(err);
            };
          })
      : skipToken,
  });
}

export function useSuspenseImageSize(
  url: string,
  options?: UseImageSizeOptions,
) {
  const { crossOrigin = false, queryKey } = options ?? {};
  return useSuspenseQuery({
    queryKey: queryKey
      ? ["hooks", "useImageSize", ...queryKey]
      : ["hooks", "useImageSize", url, crossOrigin],
    queryFn: () =>
      new Promise<[number, number]>((resolve, reject) => {
        const image = new Image();
        if (crossOrigin) {
          image.crossOrigin = "anonymous";
        }
        image.src = url;
        image.onload = () => {
          resolve([image.width, image.height]);
        };
        image.onerror = (err) => {
          reject(err);
        };
      }),
  });
}
