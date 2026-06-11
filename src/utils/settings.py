"""
Fenrir Settings — persistent application settings using QSettings.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QByteArray
from typing import Any


APP_NAME = "Fenrir"
ORG_NAME = "FlowRidge"


def get_settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


class AppSettings:
    """Typed accessors for persistent settings."""

    @staticmethod
    def window_geometry() -> QByteArray | None:
        s = get_settings()
        return s.value("window/geometry", None)

    @staticmethod
    def set_window_geometry(geo: QByteArray) -> None:
        s = get_settings()
        s.setValue("window/geometry", geo)

    @staticmethod
    def window_state() -> QByteArray | None:
        s = get_settings()
        return s.value("window/state", None)

    @staticmethod
    def set_window_state(state: QByteArray) -> None:
        s = get_settings()
        s.setValue("window/state", state)

    @staticmethod
    def sidebar_visible() -> bool:
        s = get_settings()
        return s.value("ui/sidebar_visible", True, type=bool)

    @staticmethod
    def set_sidebar_visible(v: bool) -> None:
        s = get_settings()
        s.setValue("ui/sidebar_visible", v)

    @staticmethod
    def sidebar_width() -> int:
        s = get_settings()
        return s.value("ui/sidebar_width", 220, type=int)

    @staticmethod
    def set_sidebar_width(w: int) -> None:
        s = get_settings()
        s.setValue("ui/sidebar_width", w)

    @staticmethod
    def zoom() -> float:
        s = get_settings()
        return s.value("view/zoom", 1.0, type=float)

    @staticmethod
    def set_zoom(z: float) -> None:
        s = get_settings()
        s.setValue("view/zoom", z)

    @staticmethod
    def recent_files() -> list[str]:
        s = get_settings()
        return s.value("recent/files", [], type=list) or []

    @staticmethod
    def set_recent_files(files: list[str]) -> None:
        s = get_settings()
        s.setValue("recent/files", files[:10])  # Keep last 10

    @staticmethod
    def add_recent_file(path: str) -> None:
        files = AppSettings.recent_files()
        if path in files:
            files.remove(path)
        files.insert(0, path)
        AppSettings.set_recent_files(files)

    @staticmethod
    def dark_mode() -> bool:
        s = get_settings()
        return s.value("appearance/dark_mode", False, type=bool)

    @staticmethod
    def set_dark_mode(v: bool) -> None:
        s = get_settings()
        s.setValue("appearance/dark_mode", v)