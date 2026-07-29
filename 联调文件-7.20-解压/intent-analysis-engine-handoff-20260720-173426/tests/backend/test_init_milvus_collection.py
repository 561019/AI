from types import SimpleNamespace

import pytest

from scripts import init_milvus_collection


class FakeDataTypeValue:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeDataType:
    INT64 = FakeDataTypeValue("INT64")
    VARCHAR = FakeDataTypeValue("VARCHAR")
    FLOAT_VECTOR = FakeDataTypeValue("FLOAT_VECTOR")
    JSON = FakeDataTypeValue("JSON")


class FakeFieldSchema:
    def __init__(
        self,
        *,
        name: str,
        dtype,
        is_primary: bool = False,
        auto_id: bool = False,
        max_length: int | None = None,
        dim: int | None = None,
    ) -> None:
        self.name = name
        self.dtype = dtype
        self.is_primary = is_primary
        self.auto_id = auto_id
        self.params = {}
        if max_length is not None:
            self.params["max_length"] = max_length
        if dim is not None:
            self.params["dim"] = dim


class FakeCollectionSchema:
    def __init__(self, *, fields, description: str, enable_dynamic_field: bool) -> None:
        self.fields = fields
        self.description = description
        self.enable_dynamic_field = enable_dynamic_field


class FakeIndex:
    field_name = "embedding"
    index_name = "embedding_autindex"
    params = {"metric_type": "COSINE", "index_type": "AUTOINDEX"}

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "index_name": self.index_name,
            "params": self.params,
        }


class FakeCollection:
    instances: list["FakeCollection"] = []

    def __init__(self, name: str, schema=None, using: str = "default") -> None:
        self.name = name
        self.schema = schema or FakeCollectionSchema(
            fields=[],
            description="existing",
            enable_dynamic_field=False,
        )
        self.using = using
        self.indexes = []
        self.create_index_calls = []
        self.loaded = False
        FakeCollection.instances.append(self)

    def create_index(self, *, field_name: str, index_params: dict) -> None:
        self.create_index_calls.append(
            {
                "field_name": field_name,
                "index_params": index_params,
            },
        )
        self.indexes.append(FakeIndex())

    def load(self) -> None:
        self.loaded = True


class FakeConnections:
    def __init__(self) -> None:
        self.calls = []

    def connect(self, **kwargs) -> None:
        self.calls.append(kwargs)


class FakeUtility:
    def __init__(self, exists: bool) -> None:
        self.exists = exists
        self.calls = []

    def has_collection(self, name: str) -> bool:
        self.calls.append(name)
        return self.exists


@pytest.fixture
def fake_pymilvus(monkeypatch):
    FakeCollection.instances = []
    connections = FakeConnections()
    utility = FakeUtility(exists=False)
    fake_module = SimpleNamespace(
        Collection=FakeCollection,
        CollectionSchema=FakeCollectionSchema,
        DataType=FakeDataType,
        FieldSchema=FakeFieldSchema,
        connections=connections,
        utility=utility,
    )
    monkeypatch.setitem(__import__("sys").modules, "pymilvus", fake_module)
    return connections, utility


def test_build_collection_schema_uses_configured_dimension(fake_pymilvus) -> None:
    schema = init_milvus_collection.build_collection_schema(dimension=768)

    fields = {field.name: field for field in schema.fields}
    assert list(fields) == ["id", "function_code", "text", "embedding", "metadata"]
    assert fields["id"].dtype.name == "INT64"
    assert fields["id"].is_primary is True
    assert fields["id"].auto_id is True
    assert fields["function_code"].params["max_length"] == 128
    assert fields["text"].params["max_length"] == 4096
    assert fields["embedding"].params["dim"] == 768
    assert fields["metadata"].dtype.name == "JSON"


def test_initialize_milvus_collection_creates_index_and_loads(monkeypatch, fake_pymilvus) -> None:
    connections, utility = fake_pymilvus
    monkeypatch.setattr(init_milvus_collection.settings, "milvus_host", "milvus-test")
    monkeypatch.setattr(init_milvus_collection.settings, "milvus_port", 19531)
    monkeypatch.setattr(init_milvus_collection.settings, "milvus_collection", "intent_vectors_test")
    monkeypatch.setattr(init_milvus_collection.settings, "embedding_dimension", 384)

    result = init_milvus_collection.initialize_milvus_collection()
    collection = FakeCollection.instances[0]

    assert connections.calls == [
        {
            "alias": "default",
            "host": "milvus-test",
            "port": "19531",
        },
    ]
    assert utility.calls == ["intent_vectors_test"]
    assert collection.create_index_calls == [
        {
            "field_name": "embedding",
            "index_params": {
                "metric_type": "COSINE",
                "index_type": "AUTOINDEX",
                "params": {},
            },
        },
    ]
    assert collection.loaded is True
    assert result["collection"] == "intent_vectors_test"
    assert result["created"] is True
    assert result["embedding_dimension"] == 384
    assert result["index_created"] is True
    assert result["loaded"] is True
    assert [field["name"] for field in result["schema"]["fields"]] == [
        "id",
        "function_code",
        "text",
        "embedding",
        "metadata",
    ]
    assert result["indexes"][0]["field_name"] == "embedding"
