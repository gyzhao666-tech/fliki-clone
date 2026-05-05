"use client";

import { useEffect, useState } from "react";
import { Link } from "@/i18n/navigation";
import { Download, Loader2, AlertCircle, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

type ExportJob = {
  id: string;
  file_id: string;
  title: string;
  format: string;
  status: "pending" | "processing" | "done" | "failed";
  file_url: string | null;
  file_size: number | null;
  created_at: string;
};

const statusVariant: Record<ExportJob["status"], "success" | "warning" | "danger" | "default"> = {
  done: "success",
  pending: "default",
  processing: "warning" as const,
  failed: "danger" as const,
};

function formatSize(bytes: number | null) {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "Just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "Yesterday" : `${d} days ago`;
}

export default function ExportsPage() {
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await api<ExportJob[]>("/exports");
        if (!mounted) return;
        setJobs(data);
      } catch {
        if (!mounted) return;
        setError("Failed to load exports");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function deleteJob(id: string) {
    try {
      await api<{ message: string }>(`/exports/${id}`, { method: "DELETE" });
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch {
      setError("Failed to delete export");
    }
  }

  return (
    <div className="p-7">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[var(--text)]">Exports</h1>
        <p className="text-sm text-[var(--text-secondary)]">Download rendered videos and audio from your projects.</p>
      </div>

      {loading ? (
        <div className="text-sm text-[var(--text-secondary)]">Loading exports...</div>
      ) : error ? (
        <div className="text-sm text-red-500 mb-4">{error}</div>
      ) : null}

      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--bg-subtle)] text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Format</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-muted)]/50">
                <td className="px-4 py-3 font-medium text-[var(--text)]">{job.title || job.file_id}</td>
                <td className="px-4 py-3 text-[var(--text-secondary)]">{job.format.toUpperCase()}</td>
                <td className="px-4 py-3 text-[var(--text-secondary)]">{formatSize(job.file_size)}</td>
                <td className="px-4 py-3">
                  <Badge variant={statusVariant[job.status]} className="inline-flex items-center gap-1">
                    {job.status === "processing" && <Loader2 className="h-3 w-3 animate-spin" />}
                    {job.status === "failed" && <AlertCircle className="h-3 w-3" />}
                    {job.status === "done" ? "ready" : job.status}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-[var(--text-muted)]" suppressHydrationWarning>
                  {relativeTime(job.created_at)}
                </td>
                <td className="px-4 py-3 text-right">
                  {job.status === "done" ? (
                    <div className="inline-flex items-center gap-2">
                      <a
                        href={`/api/exports/${job.id}/download`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex"
                      >
                        <Button size="sm" variant="outline" className="gap-1">
                          <Download className="h-3.5 w-3.5" /> Download
                        </Button>
                      </a>
                      <Button size="sm" variant="ghost" className="gap-1 text-red-500" onClick={() => deleteJob(job.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-[var(--text-muted)]">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!loading && jobs.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-[var(--text-secondary)]">
                  No exports yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-[var(--text-muted)] mt-4">
        Exports are kept for 7 days.{" "}
        <Link href="/app/files" className="text-[var(--brand-600)] hover:underline">
          Open a project
        </Link>{" "}
        to create a new export.
      </p>
    </div>
  );
}
