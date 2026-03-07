"""
ML-based optimization engine.
Uses historical usage data to predict optimal resource configurations
and detect billing anomalies.
"""

import numpy as np
from dataclasses import dataclass
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression

from src.core.logging import logger


# Common instance families ordered by size for rightsizing
INSTANCE_FAMILIES = {
    "aws": {
        "t3": ["t3.nano", "t3.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge"],
        "m5": ["m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge", "m5.8xlarge"],
        "c5": ["c5.large", "c5.xlarge", "c5.2xlarge", "c5.4xlarge", "c5.9xlarge"],
        "r5": ["r5.large", "r5.xlarge", "r5.2xlarge", "r5.4xlarge", "r5.8xlarge"],
    },
    "azure": {
        "B": ["Standard_B1s", "Standard_B1ms", "Standard_B2s", "Standard_B2ms", "Standard_B4ms"],
        "D": ["Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3", "Standard_D16s_v3"],
    },
    "gcp": {
        "e2": ["e2-micro", "e2-small", "e2-medium", "e2-standard-2", "e2-standard-4", "e2-standard-8"],
        "n2": ["n2-standard-2", "n2-standard-4", "n2-standard-8", "n2-standard-16"],
    },
}


@dataclass
class RightsizeRecommendation:
    current_type: str
    recommended_type: str
    current_cost: float
    estimated_cost: float
    confidence: float
    reasoning: str


@dataclass
class AnomalyResult:
    is_anomaly: bool
    anomaly_score: float
    description: str


@dataclass
class ForecastResult:
    predicted_monthly_costs: list[float]  # next N months
    trend: str  # "increasing", "decreasing", "stable"
    confidence: float


class MLOptimizer:
    """ML-based cost optimization predictions."""

    def predict_rightsize(
        self,
        current_type: str,
        provider: str,
        cpu_avg: float,
        cpu_max: float,
        memory_avg: float | None,
        memory_max: float | None,
        current_cost: float,
    ) -> RightsizeRecommendation | None:
        """Predict the optimal instance size based on utilization."""
        # Find the instance family
        family_key = None
        family_list = None
        current_idx = None

        provider_families = INSTANCE_FAMILIES.get(provider, {})
        for fam, sizes in provider_families.items():
            if current_type in sizes:
                family_key = fam
                family_list = sizes
                current_idx = sizes.index(current_type)
                break

        if family_list is None or current_idx is None:
            return None

        # Determine target utilization band: 40-70% CPU
        # If avg < 15%, drop 2 sizes. If avg < 30%, drop 1 size.
        steps_down = 0
        if cpu_avg < 10 and cpu_max < 25:
            steps_down = 2
        elif cpu_avg < 20 and cpu_max < 45:
            steps_down = 1
        elif cpu_avg < 35 and cpu_max < 60:
            steps_down = 1

        if steps_down == 0:
            return None

        new_idx = max(0, current_idx - steps_down)
        if new_idx == current_idx:
            return None

        recommended_type = family_list[new_idx]
        # Estimate cost reduction proportional to size step
        cost_ratio = (new_idx + 1) / (current_idx + 1)
        estimated_cost = current_cost * cost_ratio
        confidence = min(0.95, 0.6 + (0.1 * steps_down) + (0.05 if cpu_max < 40 else 0))

        return RightsizeRecommendation(
            current_type=current_type,
            recommended_type=recommended_type,
            current_cost=current_cost,
            estimated_cost=round(estimated_cost, 2),
            confidence=round(confidence, 2),
            reasoning=(
                f"CPU avg {cpu_avg:.1f}% (max {cpu_max:.1f}%) suggests "
                f"{recommended_type} would maintain <70% utilization target."
            ),
        )

    def detect_billing_anomaly(
        self, monthly_costs: list[float], current_month_cost: float
    ) -> AnomalyResult:
        """Detect anomalous billing using Isolation Forest."""
        if len(monthly_costs) < 3:
            return AnomalyResult(False, 0.0, "Insufficient data for anomaly detection.")

        data = np.array(monthly_costs + [current_month_cost]).reshape(-1, 1)
        model = IsolationForest(contamination=0.1, random_state=42)
        model.fit(data)

        score = model.score_samples(np.array([[current_month_cost]]))[0]
        prediction = model.predict(np.array([[current_month_cost]]))[0]

        is_anomaly = prediction == -1
        avg = np.mean(monthly_costs)
        pct_change = ((current_month_cost - avg) / avg * 100) if avg > 0 else 0

        description = ""
        if is_anomaly:
            direction = "increase" if current_month_cost > avg else "decrease"
            description = (
                f"Anomalous {direction} detected: ${current_month_cost:.2f} vs "
                f"${avg:.2f} avg ({pct_change:+.1f}%)."
            )
        else:
            description = f"Current spend ${current_month_cost:.2f} is within normal range."

        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_score=round(abs(score), 3),
            description=description,
        )

    def forecast_costs(
        self, monthly_costs: list[float], months_ahead: int = 3
    ) -> ForecastResult:
        """Predict future monthly costs using linear regression."""
        if len(monthly_costs) < 2:
            return ForecastResult(
                predicted_monthly_costs=[monthly_costs[-1]] * months_ahead if monthly_costs else [0] * months_ahead,
                trend="stable",
                confidence=0.0,
            )

        X = np.arange(len(monthly_costs)).reshape(-1, 1)
        y = np.array(monthly_costs)

        model = LinearRegression()
        model.fit(X, y)

        future_X = np.arange(len(monthly_costs), len(monthly_costs) + months_ahead).reshape(-1, 1)
        predictions = model.predict(future_X)
        predictions = [max(0, round(p, 2)) for p in predictions]

        slope = model.coef_[0]
        avg = np.mean(monthly_costs)
        slope_pct = (slope / avg * 100) if avg > 0 else 0

        if slope_pct > 5:
            trend = "increasing"
        elif slope_pct < -5:
            trend = "decreasing"
        else:
            trend = "stable"

        confidence = min(0.95, round(model.score(X, y), 2)) if len(monthly_costs) >= 3 else 0.3

        return ForecastResult(
            predicted_monthly_costs=predictions,
            trend=trend,
            confidence=confidence,
        )
