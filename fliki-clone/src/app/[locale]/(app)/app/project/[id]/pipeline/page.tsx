"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Link as LinkIcon,
  Loader2,
  PlayCircle,
  Plus,
  RefreshCcw,
  RotateCcw,
  Send,
  ShieldAlert,
  Skull,
  ThumbsUp,
  Trash2,
  Unplug,
  Upload,
  XCircle,
} from "lucide-react";

import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { DagView } from "@/components/pipeline/dag-view";
import { feedback } from "@/lib/feedback";
import { ApiError } from "@/lib/api";
import {
  PipelineEstimate,
  PipelineQuota,
  PipelineRun,
  PipelineStep,
  approvePipelineStep,
  estimatePipeline,
  getPipeline,
  getPipelineQuota,
  isRunTerminal,
  rerunPipelineStep,
  startPipeline,
} from "@/lib/pipelines";
import { usePipelineStream } from "@/hooks/use-pipeline-stream";
import {
  useAudioCurrentWord,
  type SubtitleWithWords,
  type WordTimestamp,
} from "@/hooks/use-audio-current-word";
// Track-27 · RBAC editor/viewer 写权限分级：viewer 看到的写按钮 disable + tooltip
import { useCurrentRole } from "@/hooks/use-current-role";
import { canWrite, disabledReason } from "@/lib/role";
import { useRunRenders } from "@/hooks/use-run-renders";
import { useRunShotList } from "@/hooks/use-run-shot-list";
import { useDlq } from "@/hooks/use-dlq";
import { usePublishPlanStream } from "@/hooks/use-publish-plan-stream";
import {
  CostSummary,
  ProviderCostRow,
  getCostSummary,
} from "@/lib/cost";
import {
  DLQ_STATUSES,
  DlqItemOut,
  DlqStatus,
  discardDlq,
  retryDlq,
} from "@/lib/dlq";
import {
  CredentialOut,
  PUBLISH_PLAN_STATUSES,
  PlatformOut,
  PublishPlanOut,
  RenderOut,
  ShotListOut,
  ShotOut,
  VersionOut,
  createPublishPlan,
  createVersion,
  deletePublishPlan,
  deleteVersion,
  executePublishPlan,
  listFilePublishPlans,
  listFileVersions,
  listPlatformCredentials,
  listPlatforms,
  patchPublishPlan,
  publishVersion,
  revokePlatformCredentials,
  startPlatformOAuth,
} from "@/lib/production";

const TEMPLATES: Array<{ value: string; label: string; hint: string }> = [
  {
    value: "script_only",
    label: "script_only · 研究 → 脚本",
    hint: "最快验证 LLM 链路，不烧视频积分",
  },
  {
    value: "video_demo",
    label: "video_demo · 研究 → 脚本 → 视频 → 质检",
    hint: "端到端 demo，每个 shot 调一次 Kling/SF（≈ $1/镜，耗时较长）",
  },
  {
    value: "video_full",
    label: "video_full · 研究 → 脚本 → 美术 → 配音 → 视频 → 拼接 → 质检",
    hint: "在 demo 基础上加 ArtAgent（一致性提示词）+ VoiceAgent（旁白 TTS）；视频部分耗时与 demo 相同",
  },
];

const DEFAULT_BRIEF = {
  目标平台: ["bilibili", "youtube"],
  受众: "对 AI 视频感兴趣的产品/内容创作者",
  人设: "实战派 + 不堆术语",
  目标: "让观众理解流程层 vs 技能层的边界",
  禁区: ["夸张承诺", "未授权素材"],
  参考链接: [],
};

export default function ProjectPipelinePage() {
  const params = useParams<{ id: string }>();
  const fileId = params?.id ?? "";

  const [briefText, setBriefText] = useState<string>(
    JSON.stringify(DEFAULT_BRIEF, null, 2)
  );
  const [targetTopic, setTargetTopic] = useState<string>("");
  const [templateName, setTemplateName] = useState<string>(TEMPLATES[0].value);
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [quota, setQuota] = useState<PipelineQuota | null>(null);
  // Track-18：当前 tenant 本月成本（含按 provider 拆分），跟 quota 一起刷新
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);
  const [estimate, setEstimate] = useState<PipelineEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  // Track-07：流水线节点 section 视图模式（list / dag）。
  // 默认 list；切到 dag 后写入 localStorage `pipeline.view`，刷新后恢复。
  // 仅作用于「流水线节点」section，其他 panel 不受影响。
  const [pipelineView, setPipelineView] = useState<"list" | "dag">("list");
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem("pipeline.view");
    if (saved === "dag" || saved === "list") setPipelineView(saved);
  }, []);
  const setPipelineViewPersist = useCallback((v: "list" | "dag") => {
    setPipelineView(v);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("pipeline.view", v);
    }
  }, []);
  // 点 DAG 节点 → 滚动到对应 step 卡片（StepCard <li id="step-{name}"/>）。
  // 即使当前视图是 dag，也保留下方 list（DOM 始终在），只是用 hidden 控制可视性，
  // 这样切回 list 也无需重渲；scrollIntoView 在 hidden 时不生效，因此点击时强制切回 list。
  const handleDagNodeClick = useCallback((stepName: string) => {
    if (typeof window === "undefined") return;
    const el = window.document.getElementById(`step-${stepName}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ring-2", "ring-blue-500/40");
      window.setTimeout(() => {
        el.classList.remove("ring-2", "ring-blue-500/40");
      }, 1500);
    }
  }, []);

  // SSE：替代 2.5s polling；run 终态后 hook 自动断开 EventSource。
  // 连接错误时 hook 内部会退化到 polling，UI 仍能更新。
  const { mode: streamMode } = usePipelineStream({
    runId: run?.id ?? null,
    enabled: !!run && !isRunTerminal(run.state),
    onUpdate: setRun,
  });

  // Track-27 · 当前用户 role 探测：viewer 无写权限，启动 / 另存版本 / 新建发布计划等按钮 disable
  const role = useCurrentRole();
  const writeAllowed = canWrite(role, role.loading);
  const writeDisabledReason = disabledReason(role, role.loading);

  // shot-list 拉新表数据，供 art / video step 卡片优先消费（含每镜 art prompt + video URL 合并）。
  // 监听 art / video step state 变化时 reload —— persist 在 SSE publish 之前同步，重拉一定能拿到最新。
  const { shotList, reload: reloadShotList } = useRunShotList(run?.id ?? null, {
    enabled: !!run,
  });
  const artStepState = run?.steps.find((s) => s.agent_type === "art")?.state;
  const videoStepState = run?.steps.find((s) => s.agent_type === "video")?.state;
  useEffect(() => {
    if (run?.id) reloadShotList();
  }, [run?.id, artStepState, videoStepState, reloadShotList]);

  // 首次加载 + run 终态变化时刷新 quota（reserve / refund 都会改它）+ Track-18 cost summary
  const refreshQuota = useCallback(async () => {
    try {
      setQuota(await getPipelineQuota());
    } catch (error) {
      // 静默失败：不影响主流程
    }
    try {
      // Track-18：跟 quota 同步刷新本月成本汇总；run 终态后 record_call 已写完
      // 拉的就是新数。后端 resolve_query_tenant 会兜底成调用方自己的 tenant_id。
      const cs = await getCostSummary({ period: "monthly" });
      setCostSummary(cs);
    } catch (error) {
      // 静默失败：cost panel 仅信息展示，不影响主流程
    }
  }, []);

  useEffect(() => {
    refreshQuota();
  }, [refreshQuota, run?.state]);

  // 手动刷新（用户点按钮）：直接打一发 GET，SSE 流仍在跑
  const handleManualRefresh = useCallback(async () => {
    if (!run) return;
    try {
      const next = await getPipeline(run.id);
      setRun(next);
    } catch (error) {
      const message =
        error instanceof ApiError ? `API ${error.status}` : "网络错误";
      feedback.error(`流水线状态拉取失败：${message}`);
    }
  }, [run]);

  // 模板 / brief 改动时重新预估，给「启动」按钮一个明确的预算
  useEffect(() => {
    let cancelled = false;
    let parsedBrief: Record<string, unknown> = {};
    try {
      parsedBrief = JSON.parse(briefText);
    } catch {
      setEstimate(null);
      return;
    }
    setEstimating(true);
    const handle = setTimeout(async () => {
      try {
        const est = await estimatePipeline({
          template_name: templateName,
          brief: parsedBrief,
          target_topic: targetTopic.trim() || undefined,
        });
        if (!cancelled) setEstimate(est);
      } catch {
        if (!cancelled) setEstimate(null);
      } finally {
        if (!cancelled) setEstimating(false);
      }
    }, 350); // 防抖
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [briefText, templateName, targetTopic]);

  const handleStart = useCallback(async () => {
    let parsedBrief: Record<string, unknown> = {};
    try {
      parsedBrief = JSON.parse(briefText);
    } catch (error) {
      feedback.error("Brief 不是合法 JSON，请检查");
      return;
    }
    setStarting(true);
    try {
      const created = await startPipeline({
        template_name: templateName,
        file_id: fileId || undefined,
        brief: parsedBrief,
        target_topic: targetTopic.trim() || undefined,
      });
      // setRun 触发 usePipelineStream 自动开 SSE
      setRun(created);
      feedback.success("流水线已启动");
      refreshQuota();
    } catch (error) {
      // 优先把 402 / 429 之类的服务端 detail 暴给用户
      let message = "网络错误";
      if (error instanceof ApiError) {
        const detail =
          (error.body as { detail?: string } | null)?.detail ?? null;
        message = detail || `API ${error.status}`;
      }
      feedback.error(`启动失败：${message}`);
    } finally {
      setStarting(false);
    }
  }, [briefText, fileId, refreshQuota, targetTopic, templateName]);

  // 启动条件计算：估算 OK + 剩余额度足够 + 并发未到上限
  const startGate = useMemo(() => {
    if (!estimate) {
      return {
        canStart: !estimating,
        reason: estimating ? "正在预估成本…" : null,
      };
    }
    if (quota) {
      if (estimate.total_usd > quota.remaining_usd + 1e-6) {
        return {
          canStart: false,
          reason: `预估 $${estimate.total_usd.toFixed(4)} > 剩余额度 $${quota.remaining_usd.toFixed(4)}`,
        };
      }
      if (quota.active_runs >= quota.concurrent_max) {
        return {
          canStart: false,
          reason: `已有 ${quota.active_runs}/${quota.concurrent_max} 个 run 在跑，请等一下`,
        };
      }
    }
    return { canStart: true, reason: null };
  }, [estimate, estimating, quota]);

  const activeTemplate = useMemo(
    () => TEMPLATES.find((t) => t.value === templateName) ?? TEMPLATES[0],
    [templateName]
  );

  const handleRerun = useCallback(
    async (step: PipelineStep) => {
      if (!run) return;
      try {
        await rerunPipelineStep(run.id, step.name);
        feedback.info(`已重跑 ${step.name}`);
        // 后续 step_state / run_state 事件会通过 SSE 自动 patch
      } catch (error) {
        const message =
          error instanceof ApiError ? `API ${error.status}` : "网络错误";
        feedback.error(`重跑失败：${message}`);
      }
    },
    [run]
  );

  const handleApprove = useCallback(
    async (step: PipelineStep) => {
      if (!run) return;
      try {
        const next = await approvePipelineStep(run.id, step.name);
        setRun(next);
        feedback.success(`已通过 ${step.name}`);
      } catch (error) {
        const message =
          error instanceof ApiError ? `API ${error.status}` : "网络错误";
        feedback.error(`审批失败：${message}`);
      }
    },
    [run]
  );

  return (
    <div className="mx-auto flex min-h-[calc(100vh-3.5rem)] w-full max-w-6xl flex-col gap-6 px-6 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/app/project/${fileId}`}>
              <ArrowLeft className="size-4" />
              返回工作台
            </Link>
          </Button>
          <div>
            <h1 className="text-xl font-semibold">Agent 流水线</h1>
            <p className="text-sm text-muted-foreground">
              file_id: <code className="font-mono">{fileId || "(无)"}</code>
            </p>
          </div>
        </div>
        {run ? <RunStatePill state={run.state} /> : null}
      </header>

      <section className="grid gap-6 md:grid-cols-[1fr_1fr]">
        <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="text-sm font-medium">Brief（人输入的最高约束）</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Agent 只接收结构化输入；这里改 Brief 影响所有下游节点。
          </p>
          <Textarea
            className="mt-3 h-56 font-mono text-xs"
            value={briefText}
            onChange={(e) => setBriefText(e.target.value)}
          />
          <div className="mt-3 flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">
              指定选题（可选；不填则用 Research 输出第一条）
            </label>
            <Textarea
              className="h-16 font-mono text-xs"
              value={targetTopic}
              onChange={(e) => setTargetTopic(e.target.value)}
              placeholder="例如：AI 视频流程层 vs 技能层（也可以传整段 JSON）"
            />
          </div>
          <div className="mt-3 flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">
              Pipeline 模板
            </label>
            <select
              className="h-9 rounded border border-border bg-background px-2 text-sm"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              disabled={starting}
            >
              {TEMPLATES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">{activeTemplate.hint}</p>
          </div>
          <div className="mt-3 flex flex-col items-end gap-2">
            {!startGate.canStart && startGate.reason ? (
              <span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-500">
                {startGate.reason}
              </span>
            ) : null}
            <Button
              onClick={handleStart}
              disabled={starting || !startGate.canStart || !writeAllowed}
              title={writeDisabledReason ?? undefined}
            >
              {starting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  启动中
                </>
              ) : (
                <>
                  <PlayCircle className="size-4" />
                  {estimate
                    ? `启动（预估 $${estimate.total_usd.toFixed(4)}）`
                    : "启动流水线"}
                </>
              )}
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="text-sm font-medium">本次成本 & 月度配额</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            数据来自 model_calls 表；启动时按预估预扣，run 终态后退还差额。
          </p>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Stat label="本次预估" value={estimate?.total_usd ?? 0} />
            <Stat label="本次预扣" value={run?.cost_reserved_usd ?? 0} />
            <Stat label="实际花费" value={run?.cost_actual_usd ?? 0} />
            <Stat label="本月剩余配额" value={quota?.remaining_usd ?? 0} />
          </div>
          {quota ? (
            <>
              <p className="mt-3 text-xs text-muted-foreground">
                本月已用 ${quota.current_period_usage_usd.toFixed(4)} /{" "}
                ${quota.monthly_limit_usd.toFixed(2)} · 并发{" "}
                {quota.active_runs}/{quota.concurrent_max}
              </p>
              {quota.tenant_id ? (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                  <span
                    className="rounded bg-muted px-1.5 py-0.5 font-mono text-muted-foreground"
                    title="配额 v2：当前 tenant 命名空间（ws:{workspace_id} 或 u:{user_id}）"
                  >
                    tenant {quota.tenant_id}
                  </span>
                  <span
                    className="rounded bg-sky-500/10 px-1.5 py-0.5 text-sky-700 dark:text-sky-300"
                    title="按 plan 派生月度额度 / 并发上限 / 各 provider 桶 max"
                  >
                    plan {quota.tenant_plan}
                  </span>
                  {quota.tenant_display_name ? (
                    <span className="text-muted-foreground">
                      {quota.tenant_display_name}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {quota.provider_buckets?.length ? (
                <details className="mt-3 rounded bg-muted/30 p-2 text-xs">
                  <summary className="cursor-pointer text-muted-foreground">
                    Provider 并发桶（{quota.provider_buckets.length}）·
                    满桶请求会返 RATE_LIMITED 不计费
                  </summary>
                  <ul className="mt-2 flex flex-col gap-1.5">
                    {quota.provider_buckets.map((b) => {
                      const pct = Math.min(
                        100,
                        Math.max(0, b.utilization_pct)
                      );
                      const tone =
                        pct >= 95
                          ? "bg-rose-500"
                          : pct >= 70
                          ? "bg-amber-500"
                          : "bg-emerald-500";
                      return (
                        <li
                          key={b.provider_name}
                          className="flex items-center gap-2"
                        >
                          <span className="w-24 font-mono text-muted-foreground">
                            {b.provider_name}
                          </span>
                          <div className="relative h-1.5 flex-1 overflow-hidden rounded bg-muted">
                            <div
                              className={`absolute left-0 top-0 h-full ${tone}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="tabular-nums text-foreground">
                            {b.current_in_flight}/{b.max_concurrent}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </details>
              ) : null}
              <CostBreakdownPanel summary={costSummary} />
            </>
          ) : null}
          {estimate?.by_step?.length ? (
            <details className="mt-3 rounded bg-muted/30 p-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                每步预估明细
              </summary>
              <ul className="mt-2 flex flex-col gap-1 text-foreground">
                {estimate.by_step.map((s) => (
                  <li key={s.name} className="flex justify-between gap-3">
                    <span className="font-mono text-muted-foreground">
                      {s.name} · {s.agent_type}
                    </span>
                    <span className="tabular-nums">
                      ${s.est_usd.toFixed(4)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
        <header className="mb-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium">流水线节点</h2>
            {run && !isRunTerminal(run.state) ? (
              <StreamModeBadge mode={streamMode} />
            ) : null}
            {/* Track-07：list / DAG 视图切换。默认 list；选择记忆 localStorage `pipeline.view` */}
            <div
              className="ml-2 inline-flex overflow-hidden rounded border border-border text-[11px]"
              role="tablist"
              aria-label="流水线节点视图切换"
            >
              <button
                type="button"
                role="tab"
                aria-selected={pipelineView === "list"}
                onClick={() => setPipelineViewPersist("list")}
                className={
                  "px-2 py-0.5 transition-colors " +
                  (pipelineView === "list"
                    ? "bg-emerald-500/10 text-emerald-500"
                    : "text-muted-foreground hover:bg-muted/40")
                }
              >
                列表
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={pipelineView === "dag"}
                onClick={() => setPipelineViewPersist("dag")}
                className={
                  "border-l border-border px-2 py-0.5 transition-colors " +
                  (pipelineView === "dag"
                    ? "bg-emerald-500/10 text-emerald-500"
                    : "text-muted-foreground hover:bg-muted/40")
                }
              >
                DAG
              </button>
            </div>
          </div>
          {run ? (
            <Button variant="ghost" size="sm" onClick={handleManualRefresh}>
              <RefreshCcw className="size-3.5" />
              手动刷新
            </Button>
          ) : null}
        </header>

        {!run ? (
          <p className="text-sm text-muted-foreground">
            还没启动流水线。在左侧填写 Brief 后点“启动流水线”。
          </p>
        ) : pipelineView === "dag" ? (
          <DagView
            run={run}
            onNodeClick={(name) => {
              // 切回 list 让目标 step 卡片可见，再 scrollIntoView
              setPipelineViewPersist("list");
              window.requestAnimationFrame(() => handleDagNodeClick(name));
            }}
          />
        ) : (
          <ol className="flex flex-col gap-3">
            {run.steps.map((step, index) => (
              <StepCard
                key={step.id}
                step={step}
                runId={run.id}
                runState={run.state}
                index={index + 1}
                onRerun={handleRerun}
                onApprove={handleApprove}
                shotList={shotList}
              />
            ))}
          </ol>
        )}
      </section>

      {fileId ? (
        <ProductionPanel
          fileId={fileId}
          currentRunId={run?.id ?? null}
          currentRunState={run?.state ?? null}
        />
      ) : null}

      <PlatformCredentialsPanel />

      <DeadLetterPanel currentRunId={run?.id ?? null} />
    </div>
  );
}

interface SubtitleStyleDebug {
  aspect_used: string;
  font_name?: string;
  font_size: number;
  margin_v: number;
  outline: number;
  shadow?: number;
  alignment?: string;
  scale?: number;
}

interface AspectPreview {
  url: string | null;
  muxed: boolean;
  burned_in_subtitles: boolean;
  looped_video: boolean;
  aspect_fit: string;
  warning: string | null;
  subtitle_style?: SubtitleStyleDebug | null;
}

/** 把 RenderOut[] 折成 outputs_json.previews_by_aspect 结构，便于复用现有渲染逻辑。 */
function buildAspectMapFromRenders(
  renders: RenderOut[]
): Record<string, AspectPreview> | null {
  if (!renders.length) return null;
  const out: Record<string, AspectPreview> = {};
  for (const r of renders) {
    if (!r.url) continue;
    out[r.aspect_ratio] = {
      url: r.url,
      muxed: r.muxed,
      burned_in_subtitles: r.burned_in_subtitles,
      looped_video: r.looped_video,
      aspect_fit: r.aspect_fit ?? "cover",
      warning: r.warning,
    };
  }
  return Object.keys(out).length ? out : null;
}

function EditArtifact({
  runId,
  runState,
  stepState,
  out,
  previewUrl,
  narrationUrl,
  subtitles,
}: {
  runId: string;
  runState: PipelineRun["state"];
  stepState: PipelineStep["state"];
  out: Record<string, unknown>;
  previewUrl: string | null;
  narrationUrl: string | null;
  subtitles: Array<Record<string, unknown>> | null;
}) {
  // 优先用新生产 API（权威源）；hook 在 step 进 succeeded / awaiting_review 时拉
  const editFinished =
    stepState === "succeeded" || stepState === "awaiting_review";
  const { renders, reload } = useRunRenders(runId, { enabled: editFinished });

  // step 状态变化时自动 reload（SSE event 已经触发渲染）
  useEffect(() => {
    if (editFinished) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepState, runState]);

  const fromApi = useMemo(
    () => buildAspectMapFromRenders(renders),
    [renders]
  );

  // outputs_json 的 previews_by_aspect 仅在 API 还没返数据时作 fallback
  const previewsByAspectRaw =
    out.previews_by_aspect && typeof out.previews_by_aspect === "object"
      ? (out.previews_by_aspect as Record<string, AspectPreview>)
      : null;
  const previewsByAspect = fromApi ?? previewsByAspectRaw;
  // v5：subtitle_style debug 只在 outputs_json 里（renders 表暂未存这个字段）；
  // 即使 fromApi 走主路径，仍从 outputs_json 旁路读出 hover 用
  const subtitleStyleByAspect =
    previewsByAspectRaw
      ? Object.fromEntries(
          Object.entries(previewsByAspectRaw)
            .filter(([, v]) => v?.subtitle_style)
            .map(([k, v]) => [k, v.subtitle_style as SubtitleStyleDebug])
        )
      : {};
  const apiPrimary = renders.find((r) => r.is_primary)?.aspect_ratio ?? null;
  const primaryAspect =
    apiPrimary ??
    (typeof out.primary_aspect === "string"
      ? (out.primary_aspect as string)
      : null);
  const aspectFit =
    renders[0]?.aspect_fit ??
    (typeof out.aspect_fit === "string" ? (out.aspect_fit as string) : null);
  const looped =
    renders.some((r) => r.looped_video) || out.looped_video === true;

  const aspectKeys = previewsByAspect
    ? Object.keys(previewsByAspect).filter(
        (k) => previewsByAspect[k] && previewsByAspect[k].url
      )
    : [];
  const initial =
    primaryAspect && aspectKeys.includes(primaryAspect)
      ? primaryAspect
      : aspectKeys[0] ?? null;
  const [selectedAspect, setSelectedAspect] = useState<string | null>(initial);

  // primary 切换 / aspect 增减后自动选中合理的 tab
  useEffect(() => {
    if (!selectedAspect && initial) setSelectedAspect(initial);
    else if (selectedAspect && !aspectKeys.includes(selectedAspect)) {
      setSelectedAspect(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aspectKeys.join("|"), initial]);

  const entry: AspectPreview | null =
    previewsByAspect && selectedAspect
      ? previewsByAspect[selectedAspect] ?? null
      : null;
  const currentUrl = entry?.url ?? previewUrl;
  const muxed = entry ? entry.muxed : out.muxed === true;
  const burned = entry ? entry.burned_in_subtitles : out.burned_in_subtitles === true;
  const warning =
    entry?.warning ??
    (typeof out.warning === "string" ? (out.warning as string) : null);
  const subtitleUrl =
    renders.find((r) => r.subtitle_url)?.subtitle_url ??
    (typeof out.subtitle_url === "string" ? (out.subtitle_url as string) : null);
  const dataSource: "api" | "outputs_json" | "none" = fromApi
    ? "api"
    : previewsByAspectRaw
    ? "outputs_json"
    : "none";

  return (
    <div className="flex flex-col gap-2 text-xs">
      {aspectKeys.length > 1 ? (
        <AspectTabs
          aspects={aspectKeys}
          selected={selectedAspect}
          onSelect={setSelectedAspect}
          aspectFit={aspectFit}
          dataSource={dataSource}
          subtitleStyleByAspect={subtitleStyleByAspect}
        />
      ) : null}
      {selectedAspect && subtitleStyleByAspect[selectedAspect] && burned ? (
        <SubtitleStyleHint style={subtitleStyleByAspect[selectedAspect]} />
      ) : null}
      {currentUrl ? (
        <video
          key={currentUrl}
          src={currentUrl}
          controls
          className="w-full max-w-md rounded border border-border bg-black"
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        {burned ? (
          <span className="rounded bg-emerald-500/10 px-2 py-1 text-emerald-500">
            字幕已烧录 ✓
          </span>
        ) : null}
        {muxed && !burned ? (
          <span className="rounded bg-emerald-500/10 px-2 py-1 text-emerald-500">
            已混音旁白 ✓
          </span>
        ) : null}
        {!muxed && narrationUrl ? (
          <span className="rounded bg-amber-500/10 px-2 py-1 text-amber-500">
            未混音 / 静默版
          </span>
        ) : null}
        {looped ? (
          <span
            className="rounded bg-sky-500/10 px-2 py-1 text-sky-500"
            title="audio 比 video 长，已对视频做循环以匹配旁白时长"
          >
            视频已循环 ↻
          </span>
        ) : null}
        {subtitleUrl ? (
          <a
            href={subtitleUrl}
            target="_blank"
            rel="noreferrer"
            className="rounded border border-border px-2 py-1 text-muted-foreground hover:bg-muted/30"
          >
            下载 .srt
          </a>
        ) : null}
      </div>
      {warning ? (
        <div className="rounded bg-amber-500/10 px-2 py-1 text-amber-500">
          {warning}
        </div>
      ) : null}
      {narrationUrl ? (
        <div>
          <div className="text-muted-foreground">独立旁白音轨（备查）</div>
          <audio
            src={narrationUrl}
            controls
            className="w-full max-w-md"
            preload="none"
          />
        </div>
      ) : null}
      {subtitles?.length ? (
        <details className="rounded bg-muted/30 p-2">
          <summary className="cursor-pointer text-muted-foreground">
            字幕（{subtitles.length} 条）
          </summary>
          <ul className="mt-2 flex flex-col gap-1 text-foreground">
            {subtitles.slice(0, 12).map((s, i) => (
              <li key={i}>
                <span className="font-mono text-muted-foreground">
                  {formatTimeRange(s.start, s.end)}
                </span>{" "}
                {(s.text as string) || ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function AspectTabs({
  aspects,
  selected,
  onSelect,
  aspectFit,
  dataSource,
  subtitleStyleByAspect,
}: {
  aspects: string[];
  selected: string | null;
  onSelect: (v: string) => void;
  aspectFit: string | null;
  dataSource?: "api" | "outputs_json" | "none";
  subtitleStyleByAspect?: Record<string, SubtitleStyleDebug>;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground">导出比例：</span>
      {aspects.map((a) => {
        const active = a === selected;
        const ss = subtitleStyleByAspect?.[a];
        const hint = ss
          ? `字幕样式 (v5)：字号 ${ss.font_size} · MarginV ${ss.margin_v} · Outline ${ss.outline}` +
            (ss.scale && ss.scale !== 1 ? ` · scale ×${ss.scale}` : "")
          : `导出 ${a}`;
        return (
          <button
            key={a}
            type="button"
            onClick={() => onSelect(a)}
            title={hint}
            className={
              "rounded border px-2 py-0.5 font-mono text-[11px] transition-colors " +
              (active
                ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-500"
                : "border-border text-muted-foreground hover:bg-muted/30")
            }
          >
            {a}
          </button>
        );
      })}
      {aspectFit ? (
        <span
          className="ml-1 rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
          title={
            aspectFit === "cover"
              ? "等比缩放后裁掉超出部分填满目标画幅，无黑边"
              : "letterbox 黑边补齐，画面完整不变形"
          }
        >
          {aspectFit}
        </span>
      ) : null}
      {dataSource === "api" ? (
        <span
          className="ml-auto rounded border border-emerald-500/40 px-1.5 py-0.5 text-[10px] text-emerald-500"
          title="数据来自 /api/production/runs/{id}/renders（权威源）"
        >
          renders 表
        </span>
      ) : dataSource === "outputs_json" ? (
        <span
          className="ml-auto rounded border border-amber-500/40 px-1.5 py-0.5 text-[10px] text-amber-500"
          title="兼容期：仍读 outputs_json（新表无数据，可能是老 run 或后端 persist 还没完成）"
        >
          outputs_json
        </span>
      ) : null}
    </div>
  );
}

// EditAgent v5：当前选中 aspect 的字幕样式调试条；只在「字幕已烧录」时展示，
// 让用户能立刻看到「这个比例用了多大字号 / 多高边距」，验证 v5 改造是否生效。
function SubtitleStyleHint({ style }: { style: SubtitleStyleDebug }) {
  return (
    <div
      className="rounded border border-sky-500/30 bg-sky-500/5 px-2 py-1 text-[11px] text-sky-500"
      title={
        "v5 字幕样式按目标 aspect 自动调整：9:16 / 4:5 字号更大 + MarginV 更高（避开平台 UI），16:9 沿用基线"
      }
    >
      <span className="font-mono">{style.aspect_used}</span>
      <span className="ml-2 text-muted-foreground">
        字号 <span className="text-foreground">{style.font_size}</span>
        {" · MarginV "}
        <span className="text-foreground">{style.margin_v}</span>
        {" · Outline "}
        <span className="text-foreground">{style.outline}</span>
        {style.scale && style.scale !== 1
          ? ` · scale ×${style.scale}`
          : ""}
        {style.font_name ? ` · ${style.font_name}` : ""}
      </span>
    </div>
  );
}

function StreamModeBadge({ mode }: { mode: "idle" | "stream" | "polling" }) {
  if (mode === "idle") return null;
  const isStream = mode === "stream";
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium " +
        (isStream
          ? "border-emerald-500/40 text-emerald-500"
          : "border-amber-500/40 text-amber-500")
      }
      title={
        isStream
          ? "实时事件（SSE）"
          : "事件流断开，已退到 2.5s 轮询；恢复后会自动切回"
      }
    >
      <span
        className={
          "size-1.5 rounded-full " +
          (isStream ? "bg-emerald-500" : "bg-amber-500 animate-pulse")
        }
      />
      {isStream ? "实时" : "轮询"}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-border bg-muted/40 px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">
        ${value.toFixed(4)}
      </div>
    </div>
  );
}

// Track-18：本月按 tenant 聚合的成本明细（含 provider 拆分横向 bar）。
// quota 视图是「容量」（reserved / monthly_limit / concurrent_max），这里是「明细」
// （model_calls 实际写入），数据源不同所以分开渲染；折叠 details 默认收起，避免
// 干扰主流程；total_cost_usd 与 quota.usage 通常接近但不严格等于（quota 是 run
// 级 reserve+settle 后的累计；cost 是 model_call 粒度，差额来自 partial_failed
// 不退还的 reserved 漂移）。
function CostBreakdownPanel({ summary }: { summary: CostSummary | null }) {
  if (!summary || summary.by_provider.length === 0) return null;
  const total = summary.total_cost_usd;
  // 横向 bar 的归一化基准取 max(provider.cost_usd)，让最大 provider 占 100% 视觉宽度
  const maxCost = Math.max(...summary.by_provider.map((r) => r.cost_usd), 0.0000001);
  const periodLabel =
    summary.period === "weekly"
      ? "最近 7 天"
      : summary.period === "daily"
      ? "最近 24 小时"
      : "本月";
  return (
    <details className="mt-3 rounded bg-muted/30 p-2 text-xs">
      <summary className="cursor-pointer text-muted-foreground">
        Provider 成本拆分（{periodLabel} · {summary.by_provider.length} 个 provider · 共 {summary.total_calls} 次调用）
        · 累计 ${total.toFixed(4)}
      </summary>
      <ul className="mt-2 flex flex-col gap-1.5">
        {summary.by_provider.map((r) => {
          const pct = Math.min(100, Math.max(0, (r.cost_usd / maxCost) * 100));
          const tone = providerTone(r.provider);
          return (
            <li key={r.provider} className="flex items-center gap-2">
              <span className="w-24 font-mono text-muted-foreground">
                {r.provider}
              </span>
              <div className="relative h-1.5 flex-1 overflow-hidden rounded bg-muted">
                <div
                  className={`absolute left-0 top-0 h-full ${tone}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span
                className="tabular-nums text-foreground"
                title={`成功 ${r.success_count} · 失败 ${r.failed_count}`}
              >
                ${r.cost_usd.toFixed(4)} · {r.call_count} 次
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

// 简单 provider → 颜色映射（与既有 provider bucket panel 保持视觉一致：
// emerald = OpenAI 系（贵但稳）; sky = SiliconFlow（便宜量大）; amber = Kling 视频）。
function providerTone(provider: string): string {
  const p = provider.toLowerCase();
  if (p.includes("openai")) return "bg-emerald-500";
  if (p.includes("siliconflow")) return "bg-sky-500";
  if (p.includes("kling")) return "bg-amber-500";
  if (p.includes("elevenlabs")) return "bg-violet-500";
  if (p.includes("faster_whisper") || p.includes("local")) return "bg-slate-500";
  return "bg-muted-foreground/50";
}

function RunStatePill({ state }: { state: PipelineRun["state"] }) {
  const meta = RUN_STATE_META[state];
  const Icon = meta.icon;
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium " +
        meta.cls
      }
    >
      <Icon className="size-3.5" />
      {meta.label}
    </span>
  );
}

const RUN_STATE_META: Record<
  PipelineRun["state"],
  { label: string; icon: typeof CircleDashed; cls: string }
> = {
  queued: {
    label: "排队中",
    icon: CircleDashed,
    cls: "border-muted text-muted-foreground",
  },
  running: {
    label: "运行中",
    icon: Loader2,
    cls: "border-blue-500/40 text-blue-500",
  },
  awaiting_review: {
    label: "等待审批",
    icon: ShieldAlert,
    cls: "border-amber-500/40 text-amber-500",
  },
  partial_failed: {
    label: "部分失败",
    icon: ShieldAlert,
    cls: "border-rose-500/40 text-rose-500",
  },
  succeeded: {
    label: "已完成",
    icon: CheckCircle2,
    cls: "border-emerald-500/40 text-emerald-500",
  },
  failed: {
    label: "失败",
    icon: XCircle,
    cls: "border-rose-500/40 text-rose-500",
  },
  cancelled: {
    label: "已取消",
    icon: XCircle,
    cls: "border-muted text-muted-foreground",
  },
};

function StepCard({
  step,
  runId,
  runState,
  index,
  onRerun,
  onApprove,
  shotList,
}: {
  step: PipelineStep;
  runId: string;
  runState: PipelineRun["state"];
  index: number;
  onRerun: (step: PipelineStep) => void;
  onApprove: (step: PipelineStep) => void;
  shotList: ShotListOut | null;
}) {
  const meta = STEP_STATE_META[step.state];
  const Icon = meta.icon;
  const previewText = useMemo(
    () => formatOutputs(step.outputs_json),
    [step.outputs_json]
  );

  return (
    <li
      id={`step-${step.name}`}
      className="flex flex-col gap-2 rounded border border-border bg-background/40 p-3 scroll-mt-20 transition-shadow"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground tabular-nums">
            {String(index).padStart(2, "0")}
          </span>
          <Icon className={`size-4 ${meta.iconCls}`} />
          <div>
            <div className="text-sm font-medium">
              {step.name}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {step.agent_type}
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              attempt {step.attempt}
              {step.cost_usd > 0
                ? ` · cost $${step.cost_usd.toFixed(4)}`
                : ""}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {step.state === "awaiting_review" ? (
            <Button size="sm" onClick={() => onApprove(step)}>
              <ThumbsUp className="size-3.5" />
              通过
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onRerun(step)}
            disabled={step.state === "running"}
          >
            <RefreshCcw className="size-3.5" />
            重跑
          </Button>
        </div>
      </div>

      {step.error ? (
        <pre className="overflow-auto rounded bg-rose-500/10 p-2 text-xs text-rose-400">
          {step.error}
        </pre>
      ) : null}

      <StepArtifacts
        step={step}
        runId={runId}
        runState={runState}
        shotList={shotList}
      />

      {previewText ? (
        <details className="rounded bg-muted/40 p-2 text-xs">
          <summary className="cursor-pointer text-muted-foreground">
            完整 outputs JSON
          </summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap break-words text-foreground">
            {previewText}
          </pre>
        </details>
      ) : null}
    </li>
  );
}

function StepArtifacts({
  step,
  runId,
  runState,
  shotList,
}: {
  step: PipelineStep;
  runId: string;
  runState: PipelineRun["state"];
  shotList: ShotListOut | null;
}) {
  const out = step.outputs_json;
  if (!out) return null;

  // 视频/拼接预览（video / edit）
  const previewUrl =
    typeof out.preview_url === "string" ? (out.preview_url as string) : null;
  const narrationUrl =
    typeof out.narration_url === "string" ? (out.narration_url as string) : null;
  const subtitles = Array.isArray(out.subtitles)
    ? (out.subtitles as Array<Record<string, unknown>>)
    : null;

  if (step.agent_type === "art") {
    const styleBoard =
      out.style_board && typeof out.style_board === "object"
        ? (out.style_board as Record<string, unknown>)
        : null;
    const characters = Array.isArray(out.character_cards)
      ? (out.character_cards as Array<Record<string, unknown>>)
      : [];
    // v3 角色一致性
    const consistencyMode =
      typeof out.consistency_mode === "string"
        ? (out.consistency_mode as string)
        : null;
    const characterAnchor =
      out.character_anchor && typeof out.character_anchor === "object"
        ? (out.character_anchor as Record<string, unknown>)
        : null;
    // v5：多角色 anchor 字典（dict[name -> anchor]）；v3 老 run 时为 null
    const characterAnchors =
      out.character_anchors && typeof out.character_anchors === "object"
        ? (out.character_anchors as Record<string, Record<string, unknown>>)
        : null;
    const protagonistName =
      typeof out.protagonist_name === "string"
        ? (out.protagonist_name as string)
        : null;
    const consistencyWarning =
      typeof out.consistency_warning === "string"
        ? (out.consistency_warning as string)
        : null;
    // shots 优先读 shot_lists.shots（权威源，含 art + video 合并字段）；缺失 fallback 到 outputs_json
    const shotListShots = shotList?.shots ?? [];
    const fallbackShots = Array.isArray(out.shots)
      ? (out.shots as Array<Record<string, unknown>>)
      : [];
    const useShotListSource = shotListShots.length > 0;
    const shots: Array<Record<string, unknown>> = useShotListSource
      ? (shotListShots as unknown as Array<Record<string, unknown>>)
      : fallbackShots;
    return (
      <div className="flex flex-col gap-2 text-xs">
        {consistencyMode ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {consistencyMode === "anchor" ? (
              <span
                className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-600 dark:text-emerald-400"
                title={
                  "v3 角色一致性：锚点 ✓。先单独生成主角参考板，再把角色描述强制注入到每镜 prompt 头；防漂关键词写入 negative prompt"
                }
              >
                角色锚点 ✓ v3
                {protagonistName ? ` · ${protagonistName}` : ""}
              </span>
            ) : consistencyMode === "prompt-only" ? (
              <span
                className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-500"
                title="v3 prompt-only：仅把角色描述注入每镜 prompt（未生成锚点）"
              >
                prompt-only v3
                {protagonistName ? ` · ${protagonistName}` : ""}
              </span>
            ) : (
              <span
                className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                title="角色一致性未启用（off / 无角色卡）"
              >
                一致性 off
              </span>
            )}
            {consistencyWarning ? (
              <span
                className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-500"
                title={consistencyWarning}
              >
                ⚠ 锚点失败 → prompt-only 兜底
              </span>
            ) : null}
          </div>
        ) : null}
        {/* v5：多角色 anchors 优先展示；缺失时退回 v3 单 anchor 渲染 */}
        {characterAnchors && Object.keys(characterAnchors).length ? (
          <div className="flex flex-col gap-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              角色锚点（{Object.keys(characterAnchors).length}）
              {Object.keys(characterAnchors).length > 1 ? (
                <span
                  className="ml-1 rounded bg-violet-500/15 px-1 py-0.5 text-[9px] text-violet-500"
                  title="v5 多角色锁定：每个 character_card 各出一份 anchor，逐镜按 focus_character 选对应 anchor + 注入对应前缀"
                >
                  v5 多角色
                </span>
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {Object.entries(characterAnchors).map(([name, anchor]) => {
                const url =
                  typeof anchor.url === "string"
                    ? (anchor.url as string)
                    : null;
                const isProtagonist = name === protagonistName;
                const err =
                  typeof anchor.error === "string"
                    ? (anchor.error as string)
                    : null;
                return (
                  <div
                    key={name}
                    className={`flex items-start gap-2 rounded border p-2 ${
                      isProtagonist
                        ? "border-emerald-500/30 bg-emerald-500/5"
                        : "border-violet-500/30 bg-violet-500/5"
                    }`}
                  >
                    {url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={url}
                        alt={`character anchor ${name}`}
                        className="size-16 shrink-0 rounded object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex size-16 shrink-0 items-center justify-center rounded bg-rose-500/10 text-[10px] text-rose-400">
                        ✕
                      </div>
                    )}
                    <div className="flex min-w-0 flex-col gap-0.5 text-[11px]">
                      <div className="font-medium">
                        <code className="font-mono">{name}</code>
                        {isProtagonist ? (
                          <span className="ml-1 text-[9px] text-emerald-500">
                            主角
                          </span>
                        ) : (
                          <span className="ml-1 text-[9px] text-violet-500">
                            配角
                          </span>
                        )}
                      </div>
                      <div className="text-muted-foreground line-clamp-2">
                        {(anchor.appearance as string) || ""}
                        {anchor.wardrobe
                          ? `；${anchor.wardrobe as string}`
                          : ""}
                      </div>
                      {err ? (
                        <div
                          className="truncate text-[10px] text-rose-400"
                          title={err}
                        >
                          ✕ {err}
                        </div>
                      ) : (
                        <div className="text-[10px] text-muted-foreground">
                          {(anchor.provider as string) || "—"}
                          {anchor.model
                            ? ` / ${anchor.model as string}`
                            : ""}
                          {typeof anchor.cost_usd === "number"
                            ? ` · $${(anchor.cost_usd as number).toFixed(4)}`
                            : ""}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : characterAnchor && characterAnchor.url ? (
          <div className="flex items-start gap-2 rounded border border-emerald-500/30 bg-emerald-500/5 p-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={characterAnchor.url as string}
              alt={`character anchor ${characterAnchor.name as string}`}
              className="size-20 shrink-0 rounded object-cover"
              loading="lazy"
            />
            <div className="flex min-w-0 flex-col gap-0.5 text-[11px]">
              <div className="font-medium">
                角色锚点 ·{" "}
                <code className="font-mono">
                  {(characterAnchor.name as string) || protagonistName || "—"}
                </code>
              </div>
              <div className="text-muted-foreground line-clamp-2">
                {(characterAnchor.appearance as string) || ""}
                {characterAnchor.wardrobe
                  ? `；${characterAnchor.wardrobe as string}`
                  : ""}
              </div>
              <div className="text-[10px] text-muted-foreground">
                provider{" "}
                <code className="font-mono">
                  {(characterAnchor.provider as string) || "—"}
                </code>
                {characterAnchor.model
                  ? ` / ${characterAnchor.model as string}`
                  : ""}
                {typeof characterAnchor.cost_usd === "number"
                  ? ` · $${(characterAnchor.cost_usd as number).toFixed(4)}`
                  : ""}
              </div>
            </div>
          </div>
        ) : null}
        {styleBoard ? (
          <div className="rounded border border-border bg-muted/30 p-2">
            <div className="mb-1 font-medium">风格板</div>
            <KeyValRow
              label="aspect"
              value={(styleBoard.aspect_ratio as string) || "—"}
            />
            <KeyValRow
              label="style"
              value={joinList(styleBoard.style_keywords)}
            />
            <KeyValRow label="palette" value={joinList(styleBoard.palette)} />
            <KeyValRow
              label="lighting"
              value={(styleBoard.lighting as string) || "—"}
            />
            <KeyValRow
              label="camera"
              value={joinList(styleBoard.camera_language)}
            />
            {styleBoard.reference_notes ? (
              <KeyValRow
                label="notes"
                value={styleBoard.reference_notes as string}
              />
            ) : null}
          </div>
        ) : null}
        {characters.length ? (
          <div className="rounded border border-border bg-muted/30 p-2">
            <div className="mb-1 font-medium">
              角色卡（{characters.length}）
            </div>
            <ul className="flex flex-col gap-1">
              {characters.map((c, i) => (
                <li key={i} className="text-foreground">
                  <span className="font-mono text-muted-foreground">
                    {(c.name as string) || `#${i + 1}`}
                  </span>
                  ：{(c.appearance as string) || ""}
                  {c.wardrobe ? `；${c.wardrobe as string}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {shots.length ? (
          <>
            <div className="flex items-center gap-1.5">
              <ShotsSourceBadge useShotList={useShotListSource} />
              <span className="text-[11px] text-muted-foreground">
                {shots.length} 镜
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
              {shots.slice(0, 12).map((s, i) => {
                const url =
                  typeof s.keyframe_url === "string"
                    ? (s.keyframe_url as string)
                    : null;
                const idx = (s.index as number) ?? i + 1;
                const err =
                  typeof s.keyframe_error === "string"
                    ? (s.keyframe_error as string)
                    : null;
                const characterLocked = s.character_locked === true;
                // v5：本镜真正被锁定的角色名（focus_character 命中的卡）
                const lockedCharacter =
                  typeof s.locked_character === "string"
                    ? (s.locked_character as string)
                    : null;
                const focusCharacter =
                  typeof s.focus_character === "string"
                    ? (s.focus_character as string)
                    : null;
                const isNonProtagonistShot =
                  characterLocked &&
                  lockedCharacter &&
                  protagonistName &&
                  lockedCharacter !== protagonistName;
                const ipAdapterUsed = s.ip_adapter_used === true;
                const ipDegradeReason =
                  typeof s.ip_adapter_degrade_reason === "string"
                    ? (s.ip_adapter_degrade_reason as string)
                    : null;
                return (
                  <div
                    key={i}
                    className="relative flex flex-col gap-1 rounded border border-border bg-muted/20 p-1"
                  >
                    {url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={url}
                        alt={`shot ${idx} keyframe`}
                        className="aspect-square w-full rounded object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex aspect-square w-full items-center justify-center rounded bg-rose-500/10 text-[10px] text-rose-400">
                        {err ? "✕" : "—"}
                      </div>
                    )}
                    {characterLocked ? (
                      <span className="absolute right-1 top-1 flex items-center gap-0.5">
                        <span
                          className={`rounded px-1 text-[9px] font-mono backdrop-blur ${
                            isNonProtagonistShot
                              ? "bg-violet-500/30 text-violet-100"
                              : "bg-emerald-500/20 text-emerald-200"
                          }`}
                          title={`v3 角色一致性 prompt 已注入（locked_character=${
                            lockedCharacter || protagonistName || "?"
                          }）`}
                        >
                          🔒
                        </span>
                        {ipAdapterUsed ? (
                          <span
                            className="rounded bg-violet-500/30 px-1 text-[9px] font-mono text-violet-100 backdrop-blur"
                            title={`v4 IP-Adapter 真接入：本镜把 ${
                              lockedCharacter || protagonistName || "anchor"
                            } 的 anchor 喂给 image provider（ip_adapter_used=true）`}
                          >
                            IP
                          </span>
                        ) : ipDegradeReason ? (
                          <span
                            className="rounded bg-amber-500/30 px-1 text-[9px] font-mono text-amber-100 backdrop-blur"
                            title={`v4 IP-Adapter 降级：${ipDegradeReason}`}
                          >
                            IP↓
                          </span>
                        ) : null}
                      </span>
                    ) : null}
                    <div className="text-center text-[10px] text-muted-foreground">
                      shot {idx}
                      {lockedCharacter && isNonProtagonistShot ? (
                        <span
                          className="ml-1 rounded bg-violet-500/15 px-1 text-[9px] text-violet-500"
                          title={`v5 多角色：本镜锁定 ${lockedCharacter}（focus_character=${
                            focusCharacter || lockedCharacter
                          }）`}
                        >
                          {lockedCharacter}
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            <details className="rounded bg-muted/30 p-2">
              <summary className="cursor-pointer text-muted-foreground">
                增强 prompt（{shots.length} 镜）
              </summary>
              <ul className="mt-2 flex flex-col gap-2 text-foreground">
                {shots.slice(0, 12).map((s, i) => (
                  <li key={i}>
                    <div className="text-muted-foreground">
                      shot {(s.index as number) ?? i + 1} · aspect{" "}
                      {(s.aspect_ratio as string) || "—"}
                      {s.keyframe_url ? " · ref-image ✓" : ""}
                    </div>
                    <div>{(s.enhanced_prompt as string) || ""}</div>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : null}
      </div>
    );
  }

  if (step.agent_type === "video") {
    return (
      <VideoArtifact
        step={step}
        shotList={shotList}
        outputsShots={
          Array.isArray(out.shots)
            ? (out.shots as Array<Record<string, unknown>>)
            : []
        }
      />
    );
  }

  if (step.agent_type === "voice") {
    return (
      <VoiceArtifact
        out={out}
        narrationUrl={narrationUrl}
        subtitles={subtitles}
      />
    );
  }

  // edit：视频 + 可选的旁白 + 字幕（v4：可能有多比例）
  if (previewUrl || narrationUrl) {
    return (
      <EditArtifact
        runId={runId}
        runState={runState}
        stepState={step.state}
        out={out}
        previewUrl={previewUrl}
        narrationUrl={narrationUrl}
        subtitles={subtitles}
      />
    );
  }

  // review：高亮 issues
  if (step.agent_type === "review" && Array.isArray(out.issues)) {
    const issues = out.issues as Array<Record<string, unknown>>;
    if (!issues.length)
      return (
        <div className="text-xs text-emerald-500">无质检 issue ✓</div>
      );
    return (
      <ul className="flex flex-col gap-1 text-xs">
        {issues.map((iss, i) => (
          <li
            key={i}
            className={
              "rounded border px-2 py-1 " +
              (iss.severity === "error"
                ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
                : iss.severity === "warning"
                ? "border-amber-500/40 bg-amber-500/10 text-amber-400"
                : "border-border bg-muted/30 text-muted-foreground")
            }
          >
            <span className="font-mono">[{(iss.area as string) || "?"}]</span>{" "}
            {(iss.message as string) || ""}
          </li>
        ))}
      </ul>
    );
  }

  return null;
}

/**
 * VoiceArtifact —— Voice step 卡片渲染。
 *
 * Track-26 / L-02：在已有的「字幕条 + word 时间轴小卡片」之上，挂 `useAudioCurrentWord`
 * 让前端跟随 `<audio>` 的 `currentTime` 实时高亮当前字幕条 + 当前 word（卡拉 OK 视觉）。
 *
 * 仅 v4 word-level 字幕（`subtitle_granularity === "word"` 且字幕条带 `words[]`）
 * 才点亮 word 高亮；v3 行级 / v2 镜级 字幕仍按原样展示，整条字幕命中时也会有 sky 背景。
 */
function VoiceArtifact({
  out,
  narrationUrl,
  subtitles,
}: {
  out: Record<string, unknown>;
  narrationUrl: string | null;
  subtitles: Array<Record<string, unknown>> | null;
}) {
  const charCount =
    typeof out.char_count === "number" ? (out.char_count as number) : null;
  const totalDur =
    typeof out.total_duration_s === "number"
      ? (out.total_duration_s as number)
      : null;
  const audioDur =
    typeof out.audio_duration_s === "number"
      ? (out.audio_duration_s as number)
      : null;
  const aligned = out.aligned === true;
  const alignmentSource =
    typeof out.alignment_source === "string"
      ? (out.alignment_source as string)
      : null;
  const asrProvider =
    typeof out.asr_provider === "string" ? (out.asr_provider as string) : null;
  const asrModel =
    typeof out.asr_model === "string" ? (out.asr_model as string) : null;
  const asrMs =
    typeof out.asr_duration_ms === "number"
      ? (out.asr_duration_ms as number)
      : null;
  const asrSegments =
    typeof out.asr_segments_count === "number"
      ? (out.asr_segments_count as number)
      : null;
  const alignWarning =
    typeof out.align_warning === "string" ? (out.align_warning as string) : null;
  // v3 字段
  const subtitleGranularity =
    typeof out.subtitle_granularity === "string"
      ? (out.subtitle_granularity as string)
      : null;
  const linesPerShot = Array.isArray(out.subtitle_lines_per_shot)
    ? (out.subtitle_lines_per_shot as number[])
    : null;
  const subtitleMaxChars =
    typeof out.subtitle_max_chars === "number"
      ? (out.subtitle_max_chars as number)
      : null;
  // v4 字段
  const alignmentQuality =
    typeof out.subtitle_alignment_quality === "string"
      ? (out.subtitle_alignment_quality as string)
      : null;
  const asrWordsCount =
    typeof out.asr_words_count === "number"
      ? (out.asr_words_count as number)
      : null;

  // ──────────── Track-26 卡拉 OK 实时高亮 ────────────
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const isWordLevel = subtitleGranularity === "word";

  // 把 outputs_json 的 subtitles 适配成 hook 接受的 SubtitleWithWords 形状（带数值 start/end + words[]）
  const subtitlesForHook: SubtitleWithWords[] = useMemo(() => {
    if (!isWordLevel || !subtitles?.length) return [];
    const acc: SubtitleWithWords[] = [];
    for (const s of subtitles) {
      const start = typeof s.start === "number" ? (s.start as number) : null;
      const end = typeof s.end === "number" ? (s.end as number) : null;
      if (start == null || end == null) continue;
      const wordsRaw = Array.isArray(s.words)
        ? (s.words as Array<{ start: number; end: number; word: string }>)
        : null;
      const words: WordTimestamp[] | null = wordsRaw
        ? wordsRaw
            .filter(
              (w) =>
                typeof w.start === "number" &&
                typeof w.end === "number" &&
                typeof w.word === "string",
            )
            .map((w) => ({ start: w.start, end: w.end, word: w.word }))
        : null;
      acc.push({ start, end, words });
    }
    return acc;
  }, [subtitles, isWordLevel]);

  const { currentSubtitleIndex, currentWordIndex } = useAudioCurrentWord({
    audioRef,
    subtitles: subtitlesForHook,
    enabled: isWordLevel && isPlaying,
  });

  return (
    <div className="flex flex-col gap-2 text-xs">
      {narrationUrl ? (
        <audio
          ref={audioRef}
          src={narrationUrl}
          controls
          className="w-full max-w-md"
          preload="none"
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
        />
      ) : (
        <div className="rounded bg-amber-500/10 px-2 py-1 text-amber-500">
          未生成旁白音频（{(out.warning as string) || "TTS 未启用或失败"}）
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {aligned ? (
          <span
            className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-500"
            title={
              alignmentSource === "asr"
                ? "字幕已按 ASR 真实音频时长重切（v2+）"
                : alignmentSource === "ffprobe"
                ? "字幕已按 ffprobe 真实音频时长重切（ASR 缺 duration 时兜底）"
                : "字幕已对齐真实音频"
            }
          >
            字幕已对齐 ✓ {alignmentSource ? `(${alignmentSource})` : ""}
          </span>
        ) : narrationUrl ? (
          <span
            className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-500"
            title={alignWarning ?? "ASR / ffprobe 都未拿到真实时长，回退 v1 按 shots.duration_s 均分"}
          >
            字幕未对齐（v1 均分）
          </span>
        ) : null}
        {subtitleGranularity === "word" ? (
          <span
            className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-400"
            title={
              "字幕粒度：word 级 (v4)。每条字幕的 start/end 用 ASR word timestamp 强对齐；" +
              "前端可做卡拉 OK 高亮（hover 字幕条看 word 时间轴）" +
              (asrWordsCount ? `；asr 返 ${asrWordsCount} words` : "")
            }
          >
            word v4{asrWordsCount ? ` · ${asrWordsCount} words` : ""}
            {linesPerShot ? ` · ${linesPerShot.join("/")}条` : ""}
          </span>
        ) : subtitleGranularity === "line" ? (
          <span
            className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-500"
            title={
              "字幕粒度：行级 (v3)。按句号 / 逗号把每镜 narration 切成多条，更符合阅读节奏" +
              (subtitleMaxChars ? `；上限 ${subtitleMaxChars} 字/条` : "")
            }
          >
            行级 v3{linesPerShot ? ` · ${linesPerShot.join("/")}条` : ""}
          </span>
        ) : subtitleGranularity === "shot" ? (
          <span
            className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="字幕粒度：镜头级 (v2)。每镜 narration 太短，没触发行级细切"
          >
            镜级 v2
          </span>
        ) : subtitleGranularity === "merged" ? (
          <span
            className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="字幕粒度：v1 兜底。ASR/ffprobe 都失败时按 shots.duration_s 均分"
          >
            v1 兜底
          </span>
        ) : null}
        {alignmentQuality && alignmentQuality !== subtitleGranularity ? (
          <span
            className="rounded bg-muted/40 px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="对齐精度档位：word > segment > char-ratio > shots-duration"
          >
            align: {alignmentQuality}
          </span>
        ) : null}
        {/* Track-26：v4 word-level 字幕场景才显示卡拉 OK 徽标 */}
        {isWordLevel ? (
          <span
            className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-600 dark:text-violet-400"
            title="点 play 后，当前 word 会按 ASR word timestamp 实时高亮（throttle ≤ 33ms）"
          >
            卡拉 OK 实时高亮 ✓
          </span>
        ) : null}
      </div>
      <div className="text-muted-foreground">
        voice <code className="font-mono">{(out.voice as string) || "—"}</code>{" "}
        · model{" "}
        <code className="font-mono">
          {(out.voice_model as string) || "—"}
        </code>
        {charCount != null ? ` · ${charCount} 字` : ""}
        {totalDur != null ? ` · 字幕轨 ${totalDur.toFixed(1)}s` : ""}
        {audioDur != null ? ` · 旁白真长 ${audioDur.toFixed(1)}s` : ""}
        {totalDur != null && audioDur != null
          ? ` · 偏差 ${Math.abs(totalDur - audioDur).toFixed(2)}s`
          : ""}
      </div>
      {asrProvider || asrModel ? (
        <div className="text-[11px] text-muted-foreground">
          ASR <code className="font-mono">{asrProvider ?? "—"}</code>
          {asrModel ? (
            <>
              {" / "}
              <code className="font-mono">{asrModel}</code>
            </>
          ) : null}
          {asrMs != null ? ` · ${asrMs}ms` : ""}
          {asrSegments != null ? ` · ${asrSegments} segments` : ""}
        </div>
      ) : null}
      {alignWarning ? (
        <div className="rounded bg-amber-500/10 px-2 py-1 text-[11px] text-amber-500">
          对齐告警：{alignWarning}
        </div>
      ) : null}
      {subtitles?.length ? (
        <details className="rounded bg-muted/30 p-2" open={isWordLevel}>
          <summary className="cursor-pointer text-muted-foreground">
            字幕（{subtitles.length} 条
            {linesPerShot && linesPerShot.length
              ? ` · ${linesPerShot.length} 镜`
              : ""}
            ）
          </summary>
          <ul className="mt-2 flex flex-col gap-1 text-foreground">
            {subtitles.slice(0, 18).map((s, i) => {
              const shotIdx =
                typeof s.shot_index === "number" ? (s.shot_index as number) : null;
              const wordsRaw = Array.isArray(s.words)
                ? (s.words as Array<{ start: number; end: number; word: string }>)
                : [];
              const isCurrentSub = isWordLevel && i === currentSubtitleIndex;
              return (
                <li
                  key={i}
                  data-subtitle-index={i}
                  className={
                    "flex flex-col gap-0.5 rounded px-1 transition-colors duration-150 " +
                    (isCurrentSub
                      ? "bg-sky-500/15 ring-1 ring-sky-400/40 dark:bg-sky-400/10"
                      : "")
                  }
                >
                  <div className="flex items-baseline gap-1.5">
                    {shotIdx != null ? (
                      <span
                        className="shrink-0 rounded bg-muted/40 px-1 text-[10px] text-muted-foreground"
                        title={`shot ${shotIdx}`}
                      >
                        S{shotIdx}
                      </span>
                    ) : null}
                    <span className="font-mono text-muted-foreground">
                      {formatTimeRange(s.start, s.end)}
                    </span>
                    <span>{(s.text as string) || ""}</span>
                    {wordsRaw.length ? (
                      <span
                        className="ml-auto rounded bg-violet-500/15 px-1 text-[10px] text-violet-600 dark:text-violet-400"
                        title={`v4 word-level：${wordsRaw.length} 个 word，hover 时间轴看每词起止`}
                      >
                        {wordsRaw.length} words
                      </span>
                    ) : null}
                  </div>
                  {wordsRaw.length ? (
                    <div
                      className="ml-2 flex flex-wrap gap-0.5 text-[10px] text-violet-600/80 dark:text-violet-400/80"
                      title="word-by-word 时间戳；前端可联动 audio 高亮"
                    >
                      {wordsRaw.slice(0, 16).map((w, wi) => {
                        const isCurrentWord =
                          isCurrentSub && wi === currentWordIndex;
                        return (
                          <span
                            key={wi}
                            data-word-index={wi}
                            className={
                              "rounded border px-1 font-mono transition-colors duration-150 " +
                              (isCurrentWord
                                ? "border-violet-500 bg-violet-500 text-white shadow-sm"
                                : "border-violet-500/20 bg-violet-500/5")
                            }
                            title={`${w.start.toFixed(2)}-${w.end.toFixed(2)}s`}
                          >
                            {w.word}
                          </span>
                        );
                      })}
                      {wordsRaw.length > 16 ? (
                        <span className="text-muted-foreground">
                          …+{wordsRaw.length - 16}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
            {subtitles.length > 18 ? (
              <li className="text-[11px] text-muted-foreground">
                …还有 {subtitles.length - 18} 条
              </li>
            ) : null}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function KeyValRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2">
      <span className="w-16 shrink-0 text-muted-foreground">{label}</span>
      <span className="break-words">{value}</span>
    </div>
  );
}

function joinList(value: unknown) {
  if (!Array.isArray(value)) return "";
  return value.filter((v): v is string => typeof v === "string").join(", ");
}

function formatTimeRange(start: unknown, end: unknown) {
  const s = typeof start === "number" ? start : 0;
  const e = typeof end === "number" ? end : 0;
  return `${s.toFixed(1)}–${e.toFixed(1)}s`;
}

const STEP_STATE_META: Record<
  PipelineStep["state"],
  { icon: typeof CircleDashed; iconCls: string }
> = {
  pending: { icon: CircleDashed, iconCls: "text-muted-foreground" },
  ready: { icon: CircleDashed, iconCls: "text-muted-foreground" },
  running: { icon: Loader2, iconCls: "animate-spin text-blue-500" },
  awaiting_review: { icon: ShieldAlert, iconCls: "text-amber-500" },
  succeeded: { icon: CheckCircle2, iconCls: "text-emerald-500" },
  failed: { icon: XCircle, iconCls: "text-rose-500" },
  skipped: { icon: CircleDashed, iconCls: "text-muted-foreground" },
  cancelled: { icon: XCircle, iconCls: "text-muted-foreground" },
};

function formatOutputs(outputs: Record<string, unknown> | null | undefined) {
  if (!outputs) return "";
  try {
    return JSON.stringify(outputs, null, 2);
  } catch {
    return "";
  }
}

// ── ProductionPanel ─────────────────────────────────────────────────────────
//   读 /api/production/files/{id}/versions + /publish-plans，提供最小 CRUD：
//   - 「另存为版本」(label + notes + primary_render 下拉)
//   - 「新建发布计划」(platform + render 下拉 + scheduled_at)
//   - 列表里：版本可置顶（is_published 互斥）+ 删除；发布计划可改 status + 删除

function ProductionPanel({
  fileId,
  currentRunId,
  currentRunState,
}: {
  fileId: string;
  currentRunId: string | null;
  currentRunState: PipelineRun["state"] | null;
}) {
  const [versions, setVersions] = useState<VersionOut[]>([]);
  const [plans, setPlans] = useState<PublishPlanOut[]>([]);
  const [loading, setLoading] = useState(false);

  // 当前 run 的 renders（用作版本 / 发布计划的 render 下拉）
  const { renders } = useRunRenders(currentRunId, {
    enabled: currentRunState === "succeeded" || currentRunState === "awaiting_review",
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [v, p] = await Promise.all([
        listFileVersions(fileId),
        listFilePublishPlans(fileId),
      ]);
      setVersions(v);
      setPlans(p);
    } catch {
      // 静默
    } finally {
      setLoading(false);
    }
  }, [fileId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const canCreateVersion =
    !!currentRunId && currentRunState === "succeeded";

  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <header className="mb-4 flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">版本 & 发布</h2>
          <p className="text-xs text-muted-foreground">
            读 <code className="font-mono">/api/production/files/{fileId.slice(0, 8)}…</code>{" "}
            的 versions / publish_plans 表；当前 run 终态后可另存为版本。
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={refresh}
          disabled={loading}
        >
          <RefreshCcw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </header>
      <div className="grid gap-6 md:grid-cols-2">
        <VersionsBlock
          fileId={fileId}
          currentRunId={currentRunId}
          canCreate={canCreateVersion}
          renders={renders}
          versions={versions}
          onChanged={refresh}
        />
        <PublishPlansBlock
          fileId={fileId}
          currentRunId={currentRunId}
          renders={renders}
          plans={plans}
          onChanged={refresh}
        />
      </div>
    </section>
  );
}

function VersionsBlock({
  fileId,
  currentRunId,
  canCreate,
  renders,
  versions,
  onChanged,
}: {
  fileId: string;
  currentRunId: string | null;
  canCreate: boolean;
  renders: RenderOut[];
  versions: VersionOut[];
  onChanged: () => void;
}) {
  // Track-27 · viewer 不能另存版本 / 删除版本（按钮 disable + tooltip）
  const role = useCurrentRole();
  const writeAllowed = canWrite(role, role.loading);
  const writeDisabledReason = disabledReason(role, role.loading);
  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [primaryRenderId, setPrimaryRenderId] = useState<string>("");
  const [isPublished, setIsPublished] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = useCallback(async () => {
    if (!currentRunId || !label.trim()) return;
    setSubmitting(true);
    try {
      await createVersion({
        file_id: fileId,
        run_id: currentRunId,
        label: label.trim(),
        notes: notes.trim() || undefined,
        primary_render_id: primaryRenderId || undefined,
        is_published: isPublished,
      });
      feedback.success(`已保存版本「${label.trim()}」`);
      setLabel("");
      setNotes("");
      setPrimaryRenderId("");
      setIsPublished(false);
      setShowForm(false);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`保存版本失败：${message}`);
    } finally {
      setSubmitting(false);
    }
  }, [currentRunId, fileId, isPublished, label, notes, onChanged, primaryRenderId]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground">
          版本（{versions.length}）
        </h3>
        <Button
          size="sm"
          variant={showForm ? "ghost" : "outline"}
          onClick={() => setShowForm((v) => !v)}
          disabled={!canCreate || !writeAllowed}
          title={
            !writeAllowed
              ? (writeDisabledReason ?? undefined)
              : canCreate
                ? "把当前 run 标记为一个版本"
                : "需要当前 run 处于 succeeded 状态才能另存为版本"
          }
        >
          <Plus className="size-3.5" />
          {showForm ? "收起" : "另存为版本"}
        </Button>
      </div>
      {showForm ? (
        <div className="flex flex-col gap-2 rounded border border-dashed border-border bg-muted/30 p-3 text-xs">
          <input
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            placeholder="标签，例如 v1 / 20260504-final"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={80}
          />
          <input
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            placeholder="备注（可选）"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <select
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            value={primaryRenderId}
            onChange={(e) => setPrimaryRenderId(e.target.value)}
          >
            <option value="">-- 主比例 render（可选）--</option>
            {renders.map((r) => (
              <option key={r.id} value={r.id}>
                {r.aspect_ratio}
                {r.is_primary ? " (primary)" : ""}
                {r.warning ? " ⚠" : ""}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-muted-foreground">
            <input
              type="checkbox"
              checked={isPublished}
              onChange={(e) => setIsPublished(e.target.checked)}
            />
            标记为本 file 的当前发布版（互斥替换之前 published 版本）
          </label>
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={onSubmit}
              disabled={submitting || !label.trim()}
            >
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : null}
              保存版本
            </Button>
          </div>
        </div>
      ) : null}
      {!versions.length ? (
        <p className="rounded bg-muted/30 p-2 text-xs text-muted-foreground">
          还没有版本。run 跑完后点「另存为版本」记录一个标签。
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-xs">
          {versions.map((v) => (
            <VersionRow key={v.id} version={v} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </div>
  );
}

function VersionRow({
  version,
  onChanged,
}: {
  version: VersionOut;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  // Track-27 · viewer 不能 publish / 删除版本
  const role = useCurrentRole();
  const writeAllowed = canWrite(role, role.loading);
  const writeDisabledReason = disabledReason(role, role.loading);
  const handlePublish = useCallback(async () => {
    setBusy(true);
    try {
      await publishVersion(version.id);
      feedback.success(`「${version.label}」设为当前发布版`);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`置顶失败：${message}`);
    } finally {
      setBusy(false);
    }
  }, [onChanged, version.id, version.label]);
  const handleDelete = useCallback(async () => {
    if (!window.confirm(`删除版本「${version.label}」？`)) return;
    setBusy(true);
    try {
      await deleteVersion(version.id);
      feedback.info(`已删除「${version.label}」`);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`删除失败：${message}`);
    } finally {
      setBusy(false);
    }
  }, [onChanged, version.id, version.label]);
  return (
    <li className="flex items-center gap-2 rounded border border-border bg-background/40 px-2 py-1.5">
      <span
        className={
          "shrink-0 rounded px-1.5 py-0.5 text-[10px] " +
          (version.is_published
            ? "bg-emerald-500/15 text-emerald-500"
            : "bg-muted/40 text-muted-foreground")
        }
      >
        {version.is_published ? "★ 已发布" : "草稿"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{version.label}</div>
        <div className="truncate text-[10px] text-muted-foreground">
          run {version.run_id.slice(0, 8)}…
          {version.notes ? ` · ${version.notes}` : ""}
        </div>
      </div>
      {!version.is_published ? (
        <Button
          size="sm"
          variant="ghost"
          onClick={handlePublish}
          disabled={busy || !writeAllowed}
          title={
            writeDisabledReason ?? "把这个版本设为当前发布版"
          }
        >
          置顶
        </Button>
      ) : null}
      <Button
        size="sm"
        variant="ghost"
        onClick={handleDelete}
        disabled={busy || !writeAllowed}
        title={writeDisabledReason ?? "删除版本"}
      >
        <Trash2 className="size-3.5" />
      </Button>
    </li>
  );
}

function PublishPlansBlock({
  fileId,
  currentRunId,
  renders,
  plans,
  onChanged,
}: {
  fileId: string;
  currentRunId: string | null;
  renders: RenderOut[];
  plans: PublishPlanOut[];
  onChanged: () => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [platform, setPlatform] = useState("bilibili");
  const [renderId, setRenderId] = useState<string>("");
  const [title, setTitle] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Track-27 · viewer 不能新建发布计划
  const role = useCurrentRole();
  const writeAllowed = canWrite(role, role.loading);
  const writeDisabledReason = disabledReason(role, role.loading);

  const onSubmit = useCallback(async () => {
    setSubmitting(true);
    try {
      await createPublishPlan({
        file_id: fileId,
        run_id: currentRunId ?? undefined,
        render_id: renderId || undefined,
        platform: platform.trim(),
        title: title.trim() || undefined,
        scheduled_at: scheduledAt
          ? new Date(scheduledAt).toISOString()
          : undefined,
      });
      feedback.success(`已新建发布计划（${platform}）`);
      setTitle("");
      setRenderId("");
      setScheduledAt("");
      setShowForm(false);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`新建失败：${message}`);
    } finally {
      setSubmitting(false);
    }
  }, [currentRunId, fileId, onChanged, platform, renderId, scheduledAt, title]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground">
          发布计划（{plans.length}）
        </h3>
        <Button
          size="sm"
          variant={showForm ? "ghost" : "outline"}
          onClick={() => setShowForm((v) => !v)}
          disabled={!writeAllowed}
          title={writeDisabledReason ?? undefined}
        >
          <Plus className="size-3.5" />
          {showForm ? "收起" : "新建发布计划"}
        </Button>
      </div>
      {showForm ? (
        <div className="flex flex-col gap-2 rounded border border-dashed border-border bg-muted/30 p-3 text-xs">
          <div className="flex gap-2">
            <input
              className="h-8 flex-1 rounded border border-border bg-background px-2 text-xs"
              placeholder="平台（bilibili / youtube / xhs / douyin）"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              maxLength={40}
            />
            <input
              type="datetime-local"
              className="h-8 rounded border border-border bg-background px-2 text-xs"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              title="计划发布时间（可选）"
            />
          </div>
          <input
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            placeholder="标题（可选；后续支持平台自动渲染）"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
          />
          <select
            className="h-8 rounded border border-border bg-background px-2 text-xs"
            value={renderId}
            onChange={(e) => setRenderId(e.target.value)}
          >
            <option value="">-- 关联 render（可选；不选则后期再绑）--</option>
            {renders.map((r) => (
              <option key={r.id} value={r.id}>
                {r.aspect_ratio}
                {r.is_primary ? " (primary)" : ""}
              </option>
            ))}
          </select>
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={onSubmit}
              disabled={submitting || !platform.trim()}
            >
              {submitting ? <Loader2 className="size-3.5 animate-spin" /> : null}
              新建草稿
            </Button>
          </div>
        </div>
      ) : null}
      {!plans.length ? (
        <p className="rounded bg-muted/30 p-2 text-xs text-muted-foreground">
          还没有发布计划。先把成片定一个版本，再为它创建一个或多个发布计划。
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-xs">
          {plans.map((p) => (
            <PlanRow key={p.id} plan={p} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PlanRow({
  plan,
  onChanged,
}: {
  plan: PublishPlanOut;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  // Track-27 · viewer 不能执行 / 删除发布计划 / 改 status / 切真发开关
  const role = useCurrentRole();
  const writeAllowed = canWrite(role, role.loading);
  const writeDisabledReason = disabledReason(role, role.loading);
  // 乐观更新：toggle 真发后立刻更 UI，让 Upload 按钮颜色立刻反映闸门状态，
  // 等服务器 PATCH 回来再用 onChanged 拉权威值刷一次。
  const [confirmReal, setConfirmReal] = useState(plan.confirm_real_publish);
  useEffect(() => {
    setConfirmReal(plan.confirm_real_publish);
  }, [plan.confirm_real_publish]);

  // Track-03：execute 异步化后，PlanRow 用 SSE 等 worker 跑完
  // - executing=true 时禁掉 Upload + Send + 状态切换 + 删除按钮，避免重复派发
  // - 终态 phase=completed/system_error 由 hook onTerminal 弹 toast + onChanged 拉新数据
  const planStream = usePublishPlanStream({
    onTerminal: (event) => {
      onChanged();
      if (event?.phase === "completed") {
        if (event.ok) {
          feedback.success(
            `${plan.platform} ✓ external_id ${event.external_id ?? "—"}`
          );
        } else {
          feedback.error(event.error ?? `${plan.platform} 执行失败`);
        }
      } else if (event?.phase === "system_error") {
        feedback.error(
          `${plan.platform} 系统级失败（已入 DLQ，可在死信队列面板重投）：${
            event.error ?? "未知错误"
          }`
        );
      }
    },
  });
  const executing = planStream.pending;
  const streamMode = planStream.mode;
  const latestPhase = planStream.latestEvent?.phase ?? null;
  // Track-13：YouTube chunked PUT 进度（非终态；executing=false 时清空 → 进度条隐藏）
  const uploadProgress = executing ? planStream.latestProgress : null;

  const handleStatus = useCallback(
    async (status: PublishPlanOut["status"]) => {
      setBusy(true);
      try {
        await patchPublishPlan(plan.id, { status });
        feedback.success(`已切到 ${status}`);
        onChanged();
      } catch (err) {
        const message =
          err instanceof ApiError ? `API ${err.status}` : "网络错误";
        feedback.error(`改状态失败：${message}`);
      } finally {
        setBusy(false);
      }
    },
    [onChanged, plan.id]
  );
  const handleConfirmRealToggle = useCallback(
    async (next: boolean) => {
      // 乐观更新：先反映到本地 state，让按钮颜色 / 提示立刻变
      setConfirmReal(next);
      setBusy(true);
      try {
        await patchPublishPlan(plan.id, { confirm_real_publish: next });
        if (next) {
          feedback.warning(
            `「真发」已开启（${plan.platform}）：下次 Upload 会真打外部 API`
          );
        } else {
          feedback.info(`「真发」已关闭（${plan.platform}）：回到 mock 路径`);
        }
        onChanged();
      } catch (err) {
        // 失败回滚
        setConfirmReal(!next);
        const message =
          err instanceof ApiError ? `API ${err.status}` : "网络错误";
        feedback.error(`改真发开关失败：${message}`);
      } finally {
        setBusy(false);
      }
    },
    [onChanged, plan.id, plan.platform]
  );
  const handleExecute = useCallback(async () => {
    const realPath =
      confirmReal && plan.platform.toLowerCase() === "youtube";
    const promptText = realPath
      ? `⚠️ 真发模式开启，将把 render 真打到 ${plan.platform} 平台（不可撤销）。\n\n确认继续吗？`
      : `执行发布计划（${plan.platform}）？\n` +
        `当前为 mock 路径（dry-run / bilibili 不会真发；youtube 安全闸门关闭，回 mock external_id）。`;
    if (!window.confirm(promptText)) return;
    // Track-03：先开 SSE 订阅再发 POST，避免 worker 跑很快时事件比订阅早到丢失
    planStream.start(plan.id, plan.file_id);
    try {
      const accepted = await executePublishPlan(plan.id);
      feedback.info(
        `${plan.platform} 已派发（${accepted.dispatcher}）；正在等执行结果…`
      );
    } catch (err) {
      planStream.stop();
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`派发失败：${message}`);
    }
  }, [confirmReal, plan.file_id, plan.id, plan.platform, planStream]);
  const handleDelete = useCallback(async () => {
    if (!window.confirm(`删除发布计划（${plan.platform}）？`)) return;
    setBusy(true);
    try {
      await deletePublishPlan(plan.id);
      feedback.info(`已删除（${plan.platform}）`);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`删除失败：${message}`);
    } finally {
      setBusy(false);
    }
  }, [onChanged, plan.id, plan.platform]);

  // Upload 按钮颜色：真发开启 = 红色（危险）；关闭 = 绿色（安全 mock）。
  // 仅 youtube 受真发开关影响；其他平台按钮保持原 ghost 灰色。
  const isYoutube = plan.platform.toLowerCase() === "youtube";
  const uploadBtnCls = isYoutube
    ? confirmReal
      ? "text-rose-500 hover:text-rose-600 hover:bg-rose-500/10"
      : "text-emerald-500 hover:text-emerald-600 hover:bg-emerald-500/10"
    : "";
  const uploadBtnTitle = isYoutube
    ? confirmReal
      ? "⚠ 真发模式：将真打 YouTube Upload API（不可撤销）"
      : "安全 mock：仅返回假 external_id（开启「真发」后才真打）"
    : "调用发布执行器：把 render 真推到目标平台（dry-run / bilibili / youtube）";

  // Track-03：execute 进 worker 后，整行所有按钮都禁掉避免重复派发
  // Track-27：viewer 不能写，整行按钮额外 disable
  const rowBusy = busy || executing || !writeAllowed;
  // executing 时的状态徽标：phase=running → 「执行中（celery/polling）」
  // 没收到 phase 但 mode=stream → 「派发中…」
  const execBadge = executing ? (
    <span
      className={
        "shrink-0 rounded border px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide " +
        (latestPhase === "running"
          ? "border-sky-500/40 bg-sky-500/15 text-sky-500"
          : "border-amber-500/40 bg-amber-500/15 text-amber-500")
      }
      title={
        streamMode === "polling"
          ? "SSE 不可用，已 fallback 2.5s polling"
          : "已派发到 worker，等 publish_plan_state 推 phase=completed"
      }
    >
      {latestPhase === "running" ? "执行中" : "派发中"}
      {streamMode === "polling" ? " · poll" : ""}
    </span>
  ) : null;

  return (
    <li className="flex flex-col gap-1 rounded border border-border bg-background/40 px-2 py-1.5">
      <div className="flex items-center gap-2">
        <span
          className={
            "shrink-0 rounded px-1.5 py-0.5 text-[10px] " +
            planStatusCls(plan.status)
          }
        >
          {plan.status}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 truncate font-medium">
            <span className="truncate">
              {plan.platform}
              {plan.title ? ` · ${plan.title}` : ""}
            </span>
            {isYoutube && confirmReal ? (
              <span
                className="shrink-0 rounded bg-rose-500/15 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-rose-500"
                title="该 plan 真发闸门已开启"
              >
                LIVE
              </span>
            ) : null}
            {execBadge}
          </div>
          <div className="truncate text-[10px] text-muted-foreground">
            {plan.render_id ? `render ${plan.render_id.slice(0, 8)}…` : "无 render"}
            {plan.scheduled_at
              ? ` · 计划 ${new Date(plan.scheduled_at).toLocaleString()}`
              : ""}
            {plan.published_at
              ? ` · 实发 ${new Date(plan.published_at).toLocaleString()}`
              : ""}
            {plan.external_id ? ` · ext ${plan.external_id.slice(0, 12)}` : ""}
          </div>
        </div>
        <select
          className="h-7 rounded border border-border bg-background px-1 text-[11px]"
          value={plan.status}
          onChange={(e) =>
            handleStatus(e.target.value as PublishPlanOut["status"])
          }
          disabled={rowBusy}
        >
          {PUBLISH_PLAN_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <label
          className={
            "flex items-center gap-1 rounded border px-1.5 py-1 text-[10px] cursor-pointer select-none " +
            (confirmReal
              ? "border-rose-500/50 bg-rose-500/10 text-rose-500"
              : "border-border bg-background text-muted-foreground hover:text-foreground")
          }
          title={
            isYoutube
              ? "勾选后 youtube adapter 会真打 YouTube Upload API；不勾时回 mock external_id"
              : "「真发」开关只影响 youtube adapter；dry-run / bilibili 不读该字段"
          }
        >
          <input
            type="checkbox"
            className="size-3 accent-rose-500"
            checked={confirmReal}
            onChange={(e) => handleConfirmRealToggle(e.target.checked)}
            disabled={rowBusy}
          />
          真发
        </label>
        {plan.status !== "published" ? (
          <Button
            size="sm"
            variant="ghost"
            className={uploadBtnCls}
            onClick={handleExecute}
            disabled={rowBusy}
            title={
              !writeAllowed
                ? (writeDisabledReason ?? undefined)
                : executing
                  ? "执行中（worker 跑 publish.execute_plan）；等 SSE 推 phase=completed"
                  : uploadBtnTitle
            }
          >
            {executing ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Upload className="size-3.5" />
            )}
          </Button>
        ) : null}
        {plan.status === "scheduled" || plan.status === "draft" ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handleStatus("published")}
            disabled={rowBusy}
            title={
              writeDisabledReason ??
              "仅状态记账（不调发布执行器；适合手动发完后回填）"
            }
          >
            <Send className="size-3.5" />
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={handleDelete}
          disabled={rowBusy}
          title={writeDisabledReason ?? "删除发布计划"}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
      {uploadProgress ? <UploadProgressBar progress={uploadProgress} /> : null}
      {plan.error ? (
        <div className="rounded bg-rose-500/10 px-2 py-1 text-[11px] text-rose-500">
          ⚠ {plan.error}
        </div>
      ) : null}
    </li>
  );
}

// ── Track-13：YouTube chunked PUT 进度条 ───────────────────────────────────
//   后端 youtube adapter 改成 8 MiB 分片 PUT 后，每片完成会推一条 upload_progress
//   SSE 事件（含 percent / bytes_uploaded / total / chunk_index / chunk_count）。
//   PlanRow 在 executing 期间渲一根细横条 + 文案，让 1080p / 60s+ 大视频上传不再
//   只显示一个 spinner 干转。下载阶段（phase=downloading）单独标灰，避免用户以为
//   上传卡住；上传阶段才走 sky 主色。
function UploadProgressBar({
  progress,
}: {
  progress: NonNullable<
    ReturnType<typeof usePublishPlanStream>["latestProgress"]
  >;
}) {
  const percent = Math.max(0, Math.min(100, progress.percent ?? 0));
  const isUploading = progress.phase === "uploading";
  const phaseLabel = isUploading ? "上传中" : "下载渲染";
  const chunkLabel =
    isUploading && progress.chunk_count > 0
      ? ` · 片 ${progress.chunk_index + 1}/${progress.chunk_count}`
      : "";
  const sizeLabel =
    progress.total > 0
      ? ` · ${formatBytes(progress.bytes_uploaded)} / ${formatBytes(
          progress.total
        )}`
      : "";
  const barCls = isUploading ? "bg-sky-500" : "bg-muted-foreground/50";
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>
          {phaseLabel}
          {chunkLabel}
        </span>
        <span className="tabular-nums">
          {percent.toFixed(1)}%{sizeLabel}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded bg-muted/40">
        <div
          className={`h-full transition-[width] duration-300 ease-out ${barCls}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function planStatusCls(status: PublishPlanOut["status"]) {
  switch (status) {
    case "published":
      return "bg-emerald-500/15 text-emerald-500";
    case "scheduled":
      return "bg-sky-500/15 text-sky-500";
    case "failed":
      return "bg-rose-500/15 text-rose-500";
    case "cancelled":
      return "bg-muted/40 text-muted-foreground";
    case "draft":
    default:
      return "bg-amber-500/15 text-amber-500";
  }
}

// ── shots 数据源徽标 ────────────────────────────────────────────────────────
//   emerald = 走 /production/runs/{id}/shot-list（新表，权威）
//   amber   = 仍 fallback 到 step.outputs_json（兼容期 / 数据还没落表）

function ShotsSourceBadge({ useShotList }: { useShotList: boolean }) {
  return useShotList ? (
    <span
      className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-500"
      title="数据源：shot_lists 表（/api/production 新 API，权威源）"
    >
      shot_lists 表
    </span>
  ) : (
    <span
      className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-500"
      title="数据源：step.outputs_json（兼容期；shot_lists 表暂无数据，可能是单步重跑前的旧 run 或 persist hook 未触发）"
    >
      outputs_json
    </span>
  );
}

// ── VideoArtifact ───────────────────────────────────────────────────────────
//   video step 卡片：每镜显示 <video> 缩略图 + provider/model/cost/error。
//   优先读 shot_list（含 video_url + 同行的 keyframe_url 做 poster）；缺失退到 outputs_json。
//   v2：每镜右上角额外渲染 <RefImageSourceBadge>：emerald「anchor 锚定」/ sky「keyframe」/
//   muted「无参考」。ref_image_source 字段只活在 video step.outputs_json.shots[i] 里
//   （shot_lists 表暂不存这个字段，避免新加 alembic 迁移），所以即使主体走 shot-list 路径，
//   徽标仍会按 index 从 outputsShots 里 lookup；找不到时按 keyframe_url 推断（best-effort）。

type RefImageSource = "anchor" | "keyframe" | "none";

function VideoArtifact({
  step,
  shotList,
  outputsShots,
}: {
  step: PipelineStep;
  shotList: ShotListOut | null;
  outputsShots: Array<Record<string, unknown>>;
}) {
  // 优先用 shot-list（含 art keyframe + video URL 同行）；缺失 fallback 到 outputs_json
  const useShotListSource = !!(shotList && shotList.shots && shotList.shots.length);

  // 按 index 建 outputs lookup，给徽标读 ref_image_source 用（shot_list 路径下 schema 不带）
  const outputsByIndex = new Map<number, Record<string, unknown>>();
  outputsShots.forEach((s, i) => {
    const idx =
      typeof s.index === "number" ? (s.index as number) : i + 1;
    outputsByIndex.set(idx, s);
  });

  const rows: Array<VideoShotView> = useShotListSource
    ? shotList!.shots.map((s) =>
        toViewFromShotList(s, outputsByIndex.get(s.index)),
      )
    : outputsShots.map(toViewFromOutputs);

  const okCount = rows.filter((r) => r.video_url).length;
  const errCount = rows.filter((r) => r.error).length;
  const totalCost = rows.reduce((acc, r) => acc + (r.cost_usd || 0), 0);
  const anchorCount = rows.filter((r) => r.ref_image_source === "anchor").length;
  const keyframeCount = rows.filter((r) => r.ref_image_source === "keyframe").length;
  const noRefCount = rows.filter((r) => r.ref_image_source === "none").length;
  // v5：anchor 镜的角色分布（多角色锁定时观察每角色被多少镜引用）
  const anchorByRole: Record<string, number> = {};
  for (const r of rows) {
    if (r.ref_image_source === "anchor" && r.ref_anchor_role) {
      anchorByRole[r.ref_anchor_role] = (anchorByRole[r.ref_anchor_role] ?? 0) + 1;
    }
  }
  const anchorRoles = Object.keys(anchorByRole);
  const isMultiCharacter = anchorRoles.length > 1;

  if (!rows.length) {
    return (
      <div className="text-xs text-muted-foreground">
        暂无 shot 数据{step.state === "running" ? "（生成中…）" : ""}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <ShotsSourceBadge useShotList={useShotListSource} />
        <span className="text-[11px] text-muted-foreground">
          {rows.length} 镜 · {okCount} 成功
          {errCount ? ` · ${errCount} 失败` : ""}
          {totalCost > 0 ? ` · cost $${totalCost.toFixed(4)}` : ""}
        </span>
        {anchorCount + keyframeCount + noRefCount > 0 ? (
          <span
            className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title="ref-image 来源汇总：anchor=按 locked_character 选对应角色 anchor（v5），keyframe=每镜独立关键帧，none=无 ref（GENERATE_VIDEO 降级）"
          >
            ref:{" "}
            <span className="text-emerald-500">{anchorCount} anchor</span>
            {" · "}
            <span className="text-sky-500">{keyframeCount} keyframe</span>
            {noRefCount ? ` · ${noRefCount} none` : ""}
          </span>
        ) : null}
        {isMultiCharacter ? (
          <span
            className="rounded bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-500"
            title="v5 多角色锁定：anchor 按 shot.locked_character 逐镜选不同角色 anchor"
          >
            v5 ·{" "}
            {anchorRoles
              .map((role) => `${role}×${anchorByRole[role]}`)
              .join(" / ")}
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
        {rows.slice(0, 12).map((r) => (
          <div
            key={r.index}
            className="relative flex flex-col gap-1 rounded border border-border bg-muted/20 p-1.5"
          >
            <div className="absolute right-1 top-1 z-10">
              <RefImageSourceBadge source={r.ref_image_source} />
            </div>
            {r.video_url ? (
              <video
                src={r.video_url}
                poster={r.keyframe_url ?? undefined}
                controls
                preload="none"
                className="aspect-video w-full rounded bg-black object-cover"
              />
            ) : r.keyframe_url ? (
              // 还没出 video，但 art 已经出了 keyframe → 用关键帧占位让用户能预判镜头
              <div className="relative aspect-video w-full">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={r.keyframe_url}
                  alt={`shot ${r.index} keyframe`}
                  className="absolute inset-0 size-full rounded object-cover opacity-50"
                  loading="lazy"
                />
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-amber-400">
                  {r.error ? "✕ 视频生成失败" : "等待视频生成"}
                </div>
              </div>
            ) : (
              <div className="flex aspect-video w-full items-center justify-center rounded bg-rose-500/10 text-[10px] text-rose-400">
                {r.error ? "✕" : "—"}
              </div>
            )}
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>
                shot {r.index}
                {r.ref_image_source === "anchor" && r.ref_anchor_role ? (
                  <span
                    className="ml-1 rounded bg-emerald-500/15 px-1 text-[9px] text-emerald-500"
                    title={`v5 多角色锁定：本镜 i2v 用了 ${r.ref_anchor_role} 的 anchor`}
                  >
                    {r.ref_anchor_role}
                  </span>
                ) : null}
              </span>
              {r.duration_ms ? (
                <span className="font-mono">{(r.duration_ms / 1000).toFixed(1)}s</span>
              ) : null}
            </div>
            {r.provider ? (
              <div className="truncate text-[10px] text-muted-foreground">
                <code className="font-mono">{r.provider}</code>
                {r.mode ? ` · ${r.mode}` : ""}
                {r.cost_usd ? ` · $${r.cost_usd.toFixed(4)}` : ""}
              </div>
            ) : null}
            {r.error ? (
              <div className="truncate text-[10px] text-rose-400" title={r.error}>
                {r.error}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {rows.length > 12 ? (
        <div className="text-[11px] text-muted-foreground">
          …还有 {rows.length - 12} 镜
        </div>
      ) : null}
    </div>
  );
}

// ── ref-image 来源徽标（v2 Track-05）─────────────────────────────────────────
//   anchor   → emerald「anchor 锚定」（主角镜复用全片锚点参考板，跨镜更稳定）
//   keyframe → sky「keyframe」（每镜独立关键帧；非主角镜 / character_locked=False）
//   none     → muted「无参考」（GENERATE_VIDEO 降级路径）

function RefImageSourceBadge({ source }: { source: RefImageSource }) {
  if (source === "anchor") {
    return (
      <span
        className="rounded bg-emerald-500/85 px-1 py-0.5 text-[9px] font-medium text-emerald-50 shadow-sm"
        title="ref-image 来源：character_anchor（ArtAgent v3 主角锚点参考板，跨镜复用）"
      >
        anchor 锚定
      </span>
    );
  }
  if (source === "keyframe") {
    return (
      <span
        className="rounded bg-sky-500/85 px-1 py-0.5 text-[9px] font-medium text-sky-50 shadow-sm"
        title="ref-image 来源：本镜独立 keyframe（非主角镜或 character_locked=false）"
      >
        keyframe
      </span>
    );
  }
  return (
    <span
      className="rounded bg-muted px-1 py-0.5 text-[9px] font-medium text-muted-foreground shadow-sm"
      title="无 ref-image：降级到 GENERATE_VIDEO（无角色一致性引导）"
    >
      无参考
    </span>
  );
}

interface VideoShotView {
  index: number;
  video_url: string | null;
  keyframe_url: string | null;
  provider: string | null;
  mode: string | null;
  cost_usd: number;
  duration_ms: number;
  error: string | null;
  ref_image_source: RefImageSource;
  // v5：source=='anchor' 时本镜真正用了哪个角色的 anchor（多角色锁定时关键观测点）
  ref_anchor_role: string | null;
}

function readRefImageSource(
  raw: Record<string, unknown> | undefined,
  fallback: { keyframe_url: string | null },
): RefImageSource {
  const v =
    raw && typeof raw.ref_image_source === "string"
      ? (raw.ref_image_source as string)
      : null;
  if (v === "anchor" || v === "keyframe" || v === "none") {
    return v;
  }
  // outputs_json 还没写 ref_image_source（旧 run / persist 还没触发）→ 按 keyframe 推断
  // 注：这里推断不到 anchor，只能区分 keyframe / none；准确值由后端写入
  return fallback.keyframe_url ? "keyframe" : "none";
}

function readRefAnchorRole(
  raw: Record<string, unknown> | undefined,
): string | null {
  if (!raw) return null;
  const v = raw.ref_anchor_role;
  if (typeof v === "string" && v.trim()) {
    return v.trim();
  }
  return null;
}

function toViewFromShotList(
  s: ShotOut,
  outputsRow: Record<string, unknown> | undefined,
): VideoShotView {
  return {
    index: s.index,
    video_url: s.video_url,
    keyframe_url: s.keyframe_url,
    provider: s.video_provider,
    mode: s.video_mode,
    cost_usd: s.video_cost_usd,
    duration_ms: s.video_duration_ms,
    error: s.video_error,
    ref_image_source: readRefImageSource(outputsRow, {
      keyframe_url: s.keyframe_url,
    }),
    ref_anchor_role: readRefAnchorRole(outputsRow),
  };
}

function toViewFromOutputs(s: Record<string, unknown>, i: number): VideoShotView {
  const keyframe_url =
    typeof s.keyframe_url === "string" ? (s.keyframe_url as string) : null;
  return {
    index: typeof s.index === "number" ? (s.index as number) : i + 1,
    video_url: typeof s.video_url === "string" ? (s.video_url as string) : null,
    keyframe_url,
    // outputs_json 用 provider/model/mode（而不是 video_provider）
    provider: typeof s.provider === "string" ? (s.provider as string) : null,
    mode: typeof s.mode === "string" ? (s.mode as string) : null,
    cost_usd: typeof s.cost_usd === "number" ? (s.cost_usd as number) : 0,
    duration_ms:
      typeof s.duration_ms === "number" ? (s.duration_ms as number) : 0,
    error: typeof s.error === "string" ? (s.error as string) : null,
    ref_image_source: readRefImageSource(s, { keyframe_url }),
    ref_anchor_role: readRefAnchorRole(s),
  };
}

// ── PlatformCredentialsPanel ────────────────────────────────────────────────
//   user 级（不绑 fileId）：列出已注册的发布平台 + 当前用户已绑凭证。
//   - bind 按钮：仅 requires_credential=true 平台显示；点击调 /platforms/{p}/oauth/start
//     拿 authorize_url 后 window.location.assign 过去（YouTube）
//   - revoke：删 (user_id, platform) 行（前端确认对话框）
//   - 前端进入页面后会读 query string `?platform=...&result=ok|error` 弹反馈
//     （OAuth 回调最终落到 /app/settings/integrations，但开发环境默认 fallback 到当前路径）

function PlatformCredentialsPanel() {
  const [platforms, setPlatforms] = useState<PlatformOut[] | null>(null);
  const [credentials, setCredentials] = useState<CredentialOut[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, c] = await Promise.all([
        listPlatforms(),
        listPlatformCredentials(),
      ]);
      setPlatforms(p);
      setCredentials(c);
    } catch (err) {
      const msg = err instanceof ApiError ? `API ${err.status}` : "网络错误";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const credByPlatform = new Map<string, CredentialOut>(
    (credentials ?? []).map((c) => [c.platform, c])
  );

  const handleBind = useCallback(async (platform: string) => {
    try {
      const out = await startPlatformOAuth(platform);
      window.location.assign(out.authorize_url);
    } catch (err) {
      const msg = err instanceof ApiError
        ? typeof err.body === "object" &&
          err.body &&
          "detail" in err.body &&
          typeof (err.body as { detail?: unknown }).detail === "string"
          ? ((err.body as { detail: string }).detail)
          : `API ${err.status}`
        : "网络错误";
      feedback.error(`无法启动 ${platform} OAuth：${msg}`);
    }
  }, []);

  const handleRevoke = useCallback(
    async (platform: string) => {
      if (!window.confirm(`撤销 ${platform} 凭证？将停用该平台的发布执行`))
        return;
      try {
        const res = await revokePlatformCredentials(platform);
        if (res.deleted) {
          feedback.success(`已撤销 ${platform}`);
        } else {
          feedback.info(`${platform} 没有现有凭证`);
        }
        void reload();
      } catch (err) {
        const msg = err instanceof ApiError ? `API ${err.status}` : "网络错误";
        feedback.error(`撤销失败：${msg}`);
      }
    },
    [reload]
  );

  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <header className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">平台凭证（发布执行器 v1）</h2>
        <Button variant="ghost" size="sm" onClick={() => void reload()}>
          <RefreshCcw className="size-3.5" /> 刷新
        </Button>
      </header>
      {error ? (
        <div className="mb-2 rounded bg-rose-500/10 px-2 py-1 text-xs text-rose-500">
          加载失败：{error}
        </div>
      ) : null}
      {loading && !platforms ? (
        <div className="text-xs text-muted-foreground">加载中…</div>
      ) : !platforms || platforms.length === 0 ? (
        <div className="text-xs text-muted-foreground">
          后端没有注册任何发布 adapter。
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {platforms.map((p) => {
            const cred = credByPlatform.get(p.name);
            return (
              <li
                key={p.name}
                className="flex items-center gap-2 rounded border border-border bg-background/40 px-2 py-1.5 text-xs"
              >
                <span
                  className={
                    "shrink-0 rounded px-1.5 py-0.5 text-[10px] " +
                    (p.is_real
                      ? "bg-emerald-500/15 text-emerald-500"
                      : "bg-muted/40 text-muted-foreground")
                  }
                  title={
                    p.is_real
                      ? "真实 adapter（会真发到平台）"
                      : "stub / dry-run（不真发）"
                  }
                >
                  {p.is_real ? "real" : "stub"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{p.name}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {p.requires_credential ? "需要 OAuth 凭证" : "无需凭证"}
                    {cred
                      ? ` · 已绑 ${cred.display_name ?? cred.external_user_id ?? ""}`
                      : ""}
                    {cred?.token_expires_at
                      ? ` · token 至 ${new Date(cred.token_expires_at).toLocaleString()}`
                      : ""}
                  </div>
                </div>
                {p.requires_credential ? (
                  cred ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void handleRevoke(p.name)}
                      title="撤销凭证"
                    >
                      <Unplug className="size-3.5" />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void handleBind(p.name)}
                      title="启动 OAuth 授权"
                    >
                      <LinkIcon className="size-3.5" /> 绑定
                    </Button>
                  )
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── DeadLetterPanel ─────────────────────────────────────────────────────────
//   读 /api/dlq?status=&run_id=&limit= 列表；按 status filter 切（默认 pending）；
//   可切「仅当前 run」；行内 retry / discard；点行展开看 traceback + args/kwargs。
//   - retry / discard 仅 pending 行可用，对应后端 400 兜底（前端预先禁用）
//   - 30s 静默 polling 兜底捕捉 worker 模式新入库的死信
//   - user 级范围（与 fileId 无关），所以独立 panel，不挂在 ProductionPanel 里

const DLQ_STATUS_FILTERS: Array<{ value: DlqStatus | "all"; label: string }> = [
  { value: "pending", label: "待处理" },
  { value: "retried", label: "已重投" },
  { value: "discarded", label: "已丢弃" },
  { value: "all", label: "全部" },
];

function DeadLetterPanel({ currentRunId }: { currentRunId: string | null }) {
  const [status, setStatus] = useState<DlqStatus | "all">("pending");
  const [scopedToRun, setScopedToRun] = useState(false);
  const runId = scopedToRun && currentRunId ? currentRunId : undefined;
  const { items, loading, error, reload } = useDlq({
    status: status === "all" ? undefined : status,
    runId,
    limit: 100,
    pollIntervalMs: 30_000,
  });

  // 顶部提示用：pending 数量（即使当前过滤不是 pending 也提示）
  const pendingCount = items.filter((i) => i.status === "pending").length;

  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Skull className="size-4 text-muted-foreground" />
          <div>
            <h2 className="text-sm font-medium">死信队列</h2>
            <p className="text-xs text-muted-foreground">
              celery worker 异常 / BackgroundTasks tick 兜底入库的失败任务；
              <code className="font-mono">/api/dlq</code>
            </p>
          </div>
          {status !== "pending" && pendingCount > 0 ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-500">
              {pendingCount} 待处理
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <select
            className="h-7 rounded border border-border bg-background px-2 text-xs"
            value={status}
            onChange={(e) => setStatus(e.target.value as DlqStatus | "all")}
            title="按 status 过滤"
          >
            {DLQ_STATUS_FILTERS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <label
            className={
              "flex items-center gap-1.5 text-xs " +
              (currentRunId ? "text-muted-foreground" : "text-muted-foreground/50")
            }
            title={currentRunId ? "" : "需要先启动一个 run 才能筛"}
          >
            <input
              type="checkbox"
              checked={scopedToRun}
              onChange={(e) => setScopedToRun(e.target.checked)}
              disabled={!currentRunId}
            />
            仅当前 run
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={reload}
            disabled={loading}
          >
            <RefreshCcw
              className={`size-3.5 ${loading ? "animate-spin" : ""}`}
            />
            刷新
          </Button>
        </div>
      </header>
      {error ? (
        <p className="mb-2 rounded bg-rose-500/10 p-2 text-xs text-rose-500">
          拉取死信失败：{error}
        </p>
      ) : null}
      {!items.length ? (
        <p className="rounded bg-muted/30 p-3 text-xs text-muted-foreground">
          {loading
            ? "加载中…"
            : status === "pending"
            ? "没有待处理死信。worker / BackgroundTasks 抛出未捕获异常时会自动入库。"
            : "当前过滤下没有记录。"}
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-xs">
          {items.map((item) => (
            <DlqItemRow key={item.id} item={item} onChanged={reload} />
          ))}
        </ul>
      )}
    </section>
  );
}

function DlqItemRow({
  item,
  onChanged,
}: {
  item: DlqItemOut;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const isPending = item.status === "pending";

  const handleRetry = useCallback(async () => {
    if (!isPending) return;
    setBusy(true);
    try {
      const result = await retryDlq(item.id);
      feedback.success(`已重投（${result.dispatcher}）`);
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `API ${err.status}${
              typeof err.body === "object" &&
              err.body &&
              "detail" in err.body
                ? `: ${(err.body as { detail?: string }).detail ?? ""}`
                : ""
            }`
          : "网络错误";
      feedback.error(`重投失败：${message}`);
    } finally {
      setBusy(false);
    }
  }, [isPending, item.id, onChanged]);

  const handleDiscard = useCallback(async () => {
    if (!isPending) return;
    if (!window.confirm(`丢弃死信 ${item.task_name}？将不再可重投。`)) return;
    setBusy(true);
    try {
      await discardDlq(item.id);
      feedback.info("已丢弃");
      onChanged();
    } catch (err) {
      const message =
        err instanceof ApiError ? `API ${err.status}` : "网络错误";
      feedback.error(`丢弃失败：${message}`);
    } finally {
      setBusy(false);
    }
  }, [isPending, item.id, item.task_name, onChanged]);

  const lastFailed = new Date(item.last_failed_at).toLocaleString();
  const errorPreview = (item.error || "").split("\n")[0].slice(0, 200);

  return (
    <li className="rounded border border-border bg-background/40">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => setOpen((v) => !v)}
          title={open ? "收起详情" : "展开 traceback / args"}
        >
          {open ? (
            <ChevronDown className="size-3.5" />
          ) : (
            <ChevronRight className="size-3.5" />
          )}
        </button>
        <span
          className={
            "shrink-0 rounded px-1.5 py-0.5 text-[10px] " +
            dlqStatusCls(item.status)
          }
        >
          {item.status}
        </span>
        {item.attempt_count > 1 ? (
          <span
            className="shrink-0 rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] text-rose-500"
            title="软去重命中：同一 (task,args) 反复失败"
          >
            ×{item.attempt_count}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-mono text-[11px] font-medium">
              {item.task_name}
            </span>
            {item.run_id ? (
              <span
                className="shrink-0 truncate font-mono text-[10px] text-muted-foreground"
                title={`run ${item.run_id}`}
              >
                run {item.run_id.slice(0, 8)}…
              </span>
            ) : null}
            {item.step_id ? (
              <span
                className="shrink-0 truncate font-mono text-[10px] text-muted-foreground"
                title={`step ${item.step_id}`}
              >
                step {item.step_id.slice(0, 8)}…
              </span>
            ) : null}
          </div>
          <div className="truncate text-[10px] text-muted-foreground">
            {lastFailed} · {errorPreview || "(无错误信息)"}
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleRetry}
          disabled={busy || !isPending}
          title={isPending ? "重投到 tick / celery" : "仅 pending 可重投"}
        >
          <RotateCcw className="size-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleDiscard}
          disabled={busy || !isPending}
          title={isPending ? "丢弃（不可恢复）" : "仅 pending 可丢弃"}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
      {open ? (
        <div className="border-t border-border bg-muted/20 px-3 py-2 text-[11px]">
          {item.notes ? (
            <div className="mb-2 flex items-start gap-1.5 text-muted-foreground">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>{item.notes}</span>
            </div>
          ) : null}
          <DlqDetailField label="error" value={item.error} mono />
          {item.traceback ? (
            <DlqDetailField
              label="traceback"
              value={item.traceback}
              mono
              maxHeight={220}
            />
          ) : null}
          {item.args_json && item.args_json.length ? (
            <DlqDetailField
              label="args"
              value={JSON.stringify(item.args_json, null, 2)}
              mono
            />
          ) : null}
          {item.kwargs_json && Object.keys(item.kwargs_json).length ? (
            <DlqDetailField
              label="kwargs"
              value={JSON.stringify(item.kwargs_json, null, 2)}
              mono
            />
          ) : null}
          <div className="mt-1 text-[10px] text-muted-foreground">
            首次失败：{new Date(item.first_failed_at).toLocaleString()}
            {" · "}
            最近失败：{lastFailed}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function DlqDetailField({
  label,
  value,
  mono,
  maxHeight,
}: {
  label: string;
  value: string;
  mono?: boolean;
  maxHeight?: number;
}) {
  return (
    <div className="mb-2">
      <div className="mb-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <pre
        className={
          "overflow-auto whitespace-pre-wrap break-words rounded bg-background/60 p-2 text-[11px] " +
          (mono ? "font-mono" : "")
        }
        style={maxHeight ? { maxHeight } : undefined}
      >
        {value}
      </pre>
    </div>
  );
}

function dlqStatusCls(status: DlqStatus) {
  switch (status) {
    case "pending":
      return "bg-amber-500/15 text-amber-500";
    case "retried":
      return "bg-sky-500/15 text-sky-500";
    case "discarded":
      return "bg-muted/40 text-muted-foreground";
    default:
      return "bg-muted/40 text-muted-foreground";
  }
}
