# Casbin 种子策略映射

`policy_seed.csv` 是面向六类岗位角色的合成种子数据。它只使用占位用户 ID，不建模临时授权或层级分享。

当前 CSV 行格式：`type, priority, role, resource, action, scope, owner, effect, line_ref, description`。

运行期 Casbin 模型使用 `p = sub, obj, typ, act, eft`。因此，`internal/policy/enforcer.go` 中的 `loadCompatibleSeedPolicies` 会把种子 `p` 行转换为：

```text
p, role, resource, *, action, effect
```

其中 `typ` 使用通配符 `*`，由 `internal/policy/model.conf` 中的 `(p.typ == "*" || r.typ == p.typ)` 匹配。

## 种子策略清单

| 行 | 角色 | 效果 | 范围 | HTML 案例 | 用途 |
| --- | --- | --- | --- | --- | --- |
| 1 | `hanhe_admin` | allow | `/admin/:resource`，任意动作 | 295 | 平台管理员可使用应急审计控制台。 |
| 2 | `hanhe_admin` | allow | `/audit/:resource`，read | 295 | 平台管理员可读取审计证据。 |
| 3 | `hanhe_admin` | deny | `/personnel/:resource`，read | 246 | 平台管理员不可读取 HR 源数据。 |
| 4 | `hanhe_admin` | deny | `/asset-pool/:resource`，export | 328 | 平台管理员不可绕过资产池导出控制。 |
| 5 | `huazhong_region_manager` | allow | `/region/huazhong/:resource`，read | 295 | 华中区域经理可查看本区域业务数据。 |
| 6 | `huazhong_region_manager` | allow | `/region/huazhong/:resource`，approve | 30 | 华中区域经理可审批本区域业务流。 |
| 7 | `huazhong_region_manager` | deny | `/region/:region/:resource`，read | 30 | 区域经理跨区域读取被拒绝。 |
| 8 | `huazhong_region_manager` | deny | `/sales/private/:resource`，read | 246 | 区域经理不可读取类似 HR 私密信息的销售人员记录。 |
| 9 | `huazhong_sales` | allow | `/sales/huazhong/opportunities`，read own | 30 | 一线销售可读取自己的华中销售机会。 |
| 10 | `huazhong_sales` | allow | `/sales/huazhong/opportunities`，write own | 30 | 一线销售可更新自己的华中销售机会。 |
| 11 | `huazhong_sales` | deny | `/sales/huazhong/opportunities`，read others | 30 | 一线销售不可读取同事销售机会。 |
| 12 | `huazhong_sales` | deny | `/region/huazhong/report`，approve | 295 | 一线销售不可审批区域报告。 |
| 13 | `hr_source` | allow | `/hr/source/:resource`，read own | 246 | HR 信息源可读取分配给自己的源记录。 |
| 14 | `hr_source` | allow | `/hr/source/:resource`，write own | 246 | HR 信息源可维护分配给自己的源记录。 |
| 15 | `hr_source` | deny | `/hr/source/:resource`，read others | 246 | HR 信息源不可读取分配范围外的记录。 |
| 16 | `hr_source` | deny | `/asset-pool/:resource`，read | 328 | HR 信息源无资产池访问权限。 |
| 17 | `data_owner` | allow | `/data/owned/:dataset`，read own | 328 | 数据所有者可读取自己拥有的数据集。 |
| 18 | `data_owner` | allow | `/data/owned/:dataset`，grant own | 328 | 数据所有者可授予受治理的数据集访问权限。 |
| 19 | `data_owner` | deny | `/data/owned/:dataset`，export own | 328 | 数据所有者不可绕过资产流程直接导出。 |
| 20 | `data_owner` | deny | `/hr/source/:resource`，write | 246 | 数据所有者不可修改 HR 源记录。 |
| 21 | `asset_pool` | allow | `/asset-pool/catalog`，read own | 328 | 资产池角色可读取托管目录。 |
| 22 | `asset_pool` | allow | `/asset-pool/release`，approve own | 328 | 资产池角色可审批受治理的资产发布。 |
| 23 | `asset_pool` | deny | `/asset-pool/release`，approve others | 328 | 资产池角色不可审批不属于自己资产池的发布。 |
| 24 | `asset_pool` | deny | `/region/:region/:resource`，approve | 295 | 资产池角色不可审批区域业务动作。 |

## 角色来源映射

| 种子角色 | HTML 示例角色 | 说明 |
| --- | --- | --- |
| `hanhe_admin` | 应急监管 / 平台管理员 | 仅使用审计与应急控制台权限。 |
| `huazhong_region_manager` | 区域负责人 | 绑定 `huazhong`，不跨区域分享。 |
| `huazhong_sales` | 一线销售 | 绑定自己的占位用户 `user_id_sales_001`。 |
| `hr_source` | HR 信息源 | 绑定自己的占位用户 `user_id_hr_source_001`。 |
| `data_owner` | 数据安全员 / 数据所有者 | 拥有数据集治理权限，不拥有原始导出权限。 |
| `asset_pool` | 资产池 | 只拥有资产目录与发布审批权限。 |

## 当前代码补充策略

`newValidatePolicyAdapter` 目前除了加载并转换 `policy_seed.csv`，还追加了用于运行期校验测试的兼容策略：

- `role_data_writer` 对 `data_record_placeholder` 的 `create`、`update`、`delete` 允许策略；
- `role_data_reader` 对 `data_record_placeholder` 的 `read` 允许策略；
- `user_with_permanent_write -> role_data_writer`；
- `user_with_read -> role_data_reader`。

这些策略支持当前端到端测试中的数据读写用例，但也意味着运行期并非只依赖六角色矩阵。若下一阶段要严格使用六角色矩阵，应移除或迁移这些兼容策略，并同步更新测试用例。
