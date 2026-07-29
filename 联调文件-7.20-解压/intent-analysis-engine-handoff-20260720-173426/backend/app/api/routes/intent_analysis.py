from fastapi import APIRouter, Depends

from app.schemas.intent import IntentAnalysisRequest, IntentAnalysisResponse
from app.services.intent_analysis_service import IntentAnalysisService


router = APIRouter()


def get_intent_analysis_service() -> IntentAnalysisService:
    return IntentAnalysisService()


@router.post("", response_model=IntentAnalysisResponse)
async def analyze_intent(
    request: IntentAnalysisRequest,
    service: IntentAnalysisService = Depends(get_intent_analysis_service),
) -> IntentAnalysisResponse:
    return await service.analyze(request)
