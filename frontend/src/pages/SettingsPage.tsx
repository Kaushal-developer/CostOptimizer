import { useState, useEffect } from 'react';
import { settingsService, type IntegrationConfig } from '../services/api';
import { Cog6ToothIcon, PlusIcon, TrashIcon } from '@heroicons/react/24/outline';

type Tab = 'general' | 'integrations' | 'notifications';

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('general');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Cog6ToothIcon className="h-7 w-7 text-gray-400" />
          Settings
        </h1>
      </div>

      <div className="flex gap-2 border-b border-gray-700/50 pb-2">
        {(['general', 'integrations', 'notifications'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t ? 'text-brand-400 border-b-2 border-brand-400' : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'general' && <GeneralSettings />}
      {tab === 'integrations' && <IntegrationsSettings />}
      {tab === 'notifications' && <NotificationSettings />}
    </div>
  );
}

function GeneralSettings() {
  return (
    <div className="card space-y-4">
      <h3 className="text-white font-medium">General Settings</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-sm text-gray-400 block mb-1">Default Currency</label>
          <select className="input w-full">
            <option value="USD">USD ($)</option>
            <option value="EUR">EUR (€)</option>
            <option value="GBP">GBP (£)</option>
          </select>
        </div>
        <div>
          <label className="text-sm text-gray-400 block mb-1">Cost Anomaly Threshold (%)</label>
          <input type="number" defaultValue={20} className="input w-full" />
        </div>
        <div>
          <label className="text-sm text-gray-400 block mb-1">Auto-sync Interval</label>
          <select className="input w-full">
            <option value="1h">Every hour</option>
            <option value="6h">Every 6 hours</option>
            <option value="24h">Daily</option>
          </select>
        </div>
        <div>
          <label className="text-sm text-gray-400 block mb-1">AI Model</label>
          <select className="input w-full">
            <option value="qwen2.5:3b">Qwen 2.5 3B (Local)</option>
            <option value="claude">Claude (API)</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function IntegrationsSettings() {
  const [integrations, setIntegrations] = useState<IntegrationConfig[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [formType, setFormType] = useState('jira');
  const [formName, setFormName] = useState('');
  const [formUrl, setFormUrl] = useState('');

  const load = async () => {
    try { setIntegrations(await settingsService.listIntegrations()); } catch (e) { console.error(e); }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    await settingsService.createIntegration({
      type: formType, name: formName || formType.toUpperCase(),
      config: formUrl ? { url: formUrl } : {},
    });
    setShowForm(false); setFormName(''); setFormUrl('');
    load();
  };

  const handleDelete = async (id: number) => {
    await settingsService.deleteIntegration(id);
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-white font-medium">Integrations</h3>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-1 text-sm">
          <PlusIcon className="h-4 w-4" /> Add
        </button>
      </div>

      {showForm && (
        <div className="card">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <select value={formType} onChange={(e) => setFormType(e.target.value)} className="input">
              <option value="jira">JIRA</option>
              <option value="slack">Slack</option>
              <option value="webhook">Webhook</option>
              <option value="pagerduty">PagerDuty</option>
              <option value="teams">Teams</option>
            </select>
            <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Name" className="input" />
            <input value={formUrl} onChange={(e) => setFormUrl(e.target.value)} placeholder="URL (optional)" className="input" />
            <button onClick={handleCreate} className="btn-primary">Save</button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {integrations.map((int_) => (
          <div key={int_.id} className="card flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="px-2 py-1 bg-brand-500/10 text-brand-400 rounded text-xs font-medium uppercase">{int_.type}</span>
              <span className="text-white">{int_.name}</span>
              <span className={`text-xs ${int_.is_enabled ? 'text-green-400' : 'text-gray-500'}`}>
                {int_.is_enabled ? 'Active' : 'Disabled'}
              </span>
            </div>
            <button onClick={() => handleDelete(int_.id)} className="text-gray-500 hover:text-red-400">
              <TrashIcon className="h-4 w-4" />
            </button>
          </div>
        ))}
        {integrations.length === 0 && !showForm && (
          <p className="text-gray-500 text-center py-6">No integrations configured.</p>
        )}
      </div>
    </div>
  );
}

function NotificationSettings() {
  return (
    <div className="card space-y-4">
      <h3 className="text-white font-medium">Notification Preferences</h3>
      {[
        { label: 'Budget threshold alerts', key: 'budget' },
        { label: 'Security threat alerts', key: 'security' },
        { label: 'Compliance scan results', key: 'compliance' },
        { label: 'New cost recommendations', key: 'recommendations' },
        { label: 'Cost anomaly detection', key: 'anomalies' },
      ].map((item) => (
        <div key={item.key} className="flex items-center justify-between py-2 border-b border-gray-800/50">
          <span className="text-gray-300">{item.label}</span>
          <label className="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" defaultChecked className="sr-only peer" />
            <div className="w-9 h-5 bg-gray-700 rounded-full peer peer-checked:bg-brand-500 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
          </label>
        </div>
      ))}
    </div>
  );
}
