MODULES = {
    "application-gateway": {"port": 8100, "interface": "/api/v1/application/instructions", "implementation": "application_gateway/service.py"},
    "chat-validation": {"port": 8100, "interface": "/chat", "implementation": "framework/web/chat.html"},
    "trace-monitor": {"port": 8100, "interface": "/monitor", "implementation": "framework/web/monitor.html"},
}
