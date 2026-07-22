"""Compatibility import; implementation moved to the business application layer."""
from framework.layers.business_application.application_gateway.service import get, post
__all__ = ["get", "post"]
