from framework.layers.foundation.generic_module_adapter import get_for, post_for

MODULE_CODE = "security-compliance"


def get(handler):
    return get_for(MODULE_CODE, handler)


def post(handler, payload):
    post_for(MODULE_CODE, handler, payload)
