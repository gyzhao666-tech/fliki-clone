/**
 * Track-26 / L-02 卡拉 OK 字幕高亮 — useAudioCurrentWord 单元测试
 *
 * 用 Node 内置 `node:test` runner，避免引入 jest/vitest dev dep。
 * 直接跑：
 *   node --experimental-strip-types --test src/hooks/__tests__/use-audio-current-word.test.ts
 * 或（更兼容）通过 jiti：
 *   node --import jiti/register --test src/hooks/__tests__/use-audio-current-word.test.ts
 *
 * 覆盖：
 *   1. 空字幕 → (-1, -1)
 *   2. 边界（currentTime < 第一条 start）→ (-1, -1)
 *   3. 边界（currentTime > 最后一条 end）→ (-1, -1)
 *   4. NaN / Infinity currentTime → (-1, -1)
 *   5. 字幕推进 + word 推进 → 单调
 *   6. 字幕条无 words → (subIdx, -1)
 *   7. 字幕条间小 gap → 粘性（不回退）
 *   8. word 间小 gap → 粘性
 *   9. audio.currentTime 读 null/undefined（模拟 audio=null 走 findCurrentWord 入口） → (-1, -1)
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import {
  findCurrentWord,
  type SubtitleWithWords,
} from "../use-audio-current-word";

function mkSubtitle(
  start: number,
  end: number,
  words?: Array<[number, number, string]>,
): SubtitleWithWords {
  return {
    start,
    end,
    text: words?.map(([, , w]) => w).join(" ") ?? "",
    words: words?.map(([s, e, w]) => ({ start: s, end: e, word: w })),
  };
}

const SAMPLE: SubtitleWithWords[] = [
  // 第 0 条：1.0 - 3.0，3 个 word
  mkSubtitle(1.0, 3.0, [
    [1.0, 1.6, "你好"],
    [1.6, 2.2, "世界"],
    [2.2, 3.0, "再见"],
  ]),
  // 第 1 条：3.5 - 5.5（与上一条间有 0.5s gap），2 个 word
  mkSubtitle(3.5, 5.5, [
    [3.5, 4.5, "今天"],
    [4.5, 5.5, "天气"],
  ]),
  // 第 2 条：5.5 - 7.0，没 words（v3 行级场景）
  mkSubtitle(5.5, 7.0),
];

describe("findCurrentWord — 边界与无效输入", () => {
  it("空字幕数组 → (-1, -1)", () => {
    assert.deepEqual(findCurrentWord([], 1.0), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });

  it("subtitles 为 null → (-1, -1)（模拟 audio 为 null / 没字幕）", () => {
    assert.deepEqual(findCurrentWord(null, 1.0), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(undefined, 1.0), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });

  it("currentTime < 第一条 start → (-1, -1)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 0), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, 0.99), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });

  it("currentTime > 最后一条 end → (-1, -1)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 7.01), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, 999), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });

  it("非有限 currentTime（NaN / Infinity）→ (-1, -1)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, NaN), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, Infinity), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, -Infinity), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });
});

describe("findCurrentWord — 命中点常规", () => {
  it("currentTime 正好 = 第一条 start → (0, 0)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 1.0), {
      currentSubtitleIndex: 0,
      currentWordIndex: 0,
    });
  });

  it("第一条字幕中段 → (0, 中间 word)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 1.7), {
      currentSubtitleIndex: 0,
      currentWordIndex: 1,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, 2.5), {
      currentSubtitleIndex: 0,
      currentWordIndex: 2,
    });
  });

  it("第二条字幕 → (1, 对应 word)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 3.5), {
      currentSubtitleIndex: 1,
      currentWordIndex: 0,
    });
    assert.deepEqual(findCurrentWord(SAMPLE, 5.0), {
      currentSubtitleIndex: 1,
      currentWordIndex: 1,
    });
  });

  it("第三条字幕（无 words 数组，v3 行级 fallback）→ (2, -1)", () => {
    assert.deepEqual(findCurrentWord(SAMPLE, 6.0), {
      currentSubtitleIndex: 2,
      currentWordIndex: -1,
    });
  });

  it("字幕条之间 gap（在 SAMPLE[0].end=3.0 与 SAMPLE[1].start=3.5 之间）→ 粘到 SAMPLE[0] 末 word", () => {
    const r = findCurrentWord(SAMPLE, 3.2);
    assert.equal(r.currentSubtitleIndex, 0);
    assert.equal(r.currentWordIndex, 2);
  });
});

describe("findCurrentWord — 单调推进（卡拉 OK 主线）", () => {
  it("audio.currentTime 从 0 → 7.5 推进 → (subIdx, wordIdx) 单调不回退", () => {
    const samples: number[] = [];
    for (let t = 0; t <= 7.5; t += 0.05) {
      samples.push(Math.round(t * 100) / 100);
    }
    let lastSub = -1;
    let lastWord = -1;
    let lastInsideRange = false;
    for (const t of samples) {
      const { currentSubtitleIndex: si, currentWordIndex: wi } = findCurrentWord(
        SAMPLE,
        t,
      );
      const insideRange = si >= 0;
      if (insideRange) {
        if (lastInsideRange) {
          // 在 range 内推进时 (si, wi) 应字典序 ≥ 上一次
          assert.ok(
            si > lastSub || (si === lastSub && wi >= lastWord),
            `t=${t}: (${si},${wi}) 比上次 (${lastSub},${lastWord}) 回退了`,
          );
        }
        lastSub = si;
        lastWord = wi;
      }
      // 边界外（before-first / after-last）允许是 (-1, -1)；
      // 不进入「单调」断言（业务语义就是 boundary 关高亮）
      lastInsideRange = insideRange;
    }
  });

  it("seek 回退（currentTime 突然变小）→ 函数纯返新位置（hook 上层负责粘性，搜索本身不锁定）", () => {
    const a = findCurrentWord(SAMPLE, 5.0); // 第二条字幕中
    assert.equal(a.currentSubtitleIndex, 1);
    const b = findCurrentWord(SAMPLE, 1.5); // seek 回第一条
    assert.equal(b.currentSubtitleIndex, 0);
    assert.equal(b.currentWordIndex, 0);
  });
});

describe("findCurrentWord — 单一字幕场景", () => {
  it("单条字幕 + 单 word → 命中 (0, 0)；外面返 -1", () => {
    const single: SubtitleWithWords[] = [mkSubtitle(2, 4, [[2, 4, "Hi"]])];
    assert.deepEqual(findCurrentWord(single, 3), {
      currentSubtitleIndex: 0,
      currentWordIndex: 0,
    });
    assert.deepEqual(findCurrentWord(single, 1), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
    assert.deepEqual(findCurrentWord(single, 5), {
      currentSubtitleIndex: -1,
      currentWordIndex: -1,
    });
  });

  it("subtitle.words 为空数组 → (subIdx, -1)", () => {
    const arr: SubtitleWithWords[] = [{ start: 0, end: 1, words: [] }];
    assert.deepEqual(findCurrentWord(arr, 0.5), {
      currentSubtitleIndex: 0,
      currentWordIndex: -1,
    });
  });
});
