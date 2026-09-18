# 课研助手 V4 · 多模态AI教学智能体

本项目面向教师备课场景，完成“需求访谈—知识检索—方案生成—教师修改—文件交付”的闭环。核心生成模型使用 DeepSeek；语音识别可选用本地 Paraformer；知识库和小游戏均采用可扩展目录，不需要反复重写主网页。

## 已完成功能

- 固定浅色主题，避免跟随设备夜间模式导致文字不可见；
- 首次使用说明和四阶段导航；
- 文字/语音描述教学需求，AI每轮只追问一至两个关键问题；
- 选择教学顺序、总课时、PPT讲解时长、页数、详细程度和视觉风格；
- PDF、DOCX、PPTX、TXT、Markdown本地知识库检索；
- 跨学科融合，由教师选择语文、历史、数学史等学科；
- 分阶段可视化生成进度；
- 生成PPT、Word教案、教师讲义和学生学习单；
- 自然语言修改并重新生成文件；
- 内置AI即时小测，并为队友小游戏预留插件接口；
- 同时支持本地 `.env` 和 Streamlit Cloud Secrets。

## 最简单的本地启动方法

1. 安装 Python 3.11（推荐，不建议使用尚未广泛兼容的Python 3.14）。
2. 解压项目。
3. 将 `.env.example` 复制为 `.env`，填入自己的 DeepSeek 密钥。
4. 双击 `启动课研助手.bat`。
5. 浏览器打开 `http://localhost:8501`。

也可以在 VS Code 终端逐行执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m streamlit run .\app.py
```

PowerShell不允许运行 `Activate.ps1` 也没有关系，本项目所有命令都直接使用虚拟环境中的 Python，不要求激活环境。

## 配置DeepSeek

本地运行时，将 `.env.example` 复制为 `.env`：

```text
DEEPSEEK_API_KEY=sk-你的真实密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

不要上传 `.env`，也不要把真实密钥发给队友或评委。

## 安装本地Paraformer语音识别

先确保基础版可以正常运行，再执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-voice.txt
```

首次识别会下载模型，所需时间较长。完成后模型会保存在本机缓存中。免费云服务器可能因内存和启动时间限制无法稳定运行Paraformer，因此公网比赛版默认保证文字输入和核心生成功能可用；本机录制演示视频时可展示完整语音功能。

## 队友增加知识库

直接把资料放入：

```text
knowledge_base/documents/学科名称/
```

例如：

```text
knowledge_base/documents/数学/一元一次方程教案.docx
knowledge_base/documents/语文/古代数学故事.pdf
knowledge_base/documents/历史/方程发展史.pptx
```

重新打开网页，在“资料与知识库”页面点击“同步团队知识库”。系统会通过文件哈希判断变化，只处理新增和修改的资料。

## 队友增加小游戏

复制 `games/_template_game`，修改文件夹名称，在 `game.py` 中实现：

```python
def render_game(game_data):
    ...
```

完成后把 `game_config.json` 的 `enabled` 改为 `true`。主网页会根据学科和课题自动匹配，无需修改 `app.py`。完整要求见 `games/README.md`。

如果队友使用的是 Pygame，需要先改造成 Streamlit 或 HTML/JavaScript 网页交互；桌面Pygame窗口不能直接嵌入云端网页。

## 部署到Streamlit Community Cloud

1. 在GitHub新建一个仓库，例如 `teaching-assistant-ai`。
2. 上传本项目中的全部文件和文件夹，但不要上传 `.env`、`.venv` 和任何真实密钥。
3. 登录 Streamlit Community Cloud，点击 `Create app`。
4. 选择刚才的GitHub仓库。
5. Main file path 填写 `app.py`。
6. 在应用设置的 Secrets 中填写：

```toml
DEEPSEEK_API_KEY = "sk-你的真实密钥"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
```

7. 点击 Deploy。部署完成后复制 `https://xxxx.streamlit.app` 链接给队友和评委。

GitHub更新文件后，Streamlit Cloud会自动重新部署，不需要重新创建应用。

## 比赛前完整检查

1. 右上角显示“AI引擎在线”。
2. 完成一次文字访谈，确认需求画像会更新。
3. 本地版录一段语音并成功转文字。
4. 知识库能搜索出资料名称和真实片段。
5. 生成进度能从0%走到100%。
6. PPT、教案、教师讲义和学生学习单都能下载并打开。
7. 修改意见生效且能重新下载新版本。
8. 互动小测可以答题和判分。
9. 使用一台没有登录开发账号的电脑打开公网链接测试。
10. 准备演示视频和本地运行版作为公网故障备用。

## 项目目录

```text
app.py                    主页面
modules/                  AI、知识库、导出、语音、游戏管理模块
knowledge_base/documents  团队长期知识库
games/                    小游戏插件
templates/                后续PPT模板扩展位置
requirements.txt          公网稳定版基础依赖
requirements-voice.txt    本地Paraformer语音依赖
.streamlit/config.toml    固定浅色主题和上传设置
```
