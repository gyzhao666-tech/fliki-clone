"use client";

import { AlertCircle, RotateCcw, X } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export type RetryBannerVariant = "error" | "warning" | "info";

interface RetryBannerProps extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  description?: string;
  variant?: RetryBannerVariant;
  retryLabel?: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

const variantStyles: Record<RetryBannerVariant, string> = {
  error: "bg-red-50 border-red-200 text-red-900",
  warning: "bg-amber-50 border-amber-200 text-amber-900",
  info: "bg-[var(--brand-50)] border-[var(--brand-200)] text-[var(--brand-900)]",
};

const iconColor: Record<RetryBannerVariant, string> = {
  error: "text-red-500",
  warning: "text-amber-500",
  info: "text-[var(--brand-600)]",
};

export const RetryBanner = React.forwardRef<HTMLDivElement, RetryBannerProps>(
  ({ title, description, variant = "error", retryLabel = "Retry", onRetry, onDismiss, className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        role={variant === "error" ? "alert" : "status"}
        className={cn(
          "flex items-start gap-3 rounded-[var(--radius-lg)] border px-4 py-3 shadow-[var(--shadow-xs)]",
          variantStyles[variant],
          className
        )}
        {...props}
      >
        <AlertCircle className={cn("h-5 w-5 shrink-0 mt-0.5", iconColor[variant])} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold leading-tight">{title}</p>
          {description && (
            <p className="text-xs mt-1 opacity-80 leading-relaxed">{description}</p>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry} className="h-8 gap-1.5">
              <RotateCcw className="h-3.5 w-3.5" />
              {retryLabel}
            </Button>
          )}
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss"
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] opacity-60 hover:opacity-100 hover:bg-black/5 transition"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    );
  }
);
RetryBanner.displayName = "RetryBanner";
