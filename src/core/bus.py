import queue
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("PulseCore.Bus")


@dataclass
class Event:
    """Подія на шині. topic визначає тип, payload — довільні дані події."""

    topic: str
    payload: dict
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class InMemoryBus:
    """
    Потокобезпечна in-process шина повідомлень (publish/subscribe) для Ядра Exarchon.

    Рішення dec_001: In-memory Async Queue, а не NATS/Redis. Обґрунтування —
    система наразі один процес на одній машині: daemon-потік, CLI та майбутній
    Telegram-бот (bot.py) обмінюються повідомленнями в межах цього процесу.
    Мережевий брокер означав би окрему службу для підняття, конфігурації й
    моніторингу без жодної реальної потреби в розподіленості на цьому етапі.

    Якщо Exarchon згодом вийде за межі одного процесу — заміні підлягає лише
    ця реалізація, інтерфейс publish/subscribe лишається незмінним для всіх,
    хто вже ним користується.

    Кожен підписник отримує власну queue.Queue — стандартний потокобезпечний
    примітив, який однаково коректно читається і з синхронного коду (потоки:
    daemon, CLI), і з асинхронного (aiogram-бот через
    `await asyncio.to_thread(q.get)` або неблокуючий `q.get_nowait()` в
    циклі опитування) — без сторонніх залежностей.
    """

    def __init__(self):
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str) -> "queue.Queue[Event]":
        """Реєструє нового підписника на topic. Повертає його персональну чергу подій."""
        q: "queue.Queue[Event]" = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(topic, []).append(q)
        return q

    def unsubscribe(self, topic: str, q: "queue.Queue[Event]") -> None:
        """Прибирає підписника (наприклад, коли компонент зупиняється)."""
        with self._lock:
            subs = self._subscribers.get(topic)
            if not subs or q not in subs:
                return
            subs.remove(q)
            if not subs:
                del self._subscribers[topic]

    def publish(self, topic: str, payload: dict) -> int:
        """
        Розсилає подію всім підписникам topic.
        Повертає кількість отримувачів, яким подію реально доставлено
        (0 — валідний результат, якщо на topic ще ніхто не підписаний,
        наприклад bot.py ще не запущений).
        """
        event = Event(topic=topic, payload=payload)
        with self._lock:
            subs = list(self._subscribers.get(topic, []))

        for q in subs:
            q.put(event)

        if not subs:
            logger.debug(f"[BUS] Подія '{topic}' опублікована без жодного підписника.")

        return len(subs)


# Єдиний екземпляр на процес. Усі компоненти Ядра (daemon, CLI, майбутній
# bot.py) імпортують саме цей об'єкт, а не створюють власні шини —
# інакше publish в одному компоненті ніколи не дійде до subscribe в іншому.
bus = InMemoryBus()
