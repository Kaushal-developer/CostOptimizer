import { useQuery } from '@tanstack/react-query';
import { resourcesService } from '../../services/api';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from 'recharts';

interface Props {
  resourceId: number;
  metricName: string;
  label: string;
  unit?: string;
  color?: string;
  days?: number;
  /** If provided, shows a gauge-style summary instead of fetching history */
  summaryData?: { avg: number; max: number; min: number; p95?: number | null };
}

const METRIC_COLORS: Record<string, string> = {
  cpu_utilization: '#6366f1',
  network_in: '#10b981',
  network_out: '#f59e0b',
  disk_read_ops: '#8b5cf6',
  disk_write_ops: '#ef4444',
  database_connections: '#06b6d4',
  request_count: '#ec4899',
  disk_iops: '#f97316',
  free_storage_space: '#14b8a6',
  read_iops: '#a855f7',
  write_iops: '#f43f5e',
  freeable_memory: '#0ea5e9',
  volume_write_ops: '#fb923c',
  volume_idle_time: '#94a3b8',
  status_check_failed: '#dc2626',
  bucket_size_bytes: '#8b5cf6',
  number_of_objects: '#06b6d4',
};

function formatValue(value: number, unit: string): string {
  if (unit === ' bytes' || unit === 'bytes') {
    if (value >= 1e12) return `${(value / 1e12).toFixed(1)} TB`;
    if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`;
    if (value >= 1e6) return `${(value / 1e6).toFixed(1)} MB`;
    if (value >= 1e3) return `${(value / 1e3).toFixed(1)} KB`;
    return `${value.toFixed(0)} B`;
  }
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(value < 10 ? 2 : 0);
}

/** Summary bar showing avg/max/p95 when only single-point data is available */
function MetricSummaryBar({ data, unit, color }: { data: NonNullable<Props['summaryData']>; unit: string; color: string }) {
  const bars = [
    { name: 'Min', value: data.min, fill: '#d1d5db' },
    { name: 'Avg', value: data.avg, fill: color },
    { name: 'P95', value: data.p95 ?? data.avg, fill: `${color}cc` },
    { name: 'Max', value: data.max, fill: `${color}88` },
  ];

  return (
    <div>
      <div className="flex items-end gap-4 mb-2">
        <div>
          <span className="text-2xl font-bold" style={{ color }}>{formatValue(data.avg, unit)}</span>
          <span className="text-xs text-gray-500 ml-1">{unit === ' bytes' ? '' : unit} avg</span>
        </div>
        <div className="text-sm text-gray-500">
          max {formatValue(data.max, unit)}{unit === ' bytes' ? '' : unit}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <BarChart data={bars} layout="vertical">
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#9ca3af' }} width={30} />
          <Tooltip formatter={(v: number) => [formatValue(v, unit), '']} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {bars.map((b, i) => <Cell key={i} fill={b.fill} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function MetricsChart({ resourceId, metricName, label, unit = '', color, days = 30, summaryData }: Props) {
  const chartColor = color || METRIC_COLORS[metricName] || '#6366f1';

  // If summary data is provided, show the gauge-style bar
  if (summaryData) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h4 className="text-sm font-medium text-gray-700 mb-3">{label}</h4>
        <MetricSummaryBar data={summaryData} unit={unit} color={chartColor} />
      </div>
    );
  }

  // Otherwise fetch time-series history
  return <MetricsChartWithHistory resourceId={resourceId} metricName={metricName} label={label} unit={unit} color={chartColor} days={days} />;
}

function MetricsChartWithHistory({ resourceId, metricName, label, unit, color, days }: { resourceId: number; metricName: string; label: string; unit: string; color: string; days: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['metrics-history', resourceId, metricName, days],
    queryFn: () => resourcesService.getMetricsHistory(resourceId, metricName, days),
  });

  if (isLoading) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h4 className="text-sm font-medium text-gray-700 mb-3">{label}</h4>
        <div className="h-48 flex items-center justify-center">
          <div className="animate-spin h-5 w-5 border-2 border-indigo-600 border-t-transparent rounded-full" />
        </div>
      </div>
    );
  }

  const points = data?.datapoints ?? [];

  if (points.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h4 className="text-sm font-medium text-gray-700 mb-3">{label}</h4>
        <div className="h-48 flex items-center justify-center text-gray-400 text-sm">
          No historical data available
        </div>
      </div>
    );
  }

  const chartData = points.map((p) => ({
    date: new Date(p.collected_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    avg: Math.round(p.avg_value * 100) / 100,
    max: Math.round(p.max_value * 100) / 100,
    min: Math.round(p.min_value * 100) / 100,
  }));

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-medium text-gray-700">{label}</h4>
        {points.length > 0 && (
          <span className="text-xs text-gray-500">
            Avg: {formatValue(chartData[chartData.length - 1].avg, unit)} | Max: {formatValue(chartData[chartData.length - 1].max, unit)}
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id={`grad-${metricName}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.2} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af' }} />
          <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={45} />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            formatter={(value: number) => [formatValue(value, unit), '']}
          />
          <Area
            type="monotone"
            dataKey="avg"
            stroke={color}
            strokeWidth={2}
            fill={`url(#grad-${metricName})`}
            name="Average"
          />
          <Area
            type="monotone"
            dataKey="max"
            stroke={color}
            strokeWidth={1}
            strokeDasharray="3 3"
            fill="none"
            name="Max"
            opacity={0.5}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
