const http = require("node:http");
const { createAdapter } = require("../adapters/1.3联调适配器");

const port = Number(process.env.PORT || 8790);
const adapter = createAdapter();
const json = (res, status, body) => { res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" }); res.end(JSON.stringify(body)); };
const readBody = (req) => new Promise((resolve, reject) => {
  let raw = "";
  req.on("data", (chunk) => { raw += chunk; if (raw.length > 1_000_000) reject(new Error("REQUEST_TOO_LARGE")); });
  req.on("end", () => { try { resolve(JSON.parse(raw || "{}")); } catch { reject(new Error("INVALID_JSON")); } });
  req.on("error", reject);
});
const contextOf = (body = {}) => ({
  ...(body.context || {}),
  requestId: body.context?.requestId || `REQ-${Date.now()}`,
  actorId: body.context?.actorId || body.actorId || "",
  actorType: body.context?.actorType || "human",
  tenantId: body.context?.tenantId || body.tenantId || "TENANT-INTEGRATION",
  subjectUserId: body.context?.subjectUserId || body.subjectUserId || body.userId || "",
  roles: body.context?.roles || body.roles || []
});
const candidateIdFrom = (url) => decodeURIComponent(url.split("/")[5] || "");

const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") return json(res, 200, { ok: true, service: "l1-1.3-integration-mock" });
  if (req.method === "GET" && req.url.startsWith("/api/l1/evolution/audit")) return json(res, 200, { code: "AUDIT_OK", entries: adapter.getAuditLog() });
  try {
    const url = req.url.split("?")[0];
    const body = ["POST", "PUT", "PATCH"].includes(req.method) ? await readBody(req) : {};
    const context = contextOf(body);
    if (req.method === "POST" && url === "/api/l1/evolution/candidates") return json(res, 201, adapter.createCandidate(body.candidate || body, context));
    if (req.method === "GET" && /^\/api\/l1\/evolution\/candidates\/[^/]+$/.test(url)) {
      const candidate = adapter.getCandidate(url.split("/").pop());
      return candidate ? json(res, 200, { code: "CANDIDATE_FOUND", candidate }) : json(res, 404, { code: "CANDIDATE_NOT_FOUND" });
    }
    const candidateId = candidateIdFrom(url);
    if (req.method === "POST" && url.endsWith("/risk-check")) return json(res, 200, adapter.riskCheck({ candidateId }, context));
    if (req.method === "POST" && url.endsWith("/confirmations")) return json(res, 200, adapter.confirm({ candidateId, ...body }, context));
    if (req.method === "POST" && url.endsWith("/approvals")) return json(res, 200, adapter.approve({ candidateId, ...body }, context));
    if (req.method === "POST" && url.endsWith("/publish")) return json(res, 200, adapter.publish({ candidateId, ...context, ...body }));
    if (req.method === "POST" && url.includes("/assets/") && url.endsWith("/rollback")) return json(res, 200, adapter.rollback({ ...body, ...context, agentId: url.split("/")[5] }));
    return json(res, 404, { code: "NOT_FOUND" });
  } catch (error) {
    return json(res, 500, { code: "EVOLUTION_SERVICE_ERROR", message: error.message });
  }
});

server.listen(port, "127.0.0.1", () => console.log(`L1-1.3 integration mock listening on http://127.0.0.1:${port}`));
