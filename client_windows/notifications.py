from __future__ import annotations

import subprocess

from client_windows.config import WindowsClientConfig


class NotificationCommandRunner:
    def run(self, command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


class NotificationService:
    def __init__(
        self,
        config: WindowsClientConfig,
        command_runner: NotificationCommandRunner | None = None,
    ) -> None:
        self._config = config
        self._command_runner = command_runner or NotificationCommandRunner()

    def show_warning(self, message: str) -> str:
        return self._show_notification(message)

    def show_critical_warning(self, message: str) -> str:
        return self._show_notification(message)

    def _show_notification(self, message: str) -> str:
        if not self._config.execute_platform_actions:
            return f"Notification planned: {message}"

        toast_result = self._try_windows_toast(message)
        if toast_result.returncode == 0:
            return "Windows toast notification sent."

        fallback_result = self._command_runner.run(
            ["msg", "*", "/TIME:60", message],
            timeout_seconds=5.0,
        )
        if fallback_result.returncode == 0:
            return "Windows msg notification sent."

        stderr = fallback_result.stderr.strip() or toast_result.stderr.strip()
        stdout = fallback_result.stdout.strip() or toast_result.stdout.strip()
        return stdout or stderr or f"Notification execution failed: {message}"

    def _try_windows_toast(self, message: str) -> subprocess.CompletedProcess[str]:
        title = self._escape_powershell_string(self._config.notification_title)
        body = self._escape_powershell_string(message)
        script = (
            "$title = '{title}'; "
            "$message = '{body}'; "
            "$safeTitle = [System.Security.SecurityElement]::Escape($title); "
            "$safeMessage = [System.Security.SecurityElement]::Escape($message); "
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
            "$template = \"<toast><visual><binding template='ToastText02'><text id='1'>$safeTitle</text><text id='2'>$safeMessage</text></binding></visual></toast>\"; "
            "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            "$xml.LoadXml($template); "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('UPS Orchestrator'); "
            "$notifier.Show($toast)"
        ).format(title=title, body=body)
        return self._command_runner.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout_seconds=5.0,
        )

    @staticmethod
    def _escape_powershell_string(value: str) -> str:
        return value.replace("'", "''")
