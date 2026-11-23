"""Re-export of the generated topic catalogue (stable import path for services)."""

from contracts_py._generated.topics import *  # noqa: F403
from contracts_py._generated.topics import (  # noqa: F401
    CONSUMER_GROUPS,
    MESSAGE_TOPIC,
    RETRY_DELAY_SECONDS,
    RETRY_DELAYS,
    TOPIC_BY_NAME,
    TOPICS,
    TopicSpec,
    dlq_topic,
    retry_topics,
)
