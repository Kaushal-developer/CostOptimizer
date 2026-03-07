"""
Celery tasks for background processing.
Handles cloud sync, optimization analysis, remediation, and report generation.
"""

import asyncio
from datetime import datetime, timezone, timedelta

from src.workers.celery_app import celery_app
from src.core.logging import logger
from src.core.database import async_session_factory
from src.core.config import get_settings
from src.models.cloud_account import CloudAccount, CloudProvider, AccountStatus
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import Recommendation, RecommendationStatus
from src.models.savings import SavingsReport
from src.ingestion.aws.collector import AWSCollector
from src.ingestion.azure.collector import AzureCollector
from src.ingestion.gcp.collector import GCPCollector
from src.normalization.normalizer import ResourceNormalizer
from src.engine.rule_engine import RuleEngine
from src.engine.ml_optimizer import MLOptimizer
from src.engine.savings_calculator import SavingsCalculator
from src.llm.explanation_generator import ExplanationGenerator
from sqlalchemy import select


def _run_async(coro):
    """Run an async coroutine from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_collector(account: CloudAccount):
    """Factory to create the right collector for a cloud account."""
    if account.provider == CloudProvider.AWS:
        return AWSCollector(
            role_arn=account.aws_role_arn,
            external_id=account.aws_external_id,
        )
    elif account.provider == CloudProvider.AZURE:
        return AzureCollector(
            subscription_id=account.azure_subscription_id,
            tenant_id=account.azure_tenant_id,
            client_id=get_settings().azure_client_id,
            client_secret=get_settings().azure_client_secret,
        )
    elif account.provider == CloudProvider.GCP:
        return GCPCollector(
            project_id=account.gcp_project_id,
        )
    raise ValueError(f"Unknown provider: {account.provider}")


@celery_app.task(bind=True, max_retries=3)
def sync_cloud_account(self, cloud_account_id: int):
    """Sync resources and metrics from a single cloud account."""

    async def _sync():
        async with async_session_factory() as db:
            result = await db.execute(
                select(CloudAccount).where(CloudAccount.id == cloud_account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                logger.error("Cloud account not found", id=cloud_account_id)
                return

            logger.info("Starting sync", account_id=account.id, provider=account.provider.value)

            try:
                collector = _get_collector(account)

                # Validate credentials
                valid = await collector.validate_credentials()
                if not valid:
                    account.status = AccountStatus.ERROR
                    account.last_error = "Credential validation failed"
                    await db.commit()
                    return

                # Collect resources
                collected = await collector.collect_resources()
                logger.info("Collected resources", count=len(collected), account_id=account.id)

                # Normalize and persist
                normalizer = ResourceNormalizer(db, account)
                resources = await normalizer.normalize_and_persist(collected)

                # Mark stale resources
                current_ids = {r.resource_id for r in collected}
                stale_count = await normalizer.mark_stale_resources(current_ids)

                # Update account status
                account.status = AccountStatus.CONNECTED
                account.last_sync_at = datetime.now(timezone.utc)
                account.last_error = None
                await db.commit()

                logger.info(
                    "Sync complete",
                    account_id=account.id,
                    resources=len(resources),
                    stale=stale_count,
                )

            except Exception as e:
                account.status = AccountStatus.ERROR
                account.last_error = str(e)[:500]
                await db.commit()
                logger.exception("Sync failed", account_id=account.id)
                raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

    _run_async(_sync())


@celery_app.task
def sync_all_accounts():
    """Trigger sync for all active cloud accounts."""

    async def _trigger():
        async with async_session_factory() as db:
            result = await db.execute(
                select(CloudAccount).where(CloudAccount.status != AccountStatus.DISCONNECTED)
            )
            accounts = result.scalars().all()
            for account in accounts:
                sync_cloud_account.delay(account.id)
            logger.info("Triggered sync for all accounts", count=len(accounts))

    _run_async(_trigger())


@celery_app.task(bind=True, max_retries=2)
def run_optimization(self, tenant_id: int, cloud_account_id: int | None = None):
    """Run rule engine + ML optimizer on resources for a tenant."""

    async def _optimize():
        async with async_session_factory() as db:
            query = select(Resource).join(CloudAccount).where(
                CloudAccount.tenant_id == tenant_id
            )
            if cloud_account_id:
                query = query.where(Resource.cloud_account_id == cloud_account_id)

            result = await db.execute(query)
            resources = result.scalars().all()

            rule_engine = RuleEngine()
            ml_optimizer = MLOptimizer()
            explanation_gen = ExplanationGenerator()
            settings = get_settings()
            new_recs = 0

            for resource in resources:
                # Get metrics
                metrics_result = await db.execute(
                    select(ResourceMetric).where(ResourceMetric.resource_id == resource.id)
                )
                metrics = metrics_result.scalars().all()

                # Run rule engine
                rule_results = rule_engine.evaluate(resource, metrics)

                for rr in rule_results:
                    # Check for existing open recommendation of same type
                    existing = await db.execute(
                        select(Recommendation).where(
                            Recommendation.resource_id == resource.id,
                            Recommendation.type == rr.recommendation_type,
                            Recommendation.status == RecommendationStatus.OPEN,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    estimated_savings = resource.monthly_cost * rr.estimated_savings_pct

                    rec = Recommendation(
                        resource_id=resource.id,
                        tenant_id=tenant_id,
                        type=rr.recommendation_type,
                        priority=rr.priority,
                        title=rr.title,
                        description=rr.description,
                        current_monthly_cost=resource.monthly_cost,
                        estimated_monthly_cost=resource.monthly_cost - estimated_savings,
                        estimated_savings=estimated_savings,
                        confidence_score=0.8,
                        current_config={"instance_type": resource.instance_type, "region": resource.region},
                        recommended_config=rr.recommended_config,
                    )

                    # Generate AI explanation if API key configured
                    if settings.anthropic_api_key:
                        try:
                            rec.ai_explanation = await explanation_gen.explain_recommendation(
                                title=rr.title,
                                description=rr.description,
                                resource_type=resource.resource_type.value,
                                provider=resource.cloud_account.provider.value if resource.cloud_account else "unknown",
                                current_config=rec.current_config,
                                recommended_config=rec.recommended_config,
                                current_cost=rec.current_monthly_cost,
                                estimated_cost=rec.estimated_monthly_cost,
                            )
                        except Exception:
                            logger.warning("AI explanation generation skipped")

                    db.add(rec)
                    new_recs += 1

                # ML rightsizing for compute
                if resource.resource_type.value == "compute" and resource.instance_type:
                    cpu_metric = next((m for m in metrics if m.metric_name == "cpu_utilization"), None)
                    mem_metric = next((m for m in metrics if m.metric_name == "memory_utilization"), None)
                    if cpu_metric:
                        provider = "aws"  # Will be resolved from cloud_account
                        ml_rec = ml_optimizer.predict_rightsize(
                            current_type=resource.instance_type,
                            provider=provider,
                            cpu_avg=cpu_metric.avg_value,
                            cpu_max=cpu_metric.max_value,
                            memory_avg=mem_metric.avg_value if mem_metric else None,
                            memory_max=mem_metric.max_value if mem_metric else None,
                            current_cost=resource.monthly_cost,
                        )
                        if ml_rec:
                            rec = Recommendation(
                                resource_id=resource.id,
                                tenant_id=tenant_id,
                                type="rightsize",
                                priority="medium",
                                title=f"ML Rightsize: {resource.instance_type} → {ml_rec.recommended_type}",
                                description=ml_rec.reasoning,
                                current_monthly_cost=ml_rec.current_cost,
                                estimated_monthly_cost=ml_rec.estimated_cost,
                                estimated_savings=ml_rec.current_cost - ml_rec.estimated_cost,
                                confidence_score=ml_rec.confidence,
                                recommended_config={"instance_type": ml_rec.recommended_type},
                            )
                            db.add(rec)
                            new_recs += 1

            await db.commit()
            logger.info("Optimization complete", tenant_id=tenant_id, new_recommendations=new_recs)

    try:
        _run_async(_optimize())
    except Exception as e:
        logger.exception("Optimization failed", tenant_id=tenant_id)
        raise self.retry(exc=e, countdown=120)


@celery_app.task
def run_all_optimizations():
    """Run optimization for all active tenants."""

    async def _trigger():
        async with async_session_factory() as db:
            from src.models.tenant import Tenant
            result = await db.execute(select(Tenant).where(Tenant.is_active == True))
            tenants = result.scalars().all()
            for tenant in tenants:
                run_optimization.delay(tenant.id)

    _run_async(_trigger())


@celery_app.task
def execute_remediation(recommendation_id: int, user_id: int):
    """Execute a remediation action for an approved recommendation."""

    async def _remediate():
        async with async_session_factory() as db:
            result = await db.execute(
                select(Recommendation).where(Recommendation.id == recommendation_id)
            )
            rec = result.scalar_one_or_none()
            if not rec or rec.status != RecommendationStatus.ACCEPTED:
                return

            resource_result = await db.execute(
                select(Resource).where(Resource.id == rec.resource_id)
            )
            resource = resource_result.scalar_one_or_none()
            if not resource:
                return

            account_result = await db.execute(
                select(CloudAccount).where(CloudAccount.id == resource.cloud_account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account or not account.is_remediation_enabled:
                logger.warning("Remediation not enabled", account_id=account.id if account else None)
                return

            # Import remediator based on provider
            from src.remediation.aws.remediator import AWSRemediator
            from src.remediation.azure.remediator import AzureRemediator
            from src.remediation.gcp.remediator import GCPRemediator

            if account.provider == CloudProvider.AWS:
                remediator = AWSRemediator(account.aws_role_arn, account.aws_external_id, resource.region)
            elif account.provider == CloudProvider.AZURE:
                remediator = AzureRemediator(
                    account.azure_subscription_id, account.azure_tenant_id,
                    get_settings().azure_client_id, get_settings().azure_client_secret,
                )
            elif account.provider == CloudProvider.GCP:
                remediator = GCPRemediator(account.gcp_project_id)
            else:
                return

            # Execute based on recommendation type
            action_map = {
                "rightsize": lambda: remediator.rightsize_instance(
                    resource.resource_id,
                    rec.recommended_config.get("instance_type", ""),
                ),
                "terminate": lambda: remediator.terminate_resource(resource.resource_id),
                "delete_snapshot": lambda: remediator.delete_snapshot(resource.resource_id),
                "delete_volume": lambda: remediator.delete_volume(resource.resource_id),
                "release_ip": lambda: remediator.release_ip(resource.resource_id),
            }

            action_fn = action_map.get(rec.type.value if hasattr(rec.type, 'value') else rec.type)
            if not action_fn:
                logger.warning("No remediation handler", type=rec.type)
                return

            result = await action_fn()

            rec.applied_at = datetime.now(timezone.utc)
            rec.applied_by = user_id
            rec.status = RecommendationStatus.APPLIED if result.success else RecommendationStatus.FAILED
            await db.commit()

            logger.info(
                "Remediation result",
                recommendation_id=recommendation_id,
                success=result.success,
                details=result.details,
            )

    _run_async(_remediate())


@celery_app.task
def generate_report(tenant_id: int):
    """Generate a savings report for a tenant."""

    async def _generate():
        async with async_session_factory() as db:
            now = datetime.now(timezone.utc)
            period_start = now - timedelta(days=30)

            # Get all recommendations for the tenant
            result = await db.execute(
                select(Recommendation).where(Recommendation.tenant_id == tenant_id)
            )
            recommendations = result.scalars().all()

            # Calculate total spend from resources
            resource_result = await db.execute(
                select(Resource).join(CloudAccount).where(CloudAccount.tenant_id == tenant_id)
            )
            resources = resource_result.scalars().all()
            total_spend = sum(r.monthly_cost for r in resources)

            # Calculate savings
            calculator = SavingsCalculator()
            open_recs = [r for r in recommendations if r.status == RecommendationStatus.OPEN]
            summary = calculator.calculate(open_recs, total_spend)

            # Generate executive summary
            settings = get_settings()
            exec_summary = ""
            if settings.anthropic_api_key:
                try:
                    gen = ExplanationGenerator()
                    exec_summary = await gen.generate_executive_summary(summary)
                except Exception:
                    pass

            if not exec_summary:
                exec_summary = (
                    f"Monthly spend: ${total_spend:.2f}. "
                    f"Potential savings: ${summary.total_potential_savings:.2f}/mo."
                )

            report = SavingsReport(
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=now,
                total_spend=total_spend,
                potential_savings=summary.total_potential_savings,
                realized_savings=sum(
                    r.estimated_savings for r in recommendations
                    if r.status == RecommendationStatus.APPLIED
                ),
                optimization_score=summary.optimization_score,
                breakdown_by_category={
                    k: {"savings": v.potential_savings, "count": v.recommendation_count}
                    for k, v in summary.by_type.items()
                },
                breakdown_by_service=summary.by_priority,
                executive_summary=exec_summary,
            )
            db.add(report)
            await db.commit()
            logger.info("Report generated", tenant_id=tenant_id, report_id=report.id)

    _run_async(_generate())


@celery_app.task
def generate_all_reports():
    """Generate reports for all active tenants."""

    async def _trigger():
        async with async_session_factory() as db:
            from src.models.tenant import Tenant
            result = await db.execute(select(Tenant).where(Tenant.is_active == True))
            for tenant in result.scalars().all():
                generate_report.delay(tenant.id)

    _run_async(_trigger())
