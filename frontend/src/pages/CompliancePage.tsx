import { useState, useEffect } from 'react';
import { complianceService } from '../services/api';
import { ShieldCheckIcon, ArrowPathIcon, CheckCircleIcon, XCircleIcon, ChevronDownIcon, ChevronUpIcon } from '@heroicons/react/24/outline';

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-red-400 bg-red-500/10 border-red-500/30',
  high: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  low: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  info: 'text-gray-400 bg-gray-500/10 border-gray-500/30',
};

interface Finding {
  id: number; framework_id: number; rule_id: string; status: string;
  severity: string; title: string; description: string;
  remediation: string | null; resource_id: string | null;
  details: Record<string, unknown> | null; found_at: string;
}

interface FrameworkResult {
  framework: string; score: number; passed: number; failed: number; total_rules: number;
}

export default function CompliancePage() {
  const [scanResults, setScanResults] = useState<FrameworkResult[] | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<'all' | 'fail' | 'pass'>('fail');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const runScan = async () => {
    setLoading(true);
    try {
      const result = await complianceService.scan();
      setScanResults(result.frameworks);
      if (result.findings) {
        setFindings(result.findings);
      } else {
        const f = await complianceService.findings();
        setFindings(f);
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const loadFindings = async () => {
    try {
      const f = await complianceService.findings();
      setFindings(f);
    } catch (e) { console.error(e); }
  };

  useEffect(() => { loadFindings(); }, []);

  const filteredFindings = findings.filter((f) => {
    if (statusFilter === 'fail' && f.status === 'pass') return false;
    if (statusFilter === 'pass' && f.status !== 'pass') return false;
    if (severityFilter && f.severity !== severityFilter) return false;
    return true;
  });

  const failCount = findings.filter((f) => f.status === 'fail').length;
  const passCount = findings.filter((f) => f.status === 'pass').length;

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-green-400';
    if (score >= 60) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getBarColor = (score: number) => {
    if (score >= 80) return 'bg-green-500';
    if (score >= 60) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ShieldCheckIcon className="h-7 w-7 text-brand-400" />
            Compliance Center
          </h1>
          <p className="text-gray-400 mt-1">Real-time compliance scanning against your AWS resources</p>
        </div>
        <button onClick={runScan} disabled={loading} className="btn-primary flex items-center gap-2">
          <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Scanning AWS...' : 'Run Compliance Scan'}
        </button>
      </div>

      {/* Summary Stats */}
      {findings.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="card text-center">
            <p className="text-gray-400 text-xs">Total Checks</p>
            <p className="text-2xl font-bold text-white">{findings.length}</p>
          </div>
          <div className="card text-center">
            <p className="text-gray-400 text-xs">Passed</p>
            <p className="text-2xl font-bold text-green-400">{passCount}</p>
          </div>
          <div className="card text-center">
            <p className="text-gray-400 text-xs">Failed</p>
            <p className="text-2xl font-bold text-red-400">{failCount}</p>
          </div>
        </div>
      )}

      {/* Framework Score Cards */}
      {scanResults && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {scanResults.map((fw) => (
            <div key={fw.framework} className="card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-gray-300 truncate pr-2">{fw.framework}</h3>
                <span className={`text-2xl font-bold ${getScoreColor(fw.score)}`}>{fw.score}%</span>
              </div>
              <div className="w-full bg-gray-700 rounded-full h-2 mb-3">
                <div className={`h-2 rounded-full transition-all ${getBarColor(fw.score)}`}
                  style={{ width: `${fw.score}%` }} />
              </div>
              <div className="flex items-center justify-between text-xs text-gray-400">
                <span className="flex items-center gap-1">
                  <CheckCircleIcon className="h-3 w-3 text-green-400" />{fw.passed} passed
                </span>
                <span className="flex items-center gap-1">
                  <XCircleIcon className="h-3 w-3 text-red-400" />{fw.failed} failed
                </span>
                <span>{fw.total_rules} rules</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <div className="flex gap-1 bg-surface-50 rounded-lg p-1">
          {(['fail', 'pass', 'all'] as const).map((s) => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                statusFilter === s ? 'bg-brand-500/20 text-brand-400' : 'text-gray-400 hover:text-gray-200'
              }`}>
              {s === 'fail' ? `Failures (${failCount})` : s === 'pass' ? `Passed (${passCount})` : 'All'}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {['critical', 'high', 'medium', 'low'].map((sev) => (
            <button key={sev} onClick={() => setSeverityFilter(severityFilter === sev ? null : sev)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                severityFilter === sev ? SEVERITY_COLORS[sev] : 'text-gray-400 bg-surface-50 border-gray-700 hover:border-gray-600'
              }`}>
              {sev.charAt(0).toUpperCase() + sev.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Findings List */}
      <div className="space-y-2">
        {filteredFindings.map((f) => (
          <div key={f.id} className="card hover:border-gray-600/50 transition-colors">
            <div className="flex items-start gap-3 cursor-pointer"
              onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}>
              {f.status === 'pass'
                ? <CheckCircleIcon className="h-5 w-5 text-green-400 mt-0.5 shrink-0" />
                : <XCircleIcon className="h-5 w-5 text-red-400 mt-0.5 shrink-0" />
              }
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEVERITY_COLORS[f.severity]}`}>
                    {f.severity}
                  </span>
                  <span className="text-xs text-gray-500 font-mono">{f.rule_id}</span>
                  <span className="text-white font-medium text-sm">{f.title}</span>
                </div>
                <p className="text-gray-400 text-sm mt-1">{f.description}</p>
                {f.resource_id && (
                  <p className="text-gray-500 text-xs mt-1 font-mono truncate">{f.resource_id}</p>
                )}
              </div>
              <div className="shrink-0">
                {expandedId === f.id
                  ? <ChevronUpIcon className="h-4 w-4 text-gray-400" />
                  : <ChevronDownIcon className="h-4 w-4 text-gray-400" />
                }
              </div>
            </div>

            {expandedId === f.id && (
              <div className="mt-3 pt-3 border-t border-gray-700/50 space-y-2">
                {f.remediation && (
                  <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg">
                    <p className="text-xs text-blue-400 font-medium mb-1">Remediation</p>
                    <p className="text-sm text-blue-200 font-mono whitespace-pre-wrap">{f.remediation}</p>
                  </div>
                )}
                {f.details && Object.keys(f.details).length > 0 && (
                  <div className="p-3 bg-surface-50/50 rounded-lg">
                    <p className="text-xs text-gray-400 font-medium mb-1">Details</p>
                    <pre className="text-xs text-gray-300 overflow-x-auto">
                      {JSON.stringify(f.details, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {filteredFindings.length === 0 && !loading && (
          <div className="card text-center py-12">
            <ShieldCheckIcon className="h-12 w-12 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-400">
              {findings.length === 0
                ? 'No compliance data yet. Click "Run Compliance Scan" to check your AWS resources.'
                : 'No findings match your filters.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
