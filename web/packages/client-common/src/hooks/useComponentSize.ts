import { useEffect, useState } from "react";

interface ComponentSize {
  width: number;
  height: number;
}

export function useComponentSize<T extends HTMLElement = HTMLDivElement>() {
  const [element, ref] = useState<T | null>(null);

  const [size, setSize] = useState<ComponentSize>({
    width: 0,
    height: 0,
  });

  useEffect(() => {
    if (!element) return;

    const updateSize = (entries: ResizeObserverEntry[]) => {
      const entry = entries[0];
      if (!entry) return;

      const { width, height } = entry.contentRect;
      const newWidth = Math.floor(width);
      const newHeight = Math.floor(height);

      setSize((prev) => {
        if (prev.width === newWidth && prev.height === newHeight) {
          return prev;
        }
        return { width: newWidth, height: newHeight };
      });
    };

    const resizeObserver = new ResizeObserver(updateSize);
    resizeObserver.observe(element);

    return () => resizeObserver.disconnect();
  }, [element]);

  return { ref, ...size };
}
