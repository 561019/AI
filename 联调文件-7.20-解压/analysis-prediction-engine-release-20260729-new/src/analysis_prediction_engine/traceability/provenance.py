from collections import defaultdict
from typing import Iterable

from analysis_prediction_engine.contracts.common import ProvenanceReference


def build_provenance_reference(
    *,
    output_field: str,
    source_record_id: str,
    source_field: str,
    period: str,
    formula_version: str,
) -> ProvenanceReference:
    return ProvenanceReference(
        output_field=output_field,
        source_record_id=source_record_id,
        source_field=source_field,
        period=period,
        formula_version=formula_version,
    )


class ProvenanceIndex:
    def __init__(self, references: Iterable[ProvenanceReference]) -> None:
        entries = tuple(references)
        by_output: dict[str, list[ProvenanceReference]] = defaultdict(list)
        by_source: dict[str, list[ProvenanceReference]] = defaultdict(list)
        for reference in entries:
            by_output[reference.output_field].append(reference)
            by_source[reference.source_record_id].append(reference)
        self._by_output = {key: tuple(value) for key, value in by_output.items()}
        self._by_source = {key: tuple(value) for key, value in by_source.items()}

    def by_output_field(self, output_field: str) -> tuple[ProvenanceReference, ...]:
        return self._by_output.get(output_field, ())

    def by_source_record_id(self, source_record_id: str) -> tuple[ProvenanceReference, ...]:
        return self._by_source.get(source_record_id, ())
