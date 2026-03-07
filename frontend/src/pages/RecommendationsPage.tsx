import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { recommendationsService, exportService, type Recommendation } from '../services/api';
import { humanizeKey, formatCurrency } from '../utils/formatters';
import { ArrowDownTrayIcon } from '@heroicons/react/24/outline';
import clsx from 'clsx';
import JiraModal from '../components/recommendations/JiraModal';

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'badge-danger',
  high: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
  medium: 'badge-warning',
  low: 'badge-info',
};

interface RecFilters {
  priority?: string;
  status?: string;
  type?: string;
  page?: number;
  page_size?: number;
}

export default function RecommendationsPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<RecFilters>({ page: 1, page_size: 20 });
  const [whatIfOpen, setWhatIfOpen] = useState(false);
  const [whatIfIds, setWhatIfIds] = useState<Set<number>>(new Set());
  interface WhatIfResult {
    total_current_cost: number;
    total_estimated_cost: number;
    total_savings: number;
    savings_percentage: number;
    recommendations: Array<{ id: number; title: string; estimated_savings: number }>;
  }
  const [whatIfResult, setWhatIfResult] = useState<WhatIfResult | null>(null);
  const [jiraRec, setJiraRec] = useState<Recommendation | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['recommendations', filters],
    queryFn: () => recommendationsService.list(filters as Record<string, unknown>),
  });

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'accept' | 'reject' | 'apply' }) =>
      recommendationsService.action(id, action),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['recommendations'] }),
  });

  const whatIfMutation = useMutation({
    mutationFn: () => recommendationsService.whatIf(Array.from(whatIfIds)),
    onSuccess: (data) => setWhatIfResult(data),
  });

  const totalPages = Math.ceil((data?.total ?? 0) / (filters.page_size ?? 20));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Recommendations</h1>
        <div className="flex gap-2">
          <button onClick={() => exportService.recommendations()} className="btn-secondary flex items-center gap-2 text-sm">
            <ArrowDownTrayIcon className="h-4 w-4" /> Export
          </button>
          <button className="btn-secondary text-sm" onClick={() => setWhatIfOpen(!whatIfOpen)}>
            {whatIfOpen ? 'Close' : 'What-If Simulator'}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-3">
          <select
            className="input w-44"
            value={filters.priority ?? ''}
            onChange={(e) => setFilters({ ...filters, priority: e.target.value || undefined, page: 1 })}
          >
            <option value="">All Priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            className="input w-44"
            value={filters.status ?? ''}
            onChange={(e) => setFilters({ ...filters, status: e.target.value || undefined, page: 1 })}
          >
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
            <option value="applied">Applied</option>
          </select>
          <input
            placeholder="Type..."
            className="input w-44"
            value={filters.type ?? ''}
            onChange={(e) => setFilters({ ...filters, type: e.target.value || undefined, page: 1 })}
          />
        </div>
      </div>

      <div className="flex gap-6">
        {/* Main list */}
        <div className="flex-1 space-y-3">
          {isLoading ? (
            <div className="card flex items-center justify-center h-48">
              <div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" />
            </div>
          ) : (
            (data?.items ?? []).map((rec) => (
              <div key={rec.id} className="card">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={clsx(
                          'badge',
                          PRIORITY_STYLES[rec.priority] ?? 'badge-info',
                        )}
                      >
                        {humanizeKey(rec.priority)}
                      </span>
                      <span className="text-xs text-gray-500 uppercase">{humanizeKey(rec.type)}</span>
                    </div>
                    <h3 className="font-semibold text-white">{rec.title}</h3>
                    <p className="text-sm text-gray-400 mt-1">{rec.description}</p>
                    {rec.ai_explanation && (
                      <p className="text-xs text-brand-400 mt-1 italic">{rec.ai_explanation}</p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-lg font-bold text-emerald-400">
                      {formatCurrency(rec.estimated_savings)}
                    </p>
                    <p className="text-xs text-gray-500">/month</p>
                    <p className="text-xs text-gray-500 mt-1">
                      {rec.confidence_score}% confidence
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-4 pt-3 border-t border-gray-700/50">
                  {whatIfOpen && (
                    <label className="flex items-center gap-2 mr-auto text-sm text-gray-400 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={whatIfIds.has(rec.id)}
                        onChange={(e) => {
                          const next = new Set(whatIfIds);
                          e.target.checked ? next.add(rec.id) : next.delete(rec.id);
                          setWhatIfIds(next);
                        }}
                        className="rounded border-gray-600 bg-surface-200 text-brand-500 focus:ring-brand-500"
                      />
                      Include in simulation
                    </label>
                  )}
                  <div className={clsx(!whatIfOpen && 'ml-auto', 'flex gap-2')}>
                    <button
                      className="px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-colors"
                      onClick={() => actionMutation.mutate({ id: rec.id, action: 'accept' })}
                    >
                      Accept
                    </button>
                    <button
                      className="px-3 py-1.5 text-xs font-medium rounded-lg bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 transition-colors"
                      onClick={() => actionMutation.mutate({ id: rec.id, action: 'reject' })}
                    >
                      Reject
                    </button>
                    <button
                      className="px-3 py-1.5 text-xs font-medium rounded-lg bg-brand-500/20 text-brand-400 hover:bg-brand-500/30 transition-colors"
                      onClick={() => actionMutation.mutate({ id: rec.id, action: 'apply' })}
                    >
                      Apply
                    </button>
                    <button
                      className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 transition-colors"
                      onClick={() => setJiraRec(rec)}
                    >
                      JIRA Ticket
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
          {!isLoading && (data?.items?.length ?? 0) === 0 && (
            <div className="card text-center text-gray-500 py-12">No recommendations found</div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-2">
              <p className="text-sm text-gray-500">
                Page {filters.page} of {totalPages}
              </p>
              <div className="flex gap-2">
                <button
                  className="btn-secondary text-sm"
                  disabled={(filters.page ?? 1) <= 1}
                  onClick={() => setFilters({ ...filters, page: (filters.page ?? 1) - 1 })}
                >
                  Previous
                </button>
                <button
                  className="btn-secondary text-sm"
                  disabled={(filters.page ?? 1) >= totalPages}
                  onClick={() => setFilters({ ...filters, page: (filters.page ?? 1) + 1 })}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* What-if Panel */}
        {whatIfOpen && (
          <div className="w-80 shrink-0">
            <div className="card sticky top-6">
              <h2 className="font-semibold text-white mb-3">What-If Simulator</h2>
              <p className="text-sm text-gray-400 mb-4">
                Select recommendations to see projected savings.
              </p>
              <p className="text-sm text-gray-300 mb-3">
                <span className="font-medium">{whatIfIds.size}</span> selected
              </p>
              <button
                className="btn-primary w-full text-sm"
                disabled={whatIfIds.size === 0 || whatIfMutation.isPending}
                onClick={() => whatIfMutation.mutate()}
              >
                {whatIfMutation.isPending ? 'Simulating...' : 'Run Simulation'}
              </button>
              {whatIfResult && (
                <div className="mt-4 space-y-3">
                  <div className="p-3 bg-emerald-500/20 rounded-lg border border-emerald-500/30">
                    <p className="text-lg font-bold text-emerald-400">
                      {formatCurrency(whatIfResult.total_savings)}/mo
                    </p>
                    <p className="text-xs text-emerald-400/80">Projected Savings</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2 bg-surface-200 rounded">
                      <p className="text-gray-500">Current Cost</p>
                      <p className="font-semibold text-white">{formatCurrency(whatIfResult.total_current_cost)}/mo</p>
                    </div>
                    <div className="p-2 bg-surface-200 rounded">
                      <p className="text-gray-500">After Optimization</p>
                      <p className="font-semibold text-white">{formatCurrency(whatIfResult.total_estimated_cost)}/mo</p>
                    </div>
                  </div>
                  <div className="p-2 bg-brand-500/20 rounded text-center border border-brand-500/30">
                    <p className="text-sm font-bold text-brand-400">{whatIfResult.savings_percentage}% reduction</p>
                    <p className="text-xs text-brand-400/80">{formatCurrency(whatIfResult.total_savings * 12)}/year projected</p>
                  </div>
                  {whatIfResult.recommendations.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-gray-400 mb-1">Breakdown:</p>
                      <ul className="text-xs text-gray-400 space-y-1">
                        {whatIfResult.recommendations.map((r) => (
                          <li key={r.id} className="flex justify-between">
                            <span className="truncate mr-2">{r.title}</span>
                            <span className="text-emerald-400 font-medium shrink-0">{formatCurrency(r.estimated_savings)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {jiraRec && (
        <JiraModal
          recommendation={jiraRec}
          onClose={() => setJiraRec(null)}
          onCreated={() => { setJiraRec(null); queryClient.invalidateQueries({ queryKey: ['recommendations'] }); }}
        />
      )}
    </div>
  );
}
