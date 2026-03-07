"""
Optimization service — runs rule engine + LLM explanations on synced resources.
Generates recommendations after each sync.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cloud_account import CloudAccount
from src.models.resource import Resource, ResourceMetric, ResourceType
from src.models.recommendation import (
    Recommendation,
    RecommendationType,
    RecommendationPriority,
    RecommendationStatus,
)
from src.engine.rule_engine import RuleEngine, RuleResult
from src.engine.infra_analyzer import InfraAnalyzer
from src.llm.explanation_generator import ExplanationGenerator
from src.llm.agents.orchestrator import AgentOrchestrator

logger = structlog.get_logger(__name__)


def _build_local_llm_client():
    """Build local LLM client if configured, for use by agents."""
    from src.core.config import get_settings
    settings = get_settings()
    if settings.local_llm_url:
        from src.llm.local_llm import LocalLLMClient
        return LocalLLMClient(base_url=settings.local_llm_url, model=settings.local_llm_model)
    return None


async def run_optimization(account: CloudAccount, db: AsyncSession) -> dict:
    """Run optimization analysis on all resources for a cloud account.

    Pipeline: Rule Engine → Metadata Detection → Agent System → LLM Explanations
    Returns summary of recommendations generated.
    """
    log = logger.bind(account_id=account.id)
    log.info("optimization_started")

    # Load all resources for this account
    result = await db.execute(
        select(Resource).where(Resource.cloud_account_id == account.id)
    )
    resources = result.scalars().all()

    if not resources:
        log.info("no_resources_to_optimize")
        return {"recommendations_created": 0}

    # Delete old recommendations for resources in this account
    resource_ids = [r.id for r in resources]
    await db.execute(
        delete(Recommendation).where(Recommendation.resource_id.in_(resource_ids))
    )

    rule_engine = RuleEngine()
    infra_analyzer = InfraAnalyzer()
    llm = ExplanationGenerator()
    orchestrator = AgentOrchestrator(llm_client=_build_local_llm_client())
    recommendations_created = 0

    for resource in resources:
        # Load metrics for this resource
        metrics_result = await db.execute(
            select(ResourceMetric).where(ResourceMetric.resource_id == resource.id)
        )
        metrics = list(metrics_result.scalars().all())

        # 1. Run deterministic rule engine
        rule_results = rule_engine.evaluate(resource, metrics)

        # 2. Run metadata-based detection (works without CloudWatch metrics)
        meta_results = _evaluate_metadata(resource)
        rule_results.extend(meta_results)

        # 3. Run infrastructure cost reduction analysis
        infra_results = infra_analyzer.evaluate(resource, metrics)
        rule_results.extend(infra_results)

        # 3. Run domain-specific agents for deeper analysis
        agent_recs = await orchestrator.analyze(resource, metrics)

        # Create recommendations from rule engine results
        for rr in rule_results:
            savings = resource.monthly_cost * rr.estimated_savings_pct
            estimated_cost = resource.monthly_cost - savings

            ai_explanation = await llm.explain_recommendation(
                title=rr.title,
                description=rr.description,
                resource_type=resource.resource_type.value,
                provider=resource.provider_resource_type.split(":")[0] if resource.provider_resource_type else "aws",
                current_config=resource.metadata_,
                recommended_config=rr.recommended_config,
                current_cost=resource.monthly_cost,
                estimated_cost=estimated_cost,
            )

            rec = Recommendation(
                resource_id=resource.id,
                tenant_id=account.tenant_id,
                type=rr.recommendation_type,
                priority=rr.priority,
                status=RecommendationStatus.OPEN,
                title=rr.title,
                description=rr.description,
                ai_explanation=ai_explanation,
                current_config=resource.metadata_,
                recommended_config=rr.recommended_config,
                current_monthly_cost=resource.monthly_cost,
                estimated_monthly_cost=estimated_cost,
                estimated_savings=savings,
                confidence_score=_confidence_for_rule(rr, bool(metrics)),
            )
            db.add(rec)
            recommendations_created += 1

        # Create recommendations from agent analysis
        for ar in agent_recs:
            savings = resource.monthly_cost * ar.estimated_savings_pct
            estimated_cost = resource.monthly_cost - savings

            ai_explanation = await llm.explain_recommendation(
                title=ar.title,
                description=ar.description,
                resource_type=resource.resource_type.value,
                provider=resource.provider_resource_type.split(":")[0] if resource.provider_resource_type else "aws",
                current_config=resource.metadata_,
                recommended_config=ar.recommended_config,
                current_cost=resource.monthly_cost,
                estimated_cost=estimated_cost,
            )

            rec = Recommendation(
                resource_id=resource.id,
                tenant_id=account.tenant_id,
                type=ar.recommendation_type,
                priority=ar.priority,
                status=RecommendationStatus.OPEN,
                title=ar.title,
                description=ar.description,
                ai_explanation=ai_explanation,
                current_config=resource.metadata_,
                recommended_config=ar.recommended_config,
                current_monthly_cost=resource.monthly_cost,
                estimated_monthly_cost=estimated_cost,
                estimated_savings=savings,
                confidence_score=ar.confidence_score,
            )
            db.add(rec)
            recommendations_created += 1

    await db.flush()
    log.info("optimization_complete", recommendations=recommendations_created)
    return {"recommendations_created": recommendations_created}


def _evaluate_metadata(resource: Resource) -> list[RuleResult]:
    """Generate recommendations from resource metadata alone (no metrics needed)."""
    results = []
    meta = resource.metadata_ or {}

    # Unattached EBS volumes
    if resource.resource_type == ResourceType.VOLUME:
        attachments = meta.get("attachments", [])
        state = meta.get("state", "")
        if state == "available" or not attachments or all(a is None for a in attachments):
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.DELETE_VOLUME,
                priority=RecommendationPriority.HIGH,
                title=f"Unattached volume: {resource.name or resource.resource_id}",
                description=(
                    f"EBS volume ({meta.get('volume_type', 'unknown')} type, "
                    f"{resource.storage_gb or 0}GB) is not attached to any instance. "
                    f"Delete if no longer needed."
                ),
                estimated_savings_pct=1.0,
            ))

    # Unassociated Elastic IPs
    if resource.resource_type == ResourceType.IP_ADDRESS:
        if not meta.get("associated", True):
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.RELEASE_IP,
                priority=RecommendationPriority.MEDIUM,
                title=f"Unassociated Elastic IP: {meta.get('public_ip', resource.resource_id)}",
                description=(
                    f"Elastic IP {meta.get('public_ip', '')} is not associated with any instance. "
                    f"You're being charged $3.65/mo for an unused IP."
                ),
                estimated_savings_pct=1.0,
            ))

    # Stopped EC2 instances still incurring EBS costs
    if resource.resource_type == ResourceType.COMPUTE:
        state = meta.get("state", "")
        if state == "stopped":
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.TERMINATE,
                priority=RecommendationPriority.HIGH,
                title=f"Stopped instance: {resource.name or resource.resource_id}",
                description=(
                    f"Instance is stopped but still incurring EBS storage costs. "
                    f"Consider terminating if no longer needed, or snapshot and delete."
                ),
                estimated_savings_pct=0.8,
            ))

    # Old snapshots (estimate age from start_time)
    if resource.resource_type == ResourceType.SNAPSHOT:
        start_time = meta.get("start_time", "")
        if start_time:
            try:
                snap_time = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - snap_time).days
                if age_days > 90:
                    results.append(RuleResult(
                        triggered=True,
                        recommendation_type=RecommendationType.DELETE_SNAPSHOT,
                        priority=RecommendationPriority.LOW if age_days < 180 else RecommendationPriority.MEDIUM,
                        title=f"Old snapshot ({age_days}d): {resource.name or resource.resource_id}",
                        description=(
                            f"Snapshot is {age_days} days old ({resource.storage_gb or 0}GB). "
                            f"Review if still needed for recovery."
                        ),
                        estimated_savings_pct=1.0,
                    ))
            except (ValueError, TypeError):
                pass

    return results


def _confidence_for_rule(rr: RuleResult, has_metrics: bool) -> float:
    """Assign confidence score based on rule type and data quality."""
    base = {
        RecommendationType.DELETE_VOLUME: 90.0,
        RecommendationType.RELEASE_IP: 95.0,
        RecommendationType.DELETE_SNAPSHOT: 80.0,
        RecommendationType.TERMINATE: 70.0,
        RecommendationType.RIGHTSIZE: 75.0,
        RecommendationType.SPOT_CONVERT: 60.0,
        RecommendationType.STORAGE_TIER: 65.0,
        RecommendationType.RESERVE: 70.0,
        RecommendationType.MODERNIZE: 55.0,
        RecommendationType.ARM_MIGRATE: 75.0,
        RecommendationType.GP3_UPGRADE: 95.0,
        RecommendationType.SERVERLESS: 55.0,
        RecommendationType.SAVINGS_PLAN: 80.0,
        RecommendationType.REGION_MOVE: 40.0,
    }.get(rr.recommendation_type, 50.0)

    # Higher confidence if we have metrics backing the recommendation
    if has_metrics:
        base = min(base + 10, 99.0)

    return base
