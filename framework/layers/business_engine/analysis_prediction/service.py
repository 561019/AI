from framework.layers.business_engine.generic_module_adapter import get_for, post_for

MODULE_CODE = "analysis-prediction"


def get(handler):
    return get_for(MODULE_CODE, handler)


def post(handler, payload):
    post_for(MODULE_CODE, handler, payload)
