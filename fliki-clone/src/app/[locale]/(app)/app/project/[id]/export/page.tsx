"use client";

import { Link } from "@/i18n/navigation";
import { useParams } from "next/navigation";
import { CheckCircle2, Download, ChevronLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ProjectExportPage() {
  const params = useParams();
  const id = params.id as string;

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <Button variant="ghost" size="sm" className="gap-1.5 mb-6 -ml-2" asChild>
        <Link href={`/app/project/${id}`}>
          <ChevronLeft className="h-4 w-4" /> Back to editor
        </Link>
      </Button>

      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-8 text-center">
        <div className="flex justify-center mb-4">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10">
            <CheckCircle2 className="h-8 w-8 text-emerald-500" />
          </span>
        </div>
        <h1 className="text-xl font-bold text-[var(--text)] mb-2">Export ready</h1>
        <p className="text-sm text-[var(--text-secondary)] mb-8">
          Your video has been rendered. Download the file or find it later under Exports.
        </p>

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Button size="lg" className="gap-2">
            <Download className="h-4 w-4" /> Download MP4
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link href="/app/exports">View all exports</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
