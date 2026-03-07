import { useState } from 'react';
import { jiraService } from '../../services/api';
import { XMarkIcon, TicketIcon } from '@heroicons/react/24/outline';

interface Props {
  recommendation: { id: number; title: string; description: string; estimated_savings: number; priority: string };
  onClose: () => void;
  onCreated: (ticket: { key: string; url: string }) => void;
}

export default function JiraModal({ recommendation, onClose, onCreated }: Props) {
  const [summary, setSummary] = useState(`[Cost Optimization] ${recommendation.title}`);
  const [priority, setPriority] = useState(recommendation.priority === 'critical' ? 'Highest' : recommendation.priority === 'high' ? 'High' : 'Medium');
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setLoading(true);
    try {
      const result = await jiraService.createTicket({
        recommendation_id: recommendation.id,
        summary,
        priority,
      });
      onCreated(result.ticket);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface-100 rounded-xl border border-gray-700/50 w-full max-w-lg p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-white font-semibold flex items-center gap-2">
            <TicketIcon className="h-5 w-5 text-blue-400" />
            Create JIRA Ticket
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <XMarkIcon className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm text-gray-400 block mb-1">Summary</label>
            <input value={summary} onChange={(e) => setSummary(e.target.value)} className="input w-full" />
          </div>

          <div>
            <label className="text-sm text-gray-400 block mb-1">Description Preview</label>
            <div className="p-3 bg-surface-50 rounded-lg text-gray-300 text-sm">
              <p>{recommendation.description}</p>
              <p className="mt-2 text-green-400 font-medium">Estimated Savings: ${recommendation.estimated_savings.toLocaleString()}/mo</p>
            </div>
          </div>

          <div>
            <label className="text-sm text-gray-400 block mb-1">Priority</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} className="input w-full">
              <option value="Highest">Highest</option>
              <option value="High">High</option>
              <option value="Medium">Medium</option>
              <option value="Low">Low</option>
            </select>
          </div>

          <div className="flex gap-3 pt-2">
            <button onClick={onClose} className="flex-1 px-4 py-2 bg-surface-50 text-gray-300 rounded-lg hover:bg-surface-200 transition-colors">
              Cancel
            </button>
            <button onClick={handleCreate} disabled={loading} className="flex-1 btn-primary">
              {loading ? 'Creating...' : 'Create Ticket'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
