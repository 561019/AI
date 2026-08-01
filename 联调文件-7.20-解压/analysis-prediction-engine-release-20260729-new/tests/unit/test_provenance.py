from analysis_prediction_engine.traceability.provenance import ProvenanceIndex, build_provenance_reference


def test_provenance_index_supports_reverse_lookup() -> None:
    revenue = build_provenance_reference(
        output_field="financial.revenue.current",
        source_record_id="financial-2026-06",
        source_field="metrics.revenue",
        period="2026-06",
        formula_version="core-v1",
    )
    index = ProvenanceIndex((revenue,))

    assert index.by_output_field("financial.revenue.current") == (revenue,)
    assert index.by_source_record_id("financial-2026-06") == (revenue,)
