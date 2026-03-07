import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { resourcesService, exportService, type ResourceFilters } from '../services/api';
import { humanizeKey, formatCurrency } from '../utils/formatters';
import { ChevronUpDownIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline';
import clsx from 'clsx';

const STATUS_COLORS: Record<string, string> = {
  active: 'badge-success',
  idle: 'badge-warning',
  stopped: 'badge-info',
  underutilized: 'badge-warning',
  overprovisioned: 'badge-danger',
  zombie: 'badge-danger',
  optimized: 'badge-success',
};

type SortKey = 'name' | 'resource_type' | 'monthly_cost' | 'region';

export default function ResourcesPage() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState<ResourceFilters>({ page: 1, page_size: 20 });
  const [sortKey, setSortKey] = useState<SortKey>('monthly_cost');
  const [sortAsc, setSortAsc] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['resources', filters],
    queryFn: () => resourcesService.list(filters),
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  }

  const items = [...(data?.items ?? [])].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    const cmp = typeof av === 'number' ? av - (bv as number) : String(av ?? '').localeCompare(String(bv ?? ''));
    return sortAsc ? cmp : -cmp;
  });

  const totalPages = Math.ceil((data?.total ?? 0) / (filters.page_size ?? 20));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Resources</h1>
        <button onClick={() => exportService.resources()} className="btn-secondary flex items-center gap-2">
          <ArrowDownTrayIcon className="h-4 w-4" /> Export
        </button>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-3">
          <input
            placeholder="Filter by type..."
            className="input w-48"
            value={filters.resource_type ?? ''}
            onChange={(e) => setFilters({ ...filters, resource_type: e.target.value || undefined, page: 1 })}
          />
          <select
            className="input w-44"
            value={filters.status ?? ''}
            onChange={(e) => setFilters({ ...filters, status: e.target.value || undefined, page: 1 })}
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="idle">Idle</option>
            <option value="underutilized">Underutilized</option>
            <option value="overprovisioned">Overprovisioned</option>
            <option value="zombie">Zombie</option>
          </select>
          <input
            placeholder="Region..."
            className="input w-44"
            value={filters.region ?? ''}
            onChange={(e) => setFilters({ ...filters, region: e.target.value || undefined, page: 1 })}
          />
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-700/50">
              <tr>
                {([
                  ['name', 'Name'],
                  ['resource_type', 'Type'],
                  ['region', 'Region'],
                  ['monthly_cost', 'Cost/Mo'],
                ] as [SortKey, string][]).map(([key, label]) => (
                  <th
                    key={key}
                    className="text-left px-4 py-3 font-medium text-gray-400 text-xs uppercase tracking-wider cursor-pointer select-none"
                    onClick={() => toggleSort(key)}
                  >
                    <span className="inline-flex items-center gap-1">
                      {label}
                      <ChevronUpDownIcon className="h-3.5 w-3.5 text-gray-500" />
                    </span>
                  </th>
                ))}
                <th className="text-left px-4 py-3 font-medium text-gray-400 text-xs uppercase tracking-wider">Status</th>
                <th className="text-left px-4 py-3 font-medium text-gray-400 text-xs uppercase tracking-wider">Instance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-surface-200/50 transition-colors cursor-pointer" onClick={() => navigate(`/resources/${r.id}`)}>
                  <td className="px-4 py-3 font-medium text-white">{r.name ?? r.resource_id}</td>
                  <td className="px-4 py-3 text-gray-400">{humanizeKey(r.resource_type)}</td>
                  <td className="px-4 py-3 text-gray-400">{r.region}</td>
                  <td className="px-4 py-3 font-medium text-white">
                    {formatCurrency(r.monthly_cost)}
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('badge', STATUS_COLORS[r.status] ?? 'badge-info')}>
                      {humanizeKey(r.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {r.instance_type ?? '—'}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                    No resources found. Connect a cloud account and sync to see resources.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Page {filters.page} of {totalPages} ({data?.total} resources)
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
  );
}
