"""Reservation advisor - break-even analysis, RI vs SP comparison, commitment modeling."""

from __future__ import annotations

import math


class ReservationAdvisor:
    # Approximate pricing ratios (on-demand = 1.0)
    PRICING = {
        "on_demand": 1.0,
        "ri_1yr_no_upfront": 0.72,
        "ri_1yr_partial_upfront": 0.66,
        "ri_1yr_all_upfront": 0.60,
        "ri_3yr_no_upfront": 0.55,
        "ri_3yr_partial_upfront": 0.48,
        "ri_3yr_all_upfront": 0.42,
        "sp_1yr_no_upfront": 0.70,
        "sp_1yr_partial_upfront": 0.64,
        "sp_1yr_all_upfront": 0.58,
        "sp_3yr_no_upfront": 0.52,
        "sp_3yr_partial_upfront": 0.46,
        "sp_3yr_all_upfront": 0.40,
    }

    def analyze(self, monthly_on_demand_cost: float, usage_hours_per_month: float = 720, commitment_pct: float = 100) -> dict:
        """Full analysis comparing all commitment options."""
        effective_cost = monthly_on_demand_cost * (commitment_pct / 100)

        options = []
        for key, ratio in self.PRICING.items():
            if key == "on_demand":
                continue
            monthly_committed = effective_cost * ratio
            monthly_savings = effective_cost - monthly_committed
            annual_savings = monthly_savings * 12
            term_years = 3 if "3yr" in key else 1
            total_savings = monthly_savings * 12 * term_years

            # Break-even: for upfront, calculate when accumulated savings exceed upfront cost
            if "all_upfront" in key:
                upfront_cost = monthly_committed * 12 * term_years
                break_even_months = math.ceil(upfront_cost / effective_cost) if effective_cost > 0 else 0
            elif "partial_upfront" in key:
                upfront_cost = monthly_committed * 6 * term_years
                monthly_remaining = monthly_committed * 0.5
                net_monthly_savings = effective_cost - monthly_remaining
                break_even_months = math.ceil(upfront_cost / net_monthly_savings) if net_monthly_savings > 0 else term_years * 12
            else:
                break_even_months = 1

            plan_type = "Reserved Instance" if key.startswith("ri") else "Savings Plan"
            term = "1 Year" if "1yr" in key else "3 Year"
            payment = "No Upfront" if "no_upfront" in key else ("Partial Upfront" if "partial_upfront" in key else "All Upfront")

            options.append({
                "id": key,
                "type": plan_type,
                "term": term,
                "payment_option": payment,
                "monthly_cost": round(monthly_committed, 2),
                "monthly_savings": round(monthly_savings, 2),
                "annual_savings": round(annual_savings, 2),
                "total_savings": round(total_savings, 2),
                "savings_pct": round((1 - ratio) * 100, 1),
                "break_even_months": break_even_months,
            })

        options.sort(key=lambda x: x["savings_pct"], reverse=True)

        best = options[0] if options else None
        return {
            "current_monthly_cost": round(monthly_on_demand_cost, 2),
            "commitment_percentage": commitment_pct,
            "effective_monthly_cost": round(effective_cost, 2),
            "best_recommendation": best,
            "all_options": options,
            "recommendation_summary": (
                f"Best option: {best['type']} - {best['term']} {best['payment_option']} "
                f"saves {best['savings_pct']}% (${best['annual_savings']:,.0f}/yr)"
            ) if best else "No recommendations",
        }
