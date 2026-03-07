"""Tests for the rule engine."""

import pytest
from unittest.mock import MagicMock
from src.engine.rule_engine import RuleEngine
from src.models.resource import ResourceType, ResourceStatus
from src.models.recommendation import RecommendationType


def make_resource(resource_type=ResourceType.COMPUTE, name="test-instance", tags=None, metadata=None, monthly_cost=100.0):
    r = MagicMock()
    r.resource_type = resource_type
    r.name = name
    r.resource_id = "i-123456"
    r.instance_type = "t3.large"
    r.monthly_cost = monthly_cost
    r.tags = tags
    r.metadata_ = metadata
    return r


def make_metric(name, avg, max_val, min_val=0, period=30):
    m = MagicMock()
    m.metric_name = name
    m.avg_value = avg
    m.max_value = max_val
    m.min_value = min_val
    m.p95_value = None
    m.period_days = period
    return m


class TestRuleEngine:
    def setup_method(self):
        self.engine = RuleEngine()

    def test_idle_instance_detected(self):
        resource = make_resource()
        metrics = [
            make_metric("cpu_utilization", 2.0, 5.0),
            make_metric("network_in", 500, 1000),
            make_metric("network_out", 300, 800),
        ]
        results = self.engine.evaluate(resource, metrics)
        assert any(r.recommendation_type == RecommendationType.TERMINATE for r in results)

    def test_overprovisioned_instance(self):
        resource = make_resource()
        metrics = [make_metric("cpu_utilization", 10.0, 30.0)]
        results = self.engine.evaluate(resource, metrics)
        assert any(r.recommendation_type == RecommendationType.RIGHTSIZE for r in results)

    def test_spot_candidate_dev_env(self):
        resource = make_resource(tags={"Environment": "dev"})
        metrics = [make_metric("cpu_utilization", 50.0, 80.0)]
        results = self.engine.evaluate(resource, metrics)
        assert any(r.recommendation_type == RecommendationType.SPOT_CONVERT for r in results)

    def test_no_recommendation_for_busy_instance(self):
        resource = make_resource(tags={"Environment": "production"})
        metrics = [make_metric("cpu_utilization", 60.0, 85.0)]
        results = self.engine.evaluate(resource, metrics)
        assert len(results) == 0

    def test_unattached_volume(self):
        resource = make_resource(resource_type=ResourceType.VOLUME, metadata={"attached": False})
        results = self.engine.evaluate(resource, [])
        assert any(r.recommendation_type == RecommendationType.DELETE_VOLUME for r in results)

    def test_old_snapshot(self):
        resource = make_resource(resource_type=ResourceType.SNAPSHOT, metadata={"age_days": 120})
        results = self.engine.evaluate(resource, [])
        assert any(r.recommendation_type == RecommendationType.DELETE_SNAPSHOT for r in results)

    def test_unassociated_ip(self):
        resource = make_resource(resource_type=ResourceType.IP_ADDRESS, metadata={"attached": False})
        results = self.engine.evaluate(resource, [])
        assert any(r.recommendation_type == RecommendationType.RELEASE_IP for r in results)
