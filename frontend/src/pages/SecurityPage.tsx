import { useState, useEffect } from 'react';
import { securityService, type SecurityAlert } from '../services/api';
import { ShieldExclamationIcon, ArrowPathIcon } from '@heroicons/react/24/outline';

const SEV_COLORS: Record<string, string> = {
  critical: 'bg-red-500/10 text-red-400 border-red-500/30',
  high: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
};

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-red-500/10 text-red-400',
  acknowledged: 'bg-yellow-500/10 text-yellow-400',
  resolved: 'bg-green-500/10 text-green-400',
  suppressed: 'bg-gray-500/10 text-gray-400',
};

type Tab = 'alerts' | 'prevention';

export default function SecurityPage() {
  const [alerts, setAlerts] = useState<SecurityAlert[]>([]);
  const [summary, setSummary] = useState<{ total_alerts: number; by_severity: Record<string, number>; risk_score: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<Tab>('alerts');
  const [sevFilter, setSevFilter] = useState<string | null>(null);

  const loadData = async () => {
    try {
      const [a, s] = await Promise.all([securityService.alerts(), securityService.summary()]);
      setAlerts(a);
      setSummary(s);
    } catch (e) { console.error(e); }
  };

  const runScan = async () => {
    setLoading(true);
    try {
      await securityService.scan();
      await loadData();
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { loadData(); }, []);

  const updateStatus = async (id: number, status: string) => {
    await securityService.updateAlertStatus(id, status);
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, status } : a)));
  };

  const filtered = alerts.filter((a) => !sevFilter || a.severity === sevFilter);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ShieldExclamationIcon className="h-7 w-7 text-red-400" />
            Security Center
          </h1>
          <p className="text-gray-400 mt-1">Threat detection, alerts, and prevention assessment</p>
        </div>
        <button onClick={runScan} disabled={loading} className="btn-primary flex items-center gap-2">
          <ArrowPathIcon className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Scanning...' : 'Run Threat Scan'}
        </button>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="card text-center">
            <p className="text-gray-400 text-xs">Risk Score</p>
            <p className={`text-3xl font-bold ${summary.risk_score > 70 ? 'text-red-400' : summary.risk_score > 40 ? 'text-yellow-400' : 'text-green-400'}`}>{summary.risk_score}</p>
          </div>
          <div className="card text-center">
            <p className="text-gray-400 text-xs">Total Alerts</p>
            <p className="text-3xl font-bold text-white">{summary.total_alerts}</p>
          </div>
          {['critical', 'high', 'medium'].map((sev) => (
            <div key={sev} className="card text-center">
              <p className="text-gray-400 text-xs capitalize">{sev}</p>
              <p className={`text-3xl font-bold ${sev === 'critical' ? 'text-red-400' : sev === 'high' ? 'text-orange-400' : 'text-yellow-400'}`}>
                {summary.by_severity[sev] || 0}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-700/50 pb-2">
        {(['alerts', 'prevention'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors ${
              tab === t ? 'text-brand-400 border-b-2 border-brand-400' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'alerts' ? 'Security Alerts' : 'Prevention'}
          </button>
        ))}
      </div>

      {tab === 'alerts' && (
        <>
          <div className="flex gap-2">
            {['critical', 'high', 'medium', 'low'].map((s) => (
              <button
                key={s}
                onClick={() => setSevFilter(sevFilter === s ? null : s)}
                className={`px-3 py-1 rounded text-xs font-medium border ${
                  sevFilter === s ? SEV_COLORS[s] : 'text-gray-400 border-gray-700 hover:border-gray-600'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {filtered.map((alert) => (
              <div key={alert.id} className="card hover:border-gray-600/50 transition-colors">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium border ${SEV_COLORS[alert.severity]}`}>{alert.severity}</span>
                      <span className={`px-2 py-0.5 rounded text-xs ${STATUS_COLORS[alert.status]}`}>{alert.status}</span>
                      <span className="text-xs text-gray-500">{alert.category.replace(/_/g, ' ')}</span>
                    </div>
                    <h3 className="text-white font-medium">{alert.title}</h3>
                    <p className="text-gray-400 text-sm mt-1">{alert.description}</p>
                    {alert.resource_id && (
                      <p className="text-gray-500 text-xs mt-1 font-mono">{alert.resource_id}</p>
                    )}
                    {alert.remediation && (
                      <div className="mt-2 p-2 bg-blue-500/5 border border-blue-500/20 rounded text-xs text-blue-300">
                        <strong>Remediation:</strong> {alert.remediation}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-1 ml-4 shrink-0">
                    {alert.status === 'open' && (
                      <>
                        <button onClick={() => updateStatus(alert.id, 'acknowledged')} className="px-2 py-1 text-xs bg-yellow-500/10 text-yellow-400 rounded hover:bg-yellow-500/20">
                          Ack
                        </button>
                        <button onClick={() => updateStatus(alert.id, 'resolved')} className="px-2 py-1 text-xs bg-green-500/10 text-green-400 rounded hover:bg-green-500/20">
                          Resolve
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {filtered.length === 0 && (
              <p className="text-center py-8 text-gray-500">No alerts found. Run a threat scan to detect issues.</p>
            )}
          </div>
        </>
      )}

      {tab === 'prevention' && <PreventionTab />}
    </div>
  );
}

function PreventionTab() {
  const categories = [
    { id: 'waf', title: 'WAF Configuration', score: 60, items: [
      { name: 'WAF on ALBs', status: 'warning' }, { name: 'SQL injection rules', status: 'pass' },
      { name: 'Rate limiting', status: 'fail' }, { name: 'Geo-blocking', status: 'warning' },
    ]},
    { id: 'ddos', title: 'DDoS Protection', score: 50, items: [
      { name: 'Shield Standard', status: 'pass' }, { name: 'Shield Advanced', status: 'fail' },
      { name: 'CloudFront CDN', status: 'warning' }, { name: 'Health checks', status: 'pass' },
    ]},
    { id: 'network', title: 'Network Hardening', score: 60, items: [
      { name: 'VPC Flow Logs', status: 'warning' }, { name: 'Custom NACLs', status: 'pass' },
      { name: 'Private subnets for DBs', status: 'pass' }, { name: 'VPC endpoints', status: 'warning' },
    ]},
    { id: 'encryption', title: 'Encryption', score: 75, items: [
      { name: 'EBS default encryption', status: 'fail' }, { name: 'S3 SSE', status: 'pass' },
      { name: 'RDS encryption', status: 'warning' }, { name: 'TLS 1.2+', status: 'pass' },
    ]},
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {categories.map((cat) => (
        <div key={cat.id} className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-medium">{cat.title}</h3>
            <span className={`text-lg font-bold ${cat.score >= 70 ? 'text-green-400' : cat.score >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
              {cat.score}%
            </span>
          </div>
          <div className="space-y-2">
            {cat.items.map((item) => (
              <div key={item.name} className="flex items-center justify-between text-sm">
                <span className="text-gray-300">{item.name}</span>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  item.status === 'pass' ? 'bg-green-500/10 text-green-400' :
                  item.status === 'fail' ? 'bg-red-500/10 text-red-400' :
                  'bg-yellow-500/10 text-yellow-400'
                }`}>{item.status}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
