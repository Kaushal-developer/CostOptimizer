import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { dashboardService, exportService } from '../services/api';
import { formatCurrency, humanizeKey } from '../utils/formatters';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from 'recharts';
import { ArrowDownTrayIcon } from '@heroicons/react/24/outline';

const COLORS = ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#ec4899', '#14b8a6'];

type Dimension = 'service' | 'region';

export default function CostExplorerPage() {
  const [days, setDays] = useState(30);
  const [dimension, setDimension] = useState<Dimension>('service');

  const { data: dailyCosts, isLoading } = useQuery({
    queryKey: ['ce-daily', days],
    queryFn: () => dashboardService.dailyCosts(days),
  });
  const { data: byService } = useQuery({
    queryKey: ['ce-service', days],
    queryFn: () => dashboardService.costByService(days),
  });
  const { data: byRegion } = useQuery({
    queryKey: ['ce-region', days],
    queryFn: () => dashboardService.costByRegion(days),
  });

  // Aggregate daily totals
  const dailyAgg: Record<string, number> = {};
  (dailyCosts || []).forEach((d) => {
    const key = d.date || '';
    dailyAgg[key] = (dailyAgg[key] || 0) + d.cost;
  });
  const chartData = Object.entries(dailyAgg)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, cost]) => ({
      date: new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      cost: Math.round(cost * 100) / 100,
    }));

  const breakdownData = dimension === 'service' ? byService : byRegion;
  const barData = Object.entries(breakdownData || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 15)
    .map(([name, value]) => ({
      name: name.replace(/Amazon |AWS /g, '').slice(0, 30),
      cost: Math.round(value * 100) / 100,
    }));

  const totalCost = Object.values(breakdownData || {}).reduce((s, v) => s + v, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Cost Explorer</h1>
          <p className="text-sm text-gray-400 mt-1">Analyze your cloud spending patterns</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="input w-auto text-sm"
          >
            <option value={7}>Last 7 Days</option>
            <option value={30}>Last 30 Days</option>
            <option value={60}>Last 60 Days</option>
            <option value={90}>Last 90 Days</option>
          </select>
          <button onClick={() => exportService.costReport()} className="btn-secondary flex items-center gap-2">
            <ArrowDownTrayIcon className="h-4 w-4" /> Export
          </button>
        </div>
      </div>

      {/* Total Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card-sm">
          <p className="stat-label">Total Cost ({days}d)</p>
          <p className="stat-value">{formatCurrency(totalCost)}</p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Daily Average</p>
          <p className="stat-value">{formatCurrency(totalCost / (days || 1))}</p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Services</p>
          <p className="stat-value">{Object.keys(byService || {}).length}</p>
        </div>
      </div>

      {/* Daily Cost Chart */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">Daily Spend</h2>
        {isLoading ? (
          <div className="h-[300px] flex items-center justify-center">
            <div className="animate-spin h-6 w-6 border-2 border-brand-500 border-t-transparent rounded-full" />
          </div>
        ) : chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="ceGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af' }} />
              <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={60}
                tickFormatter={(v) => `$${v >= 1000 ? `${(v/1000).toFixed(1)}K` : v}`}
              />
              <Tooltip
                contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 12, color: '#e5e7eb' }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cost']}
              />
              <Area type="monotone" dataKey="cost" stroke="#6366f1" strokeWidth={2} fill="url(#ceGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[300px] flex items-center justify-center text-gray-500">No cost data available</div>
        )}
      </div>

      {/* Breakdown */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-200">Cost Breakdown</h2>
          <div className="flex gap-2">
            {(['service', 'region'] as Dimension[]).map((d) => (
              <button
                key={d}
                onClick={() => setDimension(d)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  dimension === d ? 'bg-brand-600 text-white' : 'bg-surface-200 text-gray-400 hover:text-white'
                }`}
              >
                By {humanizeKey(d)}
              </button>
            ))}
          </div>
        </div>
        {barData.length > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(barData.length * 35, 200)}>
            <BarChart data={barData} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: '#9ca3af' }}
                tickFormatter={(v) => `$${v >= 1000 ? `${(v/1000).toFixed(0)}K` : v}`}
              />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: '#9ca3af' }} width={180} />
              <Tooltip
                contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 8, color: '#e5e7eb' }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cost']}
              />
              <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                {barData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[200px] flex items-center justify-center text-gray-500">No breakdown data</div>
        )}
      </div>
    </div>
  );
}
