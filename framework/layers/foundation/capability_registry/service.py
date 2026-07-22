from typing import Any
from framework.core import connect,resolve_capability

def get(handler:Any)->bool:
    if handler.path=="/api/v1/capabilities":
        with connect() as db: handler.send(200,[dict(row) for row in db.execute("SELECT * FROM capabilities ORDER BY capability_code")])
        return True
    return False
def post(handler:Any,_:dict[str,Any])->None:
    if handler.path.endswith("/resolve"):
        code=handler.path.split("/")[-2]; item=resolve_capability(code); handler.send(200,item) if item else handler.send(404,{"error":"CAPABILITY_NOT_FOUND"}); return
    handler.send(404)
