import { useState, useEffect } from 'react';
import api from '../services/api';
import { CpuChipIcon, ArrowRightIcon } from '@heroicons/react/24/outline';

interface Proposal {
  area: string; current: string; proposed: string;
  savings_pct: number; savings_amount: number;
  complexity: string; timeline: string;
}

export default function ArchitectureAdvisorPage() {
  const [data, setData] = useState<{
    current_architecture: Record<string, { count: number; monthly_cost: number }>;
    total_monthly_cost: number; proposals: Proposal[];
    total_potential_savings: number; total_savings_pct: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/architecture/analyze').then((r) => setData(r.data)).catch(console.error).finally(() => setLoading(false));
  }, []);

  const complexityColors: Record<string, string> = {
    low: 'bg-green-500/10 text-green-400',
    medium: 'bg-yellow-500/10 text-yellow-400',
    high: 'bg-red-500/10 text-red-400',
  };

  if (loading) return <div className="text-gray-400 p-8">Analyzing architecture...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <CpuChipIcon className="h-7 w-7 text-violet-400" />
          Architecture Advisor
        </h1>
        <p className="text-gray-400 mt-1">AI-powered architecture optimization with cost projections</p>
      </div>

      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4">
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Current Monthly Cost</p>
              <p className="text-2xl font-bold text-white">${data.total_monthly_cost.toLocaleString()}</p>
            </div>
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Potential Savings</p>
              <p className="text-2xl font-bold text-green-400">${data.total_potential_savings.toLocaleString()}</p>
            </div>
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Savings Percentage</p>
              <p className="text-2xl font-bold text-green-400">{data.total_savings_pct}%</p>
            </div>
          </div>

          {/* Current Architecture */}
          <div className="card">
            <h3 className="text-white font-medium mb-4">Current Architecture</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(data.current_architecture).map(([type, info]) => (
                <div key={type} className="p-3 bg-surface-50/50 rounded-lg border border-gray-700/30">
                  <p className="text-gray-400 text-xs capitalize">{type.replace('_', ' ')}</p>
                  <p className="text-white font-bold text-lg">{info.count}</p>
                  <p className="text-gray-300 text-xs">${info.monthly_cost.toLocaleString()}/mo</p>
                </div>
              ))}
            </div>
          </div>

          {/* Optimization Proposals */}
          <div className="card">
            <h3 className="text-white font-medium mb-4">Optimization Proposals</h3>
            <div className="space-y-4">
              {data.proposals.map((p, i) => (
                <div key={i} className="p-4 bg-surface-50/30 rounded-lg border border-gray-700/30">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-brand-400 font-medium">{p.area}</span>
                    <span className={`px-2 py-0.5 rounded text-xs ${complexityColors[p.complexity]}`}>{p.complexity} complexity</span>
                    <span className="text-gray-500 text-xs">{p.timeline}</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
                    <div className="p-3 bg-red-500/5 border border-red-500/20 rounded">
                      <p className="text-xs text-red-400 mb-1">Current</p>
                      <p className="text-gray-200 text-sm">{p.current}</p>
                    </div>
                    <div className="flex justify-center">
                      <ArrowRightIcon className="h-5 w-5 text-brand-400" />
                    </div>
                    <div className="p-3 bg-green-500/5 border border-green-500/20 rounded">
                      <p className="text-xs text-green-400 mb-1">Proposed</p>
                      <p className="text-gray-200 text-sm">{p.proposed}</p>
                    </div>
                  </div>
                  {p.savings_amount > 0 && (
                    <div className="mt-3 text-right">
                      <span className="text-green-400 font-medium">Save ${p.savings_amount.toLocaleString()}/mo ({p.savings_pct}%)</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
