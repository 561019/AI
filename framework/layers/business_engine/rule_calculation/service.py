from typing import Any
from framework.core import standard_response
from framework.http import post_json

def get(handler:Any)->bool:
    if handler.path=="/api/v1/capabilities": handler.send(200,{"items":[{"capability_code":"rule.calculate","enabled":True}]}); return True
    return False
def post(handler:Any,envelope:dict[str,Any])->None:
    if handler.path!="/api/v1/rules/instructions": handler.send(404); return
    payload=envelope.get("payload",{})
    if not payload.get("rule_ref") or not payload.get("data_refs"): handler.send(200,standard_response(envelope,"success",data={"state":"precondition_query_required","required_inputs":[{"kind":"formal_rule"},{"kind":"authorized_data"}]})); return
    status,result=post_json("http://127.0.0.1:8012/api/v1/delivered-rules/calculate",{"trace_id":envelope["trace_id"],"values":payload.get("parameters",{}).get("values",[]),"unit":payload.get("expected_unit","CNY")},caller={"layer":"business_engine","module":"rule-adapter"})
    if status!=200 or not result.get("success"): handler.send(502,standard_response(envelope,"failed",error={"code":"DELIVERED_RULE_ENGINE_FAILED","details":result})); return
    handler.send(200,standard_response(envelope,"success",data={**result["data"],"rule_engine":result["engine_meta"]}))
