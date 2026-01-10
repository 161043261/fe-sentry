import threading
import time
from typing import Optional

from kafka import KafkaProducer as KProducer
from kafka import KafkaConsumer as KConsumer
from kafka.errors import KafkaError

from config import cfg
import logger

# Producer state
_producer: Optional[KProducer] = None
_enabled: bool = False
_lock = threading.Lock()

# Consumer state
_consumer_thread: Optional[threading.Thread] = None
_consumer_stop_event = threading.Event()


def init_producer() -> None:
    """Initialize Kafka Producer (if enabled)"""
    global _producer, _enabled

    if not cfg.kafka.enabled:
        if logger.info_logger:
            logger.info_logger.info(
                "Kafka is disabled, logs will be written directly to file"
            )
        _enabled = False
        return

    try:
        _producer = KProducer(
            bootstrap_servers=cfg.kafka.brokers,
            acks="all",
            retries=3,
            value_serializer=lambda v: v if isinstance(v, bytes) else v.encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        _enabled = True
        if logger.info_logger:
            logger.info_logger.info("Kafka producer initialized")
    except KafkaError as e:
        if logger.error_logger:
            logger.error_logger.error(
                f"Failed to create Kafka producer: {e}, falling back to direct file write"
            )
        _enabled = False


def close_producer() -> None:
    """Close Kafka Producer"""
    global _producer

    if _producer:
        _producer.close()
        _producer = None


def send_log(key: str, data: bytes) -> None:
    """Send log to Kafka"""
    global _producer, _enabled

    if not _enabled or not _producer:
        raise RuntimeError("Kafka not available")

    _producer.send(cfg.kafka.topic, key=key, value=data)
    _producer.flush()


def is_enabled() -> bool:
    """Return whether Kafka is enabled"""
    return _enabled


def is_healthy() -> bool:
    """Check if Kafka connection is healthy"""
    return _enabled and _producer is not None


def _disable_kafka() -> None:
    """Disable Kafka, fallback to direct file write"""
    global _enabled, _producer

    _enabled = False
    if _producer:
        _producer.close()
        _producer = None


def _consumer_loop() -> None:
    """Consumer loop running in background thread"""
    try:
        consumer = KConsumer(
            cfg.kafka.topic,
            bootstrap_servers=cfg.kafka.brokers,
            group_id=cfg.kafka.group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )

        if logger.info_logger:
            logger.info_logger.info("Kafka consumer started")

        while not _consumer_stop_event.is_set():
            messages = consumer.poll(timeout_ms=1000)
            for tp, msgs in messages.items():
                for msg in msgs:
                    try:
                        logger.write_sdk_log(msg.value)
                    except Exception as e:
                        if logger.error_logger:
                            logger.error_logger.error(f"Failed to write log: {e}")

        consumer.close()
    except Exception as e:
        if logger.error_logger:
            logger.error_logger.error(f"Consumer error: {e}")


def start_consumer_with_retry() -> None:
    """Start Kafka consumer with retry"""
    global _consumer_thread

    if not is_enabled():
        if logger.info_logger:
            logger.info_logger.info("Kafka consumer not started (Kafka disabled)")
        return

    kafka_cfg = cfg.kafka
    retry_max = kafka_cfg.retry_max if kafka_cfg.retry_max > 0 else 5
    retry_interval = kafka_cfg.retry_interval if kafka_cfg.retry_interval > 0 else 5

    for i in range(retry_max):
        try:
            # Test connection
            test_consumer = KConsumer(
                bootstrap_servers=kafka_cfg.brokers,
                group_id=kafka_cfg.group_id,
            )
            test_consumer.close()

            # Start consumer thread
            _consumer_stop_event.clear()
            _consumer_thread = threading.Thread(target=_consumer_loop, daemon=True)
            _consumer_thread.start()
            return
        except Exception as e:
            if logger.error_logger:
                logger.error_logger.error(
                    f"Kafka connection failed (attempt {i + 1}/{retry_max}): {e}"
                )
            time.sleep((i + 1) * retry_interval)

    # Connection failed, fallback to direct file write
    if logger.error_logger:
        logger.error_logger.error(
            f"Failed to connect to Kafka after {retry_max} attempts, falling back to direct file write"
        )
    _disable_kafka()


def stop_consumer() -> None:
    """Stop Kafka consumer"""
    global _consumer_thread

    _consumer_stop_event.set()
    if _consumer_thread and _consumer_thread.is_alive():
        _consumer_thread.join(timeout=5)
    _consumer_thread = None
