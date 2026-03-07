import { useQuery } from '@tanstack/react-query';
import { resourcesService, exportService } from '../services/api';
import { formatCurrency, humanizeKey, formatPercent } from '../utils/formatters';
import { ArrowDownTrayIcon } from '@heroicons/react/24/outline';

const METRIC_LABELS: Record<string, string> = {
  cpu_utilization: 'CPU Utilization',
  network_in: 'Network In',
  network_out: 'Network Out',
  disk_read_ops: 'Disk Read Ops',
  disk_write_ops: 'Disk Write Ops',
  database_connections: 'DB Connections',
  free_storage_space: 'Free Storage',
  read_iops: 'Read IOPS',
  write_iops: 'Write IOPS',
  freeable_memory: 'Freeable Memory',
  request_count: 'Request Count',
  volume_idle_time: 'Volume Idle Time',
};

function getUtilColor(value: number): string {
  if (value < 10) return 'text-rose-400 bg-rose-500/20';
  if (value < 30) return 'text-amber-400 bg-amber-500/20';
  if (value < 70) return 'text-emerald-400 bg-emerald-500/20';
  return 'text-cyan-400 bg-cyan-500/20';
}

export default function MonitoringPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['resources-monitoring'],
    queryFn: () => resourcesService.list({ page_size: 100 }),
  });

  const resources = data?.items ?? [];

  // Fetch metrics for each resource (in parallel via React Query)
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Resource Monitoring</h1>
          <p className="text-sm text-gray-400 mt-1">Real-time utilization metrics across all resources</p>
        </div>
        <button onClick={() => exportService.utilization()} className="btn-secondary flex items-center gap-2">
          <ArrowDownTrayIcon className="h-4 w-4" /> Export Utilization
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
        </div>
      ) : resources.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400">No resources found. Connect a cloud account and sync to see monitoring data.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Summary Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="card-sm">
              <p className="stat-label">Total Resources</p>
              <p className="stat-value">{data?.total ?? 0}</p>
            </div>
            <div className="card-sm">
              <p className="stat-label">Compute</p>
              <p className="stat-value">{resources.filter((r) => r.resource_type === 'compute').length}</p>
            </div>
            <div className="card-sm">
              <p className="stat-label">Database</p>
              <p className="stat-value">{resources.filter((r) => r.resource_type === 'database').length}</p>
            </div>
            <div className="card-sm">
              <p className="stat-label">Monthly Spend</p>
              <p className="stat-value">{formatCurrency(resources.reduce((s, r) => s + r.monthly_cost, 0))}</p>
            </div>
          </div>

          {/* Resource Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {resources.map((r) => (
              <ResourceMonitorCard key={r.id} resource={r} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ResourceMonitorCard({ resource }: { resource: { id: number; name: string | null; resource_id: string; resource_type: string; region: string; instance_type: string | null; monthly_cost: number; status: string } }) {
  const { data: metrics } = useQuery({
    queryKey: ['resource-metrics', resource.id],
    queryFn: () => resourcesService.getMetrics(resource.id),
  });

  const cpuMetric = metrics?.find((m) => m.metric_name === 'cpu_utilization');
  const topMetrics = (metrics || []).slice(0, 4);

  return (
    <a href={`/resources/${resource.id}`} className="card-sm hover:border-brand-500/50 transition-all block">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-white truncate max-w-[200px]">
            {resource.name || resource.resource_id}
          </h3>
          <p className="text-xs text-gray-500">{humanizeKey(resource.resource_type)} &middot; {resource.region}</p>
        </div>
        <span className={`badge ${resource.status === 'active' ? 'badge-success' : resource.status === 'idle' ? 'badge-warning' : 'badge-info'}`}>
          {humanizeKey(resource.status)}
        </span>
      </div>

      {cpuMetric && (
        <div className="mb-3">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-gray-400">CPU Utilization</span>
            <span className={`font-medium px-1.5 py-0.5 rounded ${getUtilColor(cpuMetric.avg_value)}`}>
              {formatPercent(cpuMetric.avg_value)}
            </span>
          </div>
          <div className="h-1.5 bg-surface-300 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-500 to-accent-cyan transition-all"
              style={{ width: `${Math.min(cpuMetric.avg_value, 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {topMetrics.filter(m => m.metric_name !== 'cpu_utilization').slice(0, 2).map((m) => (
          <div key={m.metric_name} className="text-xs">
            <span className="text-gray-500">{METRIC_LABELS[m.metric_name] || humanizeKey(m.metric_name)}</span>
            <p className="text-gray-300 font-medium">{m.avg_value < 1000 ? m.avg_value.toFixed(1) : `${(m.avg_value / 1000).toFixed(1)}K`}</p>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-gray-700/30 flex items-center justify-between text-xs">
        <span className="text-gray-500">{resource.instance_type || '-'}</span>
        <span className="text-gray-300 font-medium">{formatCurrency(resource.monthly_cost)}/mo</span>
      </div>
    </a>
  );
}
