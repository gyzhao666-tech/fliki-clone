"""VoiceAgent v4 字幕对齐 + 行级细切 + word-level 强对齐测试。

覆盖
----
1. ``test_split_narration_punctuation_chunks``     按 ``。！？`` / ``，；、`` 切行；硬切兜底
2. ``test_split_narration_merges_short_fragments`` 短碎片（< 0.4*max）合并到下一行
3. ``test_subtitles_v1_fallback``                  无 ASR / 无音频时按 shots.duration_s 均分
4. ``test_subtitles_v3_rescale_proportional``      按字符占比把 audio_duration 分到每镜每行
5. ``test_subtitles_v4_word_aligned_basic``        word 时间戳强对齐 + 边界规整 + 单调性
6. ``test_voice_agent_run_integration_with_mock_gateway``
                                                   端到端 ``VoiceAgent.run()``，mock TTS+ASR

健康降级（words 太少 / asr/origin 字符比例失调）单独抽：
   ``test_v4_falls_back_when_words_sparse``        v4 → v3 自动 fallback
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.voice


# ── 1. 行级切分（_split_narration_into_lines） ──────────────────────────────


@pytest.mark.unit
def test_split_narration_punctuation_chunks():
    """主分隔符（。！？）切多段；超长段再用次分隔符（，；、）切；标点保留在前段末。"""
    from app.services.pipeline.agents.voice import _split_narration_into_lines

    # 三句中文，主分隔符切；用 max_chars=15 让 min_chars=6（每句 7 字 >= 6 → 不触发合并）
    s = "今天天气真好。我去公园散步。傍晚回家做饭。"
    lines = _split_narration_into_lines(s, max_chars=15)
    assert len(lines) == 3, f"主分隔符 3 段切分失败：{lines}"
    assert lines[0].endswith("。")
    assert "今天天气" in lines[0]
    assert "傍晚" in lines[2]

    # 没标点的纯字符串：触发 hard_wrap
    s2 = "abcdefghijklmnopqrstuvwxyz"  # 26 字符
    lines2 = _split_narration_into_lines(s2, max_chars=10)
    # 长度 26 / max 10 = 3 段（10/10/6），可能合并 6 段进上一段（合并阈值 < 4）→ 2 段
    assert len(lines2) >= 2
    assert all(len(line) <= 10 * 1.3 + 1 for line in lines2[:-1]), (
        f"中间段不应大幅超过 max_chars*1.3；实际 {[len(l) for l in lines2]}"
    )

    # 空字符串 / 纯空白 → 空 list
    assert _split_narration_into_lines("", max_chars=20) == []
    assert _split_narration_into_lines("   ", max_chars=20) == []


@pytest.mark.unit
def test_split_narration_merges_short_fragments():
    """碎片 < 0.4*max 合并到上一行；避免「一字一条」。"""
    from app.services.pipeline.agents.voice import _split_narration_into_lines

    # 用大量短句，每句 1-3 字，最末段超短应被合并
    s = "好。是。对。可以的。" + "确认无误。"
    lines = _split_narration_into_lines(s, max_chars=20)
    # 5 个原始片段；合并后至少 < 5（短碎片合并），但 >=1
    assert 1 <= len(lines) <= 5
    # 合并行不会出现长度低于 min_chars 的孤立短行（除非全段就一行）
    if len(lines) > 1:
        min_chars = max(4, int(20 * 0.4))
        # 最后一行可能被合并放下；检查除最后外没有过短行
        for line in lines[:-1]:
            assert len(line) >= min_chars or line == lines[0], (
                f"短碎片应被合并；实际 {lines}"
            )


# ── 2. v1 / v3 / v4 算法 ────────────────────────────────────────────────────


@pytest.mark.unit
def test_subtitles_v1_fallback():
    """无音频时走 v1：按 shots.duration_s 累加，每镜 1 条字幕。"""
    from app.services.pipeline.agents.voice import _build_subtitles_v1

    shots = [
        {"index": 1, "duration_s": 3.0, "narration": "首镜旁白。"},
        {"index": 2, "duration_s": 2.5, "narration": "次镜旁白。"},
        {"index": 3, "duration_s": 4.0, "narration": "末镜旁白。"},
    ]
    subs, total = _build_subtitles_v1(shots, full_text="首镜旁白。次镜旁白。末镜旁白。")
    assert total == pytest.approx(9.5, abs=0.01)
    assert len(subs) == 3
    assert subs[0]["start"] == 0.0
    assert subs[0]["end"] == pytest.approx(3.0, abs=0.01)
    assert subs[1]["start"] == pytest.approx(3.0, abs=0.01)
    assert subs[2]["end"] == pytest.approx(9.5, abs=0.01)
    # 每条都带 shot_index
    assert all("shot_index" in s for s in subs)


@pytest.mark.unit
def test_subtitles_v3_rescale_proportional():
    """v3：按字符占比把 audio_duration 分到每镜，再在镜内按行字符占比再分。

    构造：3 镜，narration 长度 10/20/30 字符，audio_duration=12s。
    期望：shot 时长比 ~ 1:2:3 → 2/4/6s（最末段对齐到 12s）。
    """
    from app.services.pipeline.agents.voice import _rescale_subtitles_v3

    shots = [
        {"index": 1, "narration": "1234567890"},
        {"index": 2, "narration": "12345678901234567890"},
        {"index": 3, "narration": "123456789012345678901234567890"},
    ]
    subs, lines_per_shot = _rescale_subtitles_v3(
        shots, audio_duration_s=12.0, max_chars_per_line=40
    )
    # 由于每段都 <= max_chars，每镜应该 1 行（不会再切）
    assert lines_per_shot == [1, 1, 1]
    assert len(subs) == 3
    # 时间分配比例（容忍 0.1s 浮点误差）
    assert subs[0]["start"] == 0.0
    assert subs[0]["end"] == pytest.approx(2.0, abs=0.1)
    assert subs[1]["start"] == pytest.approx(2.0, abs=0.1)
    assert subs[1]["end"] == pytest.approx(6.0, abs=0.1)
    assert subs[2]["end"] == pytest.approx(12.0, abs=0.001), (
        "最末段必须严格对齐到 audio_duration"
    )


@pytest.mark.unit
def test_subtitles_v4_word_aligned_basic():
    """v4：word-level 强对齐 —— 用真实 word 时间戳替换字符比例估算。

    构造：1 镜 narration="hello brave new world today is sunny"；ASR words 给 7 个；
         audio_duration=7.0；max_chars=40（保证不切多行）
    期望：1 条字幕 start=0（边界规整）, end=7.0（边界规整）, words 列表 7 项
    """
    from app.services.pipeline.agents.voice import _build_subtitles_v4_word_aligned

    shots = [{"index": 1, "narration": "hello brave new world today is sunny"}]
    words = [
        {"word": "hello ", "start": 0.0, "end": 0.5},
        {"word": "brave ", "start": 0.6, "end": 1.5},
        {"word": "new ", "start": 1.6, "end": 2.0},
        {"word": "world ", "start": 2.1, "end": 3.0},
        {"word": "today ", "start": 3.1, "end": 4.0},
        {"word": "is ", "start": 4.1, "end": 5.0},
        {"word": "sunny", "start": 5.1, "end": 7.0},
    ]
    subs, lines_per_shot = _build_subtitles_v4_word_aligned(
        shots=shots, words=words, audio_duration_s=7.0, max_chars_per_line=80
    )
    assert lines_per_shot == [1]
    assert len(subs) == 1
    sub = subs[0]
    assert sub["start"] == 0.0  # 边界规整
    assert sub["end"] == pytest.approx(7.0, abs=0.001)  # 边界规整
    assert len(sub["words"]) == 7
    assert sub["words"][0]["word"].strip() == "hello"
    assert sub["text"] == "hello brave new world today is sunny"
    assert sub["shot_index"] == 1


@pytest.mark.unit
def test_v4_falls_back_when_words_sparse():
    """v4 健康检查：words 太少（< lines/2 且 < 5）→ 返 [] 让 caller 降级。

    以及 asr_text 与 origin_text 字符比例严重失调（< 0.4 或 > 2.5）也降级。
    """
    from app.services.pipeline.agents.voice import _build_subtitles_v4_word_aligned

    shots = [
        {"index": i + 1, "narration": "abcdefghij"} for i in range(20)
    ]  # 20 镜，20 行
    sparse_words = [
        {"word": "x", "start": 0.0, "end": 1.0},
        {"word": "y", "start": 1.0, "end": 2.0},
    ]
    subs, _ = _build_subtitles_v4_word_aligned(
        shots=shots,
        words=sparse_words,
        audio_duration_s=20.0,
        max_chars_per_line=10,
    )
    assert subs == [], "words=2 < lines/2(10) 且 < 5；应早退降级"

    # 字符比例失调（asr_text 总长度只有 origin 的 5%）：origin=200 字符，asr=10 字符
    very_short_words = [
        {"word": "x", "start": float(i), "end": float(i) + 0.1} for i in range(10)
    ]
    subs2, _ = _build_subtitles_v4_word_aligned(
        shots=shots,
        words=very_short_words,
        audio_duration_s=20.0,
        max_chars_per_line=10,
    )
    assert subs2 == [], "asr_total/origin_total = 10/200 = 0.05 < 0.4；应降级"


# ── 3. VoiceAgent.run() 集成（mock gateway） ────────────────────────────────


@pytest.mark.unit
def test_voice_agent_run_integration_with_mock_gateway(patch_gateway, fake_gateway):
    """端到端 ``VoiceAgent.run()`` 走 v4 路径：
    1. mock TTS 返一段 fake mp3 bytes
    2. mock ASR 返带 word-level 的结果（duration_s + words）
    3. 检查 outputs：subtitles 非空 / aligned=True / subtitle_granularity in ('word','line','shot')
       / asr_provider 与 mock 对齐 / cost_usd > 0

    这个 case 把 v4 算法 + agent 装配链路串起来；如果 ASR 或 TTS 任一改了
    输出 schema 都会立刻挂。
    """
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )
    from app.services.pipeline.agents.voice import VoiceAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        # TTS 响应
        RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.SILICONFLOW,
            model="cosyvoice-mock",
            output={"audio_bytes": b"\x00" * 1024, "voice": "alloy-mock"},
            cost_usd=0.005,
        ),
        # ASR 响应（带 word-level，让 v4 路径触发）
        RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.OPENAI,
            model="whisper-1-mock",
            output={
                "duration_s": 6.0,
                "segments": [],
                "words": [
                    {"word": "今天", "start": 0.0, "end": 1.0},
                    {"word": "天气", "start": 1.1, "end": 2.0},
                    {"word": "真好", "start": 2.1, "end": 3.0},
                    {"word": "我去", "start": 3.2, "end": 4.0},
                    {"word": "公园", "start": 4.1, "end": 5.0},
                    {"word": "散步", "start": 5.1, "end": 6.0},
                ],
            },
            cost_usd=0.001,
        ),
    )

    ctx = make_ctx(
        inputs={"brief": {"voice_speed": 1.0, "subtitle_max_chars": 20}},
        upstream={
            "script": {
                "script": "今天天气真好。我去公园散步。",
                "shots": [
                    {"index": 1, "duration_s": 3.0, "narration": "今天天气真好。"},
                    {"index": 2, "duration_s": 3.0, "narration": "我去公园散步。"},
                ],
            }
        },
    )

    result = VoiceAgent().run(ctx)
    out = result.outputs

    # 关键 assert：v4 路径走通
    # 注意：当前 agent 把 asr_words_count / subtitle_alignment_quality 留在 align_info
    # 内部没向外暴露；只检查实际 outputs 字段（NOTES.md 已记录此 expose gap）。
    assert result.status.value == "succeeded"
    assert out["asr_provider"] == "openai"
    assert out["asr_model"] == "whisper-1-mock"
    assert out["aligned"] is True
    assert out["audio_duration_s"] == pytest.approx(6.0, abs=0.001)
    assert out["subtitle_granularity"] == "word", (
        f"6 words 覆盖到 audio_dur*0.7 应进 v4；实际 {out['subtitle_granularity']}"
    )
    assert len(out["subtitles"]) >= 2
    assert out["subtitles"][0]["start"] == 0.0
    assert out["subtitles"][-1]["end"] == pytest.approx(6.0, abs=0.001)
    # word 字段携带（前端卡拉 OK 高亮依赖）
    assert any("words" in s and len(s["words"]) > 0 for s in out["subtitles"])
    # alignment_source 应是 asr（mock ASR 返了 duration_s，没走 ffprobe 兜底）
    assert out["alignment_source"] == "asr"

    # 调用顺序：TTS 先，然后 ASR
    assert len(fake_gateway.calls) == 2
    assert fake_gateway.calls[0].action == "tts"
    assert fake_gateway.calls[1].action == "asr"

    # 成本 = TTS + ASR cost（gateway 侧并未真扣，但 agent.cost_usd 应聚合）
    assert result.cost_usd == pytest.approx(0.005 + 0.001, abs=0.0001)
