"""Local file/terminal notifier."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from orchestrator.notifications.notifier import NotificationMessage, Notifier


class LocalNotifier(Notifier):
    """Write notification messages to data/notifications/YYYYMMDD/notification.log."""

    def __init__(self, data_dir: str | Path = "data", echo: bool = False) -> None:
        self.data_dir = Path(data_dir)
        self.echo = echo

    def send(self, message: NotificationMessage) -> bool:
        date = datetime.now().strftime("%Y%m%d")
        output_dir = self.data_dir / "notifications" / date
        output_dir.mkdir(parents=True, exist_ok=True)
        line = (
            f"{datetime.now().astimezone().isoformat()} [{message.priority}] "
            f"{message.title} | {message.body} | attachments="
            f"{','.join(str(p) for p in message.attachments)}\n"
        )
        with (output_dir / "notification.log").open("a", encoding="utf-8") as file_obj:
            file_obj.write(line)
        if self.echo:
            print(line.strip())
        return True
