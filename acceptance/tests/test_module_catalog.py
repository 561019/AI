from __future__ import annotations

from framework.module_catalog import ALL_MODULES, additional_capabilities
from framework.run_services import SERVICES
from framework.server import ENDPOINTS, SERVICE_MODULES


def test_all_catalog_modules_have_services_and_docs() -> None:
    for module in ALL_MODULES:
        service_name = module.code.replace("-", "_")
        assert service_name in SERVICES
        assert service_name in SERVICE_MODULES
        assert service_name in ENDPOINTS
        assert any(module.interface in endpoint for endpoint in ENDPOINTS[service_name])


def test_inserted_capabilities_are_unique() -> None:
    rows = additional_capabilities()
    codes = [row[0] for row in rows]
    assert len(codes) == len(set(codes))
    assert len(codes) >= 80
