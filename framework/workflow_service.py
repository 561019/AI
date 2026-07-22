"""Compatibility import; implementation moved to workflow_execution."""
from framework.layers.business_engine.workflow_execution.service import get, post
__all__ = ["get", "post"]
