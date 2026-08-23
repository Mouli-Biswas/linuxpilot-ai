"""
routes_intent.py
-----------------
Exposes the intent classifier as a clean JSON API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.ai.intent_classifier import intent_classifier
from backend.ai.schemas import ClassifyRequest, ClassifyResponse

logger = logging.getLogger("linuxpilot.api.intent")
router = APIRouter(prefix="/api/intent", tags=["intent"])


@router.post("/classify", response_model=ClassifyResponse)
async def classify_intent(payload: ClassifyRequest) -> ClassifyResponse:
    try:
        result = await intent_classifier.classify(payload.query)
        return ClassifyResponse(success=True, result=result)
    except ValueError as exc:
        return ClassifyResponse(success=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - top-level API boundary
        logger.exception("Unexpected error during classification")
        return ClassifyResponse(success=False, error=f"Internal error: {exc}")
