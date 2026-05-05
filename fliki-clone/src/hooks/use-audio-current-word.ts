"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * useAudioCurrentWord
 * ───────────────────
 * Track-26 / L-02 卡拉 OK 字幕高亮。
 *
 * 监听 `<audio>` 元素的 `timeupdate` / `seeked` 事件，按 throttle ≤ 33ms (~30fps)
 * 在 VoiceAgent v4 word-level 字幕数组里二分查找当前 (subtitleIndex, wordIndex)。
 *
 * VoiceAgent v4 outputs.subtitles 形状（见 `services/pipeline/agents/voice.py`）：
 *   [
 *     { start: 0.0, end: 1.4, text: "...", words: [{start, end, word}, ...] },
 *     ...
 *   ]
 *
 * 行为约定：
 *   - 边界（currentTime < 第一条 start / > 最后一条 end）→ 返 (-1, -1)
 *   - audio 元素为 null（ref 还没挂 / 没字幕）→ 返 (-1, -1)
 *   - 字幕条之间的小 gap → 粘到上一个 subtitle / word（保持单调推进）
 *   - 字幕条没有 words 数组（v3 行级 / v2 镜级）→ 返 (subtitleIndex, -1)
 *   - audio paused 时 listener 自然不再触发 → state 保持最后一次播放位置（粘性）
 */

export interface WordTimestamp {
  start: number;
  end: number;
  word: string;
}

export interface SubtitleWithWords {
  start: number;
  end: number;
  words?: WordTimestamp[] | null;
  text?: string;
  [key: string]: unknown;
}

export interface CurrentWordPosition {
  currentSubtitleIndex: number;
  currentWordIndex: number;
}

const NONE: CurrentWordPosition = {
  currentSubtitleIndex: -1,
  currentWordIndex: -1,
};

/**
 * 返回 items 中**最大的** index i，使 getKey(items[i]) <= target。
 * 没有任何元素满足时返 -1。
 */
function searchFloor<T>(
  items: ReadonlyArray<T>,
  getKey: (x: T) => number,
  target: number,
): number {
  let lo = 0;
  let hi = items.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (getKey(items[mid]) <= target) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return ans;
}

/**
 * 纯函数：给定 subtitles + currentTime，返回 (currentSubtitleIndex, currentWordIndex)。
 *
 * 单元测试主战场（见 `__tests__/use-audio-current-word.test.ts`）。
 */
export function findCurrentWord(
  subtitles: ReadonlyArray<SubtitleWithWords> | null | undefined,
  currentTime: number,
): CurrentWordPosition {
  if (!subtitles || subtitles.length === 0) return NONE;
  if (!Number.isFinite(currentTime)) return NONE;

  const first = subtitles[0];
  const last = subtitles[subtitles.length - 1];
  if (currentTime < first.start) return NONE;
  if (currentTime > last.end) return NONE;

  const subIdx = searchFloor(subtitles, (s) => s.start, currentTime);
  if (subIdx < 0) return NONE;

  const sub = subtitles[subIdx];
  const words = Array.isArray(sub.words) ? sub.words : null;
  if (!words || words.length === 0) {
    return { currentSubtitleIndex: subIdx, currentWordIndex: -1 };
  }

  const wordIdx = searchFloor(words, (w) => w.start, currentTime);
  return { currentSubtitleIndex: subIdx, currentWordIndex: wordIdx };
}

export interface UseAudioCurrentWordOptions {
  audioRef: RefObject<HTMLAudioElement | null>;
  subtitles: ReadonlyArray<SubtitleWithWords> | null | undefined;
  /** 默认 true。可用 onPlay/onPause 切到 false 来暂停 listener；state 保留上次位置 */
  enabled?: boolean;
  /** 节流时间，默认 33ms（≈ 30fps）；浏览器 timeupdate 一般 250ms 一次，节流主要防 seeked 抖动 */
  throttleMs?: number;
}

export function useAudioCurrentWord({
  audioRef,
  subtitles,
  enabled = true,
  throttleMs = 33,
}: UseAudioCurrentWordOptions): CurrentWordPosition {
  const [pos, setPos] = useState<CurrentWordPosition>(NONE);

  // subtitles 直接进 ref，避免每次 outputs_json 重新引用导致 effect 反复 register listener
  const subtitlesRef = useRef(subtitles);
  subtitlesRef.current = subtitles;

  const lastTickRef = useRef<number>(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !enabled) {
      // audio 为 null：保持 NONE（初始已是 NONE）
      // enabled=false：不触碰 state，保留上一次 play 时的位置（粘性）
      return;
    }

    const tick = () => {
      const now =
        typeof performance !== "undefined" && typeof performance.now === "function"
          ? performance.now()
          : Date.now();
      if (now - lastTickRef.current < throttleMs) return;
      lastTickRef.current = now;
      const t = audio.currentTime;
      const next = findCurrentWord(subtitlesRef.current, t);
      setPos((prev) => {
        if (
          prev.currentSubtitleIndex === next.currentSubtitleIndex &&
          prev.currentWordIndex === next.currentWordIndex
        ) {
          return prev;
        }
        return next;
      });
    };

    // 初次 mount / 重新 enabled 时同步一次
    tick();

    audio.addEventListener("timeupdate", tick);
    audio.addEventListener("seeked", tick);
    audio.addEventListener("seeking", tick);

    return () => {
      audio.removeEventListener("timeupdate", tick);
      audio.removeEventListener("seeked", tick);
      audio.removeEventListener("seeking", tick);
    };
    // audioRef.current 不进 deps（ref object 稳定）；subtitles 走 ref 避免 re-register
  }, [audioRef, enabled, throttleMs]);

  return pos;
}
