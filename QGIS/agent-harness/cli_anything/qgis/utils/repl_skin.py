"""Shared cli-anything REPL skin for cli-anything-qgis."""

from __future__ import annotations

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DARK_GRAY = "\033[38;5;240m"
_GRAY = "\033[38;5;245m"
_LIGHT_GRAY = "\033[38;5;250m"
_CYAN = "\033[38;5;80m"
_GREEN = "\033[38;5;78m"
_YELLOW = "\033[38;5;220m"
_RED = "\033[38;5;196m"

_ACCENT_COLORS = {
    "qgis": "\033[38;5;34m",
}
_DEFAULT_ACCENT = "\033[38;5;75m"

_ICON_SMALL = "▸"
_H_LINE = "─"
_V_LINE = "│"
_TL = "╭"
_TR = "╮"
_BL = "╰"
_BR = "╯"


def _strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\033\[[^m]*m", "", text)


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


class ReplSkin:
    """Small terminal UI wrapper for the QGIS REPL."""

    def __init__(self, software: str, version: str = "1.0.0", history_file: str | None = None):
        self.software = software.lower().replace("-", "_")
        self.display_name = software.replace("_", " ").title()
        self.version = version
        self.accent = _ACCENT_COLORS.get(self.software, _DEFAULT_ACCENT)

        if history_file is None:
            from pathlib import Path

            history_dir = Path.home() / f".cli-anything-{self.software}"
            history_dir.mkdir(parents=True, exist_ok=True)
            self.history_file = str(history_dir / "history")
        else:
            self.history_file = history_file

        self._color = self._detect_color_support()

    def _detect_color_support(self) -> bool:
        if os.environ.get("NO_COLOR") or os.environ.get("CLI_ANYTHING_NO_COLOR"):
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()

    def _c(self, code: str, text: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{_RESET}"

    def print_banner(self) -> None:
        inner = 54

        def box_line(content: str) -> str:
            padding = inner - _visible_len(content)
            return f"{self._c(_DARK_GRAY, _V_LINE)}{content}{' ' * max(0, padding)}{self._c(_DARK_GRAY, _V_LINE)}"

        top = self._c(_DARK_GRAY, f"{_TL}{_H_LINE * inner}{_TR}")
        bottom = self._c(_DARK_GRAY, f"{_BL}{_H_LINE * inner}{_BR}")
        icon = self._c(_CYAN + _BOLD, "◆")
        brand = self._c(_CYAN + _BOLD, "cli-anything")
        name = self._c(self.accent + _BOLD, self.display_name)
        dot = self._c(_DARK_GRAY, "·")

        print(top)
        print(box_line(f" {icon}  {brand} {dot} {name}"))
        print(box_line(f" {self._c(_DARK_GRAY, f'v{self.version}')}"))
        print(box_line(""))
        print(box_line(f" {self._c(_DARK_GRAY, 'Type help for commands, quit to exit')}"))
        print(bottom)
        print()

    def prompt(self, project_name: str = "", modified: bool = False, context: str = "") -> str:
        parts = []
        parts.append(self._c(_CYAN, "◆ ") if self._color else "> ")
        parts.append(self._c(self.accent + _BOLD, self.software))
        if project_name or context:
            current = context or project_name
            suffix = "*" if modified else ""
            parts.append(f" {self._c(_DARK_GRAY, '[')}")
            parts.append(self._c(_LIGHT_GRAY, f"{current}{suffix}"))
            parts.append(self._c(_DARK_GRAY, ']'))
        parts.append(self._c(_GRAY, " ❯ "))
        return "".join(parts)

    def prompt_tokens(self, project_name: str = "", modified: bool = False, context: str = ""):
        tokens = [("class:icon", "◆ "), ("class:software", self.software)]
        if project_name or context:
            current = context or project_name
            suffix = "*" if modified else ""
            tokens.extend(
                [
                    ("class:bracket", " ["),
                    ("class:context", f"{current}{suffix}"),
                    ("class:bracket", "]"),
                ]
            )
        tokens.append(("class:arrow", " ❯ "))
        return tokens

    def get_prompt_style(self):
        try:
            from prompt_toolkit.styles import Style
        except ImportError:
            return None

        accent = _ANSI_256_TO_HEX.get(self.accent, "#5fafff")
        return Style.from_dict(
            {
                "icon": "#5fd7d7 bold",
                "software": f"{accent} bold",
                "bracket": "#585858",
                "context": "#bcbcbc",
                "arrow": "#808080",
                "completion-menu.completion": "bg:#303030 #bcbcbc",
                "completion-menu.completion.current": f"bg:{accent} #000000",
                "completion-menu.meta.completion": "bg:#303030 #808080",
                "completion-menu.meta.completion.current": f"bg:{accent} #000000",
                "auto-suggest": "#585858",
            }
        )

    def error(self, message: str) -> None:
        print(f"  {self._c(_RED + _BOLD, '✗')} {self._c(_RED, message)}", file=sys.stderr)

    def warning(self, message: str) -> None:
        print(f"  {self._c(_YELLOW + _BOLD, '⚠')} {self._c(_YELLOW, message)}")

    def success(self, message: str) -> None:
        print(f"  {self._c(_GREEN + _BOLD, '✓')} {self._c(_GREEN, message)}")

    def help(self, commands: dict[str, str]) -> None:
        print()
        print(f"  {self._c(self.accent + _BOLD, 'Commands')}")
        print(f"  {self._c(_DARK_GRAY, _H_LINE * 8)}")
        width = max((len(command) for command in commands), default=0)
        for command, description in commands.items():
            print(f"{self._c(self.accent, f'  {command:<{width}}')}  {self._c(_GRAY, description)}")
        print()

    def print_goodbye(self) -> None:
        print(f"\n  {self._c(_CYAN, _ICON_SMALL)} {self._c(_GRAY, 'Goodbye!')}\n")

    def create_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.history import FileHistory
        except ImportError:
            return None

        return PromptSession(
            history=FileHistory(self.history_file),
            auto_suggest=AutoSuggestFromHistory(),
            style=self.get_prompt_style(),
            enable_history_search=True,
        )

    def get_input(self, prompt_session, project_name: str = "", modified: bool = False, context: str = "") -> str:
        if prompt_session is not None:
            from prompt_toolkit.formatted_text import FormattedText

            return prompt_session.prompt(FormattedText(self.prompt_tokens(project_name, modified, context))).strip()
        return input(self.prompt(project_name, modified, context)).strip()


_ANSI_256_TO_HEX = {
    "\033[38;5;34m": "#00af00",
    "\033[38;5;75m": "#5fafff",
}
