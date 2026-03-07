"""Enhanced AI optimizer wrapping LocalLLMClient with structured prompts."""

from __future__ import annotations

import json
import structlog
from src.llm.local_llm import LocalLLMClient
from src.llm.prompts.optimization_prompts import PROMPTS

logger = structlog.get_logger(__name__)


class AIOptimizer:
    def __init__(self, llm_client: LocalLLMClient):
        self._llm = llm_client

    async def analyze_rightsizing(self, resource_data: dict) -> dict | None:
        return await self._run_analysis("rightsizing", resource_data)

    async def analyze_reservations(self, usage_data: dict) -> dict | None:
        return await self._run_analysis("reservations", usage_data)

    async def analyze_spot_opportunity(self, workload_data: dict) -> dict | None:
        return await self._run_analysis("spot", workload_data)

    async def analyze_scheduling(self, usage_patterns: dict) -> dict | None:
        return await self._run_analysis("scheduling", usage_patterns)

    async def analyze_architecture(self, architecture_data: dict) -> dict | None:
        return await self._run_analysis("architecture", architecture_data)

    async def analyze_load_balancing(self, distribution_data: dict) -> dict | None:
        return await self._run_analysis("load_balancing", distribution_data)

    async def assess_security_risk(self, finding_data: dict) -> dict | None:
        return await self._run_analysis("security_risk", finding_data)

    async def generate_remediation(self, alert_data: dict) -> str | None:
        prompt_template = PROMPTS.get("remediation")
        if not prompt_template:
            return None
        prompt = prompt_template.format(data=json.dumps(alert_data, indent=2))
        return await self._llm.generate(
            prompt=prompt,
            system_prompt="You are a cloud security expert. Provide specific, actionable remediation steps.",
            max_tokens=512,
            temperature=0.2,
        )

    async def _run_analysis(self, analysis_type: str, data: dict) -> dict | None:
        prompt_template = PROMPTS.get(analysis_type)
        if not prompt_template:
            logger.warning("no_prompt_template", type=analysis_type)
            return None

        prompt = prompt_template.format(data=json.dumps(data, indent=2))
        system = "You are an expert cloud cost optimization AI. Return only valid JSON."

        response = await self._llm.generate(
            prompt=prompt,
            system_prompt=system,
            max_tokens=1024,
            temperature=0.2,
        )

        if not response:
            return None

        try:
            # Try to extract JSON from response
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("ai_json_parse_error", type=analysis_type, response=response[:200])
            return {"raw_analysis": response}
