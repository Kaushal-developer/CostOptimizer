"""Ollama chat API for natural language cost queries."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.cloud_account import CloudAccount
from src.models.resource import Resource
from src.models.recommendation import Recommendation
from src.models.cost_data import ChatMessage

router = APIRouter(prefix="/chat", tags=["chat"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    context: dict | None = None


@router.post("/message", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)

    # Build cost context for the LLM
    total_spend = (await db.execute(
        select(func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
    )).scalar() or 0.0

    total_resources = (await db.execute(
        select(func.count()).select_from(
            select(Resource)
            .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
            .where(CloudAccount.tenant_id == tid)
            .subquery()
        )
    )).scalar() or 0

    total_savings = (await db.execute(
        select(func.coalesce(func.sum(Recommendation.estimated_savings), 0.0))
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
    )).scalar() or 0.0

    open_recs = (await db.execute(
        select(func.count()).select_from(
            select(Recommendation)
            .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
            .subquery()
        )
    )).scalar() or 0

    # Top costly resource types
    type_rows = (await db.execute(
        select(Resource.resource_type, func.sum(Resource.monthly_cost))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.resource_type)
        .order_by(func.sum(Resource.monthly_cost).desc())
        .limit(5)
    )).all()
    top_types = [f"{r[0].value if hasattr(r[0], 'value') else r[0]}: ${float(r[1]):.2f}/mo" for r in type_rows]

    # Top recommendations
    top_recs_q = (
        select(Recommendation.title, Recommendation.estimated_savings)
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
        .order_by(Recommendation.estimated_savings.desc())
        .limit(5)
    )
    top_recs = (await db.execute(top_recs_q)).all()
    top_savings = [f"{r[0]}: ${r[1]:.2f}/mo" for r in top_recs]

    context = {
        "total_monthly_spend": round(float(total_spend), 2),
        "total_resources": total_resources,
        "potential_savings": round(float(total_savings), 2),
        "open_recommendations": open_recs,
        "top_cost_categories": top_types,
        "top_savings_opportunities": top_savings,
    }

    system_prompt = f"""You are CloudPulse AI, an expert cloud cost optimization assistant.
You have access to the user's cloud infrastructure data:
- Total Monthly Spend: ${context['total_monthly_spend']:.2f}
- Total Resources: {context['total_resources']}
- Potential Savings: ${context['potential_savings']:.2f}
- Open Recommendations: {context['open_recommendations']}
- Top Cost Categories: {', '.join(context['top_cost_categories'])}
- Top Savings Opportunities: {', '.join(context['top_savings_opportunities'])}

Provide concise, actionable advice about cloud cost optimization. Reference specific data when relevant.
Be direct and specific. Use dollar amounts and percentages when possible."""

    # Save user message
    db.add(ChatMessage(
        tenant_id=tid, user_id=current_user.id,
        role="user", content=body.message,
    ))

    # Try Ollama first, then fall back to explanation generator
    response_text = ""
    try:
        from src.llm.local_llm import LocalLLMClient
        from src.core.config import get_settings
        settings = get_settings()
        if settings.local_llm_url:
            model = settings.local_llm_model
            # Auto-detect model if not configured
            if not model:
                import httpx
                try:
                    r = httpx.get(f"{settings.local_llm_url}/v1/models", timeout=5)
                    models = r.json().get("data", [])
                    if models:
                        model = models[0]["id"]
                except Exception:
                    model = "llama3"  # sensible fallback
            client = LocalLLMClient(
                base_url=settings.local_llm_url,
                model=model,
            )
            response_text = await client.chat(
                system_prompt=system_prompt,
                user_message=body.message,
            )
    except Exception:
        pass

    if not response_text:
        try:
            from src.llm.explanation_generator import ExplanationGenerator
            gen = ExplanationGenerator()
            response_text = await gen.answer_natural_language_query(body.message, context)
        except Exception:
            response_text = (
                f"Based on your data: monthly spend is ${context['total_monthly_spend']:.2f} "
                f"with ${context['potential_savings']:.2f}/mo in potential savings "
                f"across {context['open_recommendations']} recommendations. "
                "For AI-powered answers, ensure Ollama is running on localhost:11434 "
                "or set COSTOPT_LOCAL_LLM_URL in your environment."
            )

    # Save assistant response
    db.add(ChatMessage(
        tenant_id=tid, user_id=current_user.id,
        role="assistant", content=response_text,
    ))

    return ChatResponse(response=response_text, context=context)


@router.get("/history")
async def get_chat_history(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    q = (
        select(ChatMessage)
        .where(ChatMessage.tenant_id == tid, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = (await db.execute(q)).scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in reversed(messages)
    ]
