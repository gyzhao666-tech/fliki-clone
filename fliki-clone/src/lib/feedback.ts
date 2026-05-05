import { toast, type ExternalToast } from "sonner";

type Action = { label: string; onClick: () => void };

interface FeedbackOptions extends Omit<ExternalToast, "action"> {
  description?: string;
  action?: Action;
}

export const feedback = {
  success(message: string, opts: FeedbackOptions = {}) {
    return toast.success(message, opts);
  },
  error(message: string, opts: FeedbackOptions = {}) {
    return toast.error(message, opts);
  },
  info(message: string, opts: FeedbackOptions = {}) {
    return toast.info(message, opts);
  },
  warning(message: string, opts: FeedbackOptions = {}) {
    return toast.warning(message, opts);
  },
  loading(message: string, opts: FeedbackOptions = {}) {
    return toast.loading(message, opts);
  },
  /** Wrap an async task; auto-show loading → success/error toasts. */
  promise<T>(
    promise: Promise<T>,
    msgs: { loading: string; success: string | ((data: T) => string); error: string | ((err: unknown) => string) }
  ) {
    return toast.promise(promise, msgs);
  },
  dismiss(id?: string | number) {
    toast.dismiss(id);
  },
};
