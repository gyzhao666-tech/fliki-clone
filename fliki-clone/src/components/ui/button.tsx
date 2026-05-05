import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "outline" | "destructive";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
  loading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--brand-600)] text-white hover:bg-[var(--brand-700)] active:bg-[var(--brand-800)] shadow-xs",
  secondary:
    "bg-[var(--bg-muted)] text-[var(--text)] hover:bg-[var(--border)] border border-[var(--border)]",
  ghost:
    "text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text)]",
  outline:
    "border border-[var(--border-strong)] text-[var(--text)] hover:bg-[var(--bg-subtle)]",
  destructive:
    "bg-red-600 text-white hover:bg-red-700 active:bg-red-800 shadow-xs",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm:   "h-9  px-3.5 text-sm   rounded-[var(--radius-md)] gap-1.5",
  md:   "h-10 px-4   text-sm   rounded-[var(--radius-md)] gap-2",
  lg:   "h-12 px-6   text-base rounded-[var(--radius-lg)] gap-2",
  icon: "h-10 w-10   rounded-[var(--radius-md)]",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", asChild = false, loading, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-500)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer select-none",
          variantClasses[variant],
          sizeClasses[size],
          className
        )}
        {...props}
      >
        {asChild ? children : (
          <>
            {loading && (
              <svg className="animate-spin -ml-0.5 h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            )}
            {children}
          </>
        )}
      </Comp>
    );
  }
);
Button.displayName = "Button";
