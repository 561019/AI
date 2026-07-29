const fs = require("node:fs");
const path = require("node:path");
const { createAdapter } = require("./adapters/1.3联调适配器");

const root = __dirname;
const load = (name) => JSON.parse(fs.readFileSync(path.join(root, "fixtures", name), "utf8"));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const adapter = createAdapter();
const results = [];
const test = (name, fn) => { try { fn(); results.push(`PASS ${name}`); } catch (error) { results.push(`FAIL ${name}: ${error.message}`); } };

adapter.reset();
const success = load("success-low-risk.json");
let created;
test("低风险候选生成", () => { created = adapter.createCandidate(success.candidate, success.context); assert(created.code === "CANDIDATE_CREATED", created.code); });
test("低风险判断通过", () => { const result = adapter.riskCheck({ candidateId: created.candidate.candidateId }, success.context); assert(result.risk.decision === "auto_publish", JSON.stringify(result.risk)); });
test("本人确认通过", () => { const result = adapter.confirm({ candidateId: created.candidate.candidateId, action: "KEEP", riskNoticeShown: true }, success.context); assert(result.code === "USER_CONFIRMED", result.code); });
test("低风险版本发布", () => { const result = adapter.publish({ candidateId: created.candidate.candidateId, ...success.context }); assert(result.code === "VERSION_SAVED", result.code); });
test("证据不足被拦截", () => { const blocked = load("blocked-missing-evidence.json"); const item = adapter.createCandidate(blocked.candidate, blocked.context); const result = adapter.riskCheck({ candidateId: item.candidate.candidateId }, blocked.context); assert(result.risk.decision === "need_more_evidence" && result.risk.blocked, JSON.stringify(result.risk)); });
test("审计覆盖关键事件", () => { const events = new Set(adapter.getAuditLog().map((entry) => entry.eventType)); assert(events.has("CANDIDATE_CREATED") && events.has("RISK_CHECKED") && events.has("USER_CONFIRMED") && events.has("VERSION_PUBLISHED"), [...events].join(",")); });

console.log(results.join("\n"));
const failed = results.filter((line) => line.startsWith("FAIL"));
console.log(`联调核心测试：${results.length - failed.length}/${results.length} 通过`);
process.exitCode = failed.length ? 1 : 0;
