import { useQuery } from '@tanstack/react-query';
import { dashboardService, exportService } from '../services/api';
import { formatCurrency } from '../utils/formatters';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { ArrowDownTrayIcon } from '@heroicons/react/24/outline';

export default function BillingPage() {
  const { data: trend, isLoading } = useQuery({
    queryKey: ['billing-trend'],
    queryFn: () => dashboardService.monthlyTrend(12),
  });
  const { data: costSummary } = useQuery({
    queryKey: ['billing-summary'],
    queryFn: () => dashboardService.costSummary(30),
  });

  const months = (trend || []).map((m) => ({
    month: new Date(m.month).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
    rawMonth: m.month,
    cost: Math.round(m.cost * 100) / 100,
  }));

  const currentCost = costSummary?.current_period_cost ?? 0;
  const previousCost = costSummary?.previous_period_cost ?? 0;
  const changePct = costSummary?.change_percentage ?? 0;
  const totalYTD = months.reduce((s, m) => s + m.cost, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Billing</h1>
          <p className="text-sm text-gray-400 mt-1">Monthly bills and cost history</p>
        </div>
        <button onClick={() => exportService.costReport()} className="btn-secondary flex items-center gap-2">
          <ArrowDownTrayIcon className="h-4 w-4" /> Export Report
        </button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div className="card-sm">
          <p className="stat-label">Current Period</p>
          <p className="stat-value">{formatCurrency(currentCost)}</p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Previous Period</p>
          <p className="stat-value">{formatCurrency(previousCost)}</p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Change</p>
          <p className={`stat-value ${changePct > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
            {changePct > 0 ? '+' : ''}{changePct.toFixed(1)}%
          </p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Year to Date</p>
          <p className="stat-value">{formatCurrency(totalYTD)}</p>
        </div>
      </div>

      {/* Monthly Chart */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">Monthly Bills</h2>
        {isLoading ? (
          <div className="h-[300px] flex items-center justify-center">
            <div className="animate-spin h-6 w-6 border-2 border-brand-500 border-t-transparent rounded-full" />
          </div>
        ) : months.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={months}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#9ca3af' }} />
              <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={60}
                tickFormatter={(v) => `$${v >= 1000 ? `${(v/1000).toFixed(0)}K` : v}`}
              />
              <Tooltip
                contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 8, color: '#e5e7eb' }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cost']}
              />
              <Bar dataKey="cost" radius={[6, 6, 0, 0]}>
                {months.map((_, i) => (
                  <Cell key={i} fill={i === months.length - 1 ? '#6366f1' : '#4338ca'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[300px] flex items-center justify-center text-gray-500">
            No billing history available. Connect a cloud account to see historical costs.
          </div>
        )}
      </div>

      {/* Bills Table */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">Bill History</h2>
        {months.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-700/50">
                  <th className="pb-3 pr-4">Period</th>
                  <th className="pb-3 pr-4 text-right">Total</th>
                  <th className="pb-3 text-right">Change</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {[...months].reverse().map((m, i, arr) => {
                  const prev = i < arr.length - 1 ? arr[i + 1].cost : 0;
                  const change = prev > 0 ? ((m.cost - prev) / prev * 100) : 0;
                  return (
                    <tr key={m.month} className="text-gray-300">
                      <td className="py-3 pr-4 font-medium">{m.month}</td>
                      <td className="py-3 pr-4 text-right">{formatCurrency(m.cost)}</td>
                      <td className={`py-3 text-right font-medium ${
                        change > 0 ? 'text-rose-400' : change < 0 ? 'text-emerald-400' : 'text-gray-500'
                      }`}>
                        {prev > 0 ? `${change > 0 ? '+' : ''}${change.toFixed(1)}%` : '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No bills available</p>
        )}
      </div>
    </div>
  );
}
