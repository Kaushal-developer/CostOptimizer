"""Network optimization agent — ELB, NAT, Elastic IPs, data transfer."""

from __future__ import annotations

from src.llm.agents.base_agent import (
    BaseOptimizationAgent, AgentRecommendation,
)
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import RecommendationType, RecommendationPriority


class NetworkAgent(BaseOptimizationAgent):
    """Specializes in network resource optimization."""

    @property
    def domain(self) -> str:
        return "network"

    @property
    def supported_resource_types(self) -> list[str]:
        return ["elbv2:application", "elbv2:network", "ec2:elastic_ip"]

    def _build_domain_context(self) -> str:
        return (
            "You are a cloud network cost optimization expert. You specialize in:\n"
            "- Load balancer consolidation and right-sizing\n"
            "- Elastic IP management and cleanup\n"
            "- NAT Gateway optimization and alternatives\n"
            "- Data transfer cost reduction strategies\n"
            "- VPC endpoint recommendations to reduce NAT costs\n\n"
            "Pricing context:\n"
            "- ALB: $0.0225/hour + $0.008/LCU-hour\n"
            "- NLB: $0.0225/hour + $0.006/NLCU-hour\n"
            "- Elastic IP (unattached): $0.005/hour ($3.65/month)\n"
            "- NAT Gateway: $0.045/hour + $0.045/GB processed\n"
            "Provide specific recommendations."
        )

    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        results: list[AgentRecommendation] = []
        meta = resource.metadata_ or {}
        metric_map = {m.metric_name: m for m in metrics}

        # ALB/NLB analysis
        if resource.provider_resource_type.startswith("elbv2:"):
            req_count = metric_map.get("request_count")
            healthy = metric_map.get("healthy_host_count")
            unhealthy = metric_map.get("unhealthy_host_count")

            # Single target — LB may be unnecessary
            if healthy and healthy.max_value <= 1 and (not unhealthy or unhealthy.max_value == 0):
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.LOW,
                    title=f"Consider removing LB: {resource.name or resource.resource_id}",
                    description=(
                        "This load balancer has only 1 healthy target. If you don't need "
                        "SSL termination or path-based routing, consider connecting directly "
                        "to the instance and using CloudFront for HTTPS."
                    ),
                    estimated_savings_pct=1.0,
                    confidence_score=50.0,
                ))

            # Suggest NLB over ALB for TCP-only workloads
            if resource.provider_resource_type == "elbv2:application":
                resp_time = metric_map.get("target_response_time")
                if req_count and req_count.avg_value > 1000:
                    results.append(AgentRecommendation(
                        recommendation_type=RecommendationType.MODERNIZE,
                        priority=RecommendationPriority.LOW,
                        title=f"Evaluate NLB: {resource.name or resource.resource_id}",
                        description=(
                            "For high-throughput TCP workloads, Network Load Balancers "
                            "have lower latency and cost per connection. Evaluate if your "
                            "workload can use NLB instead of ALB."
                        ),
                        estimated_savings_pct=0.1,
                        confidence_score=40.0,
                    ))

        return results
