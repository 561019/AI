from pathlib import Path

from app.services.embedding.bge_worker import BGEWorkerState
from app.services.embedding.managed_bge_provider import ManagedBGEProvider
from app.services.semantic import LocalIntentCapabilityVectorRepository


def vector_record(*, engine_code: str, task_type: str, vector: list[float]) -> dict:
    return {
        "engine_code": engine_code,
        "task_type": task_type,
        "intent_description": task_type,
        "examples": [],
        "keywords": [],
        "embedding_vector": vector,
    }


def test_local_vector_repository_persists_and_ranks_cosine_similarity(tmp_path: Path) -> None:
    path = tmp_path / "capabilities.npz"
    repository = LocalIntentCapabilityVectorRepository(path=path)
    repository.ensure_collection(dimension=3, recreate=True)
    repository.insert(
        [
            vector_record(engine_code="ENG_ANALYTICS_FORECASTING", task_type="ANALYZE", vector=[1, 0, 0]),
            vector_record(engine_code="ENG_CONTENT_OUTPUT", task_type="GENERATE", vector=[0, 1, 0]),
        ]
    )

    reloaded = LocalIntentCapabilityVectorRepository(path=path)
    results = reloaded.search([0.9, 0.1, 0], top_k=2)

    assert path.exists()
    assert reloaded.count == 2
    assert [result["task_type"] for result in results] == ["ANALYZE", "GENERATE"]
    assert results[0]["similarity_score"] > results[1]["similarity_score"]


def test_local_vector_repository_initializes_only_on_first_search(tmp_path: Path) -> None:
    calls: list[str] = []
    repository = LocalIntentCapabilityVectorRepository(path=tmp_path / "lazy.npz")
    repository.configure_initializer(
        lambda: calls.append("initialize")
        or [vector_record(engine_code="ENG_CONTENT_OUTPUT", task_type="GENERATE", vector=[1, 0])]
    )

    repository.search([1, 0])
    repository.search([1, 0])

    assert calls == ["initialize"]


class FakeResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self.payload


class FakeWorkerClient:
    def __init__(self, worker_state: dict[str, bool]) -> None:
        self.worker_state = worker_state
        self.posts: list[dict] = []

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        if not self.worker_state["running"]:
            raise RuntimeError("worker unavailable")
        return FakeResponse(status_code=200)

    def post(self, url: str, *, json: dict, timeout: float) -> FakeResponse:
        self.posts.append(json)
        return FakeResponse(status_code=200, payload={"embeddings": [[1.0, 0.0, 0.0]]})


class FakeProcess:
    def poll(self) -> None:
        return None


def test_managed_bge_provider_starts_worker_and_returns_embeddings() -> None:
    worker_state = {"running": False}
    starts: list[str] = []

    def start_worker() -> FakeProcess:
        starts.append("start")
        worker_state["running"] = True
        return FakeProcess()

    client = FakeWorkerClient(worker_state)
    provider = ManagedBGEProvider(
        dimension=3,
        startup_timeout_seconds=1,
        client=client,
        process_factory=start_worker,
    )

    assert provider.embed(["经营分析"]) == [[1.0, 0.0, 0.0]]
    assert starts == ["start"]
    assert client.posts == [{"texts": ["经营分析"]}]


class FakeBGEProvider:
    model_name = "fake-bge"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_bge_worker_state_releases_after_idle_timeout() -> None:
    state = BGEWorkerState(provider=FakeBGEProvider())
    state.keep_warm = False
    state.idle_timeout_seconds = 1

    assert state.embed(["test"]) == [[1.0, 0.0]]
    assert state.model_loaded is True
    assert state.should_shutdown() is False

    state.last_activity -= 2
    assert state.should_shutdown() is True


def test_bge_worker_state_stays_alive_when_keep_warm_is_enabled() -> None:
    state = BGEWorkerState(provider=FakeBGEProvider())
    state.keep_warm = True
    state.last_activity -= 3600

    assert state.should_shutdown() is False
