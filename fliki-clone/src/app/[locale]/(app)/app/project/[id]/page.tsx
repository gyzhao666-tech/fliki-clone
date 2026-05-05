"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  Clock,
  Download,
  Eye,
  Film,
  Loader2,
  Maximize2,
  Play,
  Save,
  Settings2,
  SkipBack,
  SkipForward,
  Sparkles,
  Volume2,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RetryBanner } from "@/components/ui/retry-banner";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { feedback } from "@/lib/feedback";

type Scene = {
  id: string;
  file_id: string;
  order_index: number;
  title: string | null;
  script: string | null;
  voice_id: string | null;
  media_url: string | null;
  media_type: string | null;
  character_id: string | null;
  duration: number | null;
  video_url: string | null;
  video_prompt: string | null;
  video_status: string | null;
};

type FileInfo = {
  id: string;
  title: string;
  status: string;
  scene_count: number;
  duration: string | null;
  preview_url: string | null;
};

type GenerateStatus = "idle" | "generating" | "success" | "error";

const MOCK_SCENES: Scene[] = [
  {
    id: "mock-1",
    file_id: "mock",
    order_index: 0,
    title: "品牌开场",
    script: "ThermoX —— 重新定义你的饮水体验。每一口，都是恰到好处的温度。",
    voice_id: null,
    media_url: null,
    media_type: "video",
    character_id: null,
    duration: 4,
    video_url: null,
    video_prompt:
      "Cinematic brand intro, sleek thermos bottle rotating on a dark reflective surface, warm golden backlight, particles floating, brand logo 'ThermoX' appearing with elegant animation, premium product photography style, 4K, shallow depth of field",
    video_status: "done",
  },
  {
    id: "mock-2",
    file_id: "mock",
    order_index: 1,
    title: "产品展示",
    script: "展示产品外观与设计细节，突出轻量与质感。",
    voice_id: null,
    media_url: null,
    media_type: "video",
    character_id: null,
    duration: 5,
    video_url: null,
    video_prompt: "Close-up product showcase with clean studio lighting and smooth camera movement.",
    video_status: "done",
  },
  {
    id: "mock-3",
    file_id: "mock",
    order_index: 2,
    title: "核心卖点",
    script: "传递产品核心功能优势，建立信任感。",
    voice_id: null,
    media_url: null,
    media_type: "video",
    character_id: null,
    duration: 6,
    video_url: null,
    video_prompt: "Feature highlight sequence with floating UI labels and energetic motion.",
    video_status: "generating",
  },
  {
    id: "mock-4",
    file_id: "mock",
    order_index: 3,
    title: "使用场景",
    script: "展示办公室、健身与通勤场景，建立代入感。",
    voice_id: null,
    media_url: null,
    media_type: "video",
    character_id: null,
    duration: 6,
    video_url: null,
    video_prompt: "Lifestyle scenes showing the product in office, workout and commuting situations.",
    video_status: "pending",
  },
  {
    id: "mock-5",
    file_id: "mock",
    order_index: 4,
    title: "CTA 结尾",
    script: "引导用户行动，完成转化。",
    voice_id: null,
    media_url: null,
    media_type: "video",
    character_id: null,
    duration: 4,
    video_url: null,
    video_prompt: "Final call to action with brand packshot and clean typography.",
    video_status: "error",
  },
];

const timelineColors = [
  "bg-violet-100 text-violet-700 border-violet-300",
  "bg-emerald-100 text-emerald-700 border-emerald-200",
  "bg-amber-100 text-amber-700 border-amber-200",
  "bg-slate-100 text-slate-500 border-slate-200",
  "bg-red-50 text-red-500 border-red-100",
];

const sceneStatusMeta = {
  done: {
    label: "已完成",
    shortLabel: "已生成",
    pill: "bg-emerald-50 text-emerald-700",
    icon: CheckCircle2,
  },
  generating: {
    label: "生成中",
    shortLabel: "生成中",
    pill: "bg-amber-50 text-amber-700",
    icon: Loader2,
  },
  error: {
    label: "失败",
    shortLabel: "失败",
    pill: "bg-red-50 text-red-600",
    icon: AlertCircle,
  },
  pending: {
    label: "未生成",
    shortLabel: "未生成",
    pill: "bg-slate-100 text-slate-500",
    icon: Clock,
  },
};

function getSceneStatus(scene: Scene | null) {
  if (!scene) return sceneStatusMeta.pending;
  if (scene.video_status === "done") return sceneStatusMeta.done;
  if (scene.video_status === "generating") return sceneStatusMeta.generating;
  if (scene.video_status === "error") return sceneStatusMeta.error;
  return sceneStatusMeta.pending;
}

function formatDuration(seconds: number | null | undefined) {
  return `${seconds ?? 0}s`;
}

function ScenePanel({
  scenes,
  active,
  onSelect,
}: {
  scenes: Scene[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const completed = scenes.filter((scene) => scene.video_status === "done").length;

  return (
    <aside className="flex h-full w-[220px] shrink-0 flex-col border-r border-slate-200 bg-[#f7f8fb]">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-extrabold text-slate-700">分镜列表</h2>
          </div>
          <span className="text-base font-semibold text-slate-300">{completed}/{scenes.length}</span>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 py-4">
        {scenes.map((scene, index) => {
          const meta = getSceneStatus(scene);
          const Icon = meta.icon;
          const isActive = active === scene.id;

          return (
            <button
              key={scene.id}
              type="button"
              onClick={() => onSelect(scene.id)}
              className={cn(
                "grid w-full grid-cols-[72px_1fr] gap-3 rounded-[18px] border bg-white p-3 text-left transition-all",
                isActive
                  ? "border-violet-500 shadow-sm ring-1 ring-violet-200"
                  : "border-transparent hover:border-violet-200"
              )}
            >
              <div className="relative grid h-[54px] w-[66px] place-items-center rounded-xl bg-slate-800 text-white">
                {scene.video_url ? (
                  <video
                    src={scene.video_url}
                    preload="metadata"
                    muted
                    playsInline
                    className="h-full w-full rounded-xl object-cover"
                  />
                ) : (
                  <Play className="h-5 w-5 fill-white/80 text-white/80" />
                )}
                <span className="absolute bottom-2 right-2 text-xs font-bold text-white/80">
                  {formatDuration(scene.duration)}
                </span>
              </div>

              <div className="min-w-0 pt-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-300">F{index + 1}</span>
                  <p className="truncate text-base font-extrabold text-slate-800">
                    {scene.title ?? `分镜 ${index + 1}`}
                  </p>
                </div>
                <p className="mt-1 truncate text-[11px] text-slate-500">
                  {scene.script ?? scene.video_prompt ?? "暂无旁白，可在右侧补充。"}
                </p>
                <span className={cn("mt-2 inline-flex items-center gap-1.5 rounded-md bg-transparent px-0 py-0 text-sm font-bold", meta.pill)}>
                  <Icon className={cn("h-3.5 w-3.5", scene.video_status === "generating" && "animate-spin")} />
                  {meta.shortLabel}
                </span>
              </div>
            </button>
          );
        })}

        {scenes.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white p-5 text-center">
            <Film className="mx-auto h-5 w-5 text-slate-300" />
            <p className="mt-2 text-[11px] text-slate-500">还没有分镜。</p>
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 bg-white px-5 py-4">
        <button className="mx-auto flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-base font-bold text-violet-600">
          <Sparkles className="h-3.5 w-3.5" />
          模板变量
        </button>
      </div>
    </aside>
  );
}

function PreviewPanel({
  status,
  progress,
  progressStep,
  previewUrl,
  onGenerate,
  activeScene,
  allScenes,
  onSelectScene,
  onOpenPrompt,
  onRegenerateScene,
  onSaveVideoPrompt,
  canMergeFullVideo,
  onMergeFullVideo,
  mergeBusy,
}: {
  status: GenerateStatus;
  progress: number;
  progressStep: string;
  previewUrl: string | null;
  onGenerate: () => void;
  activeScene: Scene | null;
  allScenes: Scene[];
  onSelectScene: (id: string) => void;
  onOpenPrompt: () => void;
  onRegenerateScene: () => void | Promise<void>;
  onSaveVideoPrompt: () => void | Promise<void>;
  canMergeFullVideo: boolean;
  onMergeFullVideo: () => void | Promise<void>;
  mergeBusy: boolean;
}) {
  const [viewMode, setViewMode] = useState<"scene" | "full">("scene");
  const hasSceneVideo = !!activeScene?.video_url;
  const hasFullVideo = !!previewUrl;
  const sceneTitle = activeScene?.title ?? `分镜 ${(activeScene?.order_index ?? 0) + 1}`;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto px-10 py-3">
        <div className="mx-auto flex w-full max-w-[560px] min-w-0 flex-1 flex-col">
          <div className="relative overflow-hidden rounded-[28px] bg-[#100b2d] shadow-[0_18px_50px_-28px_rgb(40_20_80_/_0.9)]">
            <div className="flex aspect-video w-full items-center justify-center bg-[radial-gradient(circle_at_50%_45%,#42248a_0%,#231055_42%,#0d1326_100%)]">
              {status === "generating" ? (
                <div className="flex flex-col items-center gap-3 text-center text-white">
                  <Loader2 className="h-8 w-8 animate-spin text-violet-200" />
                  <div>
                    <p className="text-sm font-semibold">正在生成分镜视频</p>
                    <p className="mt-1 text-xs text-white/55">{progressStep || "正在调度视频生成任务..."}</p>
                  </div>
                </div>
              ) : viewMode === "full" && hasFullVideo ? (
                <video
                  src={previewUrl}
                  controls
                  playsInline
                  className="h-full w-full object-contain"
                />
              ) : hasSceneVideo ? (
                <video
                  key={activeScene.video_url!}
                  src={activeScene.video_url!}
                  controls
                  playsInline
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex flex-col items-center gap-3 text-white/60">
                  <div className="grid h-12 w-12 place-items-center rounded-full bg-white/10">
                    <Film className="h-5 w-5" />
                  </div>
                  <div className="text-center">
                    <p className="text-[12px] font-semibold text-white/70">{sceneTitle}</p>
                    <p className="mt-1 text-[11px] text-white/45">已生成 · {formatDuration(activeScene?.duration ?? 4)}</p>
                  </div>
                </div>
              )}
            </div>

            <div className="absolute bottom-10 left-4 right-4 h-1 overflow-hidden rounded-full bg-white/25">
              <div
                className="h-full rounded-full bg-violet-500 transition-all"
                style={{ width: status === "generating" ? `${Math.max(progress, 8)}%` : "36%" }}
              />
            </div>

            <div className="absolute bottom-3 left-4 right-4 flex items-center justify-between gap-3 text-white/80">
              <div className="flex items-center gap-2">
                <SkipBack className="h-3.5 w-3.5" />
                <button
                  type="button"
                  onClick={status === "idle" ? onGenerate : undefined}
                  className="grid h-8 w-8 place-items-center rounded-full bg-white/20 text-white transition hover:bg-white/25"
                >
                  {status === "generating" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="ml-0.5 h-4 w-4 fill-white" />
                  )}
                </button>
                <SkipForward className="h-3.5 w-3.5" />
                <span className="text-[11px] font-medium">0:01 / 0:{String(activeScene?.duration ?? 4).padStart(2, "0")}</span>
              </div>
              <div className="flex items-center gap-2">
                <Volume2 className="h-3.5 w-3.5" />
                <Maximize2 className="h-3.5 w-3.5" />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-5 gap-1.5 pt-1.5">
            {allScenes.map((scene) => {
              const isActive = scene.id === activeScene?.id && viewMode === "scene";
              return (
                <button
                  key={scene.id}
                  type="button"
                  onClick={() => {
                    setViewMode("scene");
                    onSelectScene(scene.id);
                  }}
                  className={cn(
                    "whitespace-nowrap rounded-lg border px-3 py-1.5 text-center text-xs font-bold transition",
                    isActive ? "border-violet-500 bg-violet-100 text-violet-700" : timelineColors[scene.order_index % timelineColors.length]
                  )}
                >
                  F{scene.order_index + 1} · {formatDuration(scene.duration)}
                </button>
              );
            })}
          </div>

          <div className="mt-4 grid grid-cols-[160px_1fr] items-center border-b border-slate-200 pb-3">
            <div className="grid grid-cols-[42px_66px_44px] items-center gap-3">
              <span className="rounded-lg bg-slate-100 px-2 py-1.5 text-center text-xs font-bold text-slate-400">
                F{(activeScene?.order_index ?? 0) + 1}
              </span>
              <h3 className="text-base font-extrabold leading-tight text-slate-800">
                {sceneTitle}
              </h3>
              <span className="text-sm font-extrabold leading-tight text-emerald-600">
                已完成
              </span>
            </div>
            <div className="grid grid-cols-4 items-center gap-2 text-center text-sm font-extrabold">
              <button type="button" onClick={onOpenPrompt} className="text-violet-600">
                提示词
              </button>
              <button type="button" onClick={() => void onRegenerateScene()} className="text-slate-500">
                重新生成
              </button>
              <button type="button" onClick={() => setViewMode(hasFullVideo ? "full" : "scene")} className="text-slate-500">
                详情
              </button>
              <button type="button" onClick={() => void onSaveVideoPrompt()} className="rounded-lg bg-violet-600 px-3 py-3 text-white">
                保存
              </button>
            </div>
          </div>

          <div className="mt-4">
            <label className="text-base font-bold text-slate-400">旁白 / 脚本</label>
            <Textarea
              rows={3}
              value={activeScene?.script ?? ""}
              readOnly
              placeholder="输入旁白或文案..."
              className="mt-3 min-h-[102px] resize-none rounded-xl border-slate-200 bg-slate-50 text-xl font-semibold leading-9 text-slate-700"
            />
            <button
              type="button"
              onClick={onOpenPrompt}
              className="sr-only"
            >
              打开居中弹窗编辑生成提示词
            </button>
          </div>

          {!hasFullVideo && canMergeFullVideo && (
            <Button
              size="sm"
              onClick={() => void onMergeFullVideo()}
              disabled={mergeBusy}
              className="mt-3 h-8 text-xs"
            >
              {mergeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {mergeBusy ? "合并中..." : "合并为完整视频"}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

export default function WorkspacePage() {
  const params = useParams();
  const projectId = params.id as string;

  const [scenes, setScenes] = useState<Scene[]>([]);
  const [activeScene, setActiveScene] = useState("");
  const [status, setStatus] = useState<GenerateStatus>("idle");
  const [progress, setProgress] = useState(0);
  const [progressStep, setProgressStep] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [selectedDuration, setSelectedDuration] = useState<5 | 10 | 15>(5);
  const styleCoherence = true;
  const [videoPromptDraft, setVideoPromptDraft] = useState("");
  const [isPromptDialogOpen, setIsPromptDialogOpen] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const generationSucceededRef = useRef(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeSceneRef = useRef(activeScene);
  activeSceneRef.current = activeScene;

  useEffect(() => {
    if (!projectId || projectId === "p-new") return;
    let mounted = true;
    (async () => {
      try {
        const [file, sceneList] = await Promise.all([
          api<FileInfo>(`/files/${projectId}`),
          api<Scene[]>(`/files/${projectId}/scenes`),
        ]);
        if (!mounted) return;
        setScenes(sceneList);
        if (sceneList.length > 0) {
          const first = sceneList[0];
          setActiveScene(first.id);
          setVideoPromptDraft(first.video_prompt ?? first.script ?? "");
        }
        const scenesWithDuration = sceneList.filter((scene) => scene.duration && scene.duration > 0);
        if (scenesWithDuration.length > 0) {
          const avgDur = scenesWithDuration.reduce((sum, scene) => sum + (scene.duration ?? 0), 0) / scenesWithDuration.length;
          const snapped = avgDur >= 12.5 ? 15 : avgDur >= 7.5 ? 10 : 5;
          setSelectedDuration(snapped as 5 | 10 | 15);
        }
        if (file.preview_url) setPreviewUrl(file.preview_url);
        if (file.status === "generating") setStatus("generating");
        else if (file.status === "done") setStatus("success");
        else if (file.status === "error") setStatus("error");
      } catch {
        // The page can still render an empty workspace if the API is unavailable.
      } finally {
        // Keep the mock editor visible when the API has no data.
      }
    })();
    return () => {
      mounted = false;
    };
  }, [projectId]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  function selectScene(id: string) {
    setActiveScene(id);
    const scene = [...scenes, ...MOCK_SCENES].find((item) => item.id === id);
    if (scene) setVideoPromptDraft(scene.video_prompt ?? scene.script ?? "");
  }

  function refreshScenesAndSyncPrompt(list: Scene[]) {
    setScenes(list);
    const current = list.find((item) => item.id === activeSceneRef.current);
    if (current) setVideoPromptDraft(current.video_prompt ?? current.script ?? "");
  }

  function startFallbackPoll() {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      try {
        const file = await api<FileInfo>(`/files/${projectId}`);
        if (file.status === "done") {
          clearInterval(pollTimerRef.current!);
          pollTimerRef.current = null;
          generationSucceededRef.current = true;
          setStatus("success");
          setProgress(100);
          setPreviewUrl(file.preview_url ?? null);
          api<Scene[]>(`/files/${projectId}/scenes`).then((list) => refreshScenesAndSyncPrompt(list)).catch(() => {});
          feedback.success("Video generated successfully!", {
            description: "Your video is ready to preview and export.",
            action: { label: "Export", onClick: () => {} },
          });
        } else if (file.status === "generating") {
          setProgress((value) => (value < 88 ? Math.max(value, 5) + 4 : value));
          setProgressStep((value) => value || "生成中...（进度为估算，完成后将自动跳转）");
        } else if (file.status === "error") {
          clearInterval(pollTimerRef.current!);
          pollTimerRef.current = null;
          setStatus("error");
          feedback.error("Generation failed", { description: "Something went wrong. Please try again." });
        }
      } catch {
        // Ignore transient polling failures.
      }
    }, 4000);
  }

  function startSsePolling(jobId: string) {
    eventSourceRef.current?.close();
    generationSucceededRef.current = false;
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    const base = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
    const url = `${base}/api/files/${projectId}/status?job_id=${encodeURIComponent(jobId)}`;
    const eventSource = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as {
          status: string;
          progress?: number;
          preview_url?: string;
          error?: string;
        };

        if (data.status === "generating" || data.status === "pending") {
          setProgress(data.progress ?? 0);
          setProgressStep(data.error ?? "");
        } else if (data.status === "done") {
          generationSucceededRef.current = true;
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          setStatus("success");
          setProgress(100);
          setPreviewUrl(data.preview_url ?? null);
          eventSource.close();
          api<Scene[]>(`/files/${projectId}/scenes`).then((list) => refreshScenesAndSyncPrompt(list)).catch(() => {});
          feedback.success("Video generated successfully!", {
            description: "Your video is ready to preview and export.",
            action: { label: "Export", onClick: () => {} },
          });
        } else if (data.status === "error") {
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          setStatus("error");
          eventSource.close();
          feedback.error("Generation failed", {
            description: data.error ?? "Something went wrong. Please try again.",
          });
        }
      } catch {
        // Ignore malformed SSE messages.
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      if (generationSucceededRef.current) return;
      startFallbackPoll();
    };
  }

  async function handleGenerate() {
    setStatus("generating");
    setProgress(0);
    try {
      const res = await api<{ job_id: string; estimated_seconds: number }>(
        `/files/${projectId}/generate`,
        {
          method: "POST",
          body: JSON.stringify({
            duration: selectedDuration,
            default_scene_duration: selectedDuration,
            prevent_style_drift: styleCoherence,
          }),
        }
      );
      setProgress(2);
      setProgressStep("任务已启动，连接进度...");
      startSsePolling(res.job_id);
    } catch {
      setStatus("error");
      feedback.error("Generation failed", { description: "Could not start generation. Please try again." });
    }
  }

  async function handleSaveVideoPrompt() {
    if (!activeSceneData) return;
    if (activeSceneData.id.startsWith("mock-")) {
      setIsPromptDialogOpen(false);
      setVideoPromptDraft(videoPromptDraft);
      feedback.success("Prompt saved");
      return;
    }
    try {
      await api<Scene>(`/scenes/${activeSceneData.id}`, {
        method: "PATCH",
        body: JSON.stringify({ video_prompt: videoPromptDraft }),
      });
      setScenes((prev) =>
        prev.map((scene) =>
          scene.id === activeSceneData.id ? { ...scene, video_prompt: videoPromptDraft } : scene
        )
      );
      setIsPromptDialogOpen(false);
      feedback.success("Prompt saved");
    } catch {
      feedback.error("Failed to save prompt");
    }
  }

  async function handleRegenerateScene() {
    if (!activeSceneData) return;
    if (activeSceneData.id.startsWith("mock-")) {
      feedback.success("已进入演示分镜预览", {
        description: "当前为空数据预览分镜，连接真实项目后可重新生成。",
      });
      return;
    }
    setStatus("generating");
    setProgress(0);
    try {
      const res = await api<{ job_id: string; estimated_seconds: number }>(
        `/scenes/${activeSceneData.id}/regenerate-video`,
        {
          method: "POST",
          body: JSON.stringify({
            video_prompt: videoPromptDraft.trim() || undefined,
            prevent_style_drift: true,
            default_scene_duration: selectedDuration,
          }),
        }
      );
      startSsePolling(res.job_id);
    } catch {
      setStatus(previewUrl ? "success" : "idle");
      feedback.error("Could not regenerate this scene", {
        description: "Check that Kling API keys are configured on the server.",
      });
    }
  }

  async function handleMergeFullVideo() {
    if (!projectId || projectId === "p-new") return;
    setMergeBusy(true);
    try {
      const file = await api<FileInfo>(`/files/${projectId}/merge-preview`, { method: "POST" });
      setPreviewUrl(file.preview_url ?? null);
      if (file.status === "done") setStatus("success");
      feedback.success("完整成片已就绪");
    } catch {
      feedback.error("合并失败", { description: "请确认各分镜视频可访问，或稍后重试。" });
    } finally {
      setMergeBusy(false);
    }
  }

  const displayScenes = scenes.length > 0 ? scenes : MOCK_SCENES;
  const activeSceneData =
    displayScenes.find((scene) => scene.id === activeScene) ??
    displayScenes[0] ??
    null;

  useEffect(() => {
    if (scenes.length === 0 && activeSceneData && !videoPromptDraft) {
      setVideoPromptDraft(activeSceneData.video_prompt ?? activeSceneData.script ?? "");
    }
  }, [activeSceneData, scenes.length, videoPromptDraft]);

  const sceneCount = displayScenes.length;
  const canMergeFullVideo =
    sceneCount > 0 &&
    scenes.length > 0 &&
    scenes.every((scene) => scene.video_url && scene.video_status === "done") &&
    !previewUrl;

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="grid h-[84px] shrink-0 grid-cols-[220px_1fr] border-b border-slate-200 bg-white">
        <div className="flex min-w-0 items-center gap-3 border-r border-slate-100 px-4">
          <Button variant="ghost" size="icon" className="rounded-full text-slate-400" asChild>
            <Link href="/app/files" title="Back to files">
              <ChevronLeft className="h-6 w-6" />
            </Link>
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="line-clamp-2 text-xl font-extrabold leading-tight text-slate-800">
              ThermoX 产品发布视频
            </h1>
          </div>
          <span className="rounded-xl bg-violet-50 px-3 py-2 text-sm font-extrabold text-violet-700">
            模板<br />替换
          </span>
        </div>

        <div className="flex min-w-0 items-center justify-end gap-2 px-4">
          <span className="flex items-center gap-1 text-sm font-bold text-slate-400">
            <Film className="h-4 w-4" /> 5分镜
          </span>
          <span className="mr-2 flex items-center gap-1 text-sm font-bold text-slate-500">
            <Clock className="h-5 w-5 text-slate-400" /> 25s
          </span>
          <button className="flex h-[66px] w-[80px] items-center justify-center gap-1 rounded-xl border border-slate-200 bg-white px-3 text-base font-bold text-slate-500">
            <Settings2 className="h-4 w-4" /> 设置
          </button>
          <button className="flex h-[66px] w-[90px] items-center justify-center gap-1 rounded-xl border border-slate-200 bg-white px-3 text-base font-bold text-slate-500">
            <Eye className="h-4 w-4" /> 预览
          </button>
          <button className="flex h-[66px] w-[90px] items-center justify-center gap-1 rounded-xl border border-slate-200 bg-white px-3 text-base font-bold text-slate-500">
            <Download className="h-4 w-4" /> 导出
          </button>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={status === "generating"}
            className="flex h-[84px] w-[104px] -translate-y-3 items-center justify-center rounded-b-2xl bg-violet-600 px-4 text-base font-extrabold leading-tight text-white shadow-[0_12px_24px_-10px_rgb(109_40_217)] disabled:opacity-60"
          >
            {status === "generating" ? "生成中" : "生成视频"}
          </button>
        </div>
      </div>

      {status === "error" && (
        <div className="shrink-0 px-5 pt-3">
          <RetryBanner
            title="Generation failed"
            description="Something went wrong while generating your video. You can retry or adjust the script and try again."
            retryLabel="Retry"
            onRetry={handleGenerate}
            onDismiss={() => setStatus(previewUrl ? "success" : "idle")}
          />
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <ScenePanel
          scenes={displayScenes}
          active={activeSceneData?.id ?? activeScene}
          onSelect={selectScene}
        />
        <PreviewPanel
          key={`${activeSceneData?.id ?? "none"}-${activeSceneData?.video_url ?? ""}-${previewUrl ?? ""}`}
          status={status}
          progress={progress}
          progressStep={progressStep}
          previewUrl={previewUrl}
          onGenerate={handleGenerate}
          activeScene={activeSceneData}
          allScenes={displayScenes}
          onSelectScene={selectScene}
          onOpenPrompt={() => setIsPromptDialogOpen(true)}
          onSaveVideoPrompt={handleSaveVideoPrompt}
          onRegenerateScene={handleRegenerateScene}
          canMergeFullVideo={canMergeFullVideo}
          onMergeFullVideo={handleMergeFullVideo}
          mergeBusy={mergeBusy}
        />
      </div>

      <Dialog open={isPromptDialogOpen} onOpenChange={setIsPromptDialogOpen}>
        <DialogContent className="left-1/2 top-1/2 max-w-2xl -translate-x-1/2 -translate-y-1/2 rounded-[28px] p-7">
          <DialogHeader>
            <DialogTitle>编辑生成提示词</DialogTitle>
            <DialogDescription>
              修改当前分镜的视觉提示词，保存后可用于重新生成该分镜。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Textarea
              rows={8}
              value={videoPromptDraft}
              onChange={(event) => setVideoPromptDraft(event.target.value)}
              placeholder="请输入当前分镜的镜头、主体、环境、光线、运动方式等提示词..."
              className="min-h-[220px] resize-y rounded-[20px] bg-slate-50 text-sm"
            />
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setIsPromptDialogOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={() => void handleSaveVideoPrompt()}>
                <Save className="h-4 w-4" />
                保存提示词
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
