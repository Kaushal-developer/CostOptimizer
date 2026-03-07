"""Tests for ML optimizer."""

from src.engine.ml_optimizer import MLOptimizer


class TestMLOptimizer:
    def setup_method(self):
        self.optimizer = MLOptimizer()

    def test_rightsize_low_cpu(self):
        result = self.optimizer.predict_rightsize(
            current_type="m5.2xlarge",
            provider="aws",
            cpu_avg=8.0,
            cpu_max=20.0,
            memory_avg=None,
            memory_max=None,
            current_cost=200.0,
        )
        assert result is not None
        assert result.recommended_type == "m5.large"
        assert result.estimated_cost < result.current_cost

    def test_no_rightsize_high_cpu(self):
        result = self.optimizer.predict_rightsize(
            current_type="t3.large",
            provider="aws",
            cpu_avg=65.0,
            cpu_max=85.0,
            memory_avg=None,
            memory_max=None,
            current_cost=100.0,
        )
        assert result is None

    def test_billing_anomaly_detection(self):
        history = [100, 105, 98, 102, 101, 99]
        result = self.optimizer.detect_billing_anomaly(history, 250.0)
        assert result.is_anomaly is True

    def test_no_anomaly_normal_cost(self):
        history = [100, 105, 98, 102, 101, 99]
        result = self.optimizer.detect_billing_anomaly(history, 103.0)
        assert result.is_anomaly is False

    def test_cost_forecast(self):
        history = [100, 110, 120, 130, 140, 150]
        result = self.optimizer.forecast_costs(history, months_ahead=3)
        assert len(result.predicted_monthly_costs) == 3
        assert result.trend == "increasing"
        assert all(p > 0 for p in result.predicted_monthly_costs)

    def test_stable_forecast(self):
        history = [100, 101, 99, 100, 101, 100]
        result = self.optimizer.forecast_costs(history, months_ahead=3)
        assert result.trend == "stable"
