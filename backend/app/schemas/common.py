from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from backend.app.database.models import EnvironmentType, KeyStatus, QueueStrategy


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KeyStatusSchema(str, Enum):
    ACTIVE = KeyStatus.ACTIVE.value
    COOLDOWN = KeyStatus.COOLDOWN.value
    INVALID = KeyStatus.INVALID.value
    SUSPENDED_BILLING = KeyStatus.SUSPENDED_BILLING.value


class EnvironmentTypeSchema(str, Enum):
    DEVELOPMENT = EnvironmentType.DEVELOPMENT.value
    STAGING = EnvironmentType.STAGING.value
    PRODUCTION = EnvironmentType.PRODUCTION.value


class QueueStrategySchema(str, Enum):
    ORDERED = QueueStrategy.ORDERED.value
    SMART = QueueStrategy.SMART.value
    LATENCY = QueueStrategy.LATENCY.value


class HealthResponse(ORMModel):
    status: str
    service: str
    version: str
    schema_version: str
    timestamp: datetime | None = None
