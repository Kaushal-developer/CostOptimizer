import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { resourcesService, type ResourceRecommendation } from '../services/api';
import MetricsChart from '../components/resources/MetricsChart';
import { humanizeKey, formatCurrency, formatBytes } from '../utils/formatters';
import { ArrowLeftIcon, CheckCircleIcon, ArrowTrendingDownIcon } from '@heroicons/react/24/outline';
import clsx from 'clsx';

const STATUS_COLORS: Record<string, string> = {
  active: 'badge-success',
  idle: 'badge-warning',
  stopped: 'badge-info',
  underutilized: 'badge-warning',
  zombie: 'badge-danger',
  overprovisioned: 'badge-danger',
  optimized: 'badge-success',
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'border-rose-500/50 bg-rose-500/10',
  high: 'border-orange-500/50 bg-orange-500/10',
  medium: 'border-amber-500/50 bg-amber-500/10',
  low: 'border-cyan-500/50 bg-cyan-500/10',
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: 'badge-danger',
  high: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  medium: 'badge-warning',
  low: 'badge-info',
};

const TYPE_LABELS: Record<string, string> = {
  rightsize: 'Rightsize', terminate: 'Terminate', reserve: 'Reserved',
  spot_convert: 'Spot Convert', storage_tier: 'Storage Tier',
  delete_snapshot: 'Delete Snapshot', delete_volume: 'Delete Volume',
  release_ip: 'Release IP', modernize: 'Modernize', arm_migrate: 'ARM/Graviton',
  serverless: 'Serverless', region_move: 'Region Move',
  savings_plan: 'Savings Plan', gp3_upgrade: 'GP3 Upgrade',
};

const METRIC_DEFS: Record<string, Array<{ name: string; label: string; unit: string }>> = {
  'ec2:instance': [
    { name: 'cpu_utilization', label: 'CPU Utilization', unit: '%' },
    { name: 'network_in', label: 'Network In', unit: ' bytes' },
    { name: 'network_out', label: 'Network Out', unit: ' bytes' },
    { name: 'disk_read_ops', label: 'Disk Read Ops', unit: '' },
    { name: 'disk_write_ops', label: 'Disk Write Ops', unit: '' },
    { name: 'status_check_failed', label: 'Status Check Failed', unit: '' },
  ],
  'rds:instance': [
    { name: 'cpu_utilization', label: 'CPU Utilization', unit: '%' },
    { name: 'database_connections', label: 'DB Connections', unit: '' },
    { name: 'free_storage_space', label: 'Free Storage', unit: ' bytes' },
    { name: 'read_iops', label: 'Read IOPS', unit: '' },
    { name: 'write_iops', label: 'Write IOPS', unit: '' },
    { name: 'freeable_memory', label: 'Freeable Memory', unit: ' bytes' },
  ],
  'ebs:volume': [
    { name: 'disk_iops', label: 'Volume Read Ops', unit: '' },
    { name: 'volume_write_ops', label: 'Volume Write Ops', unit: '' },
    { name: 'volume_idle_time', label: 'Idle Time', unit: 's' },
  ],
  'elbv2:application': [
    { name: 'request_count', label: 'Request Count', unit: '' },
  ],
  's3:bucket': [
    { name: 'bucket_size_bytes', label: 'Bucket Size', unit: ' bytes' },
    { name: 'number_of_objects', label: 'Object Count', unit: '' },
  ],
};

const META_LABELS: Record<string, string> = {
  state: 'State', platform: 'Platform', launch_time: 'Launch Time',
  vpc_id: 'VPC', subnet_id: 'Subnet', availability_zone: 'Availability Zone',
  architecture: 'Architecture', security_groups: 'Security Groups',
  ebs_optimized: 'EBS Optimized', purchase_type: 'Purchase Type',
  iam_profile: 'IAM Profile', monitoring: 'Monitoring',
  engine: 'Engine', engine_version: 'Engine Version', multi_az: 'Multi-AZ',
  storage_type: 'Storage Type', encrypted: 'Encrypted',
  backup_retention_period: 'Backup Retention', publicly_accessible: 'Publicly Accessible',
  volume_type: 'Volume Type', iops: 'Provisioned IOPS', throughput: 'Throughput',
  attachments: 'Attached To', versioning: 'Versioning', encryption: 'Encryption',
  public_access_blocked: 'Public Access Blocked', type: 'Type', scheme: 'Scheme',
  dns_name: 'DNS Name', ip_address_type: 'IP Address Type', public_ip: 'Public IP',
  associated: 'Associated', instance_id: 'Instance ID', domain: 'Domain',
  deletion_protection: 'Deletion Protection', read_replicas: 'Read Replicas',
  root_device_type: 'Root Device', create_time: 'Created',
};

function formatMetaValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : '—';
  return String(value);
}

export default function ResourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const resourceId = Number(id);

  const { data: resource, isLoading } = useQuery({
    queryKey: ['resource', resourceId],
    queryFn: () => resourcesService.get(resourceId),
    enabled: !isNaN(resourceId),
  });

  const { data: recommendations } = useQuery({
    queryKey: ['resource-recommendations', resourceId],
    queryFn: () => resourcesService.getRecommendations(resourceId),
    enabled: !isNaN(resourceId),
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!resource) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Resource not found</p>
        <button className="btn-secondary mt-4" onClick={() => navigate('/resources')}>Back to Resources</button>
      </div>
    );
  }

  const metricDefs = METRIC_DEFS[resource.provider_resource_type] || [];
  const metadata = resource.metadata || {};
  const metaEntries = Object.entries(metadata).filter(([key]) => !['status'].includes(key));
  const metricMap = new Map(resource.metrics.map(m => [m.metric_name, m]));
  const recs = recommendations ?? [];
  const totalSavings = recs.reduce((sum, r) => sum + r.estimated_savings, 0);

  const monthlyCost = resource.monthly_cost;
  const annualCost = monthlyCost * 12;
  const optimizedMonthlyCost = Math.max(0, monthlyCost - totalSavings);
  const optimizedAnnualCost = optimizedMonthlyCost * 12;
  const createdDate = new Date(resource.created_at);
  const daysSinceCreated = Math.max(1, Math.floor((Date.now() - createdDate.getTime()) / 86400000));
  const estimatedSpentSoFar = monthlyCost * (daysSinceCreated / 30);

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button onClick={() => navigate('/resources')} className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors">
        <ArrowLeftIcon className="h-4 w-4" /> Back to Resources
      </button>

      {/* HEADER */}
      <div className="card">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">{resource.name || resource.resource_id}</h1>
            <p className="text-sm text-gray-400 mt-1">
              {humanizeKey(resource.provider_resource_type)} &middot; {resource.region}
              {resource.instance_type && ` \u00b7 ${resource.instance_type}`}
            </p>
            <div className="flex items-center gap-2 mt-2">
              <span className={clsx('badge', STATUS_COLORS[resource.status] ?? 'badge-info')}>
                {humanizeKey(resource.status)}
              </span>
              {metadata.purchase_type ? (
                <span className="badge bg-violet-500/20 text-violet-400 border border-violet-500/30">
                  {String(metadata.purchase_type)}
                </span>
              ) : null}
              {metadata.architecture ? (
                <span className="badge bg-brand-500/20 text-brand-400 border border-brand-500/30">
                  {String(metadata.architecture)}
                </span>
              ) : null}
            </div>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold text-white">
              {formatCurrency(monthlyCost)}<span className="text-sm text-gray-500 font-normal">/mo</span>
            </p>
            <p className="text-sm text-gray-500">{formatCurrency(annualCost)}/year</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-6 mt-4 pt-4 border-t border-gray-700/50">
          {resource.vcpus != null && <Spec label="vCPUs" value={String(resource.vcpus)} />}
          {resource.memory_gb != null && <Spec label="Memory" value={`${resource.memory_gb} GB`} />}
          {resource.storage_gb != null && resource.storage_gb > 0 && <Spec label="Storage" value={`${resource.storage_gb} GB`} />}
          <Spec label="Resource ID" value={resource.resource_id} mono />
          <Spec label="First Seen" value={createdDate.toLocaleDateString()} />
          <Spec label="Last Seen" value={new Date(resource.last_seen_at).toLocaleDateString()} />
        </div>
      </div>

      {/* COST & BILLING */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-3">Cost & Billing</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <CostCard label="Current Monthly Cost" amount={monthlyCost} sub={`${formatCurrency(annualCost)}/year`} accent="brand" />
          <CostCard label="Estimated Spent So Far" amount={estimatedSpentSoFar} sub={`${daysSinceCreated} days tracked`} accent="gray" />
          <CostCard label="Projected Optimized Cost" amount={optimizedMonthlyCost} sub={`${formatCurrency(optimizedAnnualCost)}/year projected`} accent="emerald" />
          <CostCard
            label="Potential Savings"
            amount={totalSavings}
            sub={`${monthlyCost > 0 ? `${((totalSavings / monthlyCost) * 100).toFixed(0)}% reduction` : '—'} \u00b7 ${formatCurrency(totalSavings * 12)}/year`}
            accent="cyan"
          />
        </div>
      </div>

      {/* USAGE METRICS */}
      {(metricDefs.length > 0 || resource.metrics.length > 0) && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-3">Usage Metrics (Last 30 Days)</h2>
          {resource.metrics.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {metricDefs.map((md) => {
                const m = metricMap.get(md.name);
                if (!m) return null;
                return (
                  <MetricsChart
                    key={md.name}
                    resourceId={resourceId}
                    metricName={md.name}
                    label={md.label}
                    unit={md.unit}
                    summaryData={{ avg: m.avg_value, max: m.max_value, min: m.min_value, p95: m.p95_value }}
                  />
                );
              })}
              {resource.metrics.filter(m => !metricDefs.some(md => md.name === m.metric_name)).map(m => (
                <MetricsChart
                  key={m.metric_name}
                  resourceId={resourceId}
                  metricName={m.metric_name}
                  label={humanizeKey(m.metric_name)}
                  unit=""
                  summaryData={{ avg: m.avg_value, max: m.max_value, min: m.min_value, p95: m.p95_value }}
                />
              ))}
            </div>
          ) : (
            <div className="card text-center text-gray-500 py-8">
              No metrics data collected yet. Sync your cloud account to fetch CloudWatch metrics.
            </div>
          )}
        </div>
      )}

      {/* METRICS TABLE */}
      {resource.metrics.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-3">Metrics Summary</h2>
          <div className="card p-0 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-700/50">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">Metric</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">Average</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">Max</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">Min</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">P95</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-400 text-xs uppercase tracking-wider">Period</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {resource.metrics.map((m) => {
                  const def = metricDefs.find(d => d.name === m.metric_name);
                  const unit = def?.unit || '';
                  const isBytes = unit === ' bytes';
                  return (
                    <tr key={m.id} className="hover:bg-surface-200/50 transition-colors">
                      <td className="px-4 py-2.5 font-medium text-white">
                        {def?.label || humanizeKey(m.metric_name)}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300 font-mono text-xs">
                        {isBytes ? formatBytes(m.avg_value) : m.avg_value.toFixed(2)}{!isBytes && unit}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300 font-mono text-xs">
                        {isBytes ? formatBytes(m.max_value) : m.max_value.toFixed(2)}{!isBytes && unit}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300 font-mono text-xs">
                        {isBytes ? formatBytes(m.min_value) : m.min_value.toFixed(2)}{!isBytes && unit}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300 font-mono text-xs">
                        {m.p95_value != null ? (isBytes ? formatBytes(m.p95_value) : m.p95_value.toFixed(2) + unit) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-500 text-xs">{m.period_days}d</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* OPTIMIZATION RECOMMENDATIONS */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-white">Optimization Recommendations</h2>
          {recs.length > 0 && (
            <div className="flex items-center gap-2">
              <ArrowTrendingDownIcon className="h-5 w-5 text-emerald-400" />
              <span className="text-sm font-semibold text-emerald-400">
                Save {formatCurrency(totalSavings)}/mo
              </span>
            </div>
          )}
        </div>
        {recs.length > 0 ? (
          <div className="space-y-3">
            {recs.map((rec) => <RecommendationCard key={rec.id} rec={rec} />)}
          </div>
        ) : (
          <div className="card text-center text-gray-500 py-8">
            <CheckCircleIcon className="h-8 w-8 mx-auto mb-2 text-emerald-400" />
            No optimization recommendations — this resource is already well-optimized.
          </div>
        )}
      </div>

      {/* CONFIGURATION DETAILS */}
      {metaEntries.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-3">Configuration Details</h2>
          <div className="card">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {metaEntries.map(([key, value]) => (
                <div key={key}>
                  <span className="text-xs text-gray-500">{META_LABELS[key] || humanizeKey(key)}</span>
                  <p className="text-sm font-medium text-gray-300 truncate" title={formatMetaValue(value)}>
                    {formatMetaValue(value)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAGS */}
      {resource.tags && Object.keys(resource.tags).length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-white mb-3">Tags</h2>
          <div className="card">
            <div className="flex flex-wrap gap-2">
              {Object.entries(resource.tags).map(([k, v]) => (
                <span key={k} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-surface-200 text-xs border border-gray-700/50">
                  <span className="font-medium text-gray-300">{k}</span>
                  <span className="text-gray-500">= {v}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Spec({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <span className="text-xs text-gray-500">{label}</span>
      <p className={clsx('text-sm font-semibold text-gray-200', mono && 'font-mono text-gray-400')}>{value}</p>
    </div>
  );
}

const ACCENT_MAP: Record<string, { bg: string; text: string; sub: string }> = {
  brand: { bg: 'bg-brand-500/10 border-brand-500/30', text: 'text-brand-400', sub: 'text-brand-400/80' },
  gray: { bg: 'bg-surface-200 border-gray-700/50', text: 'text-white', sub: 'text-gray-500' },
  emerald: { bg: 'bg-emerald-500/10 border-emerald-500/30', text: 'text-emerald-400', sub: 'text-emerald-400/80' },
  cyan: { bg: 'bg-cyan-500/10 border-cyan-500/30', text: 'text-cyan-400', sub: 'text-cyan-400/80' },
};

function CostCard({ label, amount, sub, accent }: { label: string; amount: number; sub: string; accent: string }) {
  const colors = ACCENT_MAP[accent] ?? ACCENT_MAP.gray;
  return (
    <div className={clsx('card border', colors.bg)}>
      <span className={clsx('text-xs font-medium', colors.sub)}>{label}</span>
      <p className={clsx('text-2xl font-bold', colors.text)}>
        {formatCurrency(amount)}
      </p>
      <span className={clsx('text-xs', colors.sub)}>{sub}</span>
    </div>
  );
}

function RecommendationCard({ rec }: { rec: ResourceRecommendation }) {
  return (
    <div className={clsx('border-l-4 rounded-lg p-4 bg-surface-100/60 border border-gray-700/50', PRIORITY_COLORS[rec.priority] ?? 'border-gray-600/50')}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={clsx('badge', PRIORITY_BADGE[rec.priority] ?? 'badge-info')}>
              {humanizeKey(rec.priority)}
            </span>
            <span className="badge bg-surface-200 text-gray-400 border border-gray-700/50">
              {TYPE_LABELS[rec.type] || humanizeKey(rec.type)}
            </span>
            <span className="text-xs text-gray-500">{rec.confidence_score}% confidence</span>
          </div>
          <h3 className="font-semibold text-white text-sm">{rec.title}</h3>
          <p className="text-sm text-gray-400 mt-1 whitespace-pre-line">{rec.description}</p>
          {rec.ai_explanation && (
            <p className="text-xs text-brand-400 mt-2 italic">{rec.ai_explanation}</p>
          )}
          {rec.recommended_config && (
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(rec.recommended_config).map(([k, v]) => (
                <span key={k} className="text-xs bg-brand-500/20 text-brand-400 px-2 py-0.5 rounded font-mono border border-brand-500/30">
                  {k}: {String(v)}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className="text-lg font-bold text-emerald-400">
            {formatCurrency(rec.estimated_savings)}
          </p>
          <p className="text-xs text-gray-500">/month</p>
          <div className="mt-1 text-xs text-gray-500">
            {formatCurrency(rec.current_monthly_cost)} &rarr; {formatCurrency(rec.estimated_monthly_cost)}
          </div>
        </div>
      </div>
    </div>
  );
}
