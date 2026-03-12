from __future__ import annotations


class NotificationService:
    def show_warning(self, message: str) -> str:
        return f"Warning placeholder: {message}"

    def show_critical_warning(self, message: str) -> str:
        return f"Critical warning placeholder: {message}"
