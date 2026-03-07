import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cloudAccountsService, type CloudAccount } from '../services/api';
import { Dialog } from '@headlessui/react';
import { PlusIcon, ArrowPathIcon, TrashIcon } from '@heroicons/react/24/outline';
import { humanizeKey } from '../utils/formatters';
import clsx from 'clsx';

const PROVIDER_CONFIG: Record<string, { label: string; fields: { key: string; label: string; placeholder: string; required?: boolean }[] }> = {
  aws: {
    label: 'Amazon Web Services',
    fields: [
      { key: 'aws_access_key_id', label: 'Access Key ID', placeholder: 'AKIA...', required: true },
      { key: 'aws_secret_access_key', label: 'Secret Access Key', placeholder: 'wJalr...', required: true },
      { key: 'aws_region', label: 'Default Region', placeholder: 'us-east-1' },
    ],
  },
  azure: {
    label: 'Microsoft Azure',
    fields: [
      { key: 'azure_subscription_id', label: 'Subscription ID', placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' },
      { key: 'azure_tenant_id', label: 'Tenant ID', placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' },
    ],
  },
  gcp: {
    label: 'Google Cloud Platform',
    fields: [{ key: 'gcp_project_id', label: 'Project ID', placeholder: 'my-project-123' }],
  },
};

const STATUS_COLORS: Record<string, string> = {
  connected: 'badge-success',
  pending: 'badge-warning',
  error: 'badge-danger',
  disconnected: 'badge-info',
};

export default function CloudAccountsPage() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [provider, setProvider] = useState<'aws' | 'azure' | 'gcp'>('aws');
  const [displayName, setDisplayName] = useState('');
  const [accountId, setAccountId] = useState('');
  const [config, setConfig] = useState<Record<string, string>>({});

  const { data, isLoading } = useQuery({
    queryKey: ['cloud-accounts'],
    queryFn: () => cloudAccountsService.list(),
  });

  const accounts = data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: () =>
      cloudAccountsService.create({
        provider,
        display_name: displayName,
        account_id: accountId,
        ...config,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cloud-accounts'] });
      setModalOpen(false);
      setDisplayName('');
      setAccountId('');
      setConfig({});
    },
  });

  const syncMutation = useMutation({
    mutationFn: (id: number) => cloudAccountsService.sync(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cloud-accounts'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => cloudAccountsService.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cloud-accounts'] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Cloud Accounts</h1>
        <button className="btn-primary flex items-center gap-2 text-sm" onClick={() => setModalOpen(true)}>
          <PlusIcon className="h-4 w-4" /> Add Account
        </button>
      </div>

      {isLoading ? (
        <div className="card flex items-center justify-center h-48">
          <div className="animate-spin h-6 w-6 border-4 border-brand-500 border-t-transparent rounded-full" />
        </div>
      ) : accounts.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-gray-400 mb-4">No cloud accounts connected</p>
          <button className="btn-primary text-sm" onClick={() => setModalOpen(true)}>
            Connect Your First Account
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {accounts.map((account: CloudAccount) => (
            <div key={account.id} className="card">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold uppercase tracking-wider text-gray-500">
                  {account.provider.toUpperCase()}
                </span>
                <span className={clsx('badge', STATUS_COLORS[account.status] ?? 'badge-info')}>
                  {humanizeKey(account.status)}
                </span>
              </div>
              <h3 className="font-semibold text-white mb-1">{account.display_name}</h3>
              <p className="text-xs text-gray-500 mb-1">ID: {account.account_id}</p>
              <p className="text-xs text-gray-500 mb-4">
                Last synced:{' '}
                {account.last_sync_at
                  ? new Date(account.last_sync_at).toLocaleString()
                  : 'Never'}
              </p>
              {account.last_error && (
                <p className="text-xs text-rose-400 mb-3">{account.last_error}</p>
              )}
              <div className="flex gap-2">
                <button
                  className="btn-secondary text-xs flex items-center gap-1"
                  onClick={() => syncMutation.mutate(account.id)}
                  disabled={syncMutation.isPending}
                >
                  <ArrowPathIcon className={clsx('h-3.5 w-3.5', syncMutation.isPending && 'animate-spin')} />
                  Sync
                </button>
                <button
                  className="text-xs text-rose-400 hover:text-rose-300 flex items-center gap-1 ml-auto transition-colors"
                  onClick={() => {
                    if (window.confirm('Remove this account?')) deleteMutation.mutate(account.id);
                  }}
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Account Modal */}
      <Dialog open={modalOpen} onClose={() => setModalOpen(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="bg-surface-100 rounded-2xl shadow-xl border border-gray-700/50 w-full max-w-md p-6">
            <Dialog.Title className="text-lg font-semibold text-white mb-4">
              Connect Cloud Account
            </Dialog.Title>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Provider</label>
                <select
                  className="input"
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value as 'aws' | 'azure' | 'gcp');
                    setConfig({});
                  }}
                >
                  {Object.entries(PROVIDER_CONFIG).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Display Name</label>
                <input
                  className="input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Production AWS"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Account ID</label>
                <input
                  className="input"
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                  placeholder={provider === 'aws' ? '123456789012' : provider === 'azure' ? 'subscription-id' : 'project-id'}
                />
              </div>
              {PROVIDER_CONFIG[provider].fields.map((f) => (
                <div key={f.key}>
                  <label className="block text-sm font-medium text-gray-300 mb-1">{f.label}</label>
                  <input
                    className="input"
                    value={config[f.key] ?? ''}
                    onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
                    placeholder={f.placeholder}
                  />
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-3 mt-6">
              <button className="btn-secondary text-sm" onClick={() => setModalOpen(false)}>
                Cancel
              </button>
              <button
                className="btn-primary text-sm"
                disabled={!displayName || !accountId || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? 'Connecting...' : 'Connect'}
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  );
}
