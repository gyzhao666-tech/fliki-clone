"use client";

import { useEffect, useMemo, useState } from "react";
import { Link } from "@/i18n/navigation";
import {
  Plus,
  Search,
  MoreHorizontal,
  Trash2,
  Edit,
  Copy,
  Film,
  Mic,
  FolderPlus,
  FilePlus,
  Layers,
  ChevronRight,
  ChevronLeft,
  Megaphone,
  Bell,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { FileThumbnail } from "@/components/file-thumbnail";

type ApiFile = {
  id: string;
  title: string;
  thumbnail_url: string | null;
  duration: string | null;
  status: "draft" | "generating" | "done" | "error";
  updated_at: string;
  scene_count: number;
  type: string;
};

const PLACEHOLDER_COLORS = [
  "#3b82f6", "#a855f7", "#10b981", "#ec4899",
  "#f59e0b", "#ef4444", "#64748b", "#8b5cf6",
];

function placeholderColor(seed: string) {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) hash = (hash << 5) - hash + seed.charCodeAt(i);
  return PLACEHOLDER_COLORS[Math.abs(hash) % PLACEHOLDER_COLORS.length];
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

/* ─── What's new data ─── */
const whatsNew = [
  {
    emoji: "🗣️",
    title: "130+ new voices",
    date: "April 02, 2026",
    body: "We've massively expanded our voice library with 130+ new voices across 20+ languages, including character-driven voices and native-quality support for Arabic, Bengali, Chinese, and more.",
  },
  {
    emoji: "🎵",
    title: "YouTube licensed music",
    date: "March 26, 2026",
    body: "Fully licensed YouTube music is now available in your video toolkit. Check the YouTube licensed music box under Advanced Settings when creating a video.",
  },
  {
    emoji: "👬",
    title: "Character library",
    date: "March 17, 2026",
    body: "A dedicated home for all your video characters. Create, save, and reuse AI characters across projects for consistent storytelling.",
  },
  {
    emoji: "🎭",
    title: "Character consistency",
    date: "February 24, 2026",
    body: "Your AI character now stays the same across every scene — same face, same outfit, same person from first frame to last.",
  },
];

/* ─── Status map ─── */
const statusMap: Record<
  ApiFile["status"],
  { label: string; variant: "success" | "warning" | "danger" | "default" }
> = {
  done: { label: "Done", variant: "success" },
  generating: { label: "Generating", variant: "warning" },
  draft: { label: "Draft", variant: "default" },
  error: { label: "Error", variant: "danger" },
};

/* ─── File card ─── */
function FileCard({
  project,
  onRename,
  onDuplicate,
  onDelete,
}: {
  project: ApiFile;
  onRename: (file: ApiFile) => void;
  onDuplicate: (file: ApiFile) => void;
  onDelete: (file: ApiFile) => void;
}) {
  const st = statusMap[project.status];
  const isAudio = project.type === "audio" || project.scene_count <= 4;
  return (
    <div className="group relative rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden hover:shadow-md hover:border-[var(--border-strong)] transition-all">
      <Link href={`/app/project/${project.id}`} className="block">
        {/* thumbnail */}
        {project.thumbnail_url ? (
          <FileThumbnail
            src={project.thumbnail_url}
            alt={project.title}
            className="aspect-video w-full object-cover opacity-85 group-hover:opacity-100 transition-opacity"
          />
        ) : (
          <div
            className="aspect-video opacity-85 group-hover:opacity-100 transition-opacity relative"
            style={{ backgroundColor: placeholderColor(project.id) }}
          >
            <span className="absolute bottom-2 left-2 flex h-5 w-5 items-center justify-center rounded-full bg-black/40">
              {isAudio
                ? <Mic className="h-3 w-3 text-white" />
                : <Film className="h-3 w-3 text-white" />}
            </span>
          </div>
        )}
        {/* info */}
        <div className="p-4">
          <p className="text-sm font-semibold text-[var(--text)] truncate mb-1.5">{project.title}</p>
          <div className="flex items-center justify-between">
            <span className="text-xs text-[var(--text-muted)]" suppressHydrationWarning>
              {relativeTime(project.updated_at)}
            </span>
            <Badge variant={st.variant}>{st.label}</Badge>
          </div>
        </div>
      </Link>

      {/* context menu */}
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] bg-black/50 text-white hover:bg-black/70 transition-colors"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onRename(project)}><Edit className="h-4 w-4" /> Rename</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onDuplicate(project)}><Copy className="h-4 w-4" /> Duplicate</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-red-500" onClick={() => onDelete(project)}><Trash2 className="h-4 w-4" /> Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

/* ─── Empty ─── */
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center col-span-full">
      <div className="flex h-14 w-14 items-center justify-center rounded-[var(--radius-2xl)] bg-[var(--bg-muted)] mb-4">
        <Layers className="h-7 w-7 text-[var(--text-muted)]" />
      </div>
      <h3 className="text-sm font-semibold text-[var(--text)] mb-1">No files yet</h3>
      <p className="text-xs text-[var(--text-secondary)] max-w-xs mb-5">
        Create a video or audio file to see it listed here.
      </p>
      <Button size="sm" asChild>
        <Link href="/app/create"><Plus className="h-3.5 w-3.5" /> New file</Link>
      </Button>
    </div>
  );
}

/* ─── Loading ─── */
function LoadingSkeleton() {
  return (
    <>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="rounded-[var(--radius-xl)] border border-[var(--border)] overflow-hidden">
          <Skeleton className="aspect-video rounded-none" />
          <div className="p-3 flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-3/4" />
            <div className="flex justify-between">
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-3.5 w-12" />
            </div>
          </div>
        </div>
      ))}
    </>
  );
}

/* ─── What's new panel ─── */
function WhatsNewPanel({ onClose }: { onClose: () => void }) {
  return (
    <aside className="w-72 shrink-0 border-l border-[var(--border)] bg-[var(--surface)] flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
        <span className="text-sm font-semibold text-[var(--text)]">What&apos;s new</span>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-[var(--bg-muted)] text-[var(--text-muted)] transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">
        {whatsNew.map((item) => (
          <div key={item.title}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-base leading-none">{item.emoji}</span>
              <span className="text-[13px] font-semibold text-[var(--text)]">{item.title}</span>
            </div>
            <p className="text-[11px] text-[var(--text-muted)] mb-1">{item.date}</p>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{item.body}</p>
          </div>
        ))}
        <button
          type="button"
          className="text-xs text-[var(--brand-600)] hover:underline self-start"
        >
          Load more
        </button>
      </div>
    </aside>
  );
}

/* ─── Page ─── */
export default function FilesPage() {
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<ApiFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showPanel, setShowPanel] = useState(true);
  const [newFolderName, setNewFolderName] = useState("");
  const [showFolderInput, setShowFolderInput] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const resp = await api<{ items: ApiFile[]; total: number }>("/files?limit=100");
        if (!mounted) return;
        setFiles(resp.items ?? []);
      } catch {
        if (!mounted) return;
        setError("Failed to load files");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const filtered = useMemo(
    () => files.filter((p) => p.title.toLowerCase().includes(query.toLowerCase())),
    [files, query]
  );

  async function renameFile(file: ApiFile) {
    const next = window.prompt("New file name", file.title)?.trim();
    if (!next || next === file.title) return;
    try {
      const updated = await api<ApiFile>(`/files/${file.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: next }),
      });
      setFiles((prev) => prev.map((f) => (f.id === file.id ? updated : f)));
    } catch {
      setError("Rename failed");
    }
  }

  async function duplicateFile(file: ApiFile) {
    try {
      const created = await api<ApiFile>(`/files/${file.id}/duplicate`, { method: "POST" });
      setFiles((prev) => [created, ...prev]);
    } catch {
      setError("Duplicate failed");
    }
  }

  async function deleteFile(file: ApiFile) {
    if (!window.confirm(`Move "${file.title}" to trash?`)) return;
    try {
      await api<{ message: string }>(`/files/${file.id}`, { method: "DELETE" });
      setFiles((prev) => prev.filter((f) => f.id !== file.id));
    } catch {
      setError("Delete failed");
    }
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* main content */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="p-6">
          {/* toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            {/* breadcrumb */}
            <nav className="flex items-center gap-1 text-sm">
              <Link href="/app/files" className="font-semibold text-[var(--text)] hover:text-[var(--brand-600)]">
                Files
              </Link>
            </nav>

            {/* actions */}
            <div className="flex items-center gap-2">
              {/* notification bell */}
              <button
                type="button"
                onClick={() => setShowPanel((v) => !v)}
                className="relative flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] transition-colors"
                title="What's new"
              >
                <Bell className="h-4 w-4" />
                <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-[var(--brand-600)]" />
              </button>

              <Button variant="outline" size="sm" className="gap-1.5 text-xs h-8">
                <Layers className="h-3.5 w-3.5" /> Bulk create
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs h-8"
                onClick={() => setShowFolderInput(true)}
              >
                <FolderPlus className="h-3.5 w-3.5" /> New folder
              </Button>
              <Button size="sm" className="gap-1.5 text-xs h-8" asChild>
                <Link href="/app/create">
                  <FilePlus className="h-3.5 w-3.5" /> New file
                </Link>
              </Button>
            </div>
          </div>

          {/* sub-nav: Trash link */}
          <div className="flex items-center gap-4 mb-4 text-xs text-[var(--text-muted)]">
            <Link
              href="/app/files/trash"
              className="flex items-center gap-1 hover:text-[var(--brand-600)] transition-colors"
            >
              <Trash2 className="h-3 w-3" /> Trash
            </Link>
          </div>

          {/* new folder inline input */}
          {showFolderInput && (
            <div className="mb-4 flex items-center gap-2">
              <FolderPlus className="h-4 w-4 text-[var(--brand-600)] shrink-0" />
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === "Escape") {
                    setShowFolderInput(false);
                    setNewFolderName("");
                  }
                }}
                placeholder="Folder name…"
                className="h-8 w-52 rounded-[var(--radius-md)] border border-[var(--brand-600)] bg-[var(--surface)] px-3 text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30"
              />
              <span className="text-xs text-[var(--text-muted)]">Enter to confirm · Esc to cancel</span>
            </div>
          )}

          {/* search */}
          <div className="relative mb-5 max-w-xs">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--text-muted)] pointer-events-none" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search files…"
              className="w-full h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] pl-8 pr-3 text-xs text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
            />
          </div>
          {error && <p className="text-xs text-red-500 mb-3">{error}</p>}

          {/* grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
            {loading ? (
              <LoadingSkeleton />
            ) : filtered.length === 0 ? (
              query ? (
                <div className="col-span-full flex flex-col items-center py-16 text-center">
                  <p className="text-sm text-[var(--text-secondary)]">No files matching &ldquo;{query}&rdquo;</p>
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    className="mt-2 text-xs text-[var(--brand-600)] hover:underline"
                  >
                    Clear search
                  </button>
                </div>
              ) : (
                <EmptyState />
              )
            ) : (
              filtered.map((p) => (
                <FileCard
                  key={p.id}
                  project={p}
                  onRename={renameFile}
                  onDuplicate={duplicateFile}
                  onDelete={deleteFile}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* What's new panel */}
      {showPanel && <WhatsNewPanel onClose={() => setShowPanel(false)} />}
    </div>
  );
}
