import { useState, useEffect } from 'react';
import { budgetService, type BudgetItem } from '../services/api';
import { BanknotesIcon, PlusIcon, TrashIcon } from '@heroicons/react/24/outline';

const STATUS_STYLES: Record<string, string> = {
  on_track: 'bg-green-500/10 text-green-400',
  warning: 'bg-yellow-500/10 text-yellow-400',
  over_budget: 'bg-red-500/10 text-red-400',
};

export default function BudgetsPage() {
  const [budgets, setBudgets] = useState<BudgetItem[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [period, setPeriod] = useState('monthly');

  const load = async () => {
    try { setBudgets(await budgetService.list()); } catch (e) { console.error(e); }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    if (!name || !amount) return;
    await budgetService.create({ name, amount: parseFloat(amount), period });
    setName(''); setAmount(''); setShowForm(false);
    load();
  };

  const handleDelete = async (id: number) => {
    await budgetService.delete(id);
    load();
  };

  const getBarColor = (pct: number) => {
    if (pct >= 100) return 'bg-red-500';
    if (pct >= 80) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BanknotesIcon className="h-7 w-7 text-green-400" />
            Budget Management
          </h1>
          <p className="text-gray-400 mt-1">Track spending against budgets with threshold alerts</p>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-2">
          <PlusIcon className="h-4 w-4" />
          New Budget
        </button>
      </div>

      {showForm && (
        <div className="card">
          <h3 className="text-white font-medium mb-4">Create Budget</h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Budget name" className="input" />
            <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount ($)" type="number" className="input" />
            <select value={period} onChange={(e) => setPeriod(e.target.value)} className="input">
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="yearly">Yearly</option>
            </select>
            <button onClick={handleCreate} className="btn-primary">Create</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {budgets.map((b) => (
          <div key={b.id} className="card">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-white font-medium">{b.name}</h3>
                <p className="text-gray-400 text-xs capitalize">{b.period}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[b.status]}`}>
                  {b.status.replace('_', ' ')}
                </span>
                <button onClick={() => handleDelete(b.id)} className="text-gray-500 hover:text-red-400">
                  <TrashIcon className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="flex items-end justify-between mb-2">
              <div>
                <p className="text-xs text-gray-400">Spent</p>
                <p className="text-xl font-bold text-white">${b.actual_spend.toLocaleString()}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-400">Budget</p>
                <p className="text-xl font-bold text-gray-300">${b.amount.toLocaleString()}</p>
              </div>
            </div>

            <div className="w-full bg-gray-700 rounded-full h-3 mb-2">
              <div
                className={`h-3 rounded-full transition-all ${getBarColor(b.utilization_pct)}`}
                style={{ width: `${Math.min(100, b.utilization_pct)}%` }}
              />
            </div>
            <p className="text-xs text-gray-400 text-right">{b.utilization_pct}% utilized</p>
          </div>
        ))}
      </div>

      {budgets.length === 0 && !showForm && (
        <div className="card text-center py-12">
          <BanknotesIcon className="h-12 w-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400">No budgets configured yet. Create one to start tracking.</p>
        </div>
      )}
    </div>
  );
}
