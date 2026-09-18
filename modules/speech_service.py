from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path


class SpeechServiceError(RuntimeError):
    pass


def speech_backend_status() -> tuple[bool, str]:
    mode = os.getenv("SPEECH_MODE", "paraformer").strip().lower()
    if mode in {"off", "disabled", "none"}:
        return False, "服务器未启用语音识别，仍可使用文字输入"
    try:
        import funasr  # noqa: F401
    except ImportError:
        return False, "未安装本地语音组件，请按说明安装 requirements-voice.txt"
    return True, "Paraformer 本地语音识别已就绪"


@lru_cache(maxsize=1)
def _load_model():
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise SpeechServiceError("未安装FunASR语音组件，请先安装 requirements-voice.txt。") from exc

    model_name = os.getenv("PARAFORMER_MODEL", "paraformer-zh").strip() or "paraformer-zh"
    try:
        return AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device="cpu",
            disable_update=True,
        )
    except Exception as exc:
        raise SpeechServiceError(f"Paraformer模型加载失败：{str(exc)[:180]}") from exc


def transcribe_audio(data: bytes, filename: str = "teacher_recording.wav") -> str:
    available, message = speech_backend_status()
    if not available:
        raise SpeechServiceError(message)
    if not data:
        raise SpeechServiceError("没有读取到录音内容，请重新录制。")
    if len(data) > 50 * 1024 * 1024:
        raise SpeechServiceError("录音文件超过50MB，请缩短录音后重试。")

    suffix = Path(filename).suffix.lower() or ".wav"
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data)
            temp_path = handle.name
        hotwords = os.getenv(
            "ASR_HOTWORDS",
            "教学目标 教学重点 教学难点 一元一次方程 移项法则 等式性质 课件 教案 PPT",
        )
        result = _load_model().generate(
            input=temp_path,
            batch_size_s=60,
            hotword=hotwords,
        )
        if not result:
            raise SpeechServiceError("没有识别出有效文字，请靠近麦克风重新录制。")
        text = str(result[0].get("text", "") if isinstance(result[0], dict) else result[0]).strip()
        if not text:
            raise SpeechServiceError("没有识别出有效文字，请靠近麦克风重新录制。")
        return text
    except SpeechServiceError:
        raise
    except Exception as exc:
        raise SpeechServiceError(f"语音识别失败：{str(exc)[:180]}") from exc
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
