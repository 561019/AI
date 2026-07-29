const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const packageRoot = path.resolve(__dirname, "..", "..");

const createLocalStorage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear()
  };
};

const createAdapter = () => {
  const window = { localStorage: createLocalStorage() };
  const context = { window, console, Date, Math, JSON };
  vm.createContext(context);
  ["用户Agent模拟存储_v2.js", "1.4风险判断_v2.js", "1.3治理服务_v3.js"].forEach((file) => {
    const source = fs.readFileSync(path.join(packageRoot, "demo", file), "utf8");
    vm.runInContext(source, context, { filename: file });
  });
  const governance = window.JinhuajizhiGovernanceServiceV3;
  if (!governance) throw new Error("1.3治理服务未加载");
  return {
    createCandidate: (input, ctx) => governance.createCandidate(input, ctx),
    getCandidate: (candidateId) => governance.getCandidate(candidateId),
    riskCheck: (input, ctx) => governance.riskCheck(input, ctx),
    confirm: (input, ctx) => governance.confirm(input, ctx),
    approve: (input, ctx) => governance.approve(input, ctx),
    publish: (input) => governance.publish(input),
    rollback: (input) => governance.rollback(input),
    getAuditLog: (filters) => governance.getAuditLog(filters),
    reset: () => governance.reset()
  };
};

module.exports = { createAdapter };
