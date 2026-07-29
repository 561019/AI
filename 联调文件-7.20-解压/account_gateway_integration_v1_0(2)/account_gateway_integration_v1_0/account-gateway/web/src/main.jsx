import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Bot,
  Building2,
  CheckCircle2,
  ClipboardList,
  Database,
  Eye,
  Fingerprint,
  KeyRound,
  Layers3,
  LogIn,
  LockKeyhole,
  LogOut,
  Network,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Users,
  XCircle
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const JWT_SECRET = "change-me";
const ORG_ID = "casdoor-e2e-org";
const LOGIN_PASSWORD = "123456";

const frontAccounts = [
  {
    id: "manager",
    name: "李志刚",
    account: "user_li_zhigang",
    role: "华南大区销售负责人",
    department: "华南大区销售",
    avatar: "李",
    summary: "可查看区域经营态势，在职责范围内授权和推广经验资产。",
    panels: ["大区经营", "知识库维护", "授权", "经验推广"],
    hidden: ["应急处理界面", "组织信息管理"]
  },
  {
    id: "sales",
    name: "付盛贤",
    account: "user_fu_shengxian",
    role: "华南一线销售",
    department: "华南大区销售",
    avatar: "付",
    summary: "只能看自己的客户数据，可使用部门授予的 Agent 和工具能力。",
    panels: ["工作汇报", "我的 Agent", "自创 Agent"],
    hidden: ["大区经营", "数据安全治理台", "应急处理界面"]
  },
  {
    id: "breakglass",
    name: "应急监察账号",
    account: "user_breakglass_decision",
    role: "集团决策层",
    department: "集团",
    avatar: "急",
    summary: "平时关闭，应急启用后出现跨常规边界处理入口并强制留痕。",
    panels: ["应急处理界面", "审计复盘"],
    hidden: ["工作汇报", "自创 Agent"]
  },
  {
    id: "hr",
    name: "HR 信息源",
    account: "user_hr_source",
    role: "组织关系维护",
    department: "人力资源部",
    avatar: "HR",
    summary: "只维护部门、岗位、汇报线和在岗状态，不直接决定业务数据权限。",
    panels: ["组织信息管理"],
    hidden: ["大区经营", "数据安全治理台", "应急处理界面"]
  },
  {
    id: "dsm",
    name: "安志诚",
    account: "user_an_zhicheng",
    role: "数据安全官",
    department: "品质管理中心",
    avatar: "安",
    summary: "负责数据取存放行、权限治理和授权链路审计。",
    panels: ["数据安全治理台", "授权", "部门资源池"],
    hidden: ["大区经营", "应急处理界面"]
  },
  {
    id: "asset",
    name: "资产池账号",
    account: "user_asset_pool",
    role: "Agent / 技能 / 知识库",
    department: "资产池",
    avatar: "产",
    summary: "管理工具、技能、知识库等资产，发布或升层时进入治理流程。",
    panels: ["部门资源池", "授权", "经验推广"],
    hidden: ["工作汇报", "应急处理界面"]
  }
];

const panelCatalog = {
  "工作汇报": {
    icon: Activity,
    text: "使用本人客户数据生成日报、周报和跟进材料。",
    tags: ["本人数据", "每次校验", "留痕"]
  },
  "我的 Agent": {
    icon: Bot,
    text: "调用部门授予的数字员工和工具能力。",
    tags: ["责任归人", "工具可用", "不带数据权"]
  },
  "自创 Agent": {
    icon: Layers3,
    text: "创建和打磨个人 Agent，不新增数据暴露时无需审批。",
    tags: ["个人资产", "自由打磨", "发布再审批"]
  },
  "大区经营": {
    icon: Network,
    text: "查看本管理域内经营看板和客户态势。",
    tags: ["管理域", "下属树", "区域边界"]
  },
  "知识库维护": {
    icon: Database,
    text: "维护区域知识库，把经验沉淀为可复用资产。",
    tags: ["知识沉淀", "版本留痕", "范围可控"]
  },
  "授权": {
    icon: ShieldCheck,
    text: "在本人职责范围内进行岗位配置或个性化转授。",
    tags: ["岗位标准", "转授链路", "可追溯"]
  },
  "经验推广": {
    icon: Sparkles,
    text: "将成熟经验或资源从个人升层到部门范围。",
    tags: ["资源升层", "审批通过", "部门公共"]
  },
  "数据安全治理台": {
    icon: Eye,
    text: "登记数据可取、可存和授权依据，治理数据访问边界。",
    tags: ["数据权限", "制度依据", "审计"]
  },
  "部门资源池": {
    icon: Building2,
    text: "管理工具、技能、知识库等资源的可见范围。",
    tags: ["资产目录", "发布升层", "公司公共"]
  },
  "组织信息管理": {
    icon: Users,
    text: "维护组织、岗位、挂岗和汇报关系等组织事实。",
    tags: ["组织事实", "人岗关系", "不定业务权限"]
  },
  "应急处理界面": {
    icon: LockKeyhole,
    text: "应急启用后临时开放，访问必须记录原因和工单。",
    tags: ["临时启用", "强制审计", "复盘"]
  },
  "审计复盘": {
    icon: ClipboardList,
    text: "查看应急访问链路和关键操作记录。",
    tags: ["访问链路", "责任追溯", "复盘"]
  }
};

const scenarios = [
  {
    id: "sales",
    title: "一线销售访问客户数据",
    person: "付盛贤",
    account: "user_fu_shengxian",
    role: "华南一线销售",
    subject: "huazhong_sales",
    resourceType: "data",
    resourceId: "/sales/huazhong/opportunities",
    action: "read",
    owner: "user_id_sales_001",
    expectation: "允许",
    policy: "岗位标准配置",
    audit: "auth.validate allow",
    allow: true
  },
  {
    id: "manager",
    title: "区域负责人查看经营看板",
    person: "李志刚",
    account: "user_li_zhigang",
    role: "华南大区销售负责人",
    subject: "huazhong_region_manager",
    resourceType: "data",
    resourceId: "/region/huazhong/report",
    action: "read",
    owner: "*",
    expectation: "允许",
    policy: "管理域范围",
    audit: "auth.validate allow",
    allow: true
  },
  {
    id: "agent",
    title: "数字员工调用工具",
    person: "销售 Agent",
    account: "agent_sales_assistant",
    role: "数字员工",
    subject: "digital_employee",
    resourceType: "tool",
    resourceId: "/tools/media-generator",
    action: "use",
    owner: "user_fu_shengxian",
    expectation: "允许",
    policy: "责任真人授权",
    audit: "digital_employee_parent_tool",
    allow: true
  },
  {
    id: "blocked",
    title: "越权读取其他区域数据",
    person: "付盛贤",
    account: "user_fu_shengxian",
    role: "华南一线销售",
    subject: "huazhong_sales",
    resourceType: "data",
    resourceId: "/region/north/report",
    action: "read",
    owner: "north_region_owner",
    expectation: "拒绝",
    policy: "无匹配策略",
    audit: "auth.validate deny",
    allow: false
  }
];

const flow = [
  {
    key: "identity",
    title: "统一身份进入",
    short: "识别当前操作者",
    icon: Fingerprint
  },
  {
    key: "gateway",
    title: "网关校验请求",
    short: "整理人、岗、资源、动作",
    icon: ShieldCheck
  },
  {
    key: "policy",
    title: "策略系统判断权限",
    short: "按岗位、域、转授、资源范围决策",
    icon: LockKeyhole
  },
  {
    key: "audit",
    title: "写入审计留痕",
    short: "记录允许、拒绝和策略来源",
    icon: ClipboardList
  }
];

function App() {
  const [mode, setMode] = useState("front");
  const [selectedId, setSelectedId] = useState("sales");
  const [loginAccountId, setLoginAccountId] = useState("manager");
  const [loggedInAccountId, setLoggedInAccountId] = useState(null);
  const [password, setPassword] = useState(LOGIN_PASSWORD);
  const [loginError, setLoginError] = useState("");
  const [activeStep, setActiveStep] = useState(-1);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [events, setEvents] = useState([]);
  const scenario = useMemo(
    () => scenarios.find((item) => item.id === selectedId) || scenarios[0],
    [selectedId]
  );

  const reset = () => {
    setActiveStep(-1);
    setRunning(false);
    setResult(null);
    setEvents([]);
  };

  const runDemo = async () => {
    reset();
    setRunning(true);
    const trail = [];
    for (let i = 0; i < flow.length; i += 1) {
      await wait(520);
      setActiveStep(i);
      trail.push(eventForStep(flow[i].key, scenario));
      setEvents([...trail]);
    }
    const response = await validateScenario(scenario);
    setResult(response);
    setRunning(false);
  };

  return (
    <main className="demo-shell">
      <header className="topbar">
        <div className="brand">
          <span><KeyRound size={22} /></span>
          <div>
            <strong>账号网关后台演示</strong>
            <em>统一身份进入 → 网关校验请求 → 策略判断权限 → 审计留痕</em>
          </div>
        </div>
        <div className="mode-tabs" aria-label="演示模式">
          <button className={mode === "front" ? "active" : ""} onClick={() => setMode("front")}>前台</button>
          <button className={mode === "backend" ? "active" : ""} onClick={() => setMode("backend")}>后台</button>
        </div>
        <div className="top-actions">
          {mode === "backend" ? (
            <>
              <button onClick={reset} disabled={running}><RefreshCw size={16} />重置</button>
              <button className="primary" onClick={runDemo} disabled={running}><Play size={16} />运行链路</button>
            </>
          ) : (
            <button className="primary" onClick={() => setMode("backend")}><ShieldCheck size={16} />查看后台校验</button>
          )}
        </div>
      </header>

      {mode === "front" ? (
        loggedInAccountId ? (
          <FrontDemo
            accountId={loggedInAccountId}
            setAccountId={setLoggedInAccountId}
            onLogout={() => setLoggedInAccountId(null)}
          />
        ) : (
          <LoginScreen
            accountId={loginAccountId}
            setAccountId={setLoginAccountId}
            password={password}
            setPassword={setPassword}
            error={loginError}
            onLogin={() => {
              if (password !== LOGIN_PASSWORD) {
                setLoginError("演示密码为 123456");
                return;
              }
              setLoginError("");
              setLoggedInAccountId(loginAccountId);
            }}
          />
        )
      ) : (
      <section className="workspace">
        <aside className="scenario-panel">
          <div className="section-title">
            <span>演示场景</span>
            <strong>选择一次真实访问</strong>
          </div>
          <div className="scenario-list">
            {scenarios.map((item) => (
              <button
                className={item.id === selectedId ? "active" : ""}
                key={item.id}
                onClick={() => {
                  setSelectedId(item.id);
                  reset();
                }}
              >
                <strong>{item.title}</strong>
                <span>{item.person} · {item.role}</span>
                <em className={item.allow ? "allow" : "deny"}>{item.expectation}</em>
              </button>
            ))}
          </div>
        </aside>

        <section className="main-stage">
          <article className="focus-card">
            <div>
              <span>当前访问</span>
              <h1>{scenario.title}</h1>
              <p>{scenario.person} 以 {scenario.role} 身份访问 {scenario.resourceType} 资源，网关负责在访问前给出可解释决策。</p>
            </div>
            <DecisionBadge result={result} scenario={scenario} running={running} />
          </article>

          <article className="flow-board">
            {flow.map((step, index) => (
              <FlowStep
                key={step.key}
                step={step}
                index={index}
                activeStep={activeStep}
                scenario={scenario}
              />
            ))}
          </article>

          <article className="request-panel">
            <div className="section-title">
              <span>网关收到的请求摘要</span>
              <strong>人、资源、动作、归属</strong>
            </div>
            <div className="request-grid">
              <Info label="账号" value={scenario.account} />
              <Info label="主体" value={scenario.subject} />
              <Info label="资源类型" value={scenario.resourceType} />
              <Info label="资源 ID" value={scenario.resourceId} />
              <Info label="动作" value={scenario.action} />
              <Info label="Owner" value={scenario.owner} />
            </div>
          </article>
        </section>

        <aside className="evidence-panel">
          <div className="section-title">
            <span>判断依据</span>
            <strong>策略与审计</strong>
          </div>
          <div className="evidence-stack">
            <Evidence icon={UserCheck} label="身份识别" value={`${scenario.person} / ${scenario.role}`} done={activeStep >= 0} />
            <Evidence icon={Database} label="请求校验" value={`${scenario.resourceType}:${scenario.action}`} done={activeStep >= 1} />
            <Evidence icon={ShieldCheck} label="策略来源" value={result?.policy_id || scenario.policy} done={activeStep >= 2} warning={!scenario.allow} />
            <Evidence icon={ClipboardList} label="审计结果" value={result?.audit || scenario.audit} done={activeStep >= 3} warning={!scenario.allow} />
          </div>

          <div className="event-log">
            <div className="section-title">
              <span>链路轨迹</span>
              <strong>{events.length ? "已记录" : "等待运行"}</strong>
            </div>
            {events.length === 0 ? (
              <div className="empty">点击“运行链路”后展示每一步后台处理结果。</div>
            ) : (
              events.map((event, index) => (
                <div key={`${event}-${index}`}>
                  <b>{String(index + 1).padStart(2, "0")}</b>
                  <span>{event}</span>
                </div>
              ))
            )}
          </div>
        </aside>
        <FrameworkDiagramPanel />
      </section>
      )}
    </main>
  );
}

function FrameworkDiagramPanel() {
  return (
    <article className="framework-card">
      <div className="section-title">
        <span>系统框架图</span>
        <strong>账号网关整体架构</strong>
      </div>
      <div className="framework-preview">
        <img src="/account-gateway-system-architecture.png" alt="账号网关系统框架图" />
      </div>
      <div className="framework-actions">
        <a href="/account-gateway-system-architecture.png" target="_blank" rel="noreferrer">打开大图</a>
        <a href="/account-gateway-system-architecture.html" target="_blank" rel="noreferrer">HTML 源图</a>
      </div>
    </article>
  );
}

function LoginScreen({ accountId, setAccountId, password, setPassword, error, onLogin }) {
  const selected = frontAccounts.find((item) => item.id === accountId) || frontAccounts[0];
  return (
    <section className="login-stage">
      <article className="login-copy">
        <span>账号网关前台登录</span>
        <h1>不同账号登录后，只看到自己被授权的业务入口。</h1>
        <p>演示重点是“统一身份进入”：先选择一个账号登录，再进入前台查看权限差异；需要解释后台原理时，再切到后台看网关校验链路。</p>
        <div className="login-flow">
          <b>登录身份</b>
          <i />
          <b>按权限渲染</b>
          <i />
          <b>访问前校验</b>
          <i />
          <b>审计留痕</b>
        </div>
      </article>

      <article className="login-panel">
        <div className="section-title">
          <span>选择账号</span>
          <strong>6 个演示身份</strong>
        </div>
        <div className="login-account-grid">
          {frontAccounts.map((item) => (
            <button className={item.id === selected.id ? "active" : ""} key={item.id} onClick={() => setAccountId(item.id)}>
              <b>{item.avatar}</b>
              <strong>{item.name}</strong>
              <span>{item.role}</span>
            </button>
          ))}
        </div>
        <label className="login-field">
          <span>演示密码</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" />
        </label>
        {error && <div className="login-error">{error}</div>}
        <button className="primary login-submit" onClick={onLogin}><LogIn size={16} />登录 {selected.name}</button>
      </article>
    </section>
  );
}

function FrontDemo({ accountId, setAccountId, onLogout }) {
  const account = frontAccounts.find((item) => item.id === accountId) || frontAccounts[0];
  return (
    <section className="front-shell">
      <aside className="front-sidebar">
        <div className="section-title">
          <span>前台身份</span>
          <strong>按人显示</strong>
        </div>
        <div className="front-account-list">
          {frontAccounts.map((item) => (
            <button className={item.id === account.id ? "active" : ""} key={item.id} onClick={() => setAccountId(item.id)}>
              <b>{item.avatar}</b>
              <strong>{item.name}</strong>
              <span>{item.role}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="front-main">
        <article className="front-hero">
          <div className="front-identity">
            <b>{account.avatar}</b>
            <div>
              <span>当前登录人</span>
              <h1>{account.name}</h1>
              <p>{account.role} · {account.department}</p>
            </div>
          </div>
          <button onClick={onLogout}><LogOut size={16} />退出登录</button>
        </article>

        <article className="front-explain">
          <div>
            <span>前台展示原则</span>
            <strong>用户只看到自己被授权的功能入口</strong>
          </div>
          <p>{account.summary}</p>
        </article>

        <div className="panel-grid">
          {account.panels.map((panelName) => (
            <FeaturePanel key={panelName} name={panelName} />
          ))}
        </div>

        <article className="hidden-strip">
          <div>
            <span>不可见入口</span>
            <strong>未授权能力不会出现在前台</strong>
          </div>
          <div>
            {account.hidden.map((item) => <em key={item}>{item}</em>)}
          </div>
        </article>
      </section>
    </section>
  );
}

function FeaturePanel({ name }) {
  const panel = panelCatalog[name] || panelCatalog["授权"];
  const Icon = panel.icon;
  return (
    <article className="feature-panel">
      <div>
        <Icon size={22} />
        <strong>{name}</strong>
      </div>
      <p>{panel.text}</p>
      <footer>
        {panel.tags.map((tag) => <span key={tag}>{tag}</span>)}
      </footer>
    </article>
  );
}

function FlowStep({ step, index, activeStep, scenario }) {
  const Icon = step.icon;
  const done = activeStep > index;
  const active = activeStep === index;
  const waiting = activeStep < index;
  return (
    <div className={`flow-step ${done ? "done" : ""} ${active ? "active" : ""} ${waiting ? "waiting" : ""}`}>
      <div className="step-number">{index + 1}</div>
      <div className="step-icon"><Icon size={24} /></div>
      <strong>{step.title}</strong>
      <span>{step.short}</span>
      <small>{detailForStep(step.key, scenario)}</small>
    </div>
  );
}

function DecisionBadge({ result, scenario, running }) {
  const allow = result ? result.allow : scenario.allow;
  return (
    <div className={`decision-badge ${allow ? "allow" : "deny"} ${running ? "running" : ""}`}>
      {allow ? <CheckCircle2 size={26} /> : <XCircle size={26} />}
      <span>{running ? "判断中" : allow ? "允许访问" : "拒绝访问"}</span>
      <strong>{result?.source || scenario.policy}</strong>
    </div>
  );
}

function Evidence({ icon: Icon, label, value, done, warning }) {
  return (
    <div className={`evidence ${done ? "done" : ""} ${warning ? "warning" : ""}`}>
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Info({ label, value }) {
  return (
    <div className="info">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function eventForStep(key, scenario) {
  switch (key) {
    case "identity":
      return `识别 ${scenario.person}，确认账号与角色上下文`;
    case "gateway":
      return `解析资源 ${scenario.resourceId} 与动作 ${scenario.action}`;
    case "policy":
      return `${scenario.policy}：${scenario.expectation}`;
    case "audit":
      return `写入审计：${scenario.audit}`;
    default:
      return "处理完成";
  }
}

function detailForStep(key, scenario) {
  switch (key) {
    case "identity":
      return scenario.account;
    case "gateway":
      return `${scenario.resourceType} · ${scenario.action}`;
    case "policy":
      return scenario.policy;
    case "audit":
      return scenario.audit;
    default:
      return "";
  }
}

async function validateScenario(scenario) {
  const token = issueJwt({
    user_id: scenario.account,
    org_id: ORG_ID,
    role_list: [scenario.subject, "staff"]
  });
  try {
    const response = await fetch(`${API_BASE}/auth/validate`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Request-ID": `demo-${Date.now()}`,
        "X-Client-ID": "visual-backend-demo",
        "X-User-ID": scenario.account,
        "X-Resource-Type": scenario.resourceType,
        "X-Resource-ID": scenario.resourceId,
        "X-Resource-Owner-ID": scenario.owner,
        "X-Action": scenario.action,
        "X-Tenant-ID": ORG_ID
      }
    });
    const body = await response.json().catch(() => ({}));
    return {
      allow: typeof body.allow === "boolean" ? body.allow : scenario.allow,
      policy_id: body.policy_id || body.reason || scenario.policy,
      audit: scenario.audit,
      source: response.ok ? "实时网关返回" : "网关返回异常"
    };
  } catch {
    return {
      allow: scenario.allow,
      policy_id: scenario.policy,
      audit: `${scenario.audit} · 演示模式`,
      source: "演示模式"
    };
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function issueJwt(payload) {
  const now = Math.floor(Date.now() / 1000);
  const fullPayload = { iat: now, exp: now + 3600, ...payload };
  const header = base64Url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = base64Url(JSON.stringify(fullPayload));
  const input = `${header}.${body}`;
  return `${input}.${hmacSha256(input, JWT_SECRET)}`;
}

function hmacSha256(message, secret) {
  const key = new TextEncoder().encode(secret);
  const data = new TextEncoder().encode(message);
  const blockSize = 64;
  const normalizedKey = key.length > blockSize ? sha256(key) : key;
  const padded = new Uint8Array(blockSize);
  padded.set(normalizedKey);
  const outer = new Uint8Array(blockSize);
  const inner = new Uint8Array(blockSize);
  for (let i = 0; i < blockSize; i += 1) {
    outer[i] = padded[i] ^ 0x5c;
    inner[i] = padded[i] ^ 0x36;
  }
  return base64UrlBytes(sha256(concat(outer, sha256(concat(inner, data)))));
}

function sha256(bytes) {
  const words = [];
  const bitLength = bytes.length * 8;
  for (let i = 0; i < bytes.length; i += 1) words[i >> 2] |= bytes[i] << (24 - (i % 4) * 8);
  words[bitLength >> 5] |= 0x80 << (24 - (bitLength % 32));
  words[(((bitLength + 64) >> 9) << 4) + 15] = bitLength;
  const h = [1779033703, 3144134277, 1013904242, 2773480762, 1359893119, 2600822924, 528734635, 1541459225];
  const k = [1116352408,1899447441,3049323471,3921009573,961987163,1508970993,2453635748,2870763221,3624381080,310598401,607225278,1426881987,1925078388,2162078206,2614888103,3248222580,3835390401,4022224774,264347078,604807628,770255983,1249150122,1555081692,1996064986,2554220882,2821834349,2952996808,3210313671,3336571891,3584528711,113926993,338241895,666307205,773529912,1294757372,1396182291,1695183700,1986661051,2177026350,2456956037,2730485921,2820302411,3259730800,3345764771,3516065817,3600352804,4094571909,275423344,430227734,506948616,659060556,883997877,958139571,1322822218,1537002063,1747873779,1955562222,2024104815,2227730452,2361852424,2428436474,2756734187,3204031479,3329325298];
  const w = new Array(64);
  for (let i = 0; i < words.length; i += 16) {
    let [a, b, c, d, e, f, g, hh] = h;
    for (let j = 0; j < 64; j += 1) {
      if (j < 16) w[j] = words[i + j] | 0;
      else {
        const s0 = rotr(w[j - 15], 7) ^ rotr(w[j - 15], 18) ^ (w[j - 15] >>> 3);
        const s1 = rotr(w[j - 2], 17) ^ rotr(w[j - 2], 19) ^ (w[j - 2] >>> 10);
        w[j] = (w[j - 16] + s0 + w[j - 7] + s1) | 0;
      }
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (hh + s1 + ch + k[j] + w[j]) | 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + maj) | 0;
      hh = g; g = f; f = e; e = (d + temp1) | 0; d = c; c = b; b = a; a = (temp1 + temp2) | 0;
    }
    h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0; h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0; h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
  }
  const out = new Uint8Array(32);
  h.forEach((word, index) => {
    out[index * 4] = word >>> 24;
    out[index * 4 + 1] = word >>> 16;
    out[index * 4 + 2] = word >>> 8;
    out[index * 4 + 3] = word;
  });
  return out;
}

function rotr(value, bits) {
  return (value >>> bits) | (value << (32 - bits));
}

function concat(a, b) {
  const out = new Uint8Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
}

function base64Url(input) {
  return btoa(unescape(encodeURIComponent(input))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlBytes(bytes) {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

createRoot(document.getElementById("root")).render(<App />);
