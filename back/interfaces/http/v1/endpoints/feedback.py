"""用户答案反馈与失败样本回流 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from SafeMealAgent.back.application.observability.metrics import FEEDBACK_SUBMISSIONS
from SafeMealAgent.back.application.use_cases.feedback.service import (
    AnswerFeedbackService,
    FeedbackTargetConflictError,
    FeedbackTargetInvalidError,
    FeedbackTargetNotFoundError,
)
from SafeMealAgent.back.interfaces.http.dependencies import (
    get_answer_feedback_service,
)
from SafeMealAgent.back.interfaces.http.security import (
    Principal,
    authorize_user_id,
    get_current_principal,
)
from SafeMealAgent.back.shared.contracts.feedback import (
    AnswerFeedbackRequest,
    AnswerFeedbackResponse,
    AnswerFeedbackStatsResponse,
)


router = APIRouter()


@router.post("/", response_model=AnswerFeedbackResponse)
async def submit_answer_feedback(
    request: AnswerFeedbackRequest,
    service: AnswerFeedbackService = Depends(get_answer_feedback_service),
    principal: Principal = Depends(get_current_principal),
) -> AnswerFeedbackResponse:
    """接收用户反馈；只有负反馈进入待人工审核队列。

    Args:
        request: 用户反馈内容。
        session_management: 会话消息查询服务。
        collector: 失败样本收集端口。
    """

    user_id = authorize_user_id(principal, request.user_id)
    try:
        message_id = int(request.message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="message_id 必须是已持久化的数字消息 ID",
        ) from exc

    try:
        result = await run_in_threadpool(
            service.submit,
            session_id=request.session_id,
            message_id=message_id,
            user_id=user_id,
            rating=request.rating,
            reason=request.reason,
            corrected_answer=request.corrected_answer,
        )
    except FeedbackTargetNotFoundError as exc:
        FEEDBACK_SUBMISSIONS.labels(request.rating, "rejected").inc()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到对应会话中的 Agent 消息",
        ) from exc
    except FeedbackTargetInvalidError as exc:
        FEEDBACK_SUBMISSIONS.labels(request.rating, "rejected").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能对 Agent 回答提交反馈",
        ) from exc
    except FeedbackTargetConflictError as exc:
        FEEDBACK_SUBMISSIONS.labels(request.rating, "rejected").inc()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="无法定位该回答对应的用户问题",
        ) from exc
    FEEDBACK_SUBMISSIONS.labels(request.rating, "accepted").inc()
    return AnswerFeedbackResponse(
        accepted=True,
        queued_for_review=result.queued_for_review,
        feedback_id=result.feedback.id,
        sample_id=result.feedback.review_sample_id,
    )


@router.get("/stats", response_model=AnswerFeedbackStatsResponse)
async def get_answer_feedback_stats(
    user_id: str,
    service: AnswerFeedbackService = Depends(get_answer_feedback_service),
    principal: Principal = Depends(get_current_principal),
) -> AnswerFeedbackStatsResponse:
    """返回当前用户正负反馈、待审核量和正反馈率。"""

    authorized_user_id = authorize_user_id(principal, user_id)
    stats = await run_in_threadpool(service.stats, user_id=authorized_user_id)
    return AnswerFeedbackStatsResponse.model_validate(stats, from_attributes=True)
