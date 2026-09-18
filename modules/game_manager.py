from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GamePlugin:
    game_id: str
    name: str
    subject: str
    topic_keywords: list[str]
    description: str
    folder: Path
    entry_file: str = "game.py"


class GamePluginError(RuntimeError):
    pass


def discover_games(root: Path) -> list[GamePlugin]:
    root = Path(root)
    if not root.exists():
        return []
    games: list[GamePlugin] = []
    for config_path in sorted(root.glob("*/game_config.json")):
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if not data.get("enabled", True):
                continue
            games.append(GamePlugin(
                game_id=str(data.get("id") or config_path.parent.name),
                name=str(data.get("name") or config_path.parent.name),
                subject=str(data.get("subject") or "通用"),
                topic_keywords=[str(item) for item in data.get("topic_keywords", [])],
                description=str(data.get("description") or "课堂互动小游戏"),
                folder=config_path.parent,
                entry_file=str(data.get("entry_file") or "game.py"),
            ))
        except Exception:
            continue
    return games


def choose_game(games: list[GamePlugin], subject: str, topic: str) -> GamePlugin | None:
    haystack = f"{subject} {topic}".lower()
    scored: list[tuple[int, GamePlugin]] = []
    for game in games:
        score = int(game.subject.lower() in haystack or game.subject == "通用")
        score += sum(2 for keyword in game.topic_keywords if keyword.lower() in haystack)
        scored.append((score, game))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else None


def load_game_renderer(game: GamePlugin) -> Callable[[dict[str, Any]], Any]:
    entry_path = game.folder / game.entry_file
    if not entry_path.exists():
        raise GamePluginError(f"找不到游戏入口文件：{entry_path.name}")
    module_name = f"lesson_game_{game.game_id}"
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise GamePluginError("无法加载游戏模块。")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise GamePluginError(f"游戏模块加载失败：{str(exc)[:160]}") from exc
    renderer = getattr(module, "render_game", None)
    if not callable(renderer):
        raise GamePluginError("游戏入口必须提供 render_game(game_data) 函数。")
    return renderer
