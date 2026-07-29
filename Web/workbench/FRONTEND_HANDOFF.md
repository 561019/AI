# 前端联调交接说明

## 登录失败的常见原因

当前前端所有后端请求都走 `/api`。开发环境下，Vite 会把 `/api` 代理到后端应用网关。

如果前端同事在自己的电脑运行前端，而后端运行在另一台电脑，不能使用默认的 `127.0.0.1:8100`。因为 `127.0.0.1` 指向前端同事自己的电脑。

## 前端同事本地运行方式

1. 在 `Web/workbench` 下复制环境配置：

```powershell
Copy-Item .\.env.example .\.env.local
```

2. 修改 `.env.local`，把后端地址改成后端所在电脑的局域网 IP：

```env
VITE_PLATFORM_PROXY_TARGET=http://后端电脑IP:8100
VITE_PLATFORM_TENANT_ID=web-workbench
```

例如：

```env
VITE_PLATFORM_PROXY_TARGET=http://192.168.1.100:8100
VITE_PLATFORM_TENANT_ID=web-workbench
```

3. 启动前端：

```powershell
npm.cmd run dev
```

4. 打开 Vite 输出的地址登录。

## 后端电脑需要确认

后端服务必须启动，并且应用网关可访问：

```powershell
Invoke-WebRequest http://127.0.0.1:8100/health
```

如果前端同事从另一台电脑访问，还需要确认局域网能访问：

```text
http://后端电脑IP:8100/health
```

如果局域网访问不了，通常是以下两个原因：

1. 后端服务只绑定本机地址。当前启动脚本默认设置 `PLATFORM_BIND_HOST=0.0.0.0`，重启后端后应监听局域网。
2. Windows 防火墙拦截 8100 端口。需要允许 Python 或 8100 端口通过专用网络。

## 不要改这些文件

除非和后端接口一起确认，否则不要直接改：

```text
src/services/platform-api.js
src/services/auth-api.js
src/services/workspace-api.js
src/services/knowledge-governance-api.js
src/services/agent-management-api.js
```

页面可以改，但请求仍必须通过：

```text
Vue 页面
  ↓
src/services/*.js
  ↓
/api
  ↓
Vite proxy
  ↓
L4 应用网关 8100
```

## 免登录设计模式

前端同事只修改页面、不需要连接后端时，在 `Web/workbench/.env.local` 中加入：

```env
VITE_WORKBENCH_SKIP_AUTH=true
```

然后重启前端：

```powershell
npm.cmd run dev
```

开启后会直接进入工作台主页面，使用本地演示数据，不会调用后端登录接口。

需要真实联调时改回：

```env
VITE_WORKBENCH_SKIP_AUTH=false
```
