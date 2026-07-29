#!/usr/bin/env python3
"""安全合规模块 —— 独立启动脚本。

使用方式：
    python run.py                # 默认 127.0.0.1:8002
    python run.py --port 8080    # 自定义端口
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="安全合规模块 (1.9 Security Compliance)")
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8002, help="绑定端口 (默认: 8002)")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════╗
║     1.9 安全合规模块 - 独立版                ║
║                                              ║
║  前端: http://{args.host}:{args.port}/frontend/check.html ║
║  API:  http://{args.host}:{args.port}/docs              ║
║  健康: http://{args.host}:{args.port}/health            ║
╚══════════════════════════════════════════════╝
""")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
