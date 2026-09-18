from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
import hashlib
import json
import zipfile

import streamlit as st

from modules.ai_service import (
    AIServiceError,
    ai_is_configured,
    generate_lesson_plan,
    interview,
    revise_lesson_plan,
)
from modules.exporters import (
    create_lesson_docx,
    create_lesson_pptx,
    create_student_handout_docx,
    create_teacher_handout_docx,
    safe_filename,
)
from modules.knowledge_base import KnowledgeChunk, LocalKnowledgeBase, parse_uploaded_document
from modules.game_manager import GamePluginError, choose_game, discover_games, load_game_renderer
from modules.speech_service import SpeechServiceError, speech_backend_status, transcribe_audio
from modules.theme import get_premium_css


st.set_page_config(
    page_title="课研助手",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    :root {
        --ink: #172033;
        --muted: #657086;
        --line: #dfe6f0;
        --blue: #2457d6;
        --blue-soft: #edf3ff;
        --green: #178763;
        --surface: #ffffff;
    }
    .stApp { background: #f5f7fb; color: var(--ink); }
    [data-testid="stSidebar"] { background: #111a2e; }
    [data-testid="stSidebar"] * { color: #eef3ff; }
    [data-testid="stSidebar"] hr { border-color: #2a3650; }
    .block-container { max-width: 1500px; padding-top: 1.35rem; }
    .app-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 1rem 1.2rem; margin-bottom: 1rem; background: var(--surface);
        border: 1px solid var(--line); border-radius: 16px;
        box-shadow: 0 8px 24px rgba(31, 45, 78, .06);
    }
    .app-title { font-size: 1.55rem; font-weight: 760; letter-spacing: -.02em; }
    .app-subtitle { color: var(--muted); font-size: .92rem; margin-top: .2rem; }
    .status-pill {
        color: #12684d; background: #e8f7f1; border: 1px solid #bde8d8;
        border-radius: 999px; padding: .42rem .72rem; font-size: .85rem;
    }
    .panel {
        background: var(--surface); border: 1px solid var(--line);
        border-radius: 16px; padding: 1.1rem 1.15rem; margin-bottom: .8rem;
        box-shadow: 0 8px 24px rgba(31, 45, 78, .045);
    }
    .panel-title { font-weight: 720; font-size: 1rem; margin-bottom: .7rem; }
    .field-row {
        display: grid; grid-template-columns: 110px 1fr; gap: .6rem;
        padding: .52rem 0; border-bottom: 1px solid #eef1f6; font-size: .92rem;
    }
    .field-row:last-child { border-bottom: 0; }
    .field-label { color: var(--muted); }
    .field-value { color: var(--ink); font-weight: 560; }
    .source-item {
        padding: .75rem .85rem; margin: .55rem 0; background: #f8faff;
        border: 1px solid #e1e8f6; border-radius: 12px;
    }
    .source-name { font-weight: 650; color: #23385f; }
    .source-meta { color: var(--muted); font-size: .82rem; margin-top: .18rem; }
    .skeleton-note {
        padding: .72rem .85rem; background: #fff8e8; color: #7a5710;
        border: 1px solid #f2d896; border-radius: 12px; font-size: .9rem;
    }
    .slide-card {
        min-height: 180px; background: linear-gradient(135deg, #153a98, #2d68dd);
        color: white; border-radius: 14px; padding: 1.3rem;
        display: flex; flex-direction: column; justify-content: space-between;
    }
    .slide-kicker { font-size: .8rem; opacity: .75; }
    .slide-title { font-size: 1.35rem; font-weight: 760; }
    .slide-copy { font-size: .88rem; opacity: .9; }
    .step-current { color: #ffffff; font-weight: 720; }
    .step-done { color: #93ddc5; }
    .step-wait { color: #8f9bb3; }
    div[data-testid="stButton"] button { border-radius: 10px; font-weight: 650; }
    div[data-testid="stFileUploader"] { background: #fff; border-radius: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.display_theme = "浅色"
st.markdown(get_premium_css("浅色"), unsafe_allow_html=True)


DEFAULT_REQUIREMENTS = {
    "学科年级": "七年级数学",
    "教材版本": "待确认",
    "课题": "一元一次方程",
    "课时时长": "待确认",
    "教学目标": "待AI访谈后生成",
    "教学重点": "待AI访谈后生成",
    "教学难点": "待AI访谈后生成",
    "学生学情": "待确认",
    "互动与风格": "待确认",
    "教学顺序": "先理论后例题",
    "PPT覆盖时长": "35分钟",
    "PPT期望页数": "12页",
    "PPT详细程度": "丰富",
    "PPT视觉风格": "科技蓝",
    "跨学科融合": "不启用",
    "跨学科呈现方式": "AI自动选择",
}

PROJECT_ROOT = Path(__file__).resolve().parent


@st.cache_resource(show_spinner="正在建立本地知识库索引……")
def load_knowledge_base() -> LocalKnowledgeBase:
    return LocalKnowledgeBase(PROJECT_ROOT / "knowledge_base")


def init_state() -> None:
    st.session_state.setdefault("step", 1)
    st.session_state.setdefault(
        "messages",
        [
            {
                "role": "assistant",
                "content": "您好，我是课研助手。请先告诉我课题、年级，并在上方选择您希望“先理论还是先例题”。",
            }
        ],
    )
    st.session_state.setdefault("requirements", DEFAULT_REQUIREMENTS.copy())
    st.session_state.setdefault("draft_ready", False)
    st.session_state.setdefault("kb_results", [])
    st.session_state.setdefault("interview_ready", False)
    st.session_state.setdefault("api_error", "")
    st.session_state.setdefault("generated_plan", None)
    st.session_state.setdefault("show_game", False)
    st.session_state.setdefault("revision_text", "")
    st.session_state.setdefault("revision_count", 0)
    st.session_state.setdefault("kb_query", "移项法则有哪些易错点？如何设计课堂互动？")
    st.session_state.setdefault("uploaded_chunks", [])
    st.session_state.setdefault("uploaded_files", [])
    st.session_state.setdefault("processed_upload_hashes", [])
    st.session_state.setdefault("teaching_order", "先理论后例题")
    st.session_state.setdefault("custom_order", "")
    st.session_state.setdefault("total_minutes", 45)
    st.session_state.setdefault("ppt_minutes", 35)
    st.session_state.setdefault("ppt_pages", 12)
    st.session_state.setdefault("ppt_detail", "丰富")
    st.session_state.setdefault("ppt_style", "科技蓝")
    st.session_state.setdefault("fusion_subjects", [])
    st.session_state.setdefault("fusion_mode", "AI自动选择")
    st.session_state.setdefault("voice_transcript", "")
    st.session_state.setdefault("voice_audio_hash", "")
    st.session_state.setdefault("export_bundle", {})
    st.session_state.setdefault("show_guide", True)


def goto(step: int) -> None:
    st.session_state.step = max(1, min(4, step))


def submit_interview_message(text: str) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    st.session_state.messages.append({"role": "user", "content": cleaned})
    try:
        reply, requirements, ready = interview(
            st.session_state.messages,
            st.session_state.requirements,
        )
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.session_state.requirements = requirements
        st.session_state.interview_ready = ready
        st.session_state.api_error = ""
    except AIServiceError as exc:
        st.session_state.api_error = str(exc)


def build_export_bundle(plan: dict) -> dict[str, bytes]:
    requirements = st.session_state.requirements
    return {
        "pptx": create_lesson_pptx(plan, requirements),
        "lesson_docx": create_lesson_docx(plan, requirements),
        "teacher_docx": create_teacher_handout_docx(plan, requirements),
        "student_docx": create_student_handout_docx(plan, requirements),
    }


def render_page_intro(eyebrow: str, title: str, subtitle: str, badge: str) -> None:
    st.markdown(
        f"""
        <div class="page-intro">
          <div>
            <div class="page-eyebrow">{escape(eyebrow)}</div>
            <div class="page-title">{escape(title)}</div>
            <div class="page-subtitle">{escape(subtitle)}</div>
          </div>
          <div class="mini-badge">{escape(badge)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_cards(items: list[tuple[str, str]], accents: list[str] | None = None) -> None:
    accents = accents or ["blue", "cyan", "violet"]
    cards = "".join(
        f'<div class="stat-card stat-accent-{accents[index % len(accents)]}">'
        f'<div class="stat-label">{escape(label)}</div><div class="stat-value">{escape(value)}</div></div>'
        for index, (label, value) in enumerate(items)
    )
    st.markdown(f'<div class="stat-grid">{cards}</div>', unsafe_allow_html=True)


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand-block"><div class="brand-mark">✦</div>'
            '<div class="brand-title">课研助手</div>'
            '<div class="brand-sub">AI LESSON DESIGN STUDIO</div></div>',
            unsafe_allow_html=True,
        )
        progress = st.session_state.step / 4 * 100
        st.markdown(
            f'<div class="side-progress"><span style="width:{progress:.0f}%"></span></div>',
            unsafe_allow_html=True,
        )
        labels = [
            ("教学需求", "访谈"),
            ("资料与知识库", "检索"),
            ("课件生成", "创作"),
            ("修改与下载", "交付"),
        ]
        for index, (label, short) in enumerate(labels, start=1):
            if index < st.session_state.step:
                css_class, mark = "done", "✓"
            elif index == st.session_state.step:
                css_class, mark = "active", f"{index:02d}"
            else:
                css_class, mark = "", f"{index:02d}"
            st.markdown(
                f'<div class="step-card {css_class}"><div class="step-index">{mark}</div>'
                f'<div><div class="step-name">{label}</div><div style="font-size:.65rem;opacity:.55">{short}</div></div></div>',
                unsafe_allow_html=True,
            )
        st.divider()
        st.caption("COMPETITION EDITION · V4.0")
        st.caption(f"会话日期 · {datetime.now():%Y-%m-%d}")
        st.caption("显示模式 · 浅色（已固定，避免设备主题造成文字不可见）")
        if st.button("查看使用说明", use_container_width=True):
            st.session_state.show_guide = True
        if st.button("重新开始本次备课", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def render_header() -> None:
    if ai_is_configured():
        status = "● AI 引擎在线"
    else:
        status = "● 等待配置密钥"
    st.markdown(
        f"""
        <div class="app-header">
          <div class="hero-copy">
            <div class="app-kicker">INTELLIGENT COURSE CREATION</div>
            <div class="app-title">智能备课工作台</div>
            <div class="app-subtitle">理解教师意图 · 检索可信资料 · 生成可修改的课堂方案</div>
          </div>
          <div class="hero-side">
            <div class="status-pill">{status}</div>
            <div class="hero-meta"><span class="hero-chip">RAG 知识检索</span><span class="hero-chip">多轮访谈</span><span class="hero-chip">文件导出</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_requirements_card() -> None:
    requirements = st.session_state.requirements
    done_count = sum(1 for value in requirements.values() if "待" not in str(value))
    percentage = done_count / len(requirements) * 100
    rows = ""
    for key, value in requirements.items():
        completed = "待" not in str(value)
        rows += (
            f'<div class="field-row"><div class="field-label">{escape(str(key))}</div>'
            f'<div class="field-value">{escape(str(value))}</div>'
            f'<div class="field-dot {"done" if completed else ""}"></div></div>'
        )
    st.markdown(
        f'<div class="panel"><div class="panel-kicker">LIVE BRIEF</div>'
        f'<div class="panel-title">课程需求画像 <span style="float:right;color:#6b7892;font-size:.72rem;font-weight:600">{done_count}/{len(requirements)} 已确认</span></div>'
        f'<div class="requirement-progress"><span style="width:{percentage:.0f}%"></span></div>{rows}</div>',
        unsafe_allow_html=True,
    )


def render_usage_guide() -> None:
    cards = [
        ("01", "描述需求", "告诉AI课题、年级和学生情况"),
        ("02", "选择偏好", "确认教学顺序、时长、页数与风格"),
        ("03", "检索资料", "上传或检索知识库，核对引用来源"),
        ("04", "生成交付", "修改后下载PPT、教案和两份讲义"),
    ]
    html = "".join(
        f'<div class="guide-card"><div class="guide-number">{number}</div><div class="guide-title">{title}</div><div class="guide-copy">{copy}</div></div>'
        for number, title, copy in cards
    )
    st.markdown('<div class="panel-kicker">首次使用说明</div><div class="guide-grid">' + html + "</div>", unsafe_allow_html=True)
    if st.session_state.show_guide:
        st.info("第一次使用：先描述课程需求并确认教学偏好，再检索资料，最后生成、修改并下载课件。语音不可用时可随时改用文字，不影响其他功能。")
        if st.button("我知道了，收起说明", key="dismiss_guide"):
            st.session_state.show_guide = False
            st.rerun()


def _fusion_suggestion() -> list[str]:
    text = str(st.session_state.requirements.get("课题", ""))
    if any(word in text for word in ("方程", "函数", "几何", "数学")):
        return ["语文", "数学史"]
    if any(word in text for word in ("古诗", "文言", "语文")):
        return ["历史", "艺术"]
    if any(word in text for word in ("物理", "化学", "生物", "科学")):
        return ["数学", "信息科技"]
    return ["历史", "生活实践"]


def _accept_fusion_suggestion() -> None:
    st.session_state.fusion_subjects = _fusion_suggestion()


def render_teaching_preferences() -> None:
    st.markdown('<div class="panel-kicker">LESSON CONTROLS</div><div class="panel-title">先确认教学节奏与课件偏好</div>', unsafe_allow_html=True)
    with st.expander("展开/收起教学设置", expanded=True):
        first, second, third = st.columns(3)
        with first:
            order = st.selectbox(
                "教学顺序",
                ["先理论后例题", "先例题后总结理论", "问题探究与例题穿插", "自定义"],
                key="teaching_order",
            )
            custom_order = ""
            if order == "自定义":
                custom_order = st.text_input("自定义教学顺序", key="custom_order")
            total = st.number_input("整节课时长（分钟）", min_value=10, max_value=180, step=5, key="total_minutes")
        with second:
            ppt_minutes = st.number_input("PPT覆盖时长（分钟）", min_value=5, max_value=180, step=5, key="ppt_minutes")
            pages = st.slider("期望PPT页数", min_value=6, max_value=24, key="ppt_pages")
            detail = st.select_slider("内容详细程度", ["精简", "标准", "丰富"], key="ppt_detail")
        with third:
            style = st.selectbox("PPT视觉风格", ["科技蓝", "活力暖色", "清新自然", "简约学术"], key="ppt_style")
            suggestion = "、".join(_fusion_suggestion())
            st.caption(f"AI跨学科建议：{suggestion}。采用后仍由教师确认。")
            st.button("采用AI融合建议", on_click=_accept_fusion_suggestion, use_container_width=True)
            subjects = st.multiselect(
                "跨学科融合（可不选）",
                ["语文", "数学", "数学史", "历史", "地理", "科学", "艺术", "信息科技", "劳动教育", "生活实践"],
                key="fusion_subjects",
            )
            fusion_mode = st.selectbox(
                "融合呈现方式",
                ["AI自动选择", "故事或古文导入", "历史发展线索", "生活案例", "课堂探究任务", "课后拓展"],
                key="fusion_mode",
            )
    requirements = st.session_state.requirements
    requirements["教学顺序"] = custom_order.strip() if order == "自定义" and custom_order.strip() else order
    requirements["课时时长"] = f"{int(total)}分钟"
    requirements["PPT覆盖时长"] = f"{int(ppt_minutes)}分钟"
    requirements["PPT期望页数"] = f"{int(pages)}页"
    requirements["PPT详细程度"] = detail
    requirements["PPT视觉风格"] = style
    requirements["跨学科融合"] = "、".join(subjects) if subjects else "不启用"
    requirements["跨学科呈现方式"] = fusion_mode
    st.markdown(
        f'<div class="fusion-banner">当前设置：{escape(requirements["教学顺序"])} · PPT {int(pages)}页/{escape(detail)} · {escape(style)} · 跨学科：{escape(requirements["跨学科融合"])}</div>',
        unsafe_allow_html=True,
    )


def render_step_one() -> None:
    confirmed = sum(1 for value in st.session_state.requirements.values() if "待" not in str(value))
    render_page_intro(
        "STEP 01 · INTENT INTERVIEW",
        "先理解老师，再开始生成",
        "AI每轮只追问关键问题，把模糊想法整理成可执行的课堂方案。",
        "实时需求画像",
    )
    render_stat_cards(
        [
            ("已完成访谈", f"{sum(m['role'] == 'user' for m in st.session_state.messages)} 轮"),
            ("需求完整度", f"{confirmed}/{len(st.session_state.requirements)} 项"),
            ("AI工作状态", "在线协作" if ai_is_configured() else "等待配置"),
        ]
    )
    render_usage_guide()
    render_teaching_preferences()
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        st.markdown('<div class="panel-kicker">AI COPILOT</div><div class="panel-title">与课研助手沟通</div>', unsafe_allow_html=True)
        st.caption("用日常语言描述即可，系统会主动澄清年级、学情、教学重点和课堂风格。")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        prompt = st.chat_input("例如：我要讲一元一次方程的移项法则……")
        if prompt:
            with st.spinner("课研助手正在理解您的需求……"):
                submit_interview_message(prompt)
            st.rerun()

        if st.session_state.api_error:
            st.error(st.session_state.api_error)

        audio_input = getattr(st, "audio_input", None)
        if audio_input:
            available, speech_message = speech_backend_status()
            recorded_audio = audio_input("语音描述教学想法")
            st.caption(speech_message)
            if recorded_audio is not None:
                audio_bytes = recorded_audio.getvalue()
                audio_hash = hashlib.sha256(audio_bytes).hexdigest()
                if available and st.button("将录音转换为文字", use_container_width=True):
                    try:
                        with st.spinner("Paraformer正在本地识别语音，请稍候……"):
                            st.session_state.voice_transcript = transcribe_audio(
                                audio_bytes,
                                getattr(recorded_audio, "name", "teacher_recording.wav"),
                            )
                            st.session_state.voice_audio_hash = audio_hash
                    except SpeechServiceError as exc:
                        st.error(str(exc))
            voice_text = st.text_area(
                "语音识别结果（发送前可以修改）",
                key="voice_transcript",
                placeholder="识别出的文字会显示在这里……",
            )
            if st.button(
                "把识别文字发送给课研助手",
                type="primary",
                use_container_width=True,
                disabled=not voice_text.strip() or not ai_is_configured(),
            ):
                with st.spinner("课研助手正在理解您的语音需求……"):
                    submit_interview_message(voice_text)
                st.session_state.voice_transcript = ""
                st.rerun()
        else:
            st.caption("当前环境升级Streamlit后可显示语音录入组件。")

    with right:
        render_requirements_card()
        if ai_is_configured():
            note = "DeepSeek 正在实时理解对话，右侧课程画像会随访谈自动更新。"
        else:
            note = "尚未检测到密钥。请按 README 将 .env.example 复制为 .env 并填写密钥。"
        st.markdown(f'<div class="skeleton-note">{note}</div>', unsafe_allow_html=True)
        st.write("")
        if st.button(
            "进入资料与知识库",
            type="primary",
            use_container_width=True,
            disabled=not ai_is_configured(),
        ):
            goto(2)
            st.rerun()


def render_step_two() -> None:
    knowledge_base = load_knowledge_base()
    uploaded_chunks: list[KnowledgeChunk] = st.session_state.uploaded_chunks
    render_page_intro(
        "STEP 02 · KNOWLEDGE GROUNDING",
        "让每一页内容都有资料依据",
        "从本地教学资料中检索相关片段，减少空泛生成，并保留来源说明。",
        "本地隐私检索",
    )
    render_stat_cards(
        [
            ("知识文档", f"{knowledge_base.document_count} 份"),
            ("可检索片段", f"{len(knowledge_base.chunks) + len(uploaded_chunks)} 条"),
            ("本次新增", f"{len(st.session_state.uploaded_files)} 份"),
        ]
    )
    sync_left, sync_right = st.columns([1, 2.4])
    with sync_left:
        if st.button("↻ 同步团队知识库", use_container_width=True):
            load_knowledge_base.clear()
            refreshed = load_knowledge_base()
            report = refreshed.last_sync_report
            st.session_state.kb_sync_message = (
                f"同步完成：新增{report.added}份，更新{report.updated}份，"
                f"未变化{report.unchanged}份，失败{report.failed}份。"
            )
            st.rerun()
    with sync_right:
        
    if st.session_state.get("kb_sync_message"):
        st.success(st.session_state.pop("kb_sync_message"))
    upload_col, source_col = st.columns([.92, 1.35], gap="large")
    with upload_col:
        st.markdown('<div class="panel-kicker">SOURCE INBOX</div><div class="panel-title">添加本次备课资料</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="format-chips"><span class="format-chip">PDF</span><span class="format-chip">DOCX</span>'
            '<span class="format-chip">PPTX</span><span class="format-chip">真实文字解析</span></div>',
            unsafe_allow_html=True,
        )
        category = st.selectbox("资料所属学科", ["数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "道德与法治", "艺术", "跨学科", "综合资料"])
        files = st.file_uploader(
            "拖入参考资料或点击选择",
            type=["pdf", "docx", "pptx", "txt", "md"],
            accept_multiple_files=True,
        )
        if st.button("解析并加入本次知识库", type="primary", use_container_width=True, disabled=not files):
            added = 0
            for file in files or []:
                data = file.getvalue()
                digest = hashlib.sha256(data).hexdigest()
                if digest in st.session_state.processed_upload_hashes:
                    continue
                try:
                    chunks = parse_uploaded_document(file.name, data, category)
                    st.session_state.uploaded_chunks.extend(chunks)
                    st.session_state.uploaded_files.append({"name": file.name, "data": data, "category": category, "chunks": len(chunks)})
                    st.session_state.processed_upload_hashes.append(digest)
                    added += 1
                except Exception as exc:
                    st.error(f"{file.name} 解析失败：{str(exc)[:120]}")
            if added:
                st.success(f"已将 {added} 份资料加入本次检索。")
                st.rerun()
        if st.session_state.uploaded_files:
            for item in st.session_state.uploaded_files:
                st.success(f"已解析 · {item['name']} · {item['chunks']} 个片段")
            review_buffer = BytesIO()
            with zipfile.ZipFile(review_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                manifest = []
                for item in st.session_state.uploaded_files:
                    archive.writestr(f"documents/{item['name']}", item["data"])
                    manifest.append({"filename": item["name"], "category": item["category"], "chunks": item["chunks"]})
                archive.writestr("upload_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            st.download_button("下载知识库收录审核包", review_buffer.getvalue(), "待审核知识库资料.zip", "application/zip", use_container_width=True)
            st.caption("上传资料已立即参与本次生成。云端免费部署重启后本地文件会丢失，因此请下载审核包，由管理员核验后放入 knowledge_base/documents 实现长期收录。")
        st.markdown(
            '<div class="source-item"><div class="source-name">🔒 本地知识库已就绪</div>'
            f'<div class="source-meta">{knowledge_base.document_count} 份筛选文档 · {len(knowledge_base.chunks)} 个内容片段 · 不上传外部平台</div></div>',
            unsafe_allow_html=True,
        )
    with source_col:
        st.markdown('<div class="panel-kicker">SMART RETRIEVAL</div><div class="panel-title">检索本地知识库</div>', unsafe_allow_html=True)
        quick_cols = st.columns(3)
        quick_queries = [
            ("易错点", "移项法则有哪些常见错误？"),
            ("课堂互动", "如何设计移项法则的课堂互动？"),
            ("分层作业", "如何设计一元一次方程分层作业？"),
        ]
        for col, (label, quick_query) in zip(quick_cols, quick_queries):
            if col.button(label, use_container_width=True, key=f"quick_{label}"):
                st.session_state.kb_query = quick_query
        query = st.text_input(
            "备课问题",
            placeholder="例如：移项法则有哪些易错点？",
            key="kb_query",
        )
        if st.button("开始检索", type="primary", use_container_width=True):
            if query.strip():
                st.session_state.kb_results = knowledge_base.search(query.strip(), top_k=5, extra_chunks=st.session_state.uploaded_chunks)
            else:
                st.warning("请先输入一个备课问题。")

        if st.session_state.kb_results:
            st.caption(f"找到 {len(st.session_state.kb_results)} 条最相关片段，按匹配度排序。")
            for index, result in enumerate(st.session_state.kb_results, start=1):
                with st.expander(
                    f"{index}. {result.title} · 匹配度 {result.score:.0%}",
                    expanded=index <= 2,
                ):
                    st.progress(min(max(result.score, 0.0), 1.0))
                    st.caption(f"{result.category} ｜ 来源文件：{result.filename}")
                    preview = result.text if len(result.text) <= 420 else result.text[:420] + "……"
                    st.write(preview)
                    st.caption(f"来源说明：{result.source}")
        else:
            st.info("点击“开始检索”，这里将显示从内置和本次上传资料中找到的真实内容。")

        st.markdown(
            '<div class="skeleton-note">检索结果会作为生成依据传入AI，并在最终方案中保留参考资料名称。</div>',
            unsafe_allow_html=True,
        )
    back, next_col = st.columns(2)
    if back.button("返回教学需求", use_container_width=True):
        goto(1)
        st.rerun()
    if next_col.button("确认资料并生成", type="primary", use_container_width=True):
        goto(3)
        st.rerun()


def render_step_three() -> None:
    plan = st.session_state.generated_plan
    render_page_intro(
        "STEP 03 · CONTENT GENERATION",
        "从教学意图到完整课堂方案",
        "AI融合需求画像和知识库证据，同步设计课件、教案、互动与作业。",
        "生成内容可继续修改",
    )
    if plan:
        render_stat_cards(
            [
                ("课件页面", f"{len(plan.get('ppt_outline', []))} 页"),
                ("教学环节", f"{len(plan.get('teaching_process', []))} 个"),
                ("互动测验", f"{len(plan.get('quiz', []))} 题"),
            ]
        )
    else:
        render_stat_cards([("生成引擎", "DeepSeek"), ("知识依据", "本地 RAG"), ("交付组合", "PPT + 教案 + 双讲义")])

    action_col, hint_col = st.columns([1, 1.45], gap="large")
    with action_col:
        generate_clicked = st.button("✦ 生成第一版教学方案", type="primary", use_container_width=True)
    with hint_col:
        st.caption("系统将完成资料检索、结构规划、课堂活动设计和分层作业生成，通常需要十几秒。")

    if generate_clicked:
        if not ai_is_configured():
            st.error("尚未配置 DeepSeek API 密钥。")
        else:
            try:
                with st.status("AI课程设计引擎正在工作", expanded=True) as generation_status:
                    progress = st.progress(0, text="0% · 正在整理教师需求")
                    st.write("✓ 已读取年级、课题、课时、教学顺序和课件偏好")
                    progress.progress(12, text="12% · 正在形成课程需求画像")

                    query = " ".join(
                        str(st.session_state.requirements.get(field, ""))
                        for field in ["课题", "教学目标", "教学重点", "教学难点", "互动与风格", "教学顺序", "跨学科融合"]
                    )
                    progress.progress(24, text="24% · 正在检索本地知识库")
                    results = load_knowledge_base().search(query, top_k=7, extra_chunks=st.session_state.uploaded_chunks)
                    context = [
                        {"title": result.title, "source": result.source, "text": result.text}
                        for result in results
                    ]
                    st.write(f"✓ 已匹配 {len(results)} 条教学资料片段")
                    progress.progress(38, text="38% · 正在设计教学结构与跨学科导入")

                    st.session_state.generated_plan = generate_lesson_plan(
                        st.session_state.requirements,
                        context,
                    )
                    generated = st.session_state.generated_plan
                    progress.progress(76, text="76% · PPT大纲与课堂活动已经生成")
                    st.write(f"✓ 已设计 {len(generated.get('ppt_outline', []))} 页课件内容")
                    progress.progress(88, text="88% · 正在生成教案、教师讲义和学生学习单")
                    st.session_state.export_bundle = build_export_bundle(generated)
                    progress.progress(96, text="96% · 正在校验并打包课堂文件")
                    st.write("✓ PPT与三份Word文档已经通过导出检查")
                    progress.progress(100, text="100% · 全部教学资源生成完成")
                    generation_status.update(label="教学资源生成完成", state="complete", expanded=True)
                st.session_state.draft_ready = True
                st.session_state.api_error = ""
            except AIServiceError as exc:
                st.session_state.api_error = str(exc)
            except Exception as exc:
                st.session_state.api_error = f"文件生成阶段失败：{str(exc)[:180]}"

    if st.session_state.api_error:
        st.error(st.session_state.api_error)

    plan = st.session_state.generated_plan
    if plan:
        st.markdown(
            '<div class="success-banner"><div class="success-icon">✓</div><div><strong>教学方案已生成</strong><br>'
            '<span style="font-size:.78rem">内容来自真实AI生成，并融合本地知识库检索结果。</span></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"### {plan.get('lesson_title', st.session_state.requirements['课题'])}")
        st.write(plan.get("summary", ""))
    else:
        st.info("点击上方按钮后，将生成教案、PPT大纲和互动活动。")

    tab_ppt, tab_doc, tab_fusion, tab_handout = st.tabs(["PPT大纲", "教案设计", "融合与作业", "教学讲义"])
    with tab_ppt:
        outlines = plan.get("ppt_outline", []) if plan else []
        if outlines:
            for start in range(0, len(outlines), 3):
                cards = st.columns(3)
                for local_index, (col, slide) in enumerate(zip(cards, outlines[start : start + 3])):
                    theme_index = (start + local_index) % 4
                    with col:
                        st.markdown(
                            f'<div class="slide-card slide-theme-{theme_index}">'
                            f'<div class="slide-kicker">课件预览 {escape(str(slide.get("page", start + 1)))}</div>'
                            f'<div class="slide-title">{escape(str(slide.get("title", "未命名页面")))}</div>'
                            f'<div class="slide-copy">{escape(str(slide.get("content", "")))}</div>'
                            "</div>",
                            unsafe_allow_html=True,
                        )
        else:
            st.caption(f"生成后将在这里显示约 {st.session_state.requirements.get('PPT期望页数', '12页')} 的PPT内容大纲。")
    with tab_doc:
        if plan:
            goal_col, point_col = st.columns(2)
            with goal_col:
                st.markdown("#### 教学目标")
                for item in plan.get("teaching_goals", []):
                    st.markdown(f"- {item}")
            with point_col:
                st.markdown("#### 重点与难点")
                for item in plan.get("key_points", []):
                    st.markdown(f"- 重点：{item}")
                for item in plan.get("difficult_points", []):
                    st.markdown(f"- 难点：{item}")
            st.markdown("#### 教学过程")
            for index, item in enumerate(plan.get("teaching_process", []), start=1):
                with st.expander(
                    f"{index}. {item.get('phase', '教学环节')} · {item.get('duration', '')}",
                    expanded=index <= 2,
                ):
                    st.write(f"**教师活动：** {item.get('teacher', '')}")
                    st.write(f"**学生活动：** {item.get('student', '')}")
                    st.write(f"**设计意图：** {item.get('purpose', '')}")
        else:
            st.caption("生成后将在这里显示教学目标、重点难点和完整教学流程。")
    with tab_fusion:
        if plan:
            fusion = plan.get("interdisciplinary_design", {}) or {}
            st.markdown("#### 跨学科融合设计")
            if fusion.get("subject") and fusion.get("subject") != "不启用":
                st.write(f"**融合学科：** {fusion.get('subject', '')}")
                st.write(f"**连接点：** {fusion.get('connection', '')}")
                st.write(f"**课堂任务：** {fusion.get('activity', '')}")
            else:
                st.caption("本次未启用跨学科融合。返回第一页选择学科后可重新生成。")
            activity = plan.get("interactive_activity", {})
            homework = plan.get("homework", {})
            st.markdown(f"#### 课堂互动 · {activity.get('name', '课堂互动活动')}")
            st.write(activity.get("rules", ""))
            st.caption(f"评价与反馈：{activity.get('feedback', '')}")
            st.markdown("#### 分层作业")
            st.write(f"**基础任务：** {homework.get('basic', '')}")
            st.write(f"**提升任务：** {homework.get('advanced', '')}")
            references = plan.get("references", [])
            if references:
                st.caption("本次生成参考：" + "、".join(str(item) for item in references))
        else:
            st.caption("生成后将在这里显示课堂活动和分层作业。")
    with tab_handout:
        if plan:
            teacher = plan.get("teacher_handout", {}) or {}
            student = plan.get("student_handout", {}) or {}
            teacher_col, student_col = st.columns(2)
            with teacher_col:
                st.markdown("#### 教师讲义")
                st.write(teacher.get("overview", plan.get("summary", "")))
                for item in teacher.get("knowledge_points", [])[:5]:
                    st.markdown(f"- {item}")
            with student_col:
                st.markdown("#### 学生学习单")
                for item in student.get("key_notes", [])[:5]:
                    st.markdown(f"- {item}")
                st.caption(f"含 {len(student.get('practice', []))} 道练习与学习反思。")
        else:
            st.caption("生成后将在这里预览教师讲义与学生学习单。")

    back, next_col = st.columns(2)
    if back.button("返回资料页面", use_container_width=True):
        goto(2)
        st.rerun()
    if next_col.button("进入修改与下载", type="primary", use_container_width=True):
        goto(4)
        st.rerun()


def render_step_four() -> None:
    plan = st.session_state.generated_plan
    render_page_intro(
        "STEP 04 · REFINE & DELIVER",
        "一句话修改，直接交付课堂文件",
        "保留教师最终决定权，AI只调整明确提出的部分，并同步更新全部交付物。",
        "可编辑文件交付",
    )
    if not plan:
        st.warning("尚未生成教学方案，请先返回课件预览页完成生成。")
        if st.button("返回课件预览"):
            goto(3)
            st.rerun()
        return

    render_stat_cards(
        [
            ("当前版本", f"V{st.session_state.revision_count + 1}.0"),
            ("PPT课件", f"{len(plan.get('ppt_outline', [])) + 3} 页"),
            ("可下载文件", "4 个"),
        ]
    )

    left, right = st.columns([1.3, 1], gap="large")
    with left:
        st.markdown('<div class="panel-kicker">NATURAL LANGUAGE EDITING</div><div class="panel-title">告诉AI你想改什么</div>', unsafe_allow_html=True)
        preset_cols = st.columns(3)
        presets = [
            ("增加互动", "增加一个5分钟的小组互动，并说明规则和评价方式。"),
            ("强化易错点", "增加一道移项易错题，突出忘记变号和只移动部分两类错误。"),
            ("精简表达", "精简PPT文字，每页只保留最关键的教学信息。"),
        ]
        for col, (label, value) in zip(preset_cols, presets):
            if col.button(label, use_container_width=True, key=f"preset_{label}"):
                st.session_state.revision_text = value
        instruction = st.text_area(
            "修改意见",
            placeholder="例如：增加一道移项易错题，并简化第5页的概念说明。",
            height=140,
            key="revision_text",
        )
        if st.button("应用修改", type="primary", disabled=not instruction.strip()):
            try:
                with st.spinner("正在根据意见修改完整方案……"):
                    st.session_state.generated_plan = revise_lesson_plan(
                        plan,
                        st.session_state.requirements,
                        instruction,
                    )
                    st.session_state.export_bundle = build_export_bundle(st.session_state.generated_plan)
                st.session_state.api_error = ""
                st.session_state.revision_count += 1
                st.success("修改完成，右侧文件已同步更新。")
                st.rerun()
            except AIServiceError as exc:
                st.session_state.api_error = str(exc)
        if st.session_state.api_error:
            st.error(st.session_state.api_error)
        st.caption("每次修改都会保留完整结构，并重新生成PPT和Word文件。")
    with right:
        st.markdown('<div class="panel-kicker">DELIVERY CENTER</div><div class="panel-title">课堂文件中心</div>', unsafe_allow_html=True)
        try:
            title = safe_filename(plan.get("lesson_title", "教学方案"))
            bundle = st.session_state.export_bundle or build_export_bundle(plan)
            st.session_state.export_bundle = bundle
            pptx_bytes = bundle["pptx"]
            docx_bytes = bundle["lesson_docx"]
            teacher_handout = bundle["teacher_docx"]
            student_handout = bundle["student_docx"]
            st.markdown(
                f'<div class="download-summary"><div class="download-title">{escape(title)}</div>'
                f'<div class="download-meta">已同步生成课件、教案、教师讲义与学生学习单 · {escape(st.session_state.requirements.get("PPT视觉风格", "科技蓝"))} · V{st.session_state.revision_count + 1}.0</div></div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "⬇ 下载 PPT 课件",
                data=pptx_bytes,
                file_name=f"{title}_课件.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )
            st.download_button(
                "⬇ 下载 Word 教案",
                data=docx_bytes,
                file_name=f"{title}_教案.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
            st.download_button(
                "⬇ 下载教师教学讲义",
                data=teacher_handout,
                file_name=f"{title}_教师讲义.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
            st.download_button(
                "⬇ 下载学生课堂学习单",
                data=student_handout,
                file_name=f"{title}_学生学习单.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"文件生成失败：{str(exc)[:160]}")
        if st.button("✦ 打开课堂互动小测", use_container_width=True):
            st.session_state.show_game = not st.session_state.show_game

    if st.session_state.show_game:
        st.markdown('<div class="panel-kicker" style="margin-top:1rem">LIVE CLASSROOM</div><div class="page-title" style="font-size:1.35rem">课堂互动中心</div>', unsafe_allow_html=True)
        games = discover_games(PROJECT_ROOT / "games")
        selected_game = choose_game(
            games,
            st.session_state.requirements.get("学科年级", ""),
            st.session_state.requirements.get("课题", ""),
        )
        if selected_game:
            st.success(f"已匹配小游戏：{selected_game.name} · {selected_game.description}")
            try:
                renderer = load_game_renderer(selected_game)
                renderer({
                    "requirements": st.session_state.requirements,
                    "plan": plan,
                    "quiz": plan.get("quiz", []),
                })
            except GamePluginError as exc:
                st.warning(str(exc))
        else:
            st.info("小游戏扩展槽位已就绪。队友把游戏文件夹放入 games 后，系统会按学科和课题自动匹配；当前先使用AI即时小测。")
        st.markdown("#### AI即时小测")
        quiz = plan.get("quiz", [])
        if not quiz:
            st.info("当前方案没有小测题，请输入修改意见“增加3道课堂小测题”后应用修改。")
        else:
            answers: list[str] = []
            with st.form("lesson_quiz"):
                for index, item in enumerate(quiz, start=1):
                    options = [str(option) for option in item.get("options", [])]
                    if options:
                        answers.append(
                            st.radio(
                                f"{index}. {item.get('question', '课堂练习')}",
                                options,
                                index=None,
                                key=f"quiz_{index}",
                            )
                        )
                submitted = st.form_submit_button("提交答案", type="primary")
            if submitted:
                score = 0
                details: list[str] = []
                for index, (item, selected) in enumerate(zip(quiz, answers), start=1):
                    options = [str(option) for option in item.get("options", [])]
                    try:
                        answer_index = int(item.get("answer_index", 0))
                    except (TypeError, ValueError):
                        answer_index = 0
                    correct = options[answer_index] if options and 0 <= answer_index < len(options) else ""
                    if selected == correct:
                        score += 1
                    else:
                        details.append(
                            f"第{index}题正确答案：{correct}。{item.get('explanation', '')}"
                        )
                st.success(f"答对 {score}/{len(quiz)} 题")
                for detail in details:
                    st.write(detail)
    if st.button("返回课件预览"):
        goto(3)
        st.rerun()


init_state()
render_sidebar()
render_header()

if st.session_state.step == 1:
    render_step_one()
elif st.session_state.step == 2:
    render_step_two()
elif st.session_state.step == 3:
    render_step_three()
else:
    render_step_four()
