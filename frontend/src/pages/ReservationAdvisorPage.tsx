import { useState } from 'react';
import { reservationService } from '../services/api';
import { CalculatorIcon, ArrowPathIcon } from '@heroicons/react/24/outline';

interface Option {
  id: string; type: string; term: string; payment_option: string;
  monthly_cost: number; monthly_savings: number; annual_savings: number;
  total_savings: number; savings_pct: number; break_even_months: number;
}

export default function ReservationAdvisorPage() {
  const [monthlyCost, setMonthlyCost] = useState('5000');
  const [commitmentPct, setCommitmentPct] = useState(80);
  const [result, setResult] = useState<{ best_recommendation: Option; all_options: Option[]; recommendation_summary: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const analyze = async () => {
    setLoading(true);
    try {
      const r = await reservationService.analyze(parseFloat(monthlyCost), commitmentPct);
      setResult(r);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <CalculatorIcon className="h-7 w-7 text-purple-400" />
          Reservation Advisor
        </h1>
        <p className="text-gray-400 mt-1">Compare Reserved Instances vs Savings Plans with break-even analysis</p>
      </div>

      {/* Input Controls */}
      <div className="card">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
          <div>
            <label className="text-sm text-gray-400 mb-1 block">Monthly On-Demand Cost ($)</label>
            <input value={monthlyCost} onChange={(e) => setMonthlyCost(e.target.value)} type="number" className="input w-full" />
          </div>
          <div>
            <label className="text-sm text-gray-400 mb-1 block">Commitment: {commitmentPct}%</label>
            <input type="range" min={10} max={100} value={commitmentPct} onChange={(e) => setCommitmentPct(Number(e.target.value))} className="w-full accent-brand-500" />
          </div>
          <button onClick={analyze} disabled={loading} className="btn-primary flex items-center gap-2 justify-center">
            <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Analyze
          </button>
        </div>
      </div>

      {result && (
        <>
          {/* Best Recommendation */}
          <div className="card border-brand-500/30 bg-brand-500/5">
            <h3 className="text-white font-medium mb-2">Best Recommendation</h3>
            <p className="text-brand-300 text-lg">{result.recommendation_summary}</p>
          </div>

          {/* Comparison Table */}
          <div className="card overflow-x-auto">
            <h3 className="text-white font-medium mb-4">All Options</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 border-b border-gray-700/50">
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-left py-2 px-3">Term</th>
                  <th className="text-left py-2 px-3">Payment</th>
                  <th className="text-right py-2 px-3">Monthly Cost</th>
                  <th className="text-right py-2 px-3">Monthly Savings</th>
                  <th className="text-right py-2 px-3">Annual Savings</th>
                  <th className="text-right py-2 px-3">Savings %</th>
                  <th className="text-right py-2 px-3">Break-even</th>
                </tr>
              </thead>
              <tbody>
                {result.all_options.map((opt) => (
                  <tr key={opt.id} className={`border-b border-gray-800/50 ${opt.id === result.best_recommendation?.id ? 'bg-brand-500/5' : ''}`}>
                    <td className="py-2 px-3 text-gray-200">{opt.type}</td>
                    <td className="py-2 px-3 text-gray-300">{opt.term}</td>
                    <td className="py-2 px-3 text-gray-300">{opt.payment_option}</td>
                    <td className="py-2 px-3 text-right text-gray-200">${opt.monthly_cost.toLocaleString()}</td>
                    <td className="py-2 px-3 text-right text-green-400">${opt.monthly_savings.toLocaleString()}</td>
                    <td className="py-2 px-3 text-right text-green-400">${opt.annual_savings.toLocaleString()}</td>
                    <td className="py-2 px-3 text-right">
                      <span className="text-green-400 font-medium">{opt.savings_pct}%</span>
                    </td>
                    <td className="py-2 px-3 text-right text-gray-300">{opt.break_even_months} mo</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
