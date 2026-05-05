"use client";


import { useEffect, useMemo, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import {
  Ban,
  BookOpen,
  Briefcase,
  Check,
  ChevronLeft,
  ChevronRight,
  Clapperboard,
  Clock,
  FileText,
  Globe2,
  Grid2X2,
  Heart,
  Megaphone,
  Share2,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/utils";

function formatApiFailure(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown };
    const d = body?.detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d) && d.length) {
      const parts = d
        .map((x: { msg?: string }) => (typeof x?.msg === "string" ? x.msg : null))
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  if (err instanceof TypeError) {
    return "无法连接服务器，请确认后端已启动且网络正常。";
  }
  return fallback;
}

type Template = {
  id: string;
  title: string;
  thumbnail_url: string | null;
  category: string;
  is_premium?: boolean;
  config_json?: {
    mode_name?: string;
    best_for?: string[];
    required_inputs?: TemplateInput[];
    scenes?: { id: string; name: string; duration: number }[];
  } | null;
};

type TemplateInput = {
  key: string;
  label: string;
};

type Voice = {
  id: string;
  name: string;
  lang: string;
  style: string | null;
};

type FileOut = {
  id: string;
};

type Step = "script" | "template" | "voice";

const TONES = [
  { value: "professional", label: "专业" },
  { value: "casual", label: "轻松" },
  { value: "energetic", label: "活力" },
  { value: "calm", label: "沉稳" },
  { value: "humorous", label: "幽默" },
];

const VIDEO_TYPES = ["产品介绍", "教程讲解", "社媒广告", "知识科普", "口播带货"];

const AUDIENCES = ["新用户", "潜在客户", "企业客户", "学生", "普通观众"];

const SCRIPT_STRUCTURE = [
  { title: "开场钩子", description: "快速吸引注意力" },
  { title: "痛点 / 背景", description: "说明为什么要继续看" },
  { title: "核心内容", description: "展开主要信息" },
  { title: "行动引导", description: "引导用户下一步操作" },
];

const SCRIPT_ACTIONS = [
  {
    label: "优化文案",
    prompt: "请优化下面的视频脚本，让表达更自然、更适合视频口播，并保留原意。",
  },
  {
    label: "翻译",
    prompt: "请把下面的视频脚本翻译成当前页面语言，保持适合视频口播的表达。",
  },
  {
    label: "缩短",
    prompt: "请缩短下面的视频脚本，保留核心信息，让节奏更紧凑。",
  },
  {
    label: "扩写",
    prompt: "请扩写下面的视频脚本，补充细节和转场，让内容更完整。",
  },
];

const TEMPLATE_FILTERS = [
  { id: "all", label: "全部", icon: Grid2X2, categories: [] },
  { id: "marketing", label: "营销", icon: Megaphone, categories: ["marketing"] },
  { id: "education", label: "教程", icon: BookOpen, categories: ["education", "tutorial"] },
  { id: "social", label: "社媒", icon: Share2, categories: ["social"] },
  { id: "business", label: "商务", icon: Briefcase, categories: ["business", "corporate"] },
  { id: "entertainment", label: "娱乐", icon: Clapperboard, categories: ["entertainment", "news"] },
  { id: "lifestyle", label: "生活方式", icon: Heart, categories: ["lifestyle", "travel"] },
];

const TEMPLATE_CATEGORY_LABELS: Record<string, string> = {
  marketing: "营销",
  education: "教程",
  tutorial: "教程",
  social: "社媒",
  business: "商务",
  corporate: "商务",
  entertainment: "娱乐",
  news: "娱乐",
  lifestyle: "生活方式",
  travel: "生活方式",
};

const REPAINT_TEMPLATE_IMAGES_BY_TITLE: Record<string, string> = {
  产品亮点: "/templates/t1.jpg",
  限时优惠: "/templates/t2.jpg",
  品牌故事: "/templates/t3.jpg",
  操作指南: "/templates/t4.jpg",
  知识分享: "/templates/t5.jpg",
  工具测评: "/templates/t6.jpg",
  短视频封面: "/templates/t7.jpg",
  热门话题: "/templates/t8.jpg",
  互动投票: "/templates/t9.jpg",
  企业简介: "/templates/t10.jpg",
  年度报告: "/templates/t11.jpg",
  搞笑日常: "/templates/t12.jpg",
  开箱体验: "/templates/t13.jpg",
  健身打卡: "/templates/t14.jpg",
  美食制作: "/templates/t15.jpg",
};

function templateImageSrc(template: Template, index: number) {
  return (
    template.thumbnail_url ||
    REPAINT_TEMPLATE_IMAGES_BY_TITLE[template.title] ||
    `/templates/t${(index % 15) + 1}.jpg`
  );
}

function normalizeCategory(category: string) {
  return category.trim().toLowerCase();
}

function displayTemplateCategory(category: string) {
  const normalized = normalizeCategory(category);
  return TEMPLATE_CATEGORY_LABELS[normalized] ?? category;
}

function displayLanguage(lang: string) {
  const normalized = lang.trim().toLowerCase();
  if (["zh", "zh-cn", "chinese", "中文"].includes(normalized)) return "中文";
  if (["en", "en-us", "en-gb", "english"].includes(normalized)) return "英语";
  return lang || "未设置";
}

const STEPS: { id: Step; label: string }[] = [
  { id: "script", label: "脚本" },
  { id: "template", label: "模板" },
  { id: "voice", label: "配音" },
];

export default function CreatePage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("script");
  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string>("");
  const [language, setLanguage] = useState("zh");
  const [creating, setCreating] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateFilter, setTemplateFilter] = useState("all");
  const [templateSlotValues, setTemplateSlotValues] = useState<Record<string, string>>({});
  const [voices, setVoices] = useState<Voice[]>([]);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // AI generate script
  const [aiTone, setAiTone] = useState("professional");
  const [videoType, setVideoType] = useState(VIDEO_TYPES[0]);
  const [audience, setAudience] = useState(AUDIENCES[1]);
  const [aiDuration, setAiDuration] = useState(60);
  const [generatingScript, setGeneratingScript] = useState(false);
  const [activeScriptAction, setActiveScriptAction] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const templateData = await api<Template[]>("/templates");
        const voiceData = await api<Voice[]>("/voices");
        if (!mounted) return;
        setTemplates(templateData);
        setVoices(voiceData);
        if (voiceData.length > 0) {
          setSelectedVoice(voiceData[0].id);
          setLanguage(voiceData[0].lang);
        }
      } catch (e) {
        if (!mounted) return;
        setError(formatApiFailure(e, "模板或配音加载失败，请稍后重试。"));
      } finally {
        if (mounted) setLoadingData(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const languages = useMemo(
    () => Array.from(new Set(voices.map((v) => v.lang))),
    [voices]
  );
  const filteredVoices = useMemo(
    () => voices.filter((v) => v.lang === language),
    [voices, language]
  );
  const filteredTemplates = useMemo(() => {
    const activeFilter = TEMPLATE_FILTERS.find((filter) => filter.id === templateFilter);
    if (!activeFilter || activeFilter.id === "all") return templates;

    return templates.filter((template) =>
      activeFilter.categories.includes(normalizeCategory(template.category))
    );
  }, [templates, templateFilter]);
  const selectedTemplateData = useMemo(
    () => templates.find((template) => template.id === selectedTemplate) ?? null,
    [templates, selectedTemplate]
  );
  const selectedTemplateInputs = useMemo(
    () => selectedTemplateData?.config_json?.required_inputs ?? [],
    [selectedTemplateData]
  );

  useEffect(() => {
    if (filteredVoices.some((v) => v.id === selectedVoice)) return;
    setSelectedVoice(filteredVoices[0]?.id ?? "");
  }, [filteredVoices, selectedVoice]);

  useEffect(() => {
    setTemplateSlotValues((current) => {
      const next: Record<string, string> = {};
      for (const input of selectedTemplateInputs) {
        next[input.key] = current[input.key] ?? "";
      }
      return next;
    });
  }, [selectedTemplateInputs]);

  async function generateScript(topic: string, fallback = "AI 生成失败，请稍后重试。") {
    if (!topic.trim()) return;
    const toneLabel = TONES.find((tone) => tone.value === aiTone)?.label ?? aiTone;
    setGeneratingScript(true);
    setAiError(null);
    try {
      const res = await api<{ script: string }>("/ai/script", {
        method: "POST",
        body: JSON.stringify({
          topic: `${topic.trim()}。视频类型：${videoType}；目标受众：${audience}；语气风格：${toneLabel}`,
          tone: aiTone,
          duration: aiDuration,
          language,
        }),
      });
      setScript(res.script);
    } catch (e) {
      setAiError(
        formatApiFailure(e, fallback)
      );
    } finally {
      setGeneratingScript(false);
    }
  }

  async function handleGenerateFromSettings() {
    await generateScript(title.trim() || videoType);
  }

  async function handleScriptAction(action: (typeof SCRIPT_ACTIONS)[number]) {
    if (!script.trim()) {
      setAiError("请先输入或生成一段视频脚本。");
      return;
    }

    setActiveScriptAction(action.label);
    try {
      await generateScript(
        `${action.prompt}\n\n当前脚本：\n${script.trim()}`,
        `${action.label}失败，请稍后重试。`
      );
    } finally {
      setActiveScriptAction(null);
    }
  }

  async function handleCreate() {
    if (!title.trim()) {
      setError("请先填写项目标题。");
      setStep("script");
      return;
    }

    if (!script.trim()) {
      setError("请先输入或生成视频脚本。");
      setStep("script");
      return;
    }

    const missingTemplateInputs = selectedTemplateInputs.filter(
      (input) => !templateSlotValues[input.key]?.trim()
    );
    if (selectedTemplate && missingTemplateInputs.length > 0) {
      setError(`请先填写模板替换内容：${missingTemplateInputs.map((input) => input.label).join("、")}`);
      setStep("template");
      return;
    }

    if (!selectedVoice) {
      setError("请先选择一个配音。");
      return;
    }

    setCreating(true);
    setError(null);
    try {
      // 按「目标总时长」平分到各段落（与项目页「每场景秒数 × 镜数」一致）
      const paragraphs = script.trim().split("\n\n").filter((p) => p.trim());
      const numScenes = Math.max(1, paragraphs.length);
      const sceneDuration =
        aiDuration > 0
          ? Math.max(5, Math.round(aiDuration / numScenes))
          : undefined;

      const created = await api<FileOut>("/files", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          script: script.trim(),
          template_id: selectedTemplate,
          template_slot_values: selectedTemplate ? templateSlotValues : {},
          voice_id: selectedVoice,
          language,
          project_type: selectedTemplate ? "template_replace" : "story_video",
          product_name: templateSlotValues.product_name || title.trim(),
          selling_points: (templateSlotValues.top_benefits || templateSlotValues.benefits || "")
            .split(/[\n,，;；]+/)
            .map((item) => item.trim())
            .filter(Boolean),
          ...(sceneDuration !== undefined && { scene_duration: sceneDuration }),
        }),
      });
      router.push(`/app/project/${created.id}`);
    } catch (e) {
      setError(formatApiFailure(e, "创建视频失败，请稍后重试。"));
      setCreating(false);
    }
  }

  const stepIdx = STEPS.findIndex((s) => s.id === step);
  const scriptParagraphs = script.trim().split(/\n\n+/).filter((p) => p.trim());
  const estimatedScenes = Math.max(1, scriptParagraphs.length || Math.ceil(script.length / 260));
  const perSceneDuration = Math.max(5, Math.round(aiDuration / estimatedScenes));
  const scriptChars = script.trim().length;
  const languageLabel = displayLanguage(language);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-6 py-6 lg:px-8">
      {/* Header */}
      {step !== "template" && (
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text)]">创建新视频</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">用脚本、模板和 AI 配音快速生成一个完整视频。</p>
          {error && <p className="text-sm text-red-500 mt-2">{error}</p>}
        </div>
      )}

      {/* Steps */}
      {step !== "template" && (
        <div className="mb-6 flex items-center gap-2">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center gap-2">
              <button
                onClick={() => i <= stepIdx && setStep(s.id)}
                className={cn(
                  "flex items-center gap-2 rounded-[var(--radius-full)] px-4 py-2 text-sm font-semibold transition-colors",
                  step === s.id
                    ? "bg-[var(--brand-600)] text-white"
                    : i < stepIdx
                    ? "bg-[var(--brand-600)]/10 text-[var(--brand-600)] cursor-pointer hover:bg-[var(--brand-600)]/20"
                    : "bg-[var(--bg-muted)] text-[var(--text-muted)] cursor-default"
                )}
              >
                <span className={cn(
                  "flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold",
                  step === s.id ? "bg-white/20" : ""
                )}>
                  {i < stepIdx ? "✓" : i + 1}
                </span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />}
            </div>
          ))}
        </div>
      )}

      {/* Step: Script */}
      {step === "script" && (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="flex flex-col gap-5">
            <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
              <Input
                label="项目标题"
                placeholder="例如：产品发布视频"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="h-11 px-4 text-sm"
              />
            </div>
            <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <label className="text-base font-semibold text-[var(--text)]">视频脚本</label>
                <span className="text-xs font-medium text-[var(--text-muted)]">{scriptChars} 字</span>
              </div>
              <div className="mb-3 flex flex-wrap gap-2">
                {SCRIPT_ACTIONS.map((action) => (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => handleScriptAction(action)}
                    disabled={generatingScript}
                    className="rounded-[var(--radius-full)] border border-[var(--border)] bg-[var(--bg-muted)] px-3 py-1.5 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:border-[var(--brand-600)]/40 hover:text-[var(--brand-600)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {activeScriptAction === action.label ? "处理中…" : action.label}
                  </button>
                ))}
              </div>
              <div className="relative">
                <Textarea
                  placeholder="输入你的脚本，或让 AI 根据主题帮你生成…"
                  rows={11}
                  value={script}
                  onChange={(e) => setScript(e.target.value)}
                  className="px-4 py-3 pr-4 pb-16 text-sm leading-6"
                />
                <Button
                  type="button"
                  size="sm"
                  onClick={handleGenerateFromSettings}
                  loading={generatingScript}
                  className="absolute bottom-4 right-4 gap-1.5 shadow-lg"
                >
                  <Sparkles className="h-4 w-4" /> AI 生成视频脚本
                </Button>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-4 text-xs font-medium text-[var(--text-muted)]">
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3.5 w-3.5" /> 预计 {estimatedScenes} 个场景
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" /> 预计配音约 {aiDuration} 秒
                </span>
                <span className="inline-flex items-center gap-1">
                  <Globe2 className="h-3.5 w-3.5" /> {languageLabel}
                </span>
              </div>
              {aiError && <p className="mt-3 text-sm text-red-500">{aiError}</p>}
            </div>
            <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
              <label className="mb-3 flex items-center justify-between gap-3 text-base font-semibold text-[var(--text)]">
                <span>目标总时长</span>
                <span className="flex items-center gap-2 text-xl font-bold text-[var(--brand-600)]">
                  {aiDuration} 秒
                  <span className="rounded-[var(--radius-full)] bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-600">
                    推荐
                  </span>
                </span>
              </label>
              <p className="mb-4 text-xs text-[var(--text-muted)]">
                每段约 {perSceneDuration} 秒 · 共 {estimatedScenes} 个场景
              </p>
              <input
                type="range"
                min={15}
                max={300}
                step={15}
                value={aiDuration}
                onChange={(e) => setAiDuration(Number(e.target.value))}
                className="w-full accent-[var(--brand-600)]"
              />
              <div className="mt-2 flex justify-between text-xs font-medium text-[var(--text-muted)]">
                <span>15 秒</span>
                <span>60 秒</span>
                <span>120 秒</span>
                <span>300 秒</span>
              </div>
            </div>
            <div className="flex items-center justify-end gap-3">
              <Button variant="ghost" size="sm" className="gap-1.5" onClick={handleGenerateFromSettings} loading={generatingScript}>
                <Sparkles className="h-4 w-4" /> 使用 AI 生成
              </Button>
              <Button
                onClick={() => setStep("template")}
                disabled={!title.trim() || !script.trim()}
                size="lg"
              >
                下一步：选择模板 <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <aside className="flex flex-col gap-5">
            <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
              <p className="flex items-center gap-2 text-base font-semibold text-[var(--text)]">
                <Sparkles className="h-4 w-4 text-[var(--brand-600)]" /> 生成设置
              </p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">配置 AI 生成脚本的方向</p>

              <div className="mt-5 space-y-5">
                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--text-secondary)]">视频类型</p>
                  <div className="flex flex-wrap gap-2">
                    {VIDEO_TYPES.map((type) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => setVideoType(type)}
                        className={cn(
                          "rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-semibold transition-colors",
                          videoType === type
                            ? "border-[var(--brand-600)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]"
                            : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--brand-600)]/40 hover:text-[var(--brand-600)]"
                        )}
                      >
                        {type}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--text-secondary)]">语气风格</p>
                  <div className="flex flex-wrap gap-2">
                    {TONES.map((tone) => (
                      <button
                        key={tone.value}
                        type="button"
                        onClick={() => setAiTone(tone.value)}
                        className={cn(
                          "rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-semibold transition-colors",
                          aiTone === tone.value
                            ? "border-[var(--brand-600)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]"
                            : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--brand-600)]/40 hover:text-[var(--brand-600)]"
                        )}
                      >
                        {tone.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-sm font-semibold text-[var(--text-secondary)]">目标受众</p>
                  <div className="flex flex-wrap gap-2">
                    {AUDIENCES.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => setAudience(item)}
                        className={cn(
                          "rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-semibold transition-colors",
                          audience === item
                            ? "border-[var(--brand-600)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]"
                            : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--brand-600)]/40 hover:text-[var(--brand-600)]"
                        )}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
              <p className="flex items-center gap-2 text-base font-semibold text-[var(--text)]">
                <FileText className="h-4 w-4 text-[var(--brand-600)]" /> 脚本结构
              </p>
              <p className="mt-1 text-xs text-[var(--text-muted)]">一个完整视频脚本通常包含以下部分</p>
              <div className="mt-5 space-y-3">
                {SCRIPT_STRUCTURE.map((item, index) => (
                  <div
                    key={item.title}
                    className="flex items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-muted)]/40 p-3"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--brand-600)]/10 text-sm font-bold text-[var(--brand-600)]">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold text-[var(--text)]">{item.title}</span>
                      <span className="mt-0.5 block text-xs text-[var(--text-muted)]">{item.description}</span>
                    </span>
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-xs font-bold text-emerald-600">
                      ✓
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </aside>

        </div>
      )}

      {/* Step: Template */}
      {step === "template" && (
        <div className="-mx-6 -my-6 flex min-h-[calc(100vh-3rem)] flex-col bg-[var(--bg)] lg:-mx-8">
          <header className="border-b border-[var(--border)] bg-[var(--surface)] px-8 py-5">
            <div className="mx-auto flex w-full max-w-[360px] items-center">
              {STEPS.map((s, i) => {
                const isDone = i < stepIdx;
                const isActive = step === s.id;

                return (
                  <div key={s.id} className="flex flex-1 items-center last:flex-none">
                    <button
                      type="button"
                      onClick={() => i <= stepIdx && setStep(s.id)}
                      className="flex items-center gap-2 text-left"
                    >
                      <span
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full text-[13px] font-semibold transition-colors",
                          isDone || isActive
                            ? "bg-[var(--brand-600)] text-white"
                            : "bg-[var(--border)] text-[var(--text-muted)]"
                        )}
                      >
                        {isDone ? <Check className="h-4 w-4" /> : i + 1}
                      </span>
                      <span
                        className={cn(
                          "whitespace-nowrap text-[13px]",
                          isActive
                            ? "font-semibold text-[var(--text)]"
                            : isDone
                            ? "font-normal text-[var(--text)]"
                            : "font-normal text-[var(--text-muted)]"
                        )}
                      >
                        {s.label}
                      </span>
                    </button>
                    {i < STEPS.length - 1 && (
                      <span
                        className={cn(
                          "mx-3 h-0.5 flex-1 rounded-full",
                          i < stepIdx ? "bg-[var(--brand-600)]" : "bg-[var(--border)]"
                        )}
                      />
                    )}
                  </div>
                );
              })}
            </div>
            <div className="mx-auto mt-5 max-w-[460px] text-center">
              <h2 className="text-[22px] font-bold text-[var(--text)]">选择视频模板</h2>
              <p className="mt-1.5 text-sm leading-6 text-[var(--text-secondary)]">
                选择一个模板来确定视频的视觉风格，也可以暂不使用模板，稍后在项目页调整。
              </p>
              {error && <p className="mt-2 text-sm text-red-500">{error}</p>}
            </div>
          </header>

          <main className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col gap-5 px-8 py-7">
            <div className="flex flex-wrap gap-2">
              {TEMPLATE_FILTERS.map((filter) => {
                const Icon = filter.icon;
                const isActive = templateFilter === filter.id;

                return (
                  <button
                    key={filter.id}
                    type="button"
                    onClick={() => setTemplateFilter(filter.id)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border-[1.5px] px-3.5 py-1.5 text-[13px] transition-all",
                      isActive
                        ? "border-[var(--brand-600)] bg-[var(--brand-600)]/10 font-semibold text-[var(--brand-600)]"
                        : "border-[var(--border)] bg-[var(--surface)] font-normal text-[var(--text-secondary)] hover:border-[var(--brand-600)]/40 hover:text-[var(--brand-600)]"
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {filter.label}
                  </button>
                );
              })}
            </div>

            {loadingData ? (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4">
                {Array.from({ length: 12 }).map((_, index) => (
                  <div
                    key={index}
                    className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)] shadow-sm"
                  >
                    <div className="aspect-[9/16] animate-pulse bg-[var(--bg-muted)]" />
                    <div className="space-y-2 px-3.5 py-3">
                      <div className="h-4 w-2/3 rounded bg-[var(--bg-muted)]" />
                      <div className="h-3 w-1/3 rounded bg-[var(--bg-muted)]" />
                    </div>
                  </div>
                ))}
              </div>
            ) : templates.length > 0 ? (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4">
              <button
                type="button"
                onClick={() => setSelectedTemplate(null)}
                className={cn(
                  "group relative flex w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border-2 bg-[var(--surface)] text-center shadow-sm outline-none transition-all hover:-translate-y-0.5 hover:shadow-md",
                  selectedTemplate === null
                    ? "border-[var(--brand-600)] ring-[3px] ring-[var(--brand-600)]/10"
                    : "border-[var(--border)] hover:border-[var(--brand-600)]/40"
                )}
              >
                {selectedTemplate === null && (
                  <span className="absolute left-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-[var(--brand-600)] text-white shadow-md">
                    <Check className="h-3.5 w-3.5" />
                  </span>
                )}
                <div className="flex aspect-[9/16] w-full flex-col items-center justify-center gap-2 bg-[var(--brand-600)]/10">
                  <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--brand-600)] text-white">
                    <Ban className="h-5 w-5" />
                  </span>
                </div>
                <div className="px-3.5 py-3">
                  <p className="text-sm font-semibold text-[var(--text)]">暂不使用模板</p>
                  <p className="mt-0.5 text-xs leading-5 text-[var(--text-muted)]">稍后在项目页调整</p>
                </div>
              </button>
              {filteredTemplates.map((t) => {
                const templateIndex = templates.findIndex((template) => template.id === t.id);
                const thumbnail = templateImageSrc(t, templateIndex >= 0 ? templateIndex : 0);
                return (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTemplate(t.id)}
                    className={cn(
                      "group relative block w-full overflow-hidden rounded-[var(--radius-lg)] border-[1.5px] bg-[var(--surface)] text-left shadow-sm outline-none transition-all hover:-translate-y-0.5 hover:border-[var(--brand-600)]/40 hover:shadow-md",
                      selectedTemplate === t.id
                        ? "border-[var(--brand-600)] ring-[3px] ring-[var(--brand-600)]/10"
                        : "border-[var(--border)] hover:border-[var(--border-strong)]"
                    )}
                  >
                    {selectedTemplate === t.id && (
                      <span className="absolute left-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-[var(--brand-600)] text-white shadow-md">
                        <Check className="h-3.5 w-3.5" />
                      </span>
                    )}
                    {t.is_premium && (
                      <span className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md bg-black/55 px-2 py-1 text-[11px] font-semibold text-amber-300 backdrop-blur">
                        <Sparkles className="h-3 w-3" /> 高级
                      </span>
                    )}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={thumbnail}
                      alt={t.title}
                      className="aspect-[9/16] w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                    <div className="border-t border-[var(--border)] bg-[var(--surface)] px-3.5 py-3">
                      <p className="truncate text-sm font-semibold leading-5 text-[var(--text)]">{t.title}</p>
                      <p className="mt-0.5 text-xs text-[var(--text-muted)]">{displayTemplateCategory(t.category)}</p>
                      {t.config_json?.mode_name && (
                        <p className="mt-1 truncate text-[11px] font-medium text-[var(--brand-600)]">
                          {t.config_json.mode_name}
                        </p>
                      )}
                    </div>
                  </button>
                );
              })}
              {filteredTemplates.length === 0 && (
                <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 text-center text-sm text-[var(--text-secondary)]">
                  当前分类暂无模板，可以切换分类或暂不使用模板继续。
                </div>
              )}
            </div>
          ) : (
            <p className="rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-secondary)]">
              暂无可用模板，将以空模板继续创建项目。
            </p>
          )}

            {selectedTemplateData?.config_json && selectedTemplateInputs.length > 0 && (
              <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)] p-5 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-[var(--text)]">
                      {selectedTemplateData.config_json.mode_name ?? "模板替换内容"}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">
                      填入这些内容后，后端会按模板固定分镜生成可替换视频。
                    </p>
                  </div>
                  {selectedTemplateData.config_json.scenes?.length ? (
                    <span className="rounded-full bg-[var(--brand-600)]/10 px-3 py-1 text-xs font-semibold text-[var(--brand-600)]">
                      {selectedTemplateData.config_json.scenes.length} 个固定分镜
                    </span>
                  ) : null}
                </div>

                {selectedTemplateData.config_json.best_for?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedTemplateData.config_json.best_for.slice(0, 4).map((item) => (
                      <span
                        key={item}
                        className="rounded-full bg-[var(--bg-muted)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)]"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                ) : null}

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {selectedTemplateInputs.map((input) => (
                    <label key={input.key} className="block">
                      <span className="mb-1.5 block text-xs font-semibold text-[var(--text-secondary)]">
                        {input.label}
                      </span>
                      <textarea
                        value={templateSlotValues[input.key] ?? ""}
                        onChange={(event) =>
                          setTemplateSlotValues((current) => ({
                            ...current,
                            [input.key]: event.target.value,
                          }))
                        }
                        rows={input.key.includes("steps") || input.key.includes("benefits") || input.key.includes("facts") ? 3 : 2}
                        placeholder={input.key.includes("steps") || input.key.includes("benefits") || input.key.includes("facts") ? "可用换行填写多条" : `填写${input.label}`}
                        className="w-full resize-none rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--brand-600)]"
                      />
                    </label>
                  ))}
                </div>
              </section>
            )}
          </main>

          <footer className="mx-auto flex w-full max-w-[1280px] items-center justify-between border-t border-[var(--border)] bg-[var(--surface)] px-8 py-4">
            <button
              type="button"
              onClick={() => setStep("script")}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border-[1.5px] border-[var(--border)] bg-[var(--surface)] px-5 py-2.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text)]"
            >
              <ChevronLeft className="h-4 w-4" />
              上一步
            </button>
            <div className="flex items-center gap-3">
              <p className="hidden text-sm text-[var(--text-muted)] sm:block">
                当前选择：{selectedTemplateData ? selectedTemplateData.title : "暂不使用模板"}
              </p>
              <button
                type="button"
                onClick={() => setStep("voice")}
                disabled={loadingData}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--brand-600)] px-6 py-2.5 text-sm font-semibold text-white shadow-[0_2px_8px_rgba(62,99,221,0.3)] transition-colors hover:bg-[var(--brand-700)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {selectedTemplate ? "下一步：选择配音" : "跳过模板，选择配音"}
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </footer>
        </div>
      )}

      {/* Step: Voice */}
      {step === "voice" && (
        <div className="flex flex-col gap-6">
          <div>
            <label className="text-sm font-medium text-[var(--text)] block mb-2">语言</label>
            {loadingData ? (
              <p className="text-sm text-[var(--text-secondary)]">正在加载语言…</p>
            ) : languages.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {languages.map((l) => (
                  <button
                    key={l}
                    onClick={() => setLanguage(l)}
                    className={cn(
                      "px-3 py-1.5 rounded-[var(--radius-full)] text-sm border transition-colors",
                      language === l
                        ? "bg-[var(--brand-600)] text-white border-[var(--brand-600)]"
                        : "bg-[var(--surface)] text-[var(--text-secondary)] border-[var(--border)] hover:border-[var(--border-strong)]"
                    )}
                  >
                    {displayLanguage(l)}
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--text-secondary)] mt-2">暂无可用语言。</p>
            )}
          </div>

          <div>
            <label className="text-sm font-medium text-[var(--text)] block mb-2">声音</label>
            {loadingData ? (
              <div className="rounded-[var(--radius-xl)] border border-dashed border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-secondary)]">
                正在加载配音…
              </div>
            ) : filteredVoices.length > 0 ? (
              <div className="grid grid-cols-2 gap-3">
                {filteredVoices.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setSelectedVoice(v.id)}
                    className={cn(
                      "flex items-center gap-3 p-3 rounded-[var(--radius-xl)] border text-left transition-all",
                      selectedVoice === v.id
                        ? "border-[var(--brand-600)] bg-[var(--brand-600)]/5"
                        : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
                    )}
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--brand-600)]/10 text-[var(--brand-600)] font-bold text-sm shrink-0">
                      {v.name.charAt(0) || "声"}
                    </span>
                    <div>
                      <p className="text-sm font-medium text-[var(--text)]">{v.name}</p>
                      <p className="text-xs text-[var(--text-muted)]">{v.style ?? "自然"}</p>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <p className="rounded-[var(--radius-xl)] border border-dashed border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-secondary)]">
                当前语言暂无可用声音，请等待后端返回配音数据后再创建。
              </p>
            )}
          </div>

          <div className="flex justify-between">
            <Button variant="ghost" onClick={() => setStep("template")}>上一步</Button>
            <Button
              onClick={handleCreate}
              loading={creating}
              disabled={!title.trim() || !script.trim() || !selectedVoice || loadingData || creating}
            >
              {creating ? "创建中…" : "创建视频"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
