import {
  type PropsWithChildren,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { cn } from "@/utils";

type TooltipSide = "top" | "bottom" | "left" | "right";

type TooltipProps = PropsWithChildren<{
  className?: string;
  contentClassName?: string;
  content: ReactNode;
  side?: TooltipSide;
  // When true, dim the rest of the screen while the tooltip is open and
  // dismiss it on backdrop click. Useful when the tooltip is the user's
  // primary attention target (e.g. an explanatory tap-to-reveal hint on
  // mobile) rather than a passive hover hint.
  backdrop?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  // The trigger wrapper is inline-flex by default. Override if the layout
  // needs the trigger to fill its parent.
  triggerAsChild?: boolean;
}>;

const SIDE_CLASSES: Record<TooltipSide, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
};

export function Tooltip({
  className,
  contentClassName,
  content,
  side = "top",
  backdrop = false,
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children,
}: TooltipProps) {
  const isControlled = controlledOpen !== undefined;
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = isControlled ? controlledOpen : uncontrolledOpen;

  const setOpen = (next: boolean) => {
    if (!isControlled) setUncontrolledOpen(next);
    onOpenChange?.(next);
  };

  const wrapperRef = useRef<HTMLDivElement>(null);
  // Generated once per Tooltip instance and kept stable across renders so
  // the trigger's `aria-describedby` and the content's `id` line up. We
  // only attach the attribute while the tooltip is open — otherwise screen
  // readers would announce a non-existent description.
  const contentId = useId();

  // Without a backdrop the tooltip is a passive hover hint and doesn't need
  // outside-click dismissal — the listener below would interfere with the
  // click target underneath.
  useEffect(() => {
    if (!open || backdrop) return;
    const handler = (event: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (wrapperRef.current.contains(event.target as Node)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, backdrop, isControlled, onOpenChange]);

  // In backdrop mode the dismissal Escape key never reaches the
  // presentation-only backdrop <div> (it isn't focusable), so attach the
  // listener at the document level while the tooltip is open. Focus is
  // typically still on the trigger button, which is fine for Escape.
  useEffect(() => {
    if (!open || !backdrop) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, backdrop, isControlled, onOpenChange]);

  return (
    <>
      {backdrop && open && (
        <div
          className="fixed inset-0 z-40 bg-black/25"
          onClick={() => setOpen(false)}
          role="presentation"
        />
      )}
      <div
        ref={wrapperRef}
        className={cn("relative inline-flex", className)}
        onMouseEnter={backdrop ? undefined : () => setOpen(true)}
        onMouseLeave={backdrop ? undefined : () => setOpen(false)}
        onFocus={backdrop ? undefined : () => setOpen(true)}
        onBlur={backdrop ? undefined : () => setOpen(false)}
      >
        {/*
          The wrapper only listens for `click` so clicks on whatever
          interactive child the consumer passes (typically a <Button>) bubble
          up and toggle the tooltip. We deliberately don't set role="button"
          / tabIndex / Enter+Space handlers on the wrapper — that would
          stack interactive semantics on top of an already-interactive
          child and let bubbled keypresses double-fire. Keyboard activation
          is the child's responsibility.
        */}
        <div
          className="inline-flex"
          onClick={backdrop ? () => setOpen(!open) : undefined}
          aria-describedby={open ? contentId : undefined}
        >
          {children}
        </div>
        {open && (
          <div
            id={contentId}
            role="tooltip"
            className={cn(
              "absolute z-50 w-max max-w-xs rounded-[6px] bg-primary-black px-3 py-2 text-paragraph leading-paragraph text-primary-white shadow-[0_4px_16px_0_rgba(0,0,0,0.25)]",
              SIDE_CLASSES[side],
              contentClassName,
            )}
          >
            {content}
          </div>
        )}
      </div>
    </>
  );
}
