import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../../store/auth';
import {
  HomeIcon,
  ServerStackIcon,
  LightBulbIcon,
  CloudIcon,
  Cog6ToothIcon,
  ArrowRightOnRectangleIcon,
  ChartBarIcon,
  CurrencyDollarIcon,
  ShieldCheckIcon,
  DocumentChartBarIcon,
  ShieldExclamationIcon,
  BanknotesIcon,
  CalculatorIcon,
  ArrowsRightLeftIcon,
  CpuChipIcon,
} from '@heroicons/react/24/outline';
import clsx from 'clsx';
import { Menu } from '@headlessui/react';
import { ChevronDownIcon } from '@heroicons/react/20/solid';
import { useEffect, useState } from 'react';
import { cloudAccountsService, type CloudAccount } from '../../services/api';

const nav = [
  { to: '/', label: 'Dashboard', icon: HomeIcon },
  { to: '/resources', label: 'Resources', icon: ServerStackIcon },
  { to: '/monitoring', label: 'Monitoring', icon: ChartBarIcon },
  { to: '/cost-explorer', label: 'Cost Explorer', icon: CurrencyDollarIcon },
  { to: '/recommendations', label: 'Recommendations', icon: LightBulbIcon },
  { to: '/savings-plans', label: 'Savings Plans', icon: ShieldCheckIcon },
  { to: '/billing', label: 'Billing', icon: DocumentChartBarIcon },
  { to: '/compliance', label: 'Compliance', icon: ShieldCheckIcon },
  { to: '/security', label: 'Security', icon: ShieldExclamationIcon },
  { to: '/budgets', label: 'Budgets', icon: BanknotesIcon },
  { to: '/reservation-advisor', label: 'Reservation Advisor', icon: CalculatorIcon },
  { to: '/load-balancing', label: 'Load Balancing', icon: ArrowsRightLeftIcon },
  { to: '/architecture-advisor', label: 'Architecture', icon: CpuChipIcon },
  { to: '/accounts', label: 'Cloud Accounts', icon: CloudIcon },
  { to: '/settings', label: 'Settings', icon: Cog6ToothIcon },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [accounts, setAccounts] = useState<CloudAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);

  useEffect(() => {
    cloudAccountsService.list().then((r) => setAccounts(r.items)).catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedAccountId) {
      sessionStorage.setItem('selected_account_id', String(selectedAccountId));
    } else {
      sessionStorage.removeItem('selected_account_id');
    }
  }, [selectedAccountId]);

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      {/* Sidebar */}
      <aside className="w-64 bg-sidebar border-r border-gray-800/50 flex flex-col shrink-0">
        <div className="h-16 flex items-center px-6 border-b border-gray-800/50">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-brand-500 to-accent-cyan flex items-center justify-center">
              <span className="text-white font-bold text-sm">CP</span>
            </div>
            <span className="text-white font-bold text-lg tracking-tight">CloudPulse</span>
          </div>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all',
                  isActive
                    ? 'bg-brand-600/20 text-brand-400 border border-brand-500/30'
                    : 'text-gray-400 hover:bg-surface-50 hover:text-gray-200',
                )
              }
            >
              <Icon className="h-4.5 w-4.5" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 py-4 border-t border-gray-800/50">
          <div className="px-3 py-2 text-xs text-gray-500">
            CloudPulse v3.0
          </div>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 bg-surface-50/80 backdrop-blur-xl border-b border-gray-800/50 flex items-center justify-between px-6 shrink-0">
          <h1 className="text-lg font-semibold text-gray-200">Cloud Cost Intelligence</h1>
          <div className="flex items-center gap-4">
            {/* Account Selector */}
            {accounts.length > 0 && (
              <select
                value={selectedAccountId ?? ''}
                onChange={(e) => setSelectedAccountId(e.target.value ? Number(e.target.value) : null)}
                className="bg-surface-100 border border-gray-700/50 text-gray-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-500/50"
              >
                <option value="">All Accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.display_name} ({a.provider})</option>
                ))}
              </select>
            )}

            <Menu as="div" className="relative">
              <Menu.Button className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 transition-colors">
                <div className="h-8 w-8 rounded-full bg-gradient-to-br from-brand-600 to-brand-400 text-white flex items-center justify-center text-xs font-bold">
                  {user?.full_name?.charAt(0).toUpperCase() ?? 'U'}
                </div>
                <span className="font-medium">{user?.full_name ?? 'User'}</span>
                <ChevronDownIcon className="h-4 w-4" />
              </Menu.Button>
              <Menu.Items className="absolute right-0 mt-2 w-48 bg-surface-100 rounded-lg shadow-lg border border-gray-700/50 py-1 z-50">
                <Menu.Item>
                  {({ active }) => (
                    <button
                      onClick={logout}
                      className={clsx(
                        'flex w-full items-center gap-2 px-4 py-2 text-sm',
                        active ? 'bg-surface-200 text-white' : 'text-gray-400',
                      )}
                    >
                      <ArrowRightOnRectangleIcon className="h-4 w-4" />
                      Sign out
                    </button>
                  )}
                </Menu.Item>
              </Menu.Items>
            </Menu>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6 bg-surface">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
