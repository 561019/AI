from app.schemas.common import ResultType
from app.schemas.intent import IntentAnalysisRequest, IntentAnalysisResponse


class IntentAnalysisService:
    async def analyze(self, request: IntentAnalysisRequest) -> IntentAnalysisResponse:
        return IntentAnalysisResponse(
            tracking_id=request.tracking_id,
            result_type=ResultType.SAFEGUARD,
            explanation_text=(
                "Intent analysis logic is not implemented yet. "
                "The API contract is available for integration scaffolding only."
            ),
        )
