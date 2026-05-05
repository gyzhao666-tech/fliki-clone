"""把目标时长拆成若干"模型友好"的子段。

可灵 v1.x 常见档位为 5 / 10 秒；v3.x 等新模型支持 15 秒及以上。
拆段策略：
- 优先选大档位（减少调用次数）
- 剩余不足最小档位时仍按最小档位发起调用（实际生成时长会略长，业务侧可裁切）
"""
from __future__ import annotations


def split_to_sub_segments(prompt: str, total_duration: float, max_duration: int) -> list[dict]:
    cap = max(5, int(max_duration))
    allowed: list[int] = [5, 10]
    if cap >= 15:
        allowed.append(15)
    allowed = [d for d in allowed if d <= cap]
    if not allowed:
        allowed = [5]

    segments: list[dict] = []
    remaining = float(total_duration)
    while remaining > 1e-3:
        fits = [d for d in allowed if d <= remaining + 1e-6]
        dur = max(fits) if fits else min(allowed)
        segments.append({"prompt": prompt, "duration": int(dur)})
        remaining -= dur
    return segments
