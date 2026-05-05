"""具体 provider 实现。

每个 provider 文件实现 `BaseProvider` 子类，gateway 在启动时注册。
"""
from .base import BaseProvider
from .faster_whisper_local import FasterWhisperLocalProvider
from .kling import KlingProvider
from .llm import OpenAICompatLLMProvider
from .openai_whisper import OpenAIWhisperProvider
from .siliconflow_asr import SiliconFlowASRProvider
from .siliconflow_image import SiliconFlowImageProvider
from .siliconflow_tts import SiliconFlowTTSProvider
from .siliconflow_video import SiliconFlowVideoProvider

__all__ = [
    "BaseProvider",
    "FasterWhisperLocalProvider",
    "OpenAICompatLLMProvider",
    "OpenAIWhisperProvider",
    "KlingProvider",
    "SiliconFlowASRProvider",
    "SiliconFlowImageProvider",
    "SiliconFlowTTSProvider",
    "SiliconFlowVideoProvider",
]
