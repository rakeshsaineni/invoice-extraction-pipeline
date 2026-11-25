"""Event bus. In-memory for tests and local runs; Kafka (or Azure Event Hubs, which speaks the
Kafka protocol) in production. Topics: invoice.received -> invoice.extracted -> invoice.matched"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable


class InMemoryBroker:
    def __init__(self):
        self.queues: dict[str, deque] = defaultdict(deque)
        self.handlers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        self.published: list[tuple[str, dict]] = []

    def publish(self, topic: str, event: dict) -> None:
        self.published.append((topic, event))
        self.queues[topic].append(json.loads(json.dumps(event, default=str)))  # same serialization as Kafka

    def subscribe(self, topic: str, handler: Callable[[dict], None]) -> None:
        self.handlers[topic].append(handler)

    def drain(self) -> int:
        """Deliver until every queue is empty (handlers may publish more events)."""
        n = 0
        while any(self.queues.values()):
            for topic, q in list(self.queues.items()):
                while q:
                    event = q.popleft()
                    for h in self.handlers[topic]:
                        h(event)
                    n += 1
        return n


class KafkaBroker:
    """Thin confluent-kafka wrapper (pip install confluent-kafka). At-least-once delivery:
    offsets are committed after the handler succeeds, so handlers must be idempotent (they are:
    every write is keyed by the document's SHA-256)."""

    def __init__(self, bootstrap: str, group: str = "invoiceflow"):
        from confluent_kafka import Consumer, Producer

        self.producer = Producer({"bootstrap.servers": bootstrap, "enable.idempotence": True, "acks": "all"})
        self.consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": group,
                                  "enable.auto.commit": False, "auto.offset.reset": "earliest"})
        self.handlers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def publish(self, topic: str, event: dict) -> None:
        self.producer.produce(topic, key=event.get("id", ""), value=json.dumps(event, default=str))
        self.producer.flush(5)

    def subscribe(self, topic: str, handler: Callable[[dict], None]) -> None:
        self.handlers[topic].append(handler)
        self.consumer.subscribe(list(self.handlers))

    def poll_once(self, timeout: float = 1.0) -> bool:
        msg = self.consumer.poll(timeout)
        if msg is None or msg.error():
            return False
        for h in self.handlers[msg.topic()]:
            h(json.loads(msg.value()))
        self.consumer.commit(msg)
        return True
