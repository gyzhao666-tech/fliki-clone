"use client";

// Track-07：流水线节点 DAG 视图。
// 把 PipelineRun.steps 用 react-flow 渲染成横向 DAG（depth 自左向右展开）。
// 颜色复用 lib/pipelines.ts 里的 stepStateTone（tone -> tailwind 语义色）。
// 点节点通过 onNodeClick 回调通知父组件滚动到对应 step 卡片。

import {
  type CSSProperties,
  type MouseEvent,
  useCallback,
  useMemo,
} from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Loader2 } from "lucide-react";

import {
  type PipelineRun,
  type PipelineStep,
  stepStateTone,
} from "@/lib/pipelines";

// ── depends_on 推断 ───────────────────────────────────────────────────────────
// 后端 StepOut 没有暴露 depends_on（runner.py 内部用 depends_on_json）；
// 这里按 run.template_name 在前端硬编码三套模板，与 fliki-clone-api/app/services/pipeline/templates.py 对齐。
// custom_graph / 未知模板：兜底走 sequential（每个 step 依赖前一步）。

const TEMPLATE_DEPS: Record<string, Record<string, string[]>> = {
  script_only: {
    research: [],
    script: ["research"],
  },
  video_demo: {
    research: [],
    script: ["research"],
    video: ["script"],
    edit: ["video"],
    review: ["video", "edit", "script"],
  },
  video_full: {
    research: [],
    script: ["research"],
    art: ["script"],
    voice: ["script"],
    video: ["script", "art"],
    edit: ["video", "voice"],
    review: ["video", "edit", "script", "voice"],
  },
};

function inferDepsForRun(run: PipelineRun): Record<string, string[]> {
  const stepNames = new Set(run.steps.map((s) => s.name));
  const known = run.template_name ? TEMPLATE_DEPS[run.template_name] : undefined;
  if (known) {
    const out: Record<string, string[]> = {};
    for (const s of run.steps) {
      out[s.name] = (known[s.name] ?? []).filter((d) => stepNames.has(d));
    }
    return out;
  }
  const out: Record<string, string[]> = {};
  run.steps.forEach((s, i) => {
    out[s.name] = i === 0 ? [] : [run.steps[i - 1].name];
  });
  return out;
}

function computeLayers(
  run: PipelineRun,
  deps: Record<string, string[]>
): string[][] {
  const depth = new Map<string, number>();

  function visit(name: string, stack: Set<string>): number {
    if (depth.has(name)) return depth.get(name)!;
    if (stack.has(name)) return 0; // 防御循环依赖
    stack.add(name);
    const ups = deps[name] ?? [];
    const d = ups.length === 0 ? 0 : Math.max(...ups.map((u) => visit(u, stack))) + 1;
    stack.delete(name);
    depth.set(name, d);
    return d;
  }

  run.steps.forEach((s) => visit(s.name, new Set()));

  const layers: string[][] = [];
  for (const s of run.steps) {
    const d = depth.get(s.name) ?? 0;
    if (!layers[d]) layers[d] = [];
    layers[d].push(s.name);
  }
  return layers;
}

// ── tone -> tailwind class ───────────────────────────────────────────────────

interface ToneClass {
  border: string;
  bg: string;
  text: string;
  dot: string;
}

const TONE_CLASS: Record<string, ToneClass> = {
  success: {
    border: "border-emerald-500/60",
    bg: "bg-emerald-500/10",
    text: "text-emerald-600 dark:text-emerald-400",
    dot: "bg-emerald-500",
  },
  warning: {
    border: "border-amber-500/60",
    bg: "bg-amber-500/10",
    text: "text-amber-600 dark:text-amber-400",
    dot: "bg-amber-500",
  },
  danger: {
    border: "border-rose-500/60",
    bg: "bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-400",
    dot: "bg-rose-500",
  },
  info: {
    border: "border-blue-500/60",
    bg: "bg-blue-500/10",
    text: "text-blue-600 dark:text-blue-400",
    dot: "bg-blue-500",
  },
  muted: {
    border: "border-border",
    bg: "bg-muted/40",
    text: "text-muted-foreground",
    dot: "bg-muted-foreground/40",
  },
};

const TONE_STROKE: Record<string, string> = {
  success: "#10b981",
  warning: "#f59e0b",
  danger: "#f43f5e",
  info: "#3b82f6",
  muted: "#94a3b8",
};

// ── 自定义节点 ────────────────────────────────────────────────────────────────

interface StepNodeData extends Record<string, unknown> {
  step: PipelineStep;
  tone: string;
}

type StepFlowNode = Node<StepNodeData, "step">;

function StepNode({ data }: NodeProps<StepFlowNode>) {
  const tone = TONE_CLASS[data.tone] ?? TONE_CLASS.muted;
  const running = data.step.state === "running";
  return (
    <div
      className={
        "flex w-[160px] cursor-pointer flex-col gap-1 rounded-lg border-2 px-3 py-2 text-xs shadow-sm transition-colors " +
        tone.border +
        " " +
        tone.bg +
        " " +
        tone.text
      }
      title={`${data.step.name} · ${data.step.agent_type} · ${data.step.state}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/60"
      />
      <div className="flex items-center gap-1.5">
        {running ? (
          <Loader2 className="size-3.5 shrink-0 animate-spin" />
        ) : (
          <span className={"size-2 shrink-0 rounded-full " + tone.dot} />
        )}
        <span className="truncate font-semibold">{data.step.name}</span>
      </div>
      <div className="truncate text-[10px] opacity-80">
        {data.step.agent_type} · {data.step.state}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-muted-foreground/60"
      />
    </div>
  );
}

const nodeTypes = { step: StepNode };

// ── 主组件 ────────────────────────────────────────────────────────────────────

interface DagViewProps {
  run: PipelineRun;
  onNodeClick?: (stepName: string) => void;
  height?: number;
}

const COLUMN_GAP = 220;
const ROW_GAP = 110;

export function DagView({ run, onNodeClick, height = 380 }: DagViewProps) {
  const deps = useMemo(() => inferDepsForRun(run), [run]);
  const layers = useMemo(() => computeLayers(run, deps), [run, deps]);

  const { nodes, edges } = useMemo(() => {
    const ns: StepFlowNode[] = [];
    const stepByName = new Map(run.steps.map((s) => [s.name, s]));

    layers.forEach((layer, depth) => {
      const yOffset = -((layer.length - 1) * ROW_GAP) / 2;
      layer.forEach((name, i) => {
        const step = stepByName.get(name);
        if (!step) return;
        const tone = stepStateTone(step.state);
        ns.push({
          id: name,
          type: "step",
          position: { x: depth * COLUMN_GAP, y: yOffset + i * ROW_GAP },
          data: { step, tone },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          draggable: false,
        });
      });
    });

    const es: Edge[] = [];
    for (const [name, ups] of Object.entries(deps)) {
      const downstream = stepByName.get(name);
      if (!downstream) continue;
      for (const up of ups) {
        const upstream = stepByName.get(up);
        if (!upstream) continue;
        const tone = stepStateTone(upstream.state);
        const stroke = TONE_STROKE[tone] ?? TONE_STROKE.muted;
        es.push({
          id: `${up}->${name}`,
          source: up,
          target: name,
          animated: downstream.state === "running",
          style: { stroke, strokeWidth: 1.5 },
        });
      }
    }
    return { nodes: ns, edges: es };
  }, [run, deps, layers]);

  const handleNodeClick = useCallback(
    (_e: MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  if (!run.steps.length) {
    return (
      <div className="rounded border border-dashed border-border bg-muted/20 p-8 text-center text-xs text-muted-foreground">
        DAG 视图：等流水线启动后会渲染节点
      </div>
    );
  }

  const containerStyle: CSSProperties = { height };

  return (
    <div
      className="rounded border border-border bg-background/40"
      style={containerStyle}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        panOnScroll={false}
        zoomOnScroll={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export default DagView;
