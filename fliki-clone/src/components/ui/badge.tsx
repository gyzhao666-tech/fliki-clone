import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "primary" | "success" | "warning" | "danger" | "purple";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  default:  "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  primary:  "bg-[var(--brand-100)] text-[var(--brand-700)]",
  success:  "bg-emerald-100 text-emerald-700",
  warning:  "bg-amber-100 text-amber-700",
  danger:   "bg-red-100 text-red-700",
  purple:   "bg-purple-100 text-purple-700",
};

export function Badge({ className, variant = "default", children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-[var(--radius-full)] text-xs font-medium",
        variantClasses[variant],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
