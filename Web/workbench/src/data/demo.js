export const accounts = [
  {
    id: 'account-leader-001',
    name: '李志刚',
    role: '华南大区负责人',
    department: '集团经营管理中心',
    avatar: '李',
    permissions: [
      'report.read.own', 'report.write.own', 'report.read.team', 'team.read', 'team.activity.read',
      'resource.group.manage', 'knowledge.group.view', 'knowledge.group.supplement', 'knowledge.group.maintain', 'knowledge.group.grant',
    ],
  },
  {
    id: 'account-sales-001',
    name: '付盛贤',
    role: '业务员',
    department: '华南大区业务部',
    avatar: '付',
    permissions: ['report.read.own', 'report.write.own', 'knowledge.group.view', 'knowledge.group.supplement', 'knowledge.group.maintain'],
  },
  {
    id: 'account-purchase-001',
    name: '唐海玲',
    role: '采购员',
    department: '集团采购部',
    avatar: '唐',
    permissions: ['report.read.own', 'report.write.own', 'knowledge.group.view', 'knowledge.group.maintain'],
  },
  {
    id: 'account-finance-001',
    name: '赵一繁',
    role: '财务人员',
    department: '集团财务部',
    avatar: '赵',
    permissions: ['report.read.own', 'report.write.own', 'knowledge.group.view', 'knowledge.group.maintain'],
  },
  {
    id: 'account-kb-admin-001',
    name: '王敏',
    role: '知识库管理员',
    department: '集团数字资产中心',
    avatar: '王',
    permissions: ['knowledge.group.grant'],
  },
]

export const teamMembers = [
  { id: 'employee-01', name: '付盛贤', role: '客户经理', status: '在线', report: '已提交', activity: '刚刚', load: 72 },
  { id: 'employee-02', name: '员工2', role: '区域主管', status: '忙碌', report: '已提交', activity: '8 分钟前', load: 86 },
  { id: 'employee-03', name: '唐海玲', role: '采购专员', status: '离线', report: '待提交', activity: '2 小时前', load: 44 },
  { id: 'employee-04', name: '赵一繁', role: '财务专员', status: '在线', report: '已提交', activity: '12 分钟前', load: 61 },
]

const commonMessages = (title) => [
  {
    id: `${title}-1`,
    role: 'assistant',
    text: `这里是“${title}”对话。我已按当前账号权限读取本 Project 的相关上下文。`,
    source: 'Project 上下文已同步',
  },
  {
    id: `${title}-2`,
    role: 'user',
    text: '先帮我整理目前的重点和下一步建议。',
  },
  {
    id: `${title}-3`,
    role: 'assistant',
    text: '已完成初步梳理。当前有 1 项需要本人确认，确认后我会生成追踪编号并继续执行。',
    source: '当前对话 · Project 知识库',
    task: {
      type: 'intent',
      title: '请确认任务理解',
      items: ['目标：形成可执行的下一步方案', '范围：当前对话与本 Project 资料', '交付：行动清单与一页简报'],
    },
  },
]

export const projects = [
  {
    id: 'project-report',
    name: '我的工作汇报',
    short: '工作汇报',
    type: 'report',
    fixed: true,
    description: '撰写、提交和查看工作汇报',
    status: '本周进行中',
    metrics: [
      { label: '本周完成', value: '7' },
      { label: '待补充', value: '2', tone: 'warning' },
      { label: '历次汇报', value: '18' },
    ],
    knowledge: [
      { name: '工作汇报标准模板.docx', meta: '系统固定 · v2.1', tone: 'warm' },
      { name: '2026 年个人工作目标.pdf', meta: '本人上传 · 3.2 MB', tone: 'blue' },
      { name: '部门季度重点事项.xlsx', meta: '部门共享 · 860 KB', tone: 'green' },
    ],
    conversations: [
      {
        id: 'report-current',
        title: '本周工作汇报',
        updated: '10 分钟前',
        badge: '待完善',
        messages: commonMessages('本周工作汇报'),
        files: [
          { name: '本周客户拜访记录.docx', meta: '对话引用 · 今天 09:20' },
          { name: '销售推进清单.xlsx', meta: '本人上传 · 今天 08:45' },
        ],
      },
      {
        id: 'report-history',
        title: '历次汇报回顾',
        updated: '昨天',
        messages: commonMessages('历次汇报回顾'),
        files: [{ name: '2026 上半年汇报汇总.pdf', meta: 'AI 生成 · 昨天 16:10' }],
      },
      {
        id: 'report-team-review',
        title: '团队汇报总览',
        updated: '刚刚',
        badge: '负责人',
        permission: 'report.read.team',
        messages: commonMessages('团队汇报总览'),
        files: [{ name: '华南大区本周汇报汇总.xlsx', meta: '系统归集 · 刚刚' }],
      },
    ],
  },
  {
    id: 'project-team',
    name: '我的队伍',
    short: '队伍',
    type: 'team',
    fixed: true,
    description: '查看队伍、成员状态和协作事项',
    status: '4 名成员',
    metrics: [
      { label: '成员', value: '4' },
      { label: '今日活跃', value: '3' },
      { label: '待提交汇报', value: '1', tone: 'warning' },
    ],
    knowledge: [
      { name: '团队岗位与职责说明.pdf', meta: 'Project 文件 · v3.0', tone: 'blue' },
      { name: '团队协作规范.docx', meta: 'Project 文件 · v1.7', tone: 'warm' },
    ],
    conversations: [
      {
        id: 'team-overview',
        title: '队伍状态总览',
        updated: '5 分钟前',
        permission: 'team.read',
        messages: commonMessages('队伍状态总览'),
        files: [{ name: '团队活跃状态快照.xlsx', meta: '系统生成 · 5 分钟前' }],
      },
      {
        id: 'team-collaboration',
        title: '本周协作事项',
        updated: '1 小时前',
        messages: commonMessages('本周协作事项'),
        files: [{ name: '跨岗位协作事项清单.docx', meta: '对话引用 · 1 小时前' }],
      },
    ],
  },
  {
    id: 'project-customer',
    name: '重点客户经营',
    short: '客户经营',
    type: 'custom',
    description: '客户画像、拜访和续约推进',
    status: '1 项待确认',
    metrics: [
      { label: '重点客户', value: '12' },
      { label: '进行中任务', value: '4' },
      { label: '待确认', value: '1', tone: 'warning' },
    ],
    knowledge: [
      { name: '重点客户分级标准.pdf', meta: 'Project 文件 · v4.2', tone: 'blue' },
      { name: '客户拜访最佳实践.docx', meta: 'Project 文件 · 28 页', tone: 'warm' },
      { name: '续约报价规则.xlsx', meta: 'Project 文件 · 今日更新', tone: 'green' },
    ],
    conversations: [
      {
        id: 'customer-expert',
        title: '专家能力平民化',
        updated: '刚刚',
        badge: '执行中',
        messages: commonMessages('专家能力平民化'),
        files: [
          { name: '付盛贤客户经营方法.docx', meta: '当前对话引用 · v0.5' },
          { name: '绿城客户画像.pdf', meta: 'Project 引用 · 2.6 MB' },
        ],
      },
      {
        id: 'customer-renewal',
        title: '绿城续约跟进',
        updated: '20 分钟前',
        badge: '待审批',
        messages: commonMessages('绿城续约跟进'),
        files: [{ name: '绿城续约合同_草案.pdf', meta: '用户上传 · v2' }],
      },
      {
        id: 'customer-visit',
        title: '重点客户拜访计划',
        updated: '昨天',
        messages: commonMessages('重点客户拜访计划'),
        files: [{ name: '7 月客户拜访排期.xlsx', meta: 'AI 生成 · 昨天' }],
      },
    ],
  },
  {
    id: 'project-analysis',
    name: '经营分析与预测',
    short: '分析预测',
    type: 'custom',
    description: '经营数据分析、预测和管理汇报',
    status: '数据已更新',
    metrics: [
      { label: '数据源', value: '6' },
      { label: '分析任务', value: '3' },
      { label: '最新成果', value: '8' },
    ],
    knowledge: [
      { name: '经营指标口径手册.pdf', meta: 'Project 文件 · v5.1', tone: 'blue' },
      { name: '月度分析模板.pptx', meta: 'Project 文件 · v2.4', tone: 'warm' },
    ],
    conversations: [
      {
        id: 'analysis-monthly',
        title: '7 月经营情况分析',
        updated: '30 分钟前',
        messages: commonMessages('7 月经营情况分析'),
        files: [{ name: '华南大区7月经营表.xlsx', meta: '经营系统 · 今天 08:45' }],
      },
      {
        id: 'analysis-forecast',
        title: '季度回款预测',
        updated: '昨天',
        messages: commonMessages('季度回款预测'),
        files: [{ name: '回款预测输入数据.xlsx', meta: '财务系统 · 昨天' }],
      },
    ],
  },
  {
    id: 'project-risk',
    name: '风险监控',
    short: '风险监控',
    type: 'custom',
    description: '价格、回款与履约风险自动预警',
    status: '2 项预警',
    metrics: [
      { label: '监控规则', value: '18' },
      { label: '风险预警', value: '2', tone: 'danger' },
      { label: '处理中', value: '1' },
    ],
    knowledge: [
      { name: '集团风险分级规则.pdf', meta: 'Project 文件 · v3.6', tone: 'blue' },
      { name: '风险处置流程.docx', meta: 'Project 文件 · v2.0', tone: 'warm' },
    ],
    conversations: [
      {
        id: 'risk-price',
        title: '原料价格上行预警',
        updated: '12 分钟前',
        badge: '风险',
        messages: commonMessages('原料价格上行预警'),
        files: [{ name: '原料价格趋势图.pdf', meta: '系统生成 · 12 分钟前' }],
      },
      {
        id: 'risk-payment',
        title: '客户回款风险排查',
        updated: '2 小时前',
        messages: commonMessages('客户回款风险排查'),
        files: [{ name: '应收账款账龄表.xlsx', meta: '财务系统 · 2 小时前' }],
      },
    ],
  },
]

export const notifications = [
  { id: 'notice-1', title: '绿城续约等待负责人拍板', meta: '紧急 · 今天 17:00', tone: 'danger', projectId: 'project-customer', conversationId: 'customer-renewal', permission: 'report.read.team' },
  { id: 'notice-2', title: '本周工作汇报还有 2 项待补充', meta: '待办 · 今天', tone: 'warning', projectId: 'project-report', conversationId: 'report-current' },
  { id: 'notice-3', title: '原料价格触发二级预警', meta: '风险 · 12 分钟前', tone: 'danger', projectId: 'project-risk', conversationId: 'risk-price' },
  { id: 'notice-4', title: '经营分析结果已生成', meta: '结果 · 30 分钟前', tone: 'success', projectId: 'project-analysis', conversationId: 'analysis-monthly' },
]

export const personalResources = {
  agents: [
    { name: '客户经营 Agent', meta: '个人级 · 运行中', tone: 'green' },
    { name: '工作汇报 Agent', meta: '个人级 · 今日使用', tone: 'green' },
  ],
  skills: [
    { name: '客户拜访纪要生成', meta: '已发布 · v2.1', tone: 'warm' },
    { name: '经营情况归因分析', meta: '公司可用 · v3.0', tone: 'warm' },
  ],
  knowledge: [
    { name: '我的客户经验库', meta: '个人知识库 · 36 个文件', tone: 'blue' },
    { name: '个人工作方法库', meta: '个人知识库 · 18 个文件', tone: 'blue' },
  ],
}

export const agentCatalog = [
  { id: 'agent-group-1', scope: 'group', name: '集团经营分析 Agent', level: '集团 L3', version: 'v3.2', status: '运行中', calls: '1,286 次', adoption: '74%', consistency: '96.8%', detail: '归集经营数据、拆解关键归因并形成管理简报。', recommendation: '建议升至集团 L4' },
  { id: 'agent-group-2', scope: 'group', name: '客户经营 Agent', level: '集团 L2', version: 'v2.7', status: '运行中', calls: '876 次', adoption: '71%', consistency: '95.4%', detail: '根据客户画像、拜访记录和规则提供下一步建议。', recommendation: '已满足升级评估条件' },
  { id: 'agent-personal-1', scope: 'personal', name: '付盛贤客户跟进助手', level: '个人自建', version: 'v1.4', status: '运行中', calls: '42 次', adoption: '88%', consistency: '97.1%', detail: '沉淀本人客户跟进节奏和拜访纪要处理方式。', recommendation: '推荐发布为部门复用' },
]

export const skillCatalog = [
  { id: 'skill-group-1', scope: 'group', name: '经营情况归因分析', level: '集团 S3', status: '已发布', detail: '按收入、回款、成本和客户结构输出归因结论。', recommendation: '建议发布升档至 S4' },
  { id: 'skill-group-2', scope: 'group', name: '客户拜访纪要标准化', level: '集团 S2', status: '已发布', detail: '从文字或语音记录生成纪要、待办和责任人。', recommendation: '质量稳定，可推荐升层' },
  { id: 'skill-personal-1', scope: 'personal', name: '我的客户拜访复盘', level: '个人自建', status: '草稿', detail: '个人常用的客户拜访复盘结构与追问模板。', recommendation: '可提交发布申请' },
]

export const personalKnowledgeBases = [
  { id: 'pkb-1', name: '我的客户经验库', meta: '个人知识库 · 36 个文件', updated: '今天 09:20' },
  { id: 'pkb-2', name: '个人工作方法库', meta: '个人知识库 · 18 个文件', updated: '昨天 17:30' },
]

export const groupKnowledgeBases = [
  {
    id: 'gkb-1',
    governanceCode: 'GKB-001',
    name: '集团经营制度与合规库',
    meta: '集团知识库 · 412 个文件',
    owner: '经营管理中心',
    contentPermission: 'knowledge.group.view',
    stewardIds: ['account-leader-001', 'account-sales-001'],
  },
  {
    id: 'gkb-2',
    governanceCode: 'GKB-002',
    name: '客户经营标准作业库',
    meta: '集团知识库 · 188 个文件',
    owner: '客户经营委员会',
    contentPermission: 'knowledge.group.view',
    stewardIds: ['account-leader-001'],
  },
]

export const sessionTimeline = [
  { time: '10:08', kind: '人工', title: '业务需求发起', detail: '在对话框确认任务目标与交付格式。', evidence: '原始对话、附件 2 份', status: 'done' },
  { time: '10:09', kind: '自动', title: '权限与范围校验', detail: '核对账号身份、Project 范围与可用资料。', evidence: '账号权限快照、Project ACL', status: 'done' },
  { time: '10:11', kind: '自动', title: '资料归集与重复校验', detail: '归集客户画像、规则和最近业务记录，排除重复数据。', evidence: '客户档案、规则版本、数据校验单', status: 'done' },
  { time: '10:16', kind: '人工', title: '负责人确认节点', detail: '关键金额与执行范围等待负责人确认。', evidence: '续约报价草案、风险说明、审批规则', status: 'blocked' },
  { time: '待续', kind: '自动', title: '执行、交付与归档', detail: '确认后恢复自动流程，生成成果并留痕归档。', evidence: '追踪编号、操作记录、产出文件', status: 'pending' },
]
