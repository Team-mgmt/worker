import { XIcon } from "lucide-react";
import type { PropsWithChildren, ReactNode } from "react";

import { cn } from "@/utils";

type ModalProps = {
  className?: string;
  open?: boolean;
  onClose?: () => void;
  children: ReactNode;
};

export function Modal({ className, open, onClose, children }: ModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2">
      <div
        className="fixed inset-0 bg-black/25"
        onClick={onClose}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose?.();
        }}
      />
      <div
        className={cn(
          "relative z-10 flex w-full max-w-[448px] flex-col gap-6 rounded-[14px] bg-white p-6 shadow-[0px_25px_50px_0px_rgba(0,0,0,0.25)]",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}

type ModalHeaderProps = {
  className?: string;
  onClose?: () => void;
  children: ReactNode;
  buttons?: ReactNode;
};

export function ModalHeader({
  className,
  onClose,
  buttons,
  children,
}: ModalHeaderProps) {
  return (
    <div className={cn("flex items-center justify-between", className)}>
      <h2 className="text-heading-3 leading-heading-3 font-bold text-primary-black">
        {children}
      </h2>
      {buttons}
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="text-primary-black transition-colors hover:text-grey-2"
        >
          <XIcon className="size-6" />
        </button>
      )}
    </div>
  );
}

export function ModalBody({
  className,
  children,
}: PropsWithChildren<{ className?: string }>) {
  return <div className={cn("flex flex-col gap-3", className)}>{children}</div>;
}

export function ModalDescription({
  className,
  children,
}: PropsWithChildren<{ className?: string }>) {
  return (
    <p
      className={cn(
        "text-[18px] leading-heading-4 font-medium text-grey-2",
        className,
      )}
    >
      {children}
    </p>
  );
}

export function ModalInfo({
  className,
  children,
}: PropsWithChildren<{ className?: string }>) {
  return (
    <p
      className={cn(
        "text-paragraph leading-paragraph font-regular text-grey-2",
        className,
      )}
    >
      {children}
    </p>
  );
}

export function ModalFooter({
  className,
  children,
}: PropsWithChildren<{ className?: string }>) {
  return (
    <div className={cn("flex items-center gap-4", className)}>{children}</div>
  );
}
