import { useState, useEffect } from 'react';
import { loadBalancingService } from '../services/api';
import { ArrowsRightLeftIcon, ArrowPathIcon } from '@heroicons/react/24/outline';

interface Distribution {
  [region: string]: { count: number; cost: number; count_pct: number; cost_pct: number; types: Record<string, number> };
}

interface Recommendation {
  type: string; title: string; description: string; estimated_savings: number; priority: string;
}

export default function LoadBalancingPage() {
  const [data, setData] = useState<{
    total_resources: number; total_monthly_cost: number; regions: number;
    distribution: Distribution; imbalance_score: number; recommendations: Recommendation[];
  } | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { setData(await loadBalancingService.analysis()); } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const getHeatColor = (pct: number) => {
    if (pct > 50) return 'bg-red-500/30 border-red-500/50';
    if (pct > 30) return 'bg-yellow-500/20 border-yellow-500/40';
    if (pct > 10) return 'bg-green-500/20 border-green-500/40';
    return 'bg-gray-500/10 border-gray-500/30';
  };

  if (loading) return <div className="text-gray-400 p-8">Loading distribution analysis...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ArrowsRightLeftIcon className="h-7 w-7 text-cyan-400" />
            Load Balancing & Distribution
          </h1>
          <p className="text-gray-400 mt-1">Analyze resource distribution across regions and availability zones</p>
        </div>
        <button onClick={load} className="btn-primary flex items-center gap-2">
          <ArrowPathIcon className="h-4 w-4" />Refresh
        </button>
      </div>

      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Regions</p>
              <p className="text-2xl font-bold text-white">{data.regions}</p>
            </div>
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Total Resources</p>
              <p className="text-2xl font-bold text-white">{data.total_resources}</p>
            </div>
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Monthly Cost</p>
              <p className="text-2xl font-bold text-white">${data.total_monthly_cost.toLocaleString()}</p>
            </div>
            <div className="card text-center">
              <p className="text-gray-400 text-xs">Imbalance Score</p>
              <p className={`text-2xl font-bold ${data.imbalance_score > 0.3 ? 'text-red-400' : data.imbalance_score > 0.15 ? 'text-yellow-400' : 'text-green-400'}`}>
                {(data.imbalance_score * 100).toFixed(0)}%
              </p>
            </div>
          </div>

          {/* Distribution Heatmap */}
          <div className="card">
            <h3 className="text-white font-medium mb-4">Region Distribution</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(data.distribution).map(([region, info]) => (
                <div key={region} className={`p-4 rounded-lg border ${getHeatColor(info.cost_pct)}`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-white font-medium text-sm">{region}</span>
                    <span className="text-gray-300 text-xs">{info.count} resources</span>
                  </div>
                  <div className="flex items-end justify-between">
                    <div>
                      <p className="text-xs text-gray-400">Cost</p>
                      <p className="text-lg font-bold text-white">${info.cost.toLocaleString()}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-gray-400">Share</p>
                      <p className="text-lg font-bold text-gray-300">{info.cost_pct}%</p>
                    </div>
                  </div>
                  <div className="w-full bg-gray-700 rounded-full h-1.5 mt-2">
                    <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${info.cost_pct}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recommendations */}
          <div className="card">
            <h3 className="text-white font-medium mb-4">Recommendations</h3>
            <div className="space-y-3">
              {data.recommendations.map((rec, i) => (
                <div key={i} className="p-3 bg-surface-50/50 rounded-lg border border-gray-700/30">
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-white text-sm font-medium">{rec.title}</h4>
                      <p className="text-gray-400 text-xs mt-1">{rec.description}</p>
                    </div>
                    {rec.estimated_savings > 0 && (
                      <span className="text-green-400 font-medium text-sm">${rec.estimated_savings.toLocaleString()}/mo</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
