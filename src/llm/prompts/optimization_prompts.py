"""Structured prompt templates for AI-powered optimization analysis."""

PROMPTS = {
    "rightsizing": """Analyze this cloud resource for rightsizing opportunities.

Resource Data:
{data}

Return JSON with:
- "recommendation": string (specific instance type recommendation)
- "current_utilization": object with cpu_avg, memory_avg percentages
- "estimated_savings_pct": number
- "confidence": number (0-1)
- "reasoning": string
- "risk_level": "low"|"medium"|"high"
""",

    "reservations": """Analyze this usage data for reservation purchase recommendations.

Usage Data:
{data}

Return JSON with:
- "recommendation": "reserved_instance"|"savings_plan"|"none"
- "commitment_term": "1_year"|"3_year"
- "payment_option": "all_upfront"|"partial_upfront"|"no_upfront"
- "estimated_savings_pct": number
- "break_even_months": number
- "confidence": number (0-1)
- "reasoning": string
""",

    "spot": """Analyze this workload for spot instance suitability.

Workload Data:
{data}

Return JSON with:
- "spot_suitable": boolean
- "interruption_tolerance": "high"|"medium"|"low"
- "recommended_strategy": string
- "estimated_savings_pct": number
- "confidence": number (0-1)
- "reasoning": string
""",

    "scheduling": """Analyze usage patterns for scheduling optimization.

Usage Patterns:
{data}

Return JSON with:
- "schedule_recommendation": object with start_time, stop_time, timezone, days
- "estimated_savings_pct": number
- "peak_hours": array of numbers
- "idle_hours": array of numbers
- "confidence": number (0-1)
- "reasoning": string
""",

    "architecture": """Analyze current architecture for cost optimization.

Architecture Data:
{data}

Return JSON with:
- "current_architecture": string description
- "proposed_changes": array of objects with change, impact, savings_pct
- "total_estimated_savings_pct": number
- "migration_complexity": "low"|"medium"|"high"
- "confidence": number (0-1)
- "reasoning": string
""",

    "load_balancing": """Analyze resource distribution across availability zones/regions.

Distribution Data:
{data}

Return JSON with:
- "current_distribution": object
- "recommended_distribution": object
- "imbalance_score": number (0-1, 0=balanced)
- "recommendations": array of strings
- "estimated_savings_pct": number
- "confidence": number (0-1)
""",

    "security_risk": """Assess the security risk of this finding.

Finding Data:
{data}

Return JSON with:
- "risk_score": number (0-100)
- "risk_level": "critical"|"high"|"medium"|"low"
- "attack_vectors": array of strings
- "potential_impact": string
- "remediation_priority": number (1-5)
- "remediation_steps": array of strings
""",

    "remediation": """Provide specific remediation steps for this security alert.

Alert Data:
{data}

Provide step-by-step remediation instructions including:
1. Immediate actions to take
2. AWS CLI commands or console steps
3. Verification steps
4. Prevention measures
""",
}
