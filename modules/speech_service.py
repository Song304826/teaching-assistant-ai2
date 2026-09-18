from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path


class SpeechServiceError(RuntimeError):
    """语音识别过程中出现的可读错误。"""

    pass


def _get_setting(name: str, default: str = "") -> str:
    """
    优先从Streamlit Secrets读取配置，
    本地运行时再从环境变量或.env文件读取。
    """
    value = ""

    try:
        import streamlit as st

        if name in st.secrets:
            value = str(st.secrets[name])
    except Exception:
        pass

    if not value:
        value = os.getenv(name, default)

    return str(value).strip()


def speech_backend_status() -> tuple[bool, str]:
    """
    判断当前可用的语音识别方式。

    云端部署：优先使用阿里云百炼Paraformer。
    本地运行：没有云端Key时，可以使用本地FunASR。
    """
    mode = _get_setting("SPEECH_MODE", "auto").lower()
    api_key = _get_setting("DASHSCOPE_API_KEY")

    if mode in {"off", "disabled", "none"}:
        return False, "语音识别目前已关闭，仍可使用文字输入"

    if mode in {"auto", "dashscope", "cloud"} and api_key:
        try:
            import dashscope  # noqa: F401
        except ImportError:
            return False, "缺少dashscope依赖，请检查requirements.txt"
        return True, "云端Paraformer语音识别已就绪"

    if mode in {"dashscope", "cloud"} and not api_key:
        return False, "尚未配置DASHSCOPE_API_KEY，请在Streamlit Secrets中填写"

    try:
        import funasr  # noqa: F401
    except ImportError:
        return False, "未配置云端语音Key，本地Paraformer组件也未安装"

    return True, "本地Paraformer语音识别已就绪"


@lru_cache(maxsize=1)
def _load_local_model():
    """加载本地FunASR模型，仅本地模式使用。"""
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise SpeechServiceError(
            "未安装FunASR语音组件，请先安装requirements-voice.txt。"
        ) from exc

    model_name = (
        _get_setting("PARAFORMER_MODEL", "paraformer-zh")
        or "paraformer-zh"
    )

    try:
        return AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            device="cpu",
            disable_update=True,
        )
    except Exception as exc:
        raise SpeechServiceError(
            f"本地Paraformer模型加载失败：{str(exc)[:180]}"
        ) from exc


def _transcribe_with_dashscope(audio_path: str) -> str:
    """使用阿里云百炼Paraformer识别录音。"""
    api_key = _get_setting("DASHSCOPE_API_KEY")

    if not api_key:
        raise SpeechServiceError(
            "没有配置DASHSCOPE_API_KEY，请先在Streamlit Secrets中填写。"
        )

    try:
        import dashscope
        from dashscope.audio.asr import Recognition
    except ImportError as exc:
        raise SpeechServiceError(
            "没有安装dashscope，请检查requirements.txt并重新部署。"
        ) from exc

    dashscope.api_key = api_key

    try:
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            language_hints=["zh", "en"],
            callback=None,
        )

        result = recognition.call(audio_path)

        if result.status_code != HTTPStatus.OK:
            message = getattr(result, "message", "未知服务错误")
            raise SpeechServiceError(
                f"云端语音识别请求失败：{message}"
            )

        sentences = result.get_sentence() or []
        text_parts = []

        if isinstance(sentences, dict):
            sentence_text = str(sentences.get("text", "")).strip()
            if sentence_text:
                text_parts.append(sentence_text)
        else:
            for sentence in sentences:
                if isinstance(sentence, dict):
                    sentence_text = str(
                        sentence.get("text", "")
                    ).strip()
                    if sentence_text:
                        text_parts.append(sentence_text)

        final_text = "".join(text_parts).strip()

        if not final_text:
            raise SpeechServiceError(
                "没有识别出有效文字，请靠近麦克风重新录制。"
            )

        return final_text

    except SpeechServiceError:
        raise
    except Exception as exc:
        raise SpeechServiceError(
            f"云端语音识别失败：{str(exc)[:180]}"
        ) from exc


def _transcribe_with_local_model(audio_path: str) -> str:
    """使用电脑中的本地FunASR模型识别录音。"""
    hotwords = _get_setting(
        "ASR_HOTWORDS",
        (
            "教学目标 教学重点 教学难点 "
            "一元一次方程 移项法则 等式性质 "
            "课件 教案 PPT"
        ),
    )

    try:
        result = _load_local_model().generate(
            input=audio_path,
            batch_size_s=60,
            hotword=hotwords,
        )

        if not result:
            raise SpeechServiceError(
                "没有识别出有效文字，请靠近麦克风重新录制。"
            )

        first_result = result[0]

        if isinstance(first_result, dict):
            text = str(first_result.get("text", "")).strip()
        else:
            text = str(first_result).strip()

        if not text:
            raise SpeechServiceError(
                "没有识别出有效文字，请靠近麦克风重新录制。"
            )

        return text

    except SpeechServiceError:
        raise
    except Exception as exc:
        raise SpeechServiceError(
            f"本地语音识别失败：{str(exc)[:180]}"
        ) from exc


def transcribe_audio(
    data: bytes,
    filename: str = "teacher_recording.wav",
) -> str:
    """
    统一语音识别入口。

    有DashScope Key时优先使用云端Paraformer；
    否则尝试本地FunASR。
    """
    available, message = speech_backend_status()

    if not available:
        raise SpeechServiceError(message)

    if not data:
        raise SpeechServiceError("没有读取到录音内容，请重新录制。")

    if len(data) > 20 * 1024 * 1024:
        raise SpeechServiceError(
            "录音文件超过20MB，请缩短录音后重试。"
        )

    suffix = Path(filename).suffix.lower()

    if suffix not in {".wav", ".mp3", ".aac", ".amr", ".opus"}:
        suffix = ".wav"

    temp_path = ""

    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as handle:
            handle.write(data)
            temp_path = handle.name

        mode = _get_setting("SPEECH_MODE", "auto").lower()
        api_key = _get_setting("DASHSCOPE_API_KEY")

        if mode in {"auto", "dashscope", "cloud"} and api_key:
            return _transcribe_with_dashscope(temp_path)

        return _transcribe_with_local_model(temp_path)

    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
