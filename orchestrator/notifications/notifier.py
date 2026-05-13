"""Notification abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class NotificationMessage:
    title: str
    body: str
    attachments: list[Path] = field(default_factory=list)
    priority: Literal["low", "normal", "high", "critical"] = "normal"


class Notifier(ABC):
    @abstractmethod
    def send(self, message: NotificationMessage) -> bool:
        """Send a notification."""
