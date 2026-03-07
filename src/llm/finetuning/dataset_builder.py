"""
Build training dataset for fine-tuning a cloud cost optimization LLM.

Generates instruction/response pairs from:
1. Rule engine knowledge (deterministic optimization rules)
2. AWS best practices (Well-Architected Cost Pillar)
3. FinOps principles
4. Synthetic recommendation patterns
5. Infrastructure alternatives (ARM, serverless, reserved/spot)

Output: JSONL file in chat format for SFTTrainer.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = (
    "You are CostOptimizer AI, an expert cloud infrastructure cost optimization assistant. "
    "You analyze cloud resources, metrics, and configurations to provide actionable cost-saving "
    "recommendations. You are deeply knowledgeable about AWS, Azure, and GCP pricing, "
    "instance types, storage tiers, and FinOps best practices."
)

# Instance type families with specs for generating varied training examples
EC2_FAMILIES = {
    "t3.micro": {"vcpus": 2, "memory_gb": 1, "cost": 7.59},
    "t3.small": {"vcpus": 2, "memory_gb": 2, "cost": 15.18},
    "t3.medium": {"vcpus": 2, "memory_gb": 4, "cost": 30.37},
    "t3.large": {"vcpus": 2, "memory_gb": 8, "cost": 60.74},
    "t3.xlarge": {"vcpus": 4, "memory_gb": 16, "cost": 121.47},
    "m5.large": {"vcpus": 2, "memory_gb": 8, "cost": 70.08},
    "m5.xlarge": {"vcpus": 4, "memory_gb": 16, "cost": 140.16},
    "m5.2xlarge": {"vcpus": 8, "memory_gb": 32, "cost": 280.32},
    "c5.large": {"vcpus": 2, "memory_gb": 4, "cost": 62.05},
    "c5.xlarge": {"vcpus": 4, "memory_gb": 8, "cost": 124.10},
    "r5.large": {"vcpus": 2, "memory_gb": 16, "cost": 91.98},
    "r5.xlarge": {"vcpus": 4, "memory_gb": 32, "cost": 183.96},
}

GRAVITON_MAP = {
    "t3": "t4g", "m5": "m6g", "c5": "c7g", "r5": "r6g",
    "m5.large": "m6g.large", "m5.xlarge": "m6g.xlarge",
    "c5.large": "c7g.large", "c5.xlarge": "c7g.xlarge",
    "t3.large": "t4g.large", "t3.xlarge": "t4g.xlarge",
}

REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
ENVIRONMENTS = ["production", "staging", "development", "test", "qa"]


def _chat(user: str, assistant: str) -> dict:
    """Format a single training example in chat format."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ]
    }


class DatasetBuilder:
    """Generates training data for cloud cost optimization fine-tuning."""

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._examples: list[dict] = []

    def build_all(self) -> list[dict]:
        """Generate the complete training dataset."""
        self._generate_idle_instance_rules()
        self._generate_rightsizing_rules()
        self._generate_spot_conversion_rules()
        self._generate_database_rules()
        self._generate_storage_rules()
        self._generate_volume_rules()
        self._generate_snapshot_rules()
        self._generate_ip_rules()
        self._generate_lb_rules()
        self._generate_arm_migration()
        self._generate_gp2_to_gp3()
        self._generate_reserved_savings()
        self._generate_serverless_candidates()
        self._generate_finops_principles()
        self._generate_aws_best_practices()
        self._generate_general_cost_qa()

        self._rng.shuffle(self._examples)
        return self._examples

    def save(self, path: str | Path) -> int:
        """Build and save dataset to JSONL file. Returns count."""
        examples = self.build_all()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")
        return len(examples)

    # ── Rule Engine Knowledge ──

    def _generate_idle_instance_rules(self):
        for itype, specs in EC2_FAMILIES.items():
            for cpu_avg in [0.5, 1.2, 2.5, 3.8]:
                for region in self._rng.sample(REGIONS, 2):
                    name = f"web-server-{self._rng.randint(1, 99):02d}"
                    self._examples.append(_chat(
                        f"Analyze this EC2 instance:\n"
                        f"Name: {name}\nType: {itype}\nRegion: {region}\n"
                        f"CPU avg: {cpu_avg}%, max: {cpu_avg * 2}%\n"
                        f"Network in: {self._rng.randint(50, 500)} bytes/s\n"
                        f"Network out: {self._rng.randint(50, 500)} bytes/s\n"
                        f"Monthly cost: ${specs['cost']:.2f}\n"
                        f"Running for 30 days",
                        f"This {itype} instance '{name}' in {region} is **idle** and should be "
                        f"**terminated**. With only {cpu_avg}% average CPU utilization and "
                        f"minimal network traffic over 30 days, this instance is not serving "
                        f"any meaningful workload. Terminating it would save the full "
                        f"${specs['cost']:.2f}/month (${specs['cost'] * 12:.2f}/year). "
                        f"Before terminating, verify there are no attached EBS volumes with "
                        f"important data and check if any DNS records point to this instance."
                    ))

    def _generate_rightsizing_rules(self):
        downsize_map = {
            "t3.xlarge": "t3.large", "t3.large": "t3.medium",
            "m5.2xlarge": "m5.xlarge", "m5.xlarge": "m5.large",
            "c5.xlarge": "c5.large", "r5.xlarge": "r5.large",
        }
        for src, dst in downsize_map.items():
            for cpu_avg in [8, 12, 14]:
                cpu_max = self._rng.randint(25, 38)
                src_cost = EC2_FAMILIES[src]["cost"]
                dst_cost = EC2_FAMILIES[dst]["cost"]
                savings = src_cost - dst_cost
                self._examples.append(_chat(
                    f"Analyze this EC2 instance for rightsizing:\n"
                    f"Type: {src}\nCPU avg: {cpu_avg}%, max: {cpu_max}%\n"
                    f"Memory: {EC2_FAMILIES[src]['memory_gb']}GB\n"
                    f"Monthly cost: ${src_cost:.2f}",
                    f"This {src} instance is **overprovisioned** with only {cpu_avg}% average "
                    f"CPU utilization (max {cpu_max}%). Recommend **downsizing to {dst}**, "
                    f"which still provides {EC2_FAMILIES[dst]['vcpus']} vCPUs and "
                    f"{EC2_FAMILIES[dst]['memory_gb']}GB memory — sufficient for the current "
                    f"workload. This saves ${savings:.2f}/month (${savings * 12:.2f}/year), "
                    f"a {savings / src_cost * 100:.0f}% cost reduction. Monitor for 1-2 weeks "
                    f"after downsizing to ensure performance remains acceptable."
                ))

    def _generate_spot_conversion_rules(self):
        for itype in ["t3.large", "m5.xlarge", "c5.xlarge"]:
            for env in ["development", "staging", "test", "qa"]:
                cost = EC2_FAMILIES[itype]["cost"]
                spot_savings = cost * 0.7
                self._examples.append(_chat(
                    f"This EC2 instance is tagged Environment={env}:\n"
                    f"Type: {itype}\nMonthly cost: ${cost:.2f}\n"
                    f"CPU avg: {self._rng.randint(10, 40)}%",
                    f"This **{env}** instance is an excellent candidate for **Spot Instances**. "
                    f"Non-production workloads can tolerate interruptions. Converting to Spot "
                    f"pricing typically saves 60-90% — approximately ${spot_savings:.2f}/month. "
                    f"Consider using Spot Fleet with capacity-optimized allocation strategy "
                    f"for better availability. Implement graceful shutdown handling and "
                    f"store state externally (S3/DynamoDB) to handle Spot interruptions."
                ))

    def _generate_database_rules(self):
        rds_types = {
            "db.t3.medium": 49.28, "db.t3.large": 98.55,
            "db.r5.large": 175.20, "db.r5.xlarge": 350.40,
        }
        for itype, cost in rds_types.items():
            # Low CPU
            for cpu in [3, 5, 8]:
                self._examples.append(_chat(
                    f"Analyze this RDS instance:\n"
                    f"Type: {itype}\nEngine: PostgreSQL 15\n"
                    f"CPU avg: {cpu}%, max: {cpu * 3}%\n"
                    f"Connections max: {self._rng.randint(10, 50)}\n"
                    f"Monthly cost: ${cost:.2f}",
                    f"This RDS {itype} instance is **underutilized** at {cpu}% average CPU. "
                    f"Consider downsizing to a smaller instance class. For databases with "
                    f"variable workloads, evaluate **Aurora Serverless v2** which auto-scales "
                    f"from 0.5 to 128 ACUs, paying only for capacity used. This could reduce "
                    f"costs by 40-60% for variable workloads."
                ))
            # Near-zero connections
            self._examples.append(_chat(
                f"This RDS instance has very low activity:\n"
                f"Type: {itype}\nMax connections: 2 over 30 days\n"
                f"CPU avg: 1%\nMonthly cost: ${cost:.2f}",
                f"This database appears **unused** with only 2 maximum connections over "
                f"30 days and 1% CPU. Recommend **terminating** after confirming no "
                f"application dependencies. Create a final snapshot before deletion for "
                f"recovery. This saves ${cost:.2f}/month. Check CloudTrail for recent "
                f"connection activity and verify with the application team."
            ))

    def _generate_storage_rules(self):
        for bucket_size in [10, 100, 500, 2000]:
            for req_count in [0, 2, 5]:
                cost = round(bucket_size * 0.023, 2)
                ia_cost = round(bucket_size * 0.0125, 2)
                glacier_cost = round(bucket_size * 0.004, 2)
                self._examples.append(_chat(
                    f"Analyze this S3 bucket:\n"
                    f"Size: {bucket_size}GB\nAvg requests/day: {req_count}\n"
                    f"Monthly cost: ${cost:.2f}\nStorage class: Standard",
                    f"This S3 bucket has **very low access** ({req_count} requests/day). "
                    f"Move to **S3 Intelligent-Tiering** for automatic optimization, or "
                    f"directly to **S3 Infrequent Access** (saves ${cost - ia_cost:.2f}/month) "
                    f"or **S3 Glacier** for archival (saves ${cost - glacier_cost:.2f}/month). "
                    f"Set up lifecycle rules to automatically transition objects based on age. "
                    f"For {bucket_size}GB, the annual savings with Glacier would be "
                    f"${(cost - glacier_cost) * 12:.2f}."
                ))

    def _generate_volume_rules(self):
        for size in [20, 50, 100, 500]:
            gp2_cost = round(size * 0.10, 2)
            # Unattached volume
            self._examples.append(_chat(
                f"This EBS volume is not attached to any instance:\n"
                f"Type: gp2\nSize: {size}GB\nState: available\n"
                f"Monthly cost: ${gp2_cost:.2f}",
                f"This **unattached** {size}GB gp2 volume is costing ${gp2_cost:.2f}/month "
                f"with no instance using it. Recommend **deleting** after creating a "
                f"snapshot for backup (snapshot cost: ${size * 0.05:.2f}/month, 50% cheaper "
                f"than maintaining the volume). Check if any instance expects to mount this "
                f"volume. Savings: ${gp2_cost:.2f}/month (${gp2_cost * 12:.2f}/year)."
            ))
            # Zero IOPS
            self._examples.append(_chat(
                f"This EBS volume has near-zero IOPS:\n"
                f"Type: gp2\nSize: {size}GB\nAvg IOPS: 0.1\n"
                f"Attached to: i-0abc123\nMonthly cost: ${gp2_cost:.2f}",
                f"This {size}GB volume is attached but has **near-zero IOPS** (0.1 avg), "
                f"indicating it is not being actively used. Investigate if the data has "
                f"been migrated elsewhere. If unneeded, detach and delete. If needed for "
                f"infrequent access, consider downsizing or taking a snapshot."
            ))

    def _generate_snapshot_rules(self):
        for age_days in [95, 150, 200, 365, 730]:
            for size in [20, 50, 100]:
                cost = round(size * 0.05, 2)
                self._examples.append(_chat(
                    f"Analyze this EBS snapshot:\n"
                    f"Age: {age_days} days\nSize: {size}GB\n"
                    f"Monthly cost: ${cost:.2f}",
                    f"This snapshot is **{age_days} days old** and may no longer be needed. "
                    f"Review your retention policy — AWS recommends keeping snapshots only as "
                    f"long as required for compliance or recovery. Deleting saves "
                    f"${cost:.2f}/month. Consider implementing automated lifecycle policies "
                    f"with AWS Data Lifecycle Manager to prevent snapshot accumulation."
                ))

    def _generate_ip_rules(self):
        for _ in range(10):
            ip = f"{self._rng.randint(50, 200)}.{self._rng.randint(0, 255)}.{self._rng.randint(0, 255)}.{self._rng.randint(1, 254)}"
            self._examples.append(_chat(
                f"This Elastic IP is not associated with any instance:\n"
                f"IP: {ip}\nMonthly cost: $3.65",
                f"Elastic IP {ip} is **unassociated** and being charged $3.65/month. "
                f"AWS charges for Elastic IPs that are allocated but not attached to a "
                f"running instance. Either associate it with an instance or **release it**. "
                f"Annual savings: $43.80. Check if any DNS records or security group rules "
                f"reference this IP before releasing."
            ))

    def _generate_lb_rules(self):
        for req_count in [0, 2, 5, 8]:
            self._examples.append(_chat(
                f"Analyze this Application Load Balancer:\n"
                f"Avg requests/day: {req_count}\n"
                f"Monthly cost: $22.27\nHealthy targets: 1",
                f"This ALB is handling only **{req_count} requests/day** — far below the "
                f"threshold where a load balancer adds value. Consider removing the ALB and "
                f"connecting directly to the instance, or consolidating multiple low-traffic "
                f"ALBs into one using path-based routing. Savings: $22.27/month. "
                f"If you need HTTPS termination, consider using CloudFront instead."
            ))

    # ── Infrastructure Alternatives ──

    def _generate_arm_migration(self):
        for x86_type, arm_type in GRAVITON_MAP.items():
            if "." not in x86_type:
                continue
            if x86_type not in EC2_FAMILIES:
                continue
            x86_cost = EC2_FAMILIES[x86_type]["cost"]
            arm_cost = round(x86_cost * 0.8, 2)  # ~20% cheaper
            savings = round(x86_cost - arm_cost, 2)
            self._examples.append(_chat(
                f"Can this instance be migrated to ARM/Graviton?\n"
                f"Type: {x86_type}\nArchitecture: x86_64\n"
                f"Workload: containerized web service\nMonthly cost: ${x86_cost:.2f}",
                f"Yes, this {x86_type} can be migrated to **{arm_type}** (AWS Graviton). "
                f"Graviton instances provide up to 20% better price-performance. "
                f"Estimated savings: ${savings:.2f}/month (${savings * 12:.2f}/year). "
                f"Migration steps: 1) Rebuild container images for ARM64, "
                f"2) Test in staging with {arm_type}, 3) Update launch template, "
                f"4) Deploy via rolling update. Most containerized workloads migrate "
                f"seamlessly — check for x86-specific native dependencies."
            ))

    def _generate_gp2_to_gp3(self):
        for size in [20, 50, 100, 200, 500, 1000]:
            gp2_cost = round(size * 0.10, 2)
            gp3_cost = round(size * 0.08, 2)
            savings = round(gp2_cost - gp3_cost, 2)
            self._examples.append(_chat(
                f"This EBS volume uses gp2:\n"
                f"Type: gp2\nSize: {size}GB\n"
                f"Provisioned IOPS: {min(size * 3, 16000)}\n"
                f"Monthly cost: ${gp2_cost:.2f}",
                f"**Migrate to gp3** — it's always cheaper and offers better baseline "
                f"performance. gp3 provides 3,000 IOPS and 125 MB/s throughput baseline "
                f"(vs gp2's 100 IOPS/GB scaling). For {size}GB: gp2 costs ${gp2_cost:.2f}/mo "
                f"vs gp3 at ${gp3_cost:.2f}/mo, saving ${savings:.2f}/month. "
                f"Migration is online — use EBS Modify Volume with zero downtime. "
                f"This is a risk-free optimization with immediate savings."
            ))

    def _generate_reserved_savings(self):
        for itype in ["m5.xlarge", "c5.xlarge", "r5.large"]:
            od_cost = EC2_FAMILIES[itype]["cost"]
            ri_1yr = round(od_cost * 0.6, 2)
            ri_3yr = round(od_cost * 0.4, 2)
            sp_1yr = round(od_cost * 0.63, 2)
            self._examples.append(_chat(
                f"This production instance runs 24/7:\n"
                f"Type: {itype}\nUptime: 100% over 6 months\n"
                f"On-demand cost: ${od_cost:.2f}/month",
                f"For steady-state workloads like this, consider **Compute Savings Plans** "
                f"or **Reserved Instances**:\n\n"
                f"- **1-Year Savings Plan**: ${sp_1yr:.2f}/mo (saves ${od_cost - sp_1yr:.2f}/mo, "
                f"{(od_cost - sp_1yr) / od_cost * 100:.0f}% off)\n"
                f"- **1-Year RI**: ${ri_1yr:.2f}/mo (saves ${od_cost - ri_1yr:.2f}/mo)\n"
                f"- **3-Year RI**: ${ri_3yr:.2f}/mo (saves ${od_cost - ri_3yr:.2f}/mo)\n\n"
                f"Savings Plans are more flexible — they apply across instance families and "
                f"regions. Start with a 1-year commitment for {(od_cost - sp_1yr) * 12:.0f}/year savings."
            ))

    def _generate_serverless_candidates(self):
        for itype in ["t3.micro", "t3.small", "t3.medium"]:
            cost = EC2_FAMILIES[itype]["cost"]
            for cpu_pattern in ["spiky (0-80% with long idle)", "bursty (peaks 2x daily)"]:
                self._examples.append(_chat(
                    f"This instance has a {cpu_pattern} CPU pattern:\n"
                    f"Type: {itype}\nCPU avg: {self._rng.randint(3, 12)}%\n"
                    f"Workload: API backend processing\nMonthly cost: ${cost:.2f}",
                    f"With a {cpu_pattern} pattern and low average CPU, this is an excellent "
                    f"candidate for **serverless migration** (AWS Lambda + API Gateway or "
                    f"AWS Fargate). Benefits:\n"
                    f"- Pay only for actual compute time (likely 70-90% savings)\n"
                    f"- Automatic scaling to zero during idle periods\n"
                    f"- No patching/maintenance overhead\n"
                    f"- Estimated cost: ${cost * 0.15:.2f}-${cost * 0.3:.2f}/month\n\n"
                    f"Migration path: Containerize the app, deploy to Fargate with "
                    f"autoscaling min=0, or refactor to Lambda functions."
                ))

    # ── FinOps & Best Practices ──

    def _generate_finops_principles(self):
        finops_qas = [
            (
                "What are the key FinOps principles for cloud cost management?",
                "The core FinOps principles are:\n\n"
                "1. **Teams need to collaborate** — Engineering, finance, and business teams "
                "must work together on cloud costs with shared accountability.\n"
                "2. **Everyone takes ownership** — Engineers should consider cost as an "
                "efficiency metric alongside performance and reliability.\n"
                "3. **A centralized team drives FinOps** — A dedicated FinOps practice sets "
                "best practices, provides tooling, and tracks optimization.\n"
                "4. **Reports should be accessible and timely** — Real-time cost visibility "
                "enables faster optimization decisions.\n"
                "5. **Decisions are driven by business value** — Not just cheapest option, "
                "but best cost-to-value ratio for the business.\n"
                "6. **Take advantage of the variable cost model** — Cloud's pay-as-you-go "
                "model is an advantage when managed properly."
            ),
            (
                "How should I implement a tagging strategy for cost allocation?",
                "A robust tagging strategy is foundational for FinOps:\n\n"
                "**Required tags** (enforce via AWS SCPs/Azure Policy):\n"
                "- `Environment`: production/staging/development\n"
                "- `Team` or `CostCenter`: maps to organizational billing\n"
                "- `Application`: identifies the workload\n"
                "- `Owner`: person/team responsible\n\n"
                "**Recommended tags**:\n"
                "- `DataClassification`: helps with compliance\n"
                "- `AutoShutdown`: for scheduling non-prod resources\n\n"
                "Use AWS Tag Policies to enforce naming conventions. Untagged resources "
                "should trigger alerts. Tag compliance should be part of CI/CD pipelines."
            ),
            (
                "What's the difference between Reserved Instances and Savings Plans?",
                "**Reserved Instances (RIs)**:\n"
                "- Locked to specific instance type, region, and OS\n"
                "- Can be Standard (cheapest, least flexible) or Convertible\n"
                "- Best for predictable, steady-state workloads\n"
                "- Up to 72% savings on 3-year terms\n\n"
                "**Savings Plans**:\n"
                "- Commit to a $/hour spend (not specific instance type)\n"
                "- **Compute Savings Plans** apply across all instance families and regions\n"
                "- **EC2 Instance Savings Plans** are cheaper but locked to instance family\n"
                "- More flexible — automatically applies to best savings\n"
                "- Up to 66% savings\n\n"
                "**Recommendation**: Start with Compute Savings Plans for flexibility, "
                "then layer EC2 Instance Savings Plans for additional savings on steady base."
            ),
        ]
        for q, a in finops_qas:
            self._examples.append(_chat(q, a))

    def _generate_aws_best_practices(self):
        practices = [
            (
                "What are the best practices for optimizing EC2 costs?",
                "Key EC2 cost optimization strategies:\n\n"
                "1. **Right-size instances** — Use CloudWatch CPU/memory metrics to identify "
                "overprovisioned instances. Target 40-70% average utilization.\n"
                "2. **Use Graviton/ARM instances** — 20% cheaper with better performance "
                "for most workloads. Test with t4g/m6g families.\n"
                "3. **Leverage Spot for fault-tolerant workloads** — 60-90% savings for "
                "batch processing, CI/CD, dev/test environments.\n"
                "4. **Schedule non-production resources** — Auto-stop dev/staging instances "
                "outside business hours (saves 65% if stopped 16h/day).\n"
                "5. **Use Savings Plans for steady-state** — Commit to predictable base "
                "spend for 30-60% savings.\n"
                "6. **Enable detailed monitoring** — $3.50/instance/month but enables "
                "1-minute metrics for better rightsizing decisions.\n"
                "7. **Review and terminate idle instances** — Resources with <5% CPU for "
                "30+ days are likely unnecessary."
            ),
            (
                "How should I optimize RDS database costs?",
                "RDS cost optimization approaches:\n\n"
                "1. **Right-size instances** — Most databases run at <20% CPU. Downsize "
                "aggressively and monitor.\n"
                "2. **Use Aurora Serverless v2** for variable workloads — auto-scales "
                "and can reduce costs 40-60% vs provisioned.\n"
                "3. **Consider read replicas** — Offload read traffic instead of scaling "
                "up the primary instance.\n"
                "4. **Disable Multi-AZ for non-production** — saves ~50% immediately.\n"
                "5. **Use Reserved Instances** for production databases on 1-year terms.\n"
                "6. **Review storage type** — gp3 is cheaper than io1/io2 for most workloads.\n"
                "7. **Schedule dev databases** — Use AWS Instance Scheduler to stop during "
                "off-hours."
            ),
            (
                "What are S3 storage optimization best practices?",
                "S3 cost optimization:\n\n"
                "1. **Use S3 Intelligent-Tiering** for unknown access patterns — "
                "automatically moves objects between tiers at no retrieval cost.\n"
                "2. **Set lifecycle policies** — Transition infrequently accessed data:\n"
                "   - Standard → IA after 30 days (46% cheaper)\n"
                "   - IA → Glacier Flexible after 90 days (83% cheaper)\n"
                "   - Glacier → Deep Archive after 180 days (95% cheaper)\n"
                "3. **Enable S3 Storage Lens** for visibility into usage patterns.\n"
                "4. **Delete incomplete multipart uploads** — They silently accumulate cost.\n"
                "5. **Use S3 Analytics** to identify optimal lifecycle rules.\n"
                "6. **Compress data before storage** — gzip/zstd can reduce size 60-80%."
            ),
        ]
        for q, a in practices:
            self._examples.append(_chat(q, a))

    def _generate_general_cost_qa(self):
        """Generate general cost optimization Q&A pairs."""
        qas = [
            (
                "My AWS bill increased 40% this month. How do I investigate?",
                "Systematic investigation steps:\n\n"
                "1. **Check Cost Explorer** with daily granularity, grouped by Service — "
                "identify which service spiked.\n"
                "2. **Filter by region** — unexpected resources in new regions are common.\n"
                "3. **Check for new resources** — Sort by 'Usage Type' to find new charges.\n"
                "4. **Review data transfer charges** — Often the hidden cost driver, "
                "especially cross-region or internet egress.\n"
                "5. **Check for orphaned resources** — Snapshots, unattached EBS volumes, "
                "and unused Elastic IPs accumulate silently.\n"
                "6. **Set up AWS Budgets** with alerts at 80% and 100% of target spend "
                "to catch future surprises early."
            ),
            (
                "Should I use on-demand, reserved, or spot instances?",
                "It depends on the workload characteristics:\n\n"
                "**On-Demand** — Use for:\n- Unpredictable, short-term workloads\n"
                "- New applications being tested\n- Workloads that can't be interrupted\n\n"
                "**Reserved/Savings Plans** — Use for:\n- Production workloads running 24/7\n"
                "- Databases and persistent services\n- Any workload running >6 months\n"
                "- Start with 1-year No Upfront for low commitment\n\n"
                "**Spot Instances** — Use for:\n- Batch processing and data pipelines\n"
                "- CI/CD build workers\n- Dev/test environments\n"
                "- Stateless web servers behind autoscaling groups\n\n"
                "**Optimal mix**: 60% Savings Plans + 20% Spot + 20% On-Demand"
            ),
            (
                "How do I reduce data transfer costs in AWS?",
                "Data transfer is often the fastest-growing cost:\n\n"
                "1. **Use VPC Endpoints** for AWS service access — eliminates NAT Gateway "
                "data processing charges ($0.045/GB).\n"
                "2. **Keep traffic in-region** — Cross-region transfer costs $0.02/GB vs "
                "$0.01/GB within-AZ.\n"
                "3. **Use CloudFront** for content delivery — cheaper than direct S3/EC2 "
                "egress and adds caching.\n"
                "4. **Compress API responses** — gzip reduces data transfer 60-80%.\n"
                "5. **Use AWS PrivateLink** for VPC-to-VPC communication.\n"
                "6. **Review NAT Gateway usage** — at $0.045/GB processed, consider "
                "alternatives like NAT instances for dev environments."
            ),
        ]
        for q, a in qas:
            self._examples.append(_chat(q, a))


def main():
    """CLI entry point to generate the training dataset."""
    builder = DatasetBuilder()
    output_path = Path(__file__).parent.parent.parent.parent / "data" / "training_dataset.jsonl"
    count = builder.save(output_path)
    print(f"Generated {count} training examples at {output_path}")


if __name__ == "__main__":
    main()
