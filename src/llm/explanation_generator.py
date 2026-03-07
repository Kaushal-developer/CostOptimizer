"""
Explanation generator — 3-tier fallback: Claude API → Local LLM → Templates.
Works fully without any API key or local model configured.
"""

from __future__ import annotations

from src.core.config import get_settings
from src.core.logging import logger
from src.engine.savings_calculator import SavingsSummary


class ExplanationGenerator:
    """Generate explanations for optimization recommendations."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model
        self._local_url = settings.local_llm_url
        self._local_model = settings.local_llm_model
        self._provider = settings.llm_provider  # "claude", "local", "auto"
        self._claude_client = None
        self._local_client = None

    @property
    def _claude(self):
        """Lazy-load Anthropic client only if API key is set."""
        if self._claude_client is None and self._api_key:
            try:
                import anthropic
                self._claude_client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        return self._claude_client

    @property
    def _local(self):
        """Lazy-load local LLM client only if URL is configured."""
        if self._local_client is None and self._local_url:
            from src.llm.local_llm import LocalLLMClient
            self._local_client = LocalLLMClient(
                base_url=self._local_url, model=self._local_model
            )
        return self._local_client

    def _call_claude(self, prompt: str, max_tokens: int = 300) -> str | None:
        """Call Claude API if available, return None otherwise."""
        if not self._claude:
            return None
        try:
            response = self._claude.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception:
            logger.exception("Claude API call failed")
            return None

    async def _call_local(self, prompt: str, max_tokens: int = 512) -> str | None:
        """Call local LLM if available, return None otherwise."""
        if not self._local:
            return None
        return await self._local.generate(
            prompt=prompt,
            system_prompt=(
                "You are CostOptimizer AI, an expert cloud cost optimization assistant. "
                "Provide concise, actionable cost-saving recommendations."
            ),
            max_tokens=max_tokens,
        )

    async def _call_llm(self, prompt: str, max_tokens: int = 300) -> str | None:
        """3-tier LLM call based on configured provider."""
        if self._provider == "claude":
            return self._call_claude(prompt, max_tokens)
        elif self._provider == "local":
            return await self._call_local(prompt, max_tokens)
        else:  # "auto" — try claude first, then local
            result = self._call_claude(prompt, max_tokens)
            if result:
                return result
            return await self._call_local(prompt, max_tokens)

    async def explain_recommendation(
        self,
        title: str,
        description: str,
        resource_type: str,
        provider: str,
        current_config: dict | None,
        recommended_config: dict | None,
        current_cost: float,
        estimated_cost: float,
    ) -> str:
        """Generate a human-readable explanation for a single recommendation."""
        savings = current_cost - estimated_cost

        prompt = (
            f"You are a cloud cost optimization expert. Explain this recommendation concisely.\n\n"
            f"Resource Type: {resource_type}\nCloud Provider: {provider}\n"
            f"Finding: {title}\nTechnical Details: {description}\n"
            f"Current Config: {current_config}\nRecommended Config: {recommended_config}\n"
            f"Current Monthly Cost: ${current_cost:.2f}\n"
            f"Estimated Monthly Cost After: ${estimated_cost:.2f}\n"
            f"Potential Savings: ${savings:.2f}/month\n\n"
            f"Write a 2-3 sentence explanation a non-technical executive could understand."
        )
        llm_result = await self._call_llm(prompt)
        if llm_result:
            return llm_result

        # Template fallback
        return (
            f"{title}. {description} "
            f"This change would reduce monthly costs from ${current_cost:.2f} to "
            f"${estimated_cost:.2f}, saving ${savings:.2f}/month "
            f"(${savings * 12:.2f}/year)."
        )

    async def generate_executive_summary(self, summary: SavingsSummary) -> str:
        """Generate an executive summary of optimization findings."""
        breakdown = "\n".join(
            f"- {cat.category}: {cat.recommendation_count} findings, "
            f"${cat.potential_savings:.2f}/mo potential savings"
            for cat in summary.by_type.values()
        )
        annual = summary.total_potential_savings * 12

        prompt = (
            f"You are a FinOps advisor. Write a concise executive summary.\n\n"
            f"Total Monthly Spend: ${summary.total_monthly_spend:.2f}\n"
            f"Potential Savings: ${summary.total_potential_savings:.2f}/mo ({summary.savings_percentage}%)\n"
            f"Optimization Score: {summary.optimization_score}/100\n\n"
            f"Breakdown:\n{breakdown}\n\n"
            f"Write 3-4 sentences covering current state, opportunities, actions, and annual projection."
        )
        llm_result = await self._call_llm(prompt, max_tokens=500)
        if llm_result:
            return llm_result

        # Template fallback
        top_category = max(summary.by_type.values(), key=lambda c: c.potential_savings, default=None)
        top_area = f" The largest opportunity is in {top_category.category} ({top_category.recommendation_count} findings, ${top_category.potential_savings:.2f}/mo)." if top_category else ""
        return (
            f"Your cloud environment has an optimization score of {summary.optimization_score}/100 "
            f"with ${summary.total_monthly_spend:.2f}/mo in total spend.{top_area} "
            f"Applying all recommendations could save ${summary.total_potential_savings:.2f}/mo "
            f"(${annual:.2f}/year), a {summary.savings_percentage}% reduction."
        )

    async def answer_natural_language_query(self, query: str, context: dict) -> str:
        """Answer natural language questions about cloud costs."""
        prompt = (
            f"You are a cloud cost optimization assistant. Answer using the data below.\n\n"
            f"Question: {query}\n\n"
            f"Data:\n"
            f"- Monthly Spend: ${context.get('total_spend', 0):.2f}\n"
            f"- Top Services: {context.get('top_services', [])}\n"
            f"- Cost Changes: {context.get('cost_changes', [])}\n"
            f"- Active Recommendations: {context.get('recommendation_count', 0)}\n"
            f"- Potential Savings: ${context.get('potential_savings', 0):.2f}/mo\n"
            f"- Regions: {context.get('regions', [])}\n\n"
            f"Provide a concise, data-driven answer."
        )
        llm_result = await self._call_llm(prompt, max_tokens=500)
        if llm_result:
            return llm_result

        # Template fallback
        spend = context.get('total_spend', 0)
        savings = context.get('potential_savings', 0)
        rec_count = context.get('recommendation_count', 0)
        return (
            f"Based on your data: monthly spend is ${spend:.2f} with "
            f"${savings:.2f}/mo in potential savings across {rec_count} recommendations. "
            f"For AI-powered answers, configure COSTOPT_ANTHROPIC_API_KEY or "
            f"COSTOPT_LOCAL_LLM_URL in your environment."
        )
