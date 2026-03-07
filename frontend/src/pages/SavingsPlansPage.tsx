import { useQuery } from '@tanstack/react-query';
import { dashboardService } from '../services/api';
import { formatCurrency, formatPercent, humanizeKey } from '../utils/formatters';

export default function SavingsPlansPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['savings-plans-data'],
    queryFn: dashboardService.savingsPlans,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  const plans = (data?.plans || []) as Array<Record<string, unknown>>;
  const coverage = (data?.coverage || {}) as Record<string, unknown>;
  const utilization = (data?.utilization || {}) as Record<string, unknown>;
  const purchaseRecs = (data?.purchase_recommendations || []) as Array<Record<string, unknown>>;

  const coveragePct = Number(coverage.avg_coverage_pct || 0);
  const utilizationPct = Number(utilization.utilization_pct || 0);
  const netSavings = Number(utilization.net_savings || 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Savings Plans & Reserved Instances</h1>
        <p className="text-sm text-gray-400 mt-1">Manage commitments and optimize coverage</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div className="card-sm">
          <p className="stat-label">Coverage</p>
          <p className="stat-value">{formatPercent(coveragePct)}</p>
          <div className="mt-2 h-2 bg-surface-300 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-brand-500 to-accent-emerald rounded-full" style={{ width: `${Math.min(coveragePct, 100)}%` }} />
          </div>
        </div>
        <div className="card-sm">
          <p className="stat-label">Utilization</p>
          <p className="stat-value">{formatPercent(utilizationPct)}</p>
          <div className="mt-2 h-2 bg-surface-300 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-accent-cyan to-brand-500 rounded-full" style={{ width: `${Math.min(utilizationPct, 100)}%` }} />
          </div>
        </div>
        <div className="card-sm">
          <p className="stat-label">Net Savings</p>
          <p className="stat-value">{formatCurrency(netSavings)}</p>
        </div>
        <div className="card-sm">
          <p className="stat-label">Active Plans</p>
          <p className="stat-value">{plans.length}</p>
        </div>
      </div>

      {/* Active Plans */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">Active Savings Plans</h2>
        {plans.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-700/50">
                  <th className="pb-3 pr-4">Type</th>
                  <th className="pb-3 pr-4">State</th>
                  <th className="pb-3 pr-4">Commitment/Hr</th>
                  <th className="pb-3 pr-4">Payment</th>
                  <th className="pb-3 pr-4">Start</th>
                  <th className="pb-3">End</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {plans.map((p, i) => (
                  <tr key={i} className="text-gray-300">
                    <td className="py-3 pr-4 font-medium">{humanizeKey(String(p.plan_type || ''))}</td>
                    <td className="py-3 pr-4">
                      <span className={`badge ${p.state === 'active' ? 'badge-success' : 'badge-info'}`}>
                        {humanizeKey(String(p.state || ''))}
                      </span>
                    </td>
                    <td className="py-3 pr-4">{formatCurrency(Number(p.commitment_per_hour || 0))}</td>
                    <td className="py-3 pr-4">{humanizeKey(String(p.payment_option || ''))}</td>
                    <td className="py-3 pr-4 text-gray-500">{String(p.start_time || '-').slice(0, 10)}</td>
                    <td className="py-3 text-gray-500">{String(p.end_time || '-').slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No active Savings Plans found. Consider purchasing plans to reduce costs.</p>
        )}
      </div>

      {/* Purchase Recommendations */}
      <div className="card">
        <h2 className="text-base font-semibold text-gray-200 mb-4">Purchase Recommendations</h2>
        {purchaseRecs.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {purchaseRecs.map((rec, i) => (
              <div key={i} className="p-4 rounded-xl bg-surface-200/50 border border-gray-700/30">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-200">Compute Savings Plan</span>
                  <span className="badge badge-success">{formatPercent(Number(rec.estimated_savings_pct || 0))} savings</span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-gray-500">Hourly Commitment</span>
                    <p className="text-gray-300 font-medium">{formatCurrency(Number(rec.hourly_commitment || 0))}/hr</p>
                  </div>
                  <div>
                    <span className="text-gray-500">Monthly Savings</span>
                    <p className="text-emerald-400 font-medium">{formatCurrency(Number(rec.estimated_monthly_savings || 0))}</p>
                  </div>
                  <div>
                    <span className="text-gray-500">Current On-Demand</span>
                    <p className="text-gray-300 font-medium">{formatCurrency(Number(rec.current_on_demand || 0))}/mo</p>
                  </div>
                  <div>
                    <span className="text-gray-500">Upfront Cost</span>
                    <p className="text-gray-300 font-medium">{formatCurrency(Number(rec.upfront_cost || 0))}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-center py-8">No purchase recommendations available at this time.</p>
        )}
      </div>
    </div>
  );
}
