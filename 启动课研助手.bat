@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 正在创建Python虚拟环境...
  py -3.11 -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo 未能创建虚拟环境，请确认 py --list 中已经显示 Python 3.11。
  pause
  exit /b 1
)
echo [2/3] 正在检查并安装基础依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo [3/3] 正在启动课研助手...
".venv\Scripts\python.exe" -m streamlit run app.py
pause
