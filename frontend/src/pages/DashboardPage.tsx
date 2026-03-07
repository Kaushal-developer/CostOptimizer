import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { dashboardService, chatService } from '../services/api';
import { formatCurrency, formatPercent } from '../utils/formatters';
import ReactMarkdown from 'react-markdown';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell, PieChart, Pie,
} from 'recharts';
import {
  CurrencyDollarIcon,
  ArrowTrendingDownIcon,
  ArrowTrendingUpIcon,
  LightBulbIcon,
  ExclamationTriangleIcon,
  ChartBarSquareIcon,
  PaperAirplaneIcon,
  ChatBubbleLeftRightIcon,
  XMarkIcon,
  ArrowDownTrayIcon,
  SparklesIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import { exportService } from '../services/api';

const PIE_COLORS = ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#ec4899', '#14b8a6'];

function KPICard({ label, value, subtitle, icon: Icon, trend, trendColor }: {
  label: string; value: string; subtitle?: string; icon: React.ElementType;
  trend?: string; trendColor?: string;
}) {
  return (
    <div className="card flex items-start justify-between">
      <div>
        <p className="stat-label">{label}</p>
        <p className="stat-value mt-1">{value}</p>
        {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
        {trend && (
          <p className={`text-xs font-medium mt-1 ${trendColor || 'text-gray-400'}`}>{trend}</p>
        )}
      </div>
      <div className="p-3 rounded-xl bg-brand-600/10">
        <Icon className="h-6 w-6 text-brand-400" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: summary, isLoading } = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: dashboardService.summary,
  });
  const { data: dailyCosts } = useQuery({
    queryKey: ['daily-costs'],
    queryFn: () => dashboardService.dailyCosts(30),
  });
  const { data: costByService } = useQuery({
    queryKey: ['cost-by-service'],
    queryFn: () => dashboardService.costByService(30),
  });
  const { data: monthlyTrend } = useQuery({
    queryKey: ['monthly-trend'],
    queryFn: () => dashboardService.monthlyTrend(12),
  });
  const { data: forecast } = useQuery({
    queryKey: ['forecast'],
    queryFn: () => dashboardService.forecast(3),
  });
  const { data: anomalies } = useQuery({
    queryKey: ['anomalies'],
    queryFn: dashboardService.anomalies,
  });

  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ role: string; content: string }>>([]);
  const chatMutation = useMutation({
    mutationFn: (msg: string) => chatService.sendMessage(msg),
    onSuccess: (data) => {
      setChatMessages((prev) => [...prev, { role: 'assistant', content: data.response }]);
    },
  });

  const handleChat = () => {
    if (!chatInput.trim()) return;
    setChatMessages((prev) => [...prev, { role: 'user', content: chatInput }]);
    chatMutation.mutate(chatInput);
    setChatInput('');
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin h-8 w-8 border-4 border-brand-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  // Aggregate daily costs for chart
  const dailyAgg: Record<string, number> = {};
  (dailyCosts || []).forEach((d) => {
    const key = d.date || '';
    dailyAgg[key] = (dailyAgg[key] || 0) + d.cost;
  });
  const dailyChartData = Object.entries(dailyAgg)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, cost]) => ({
      date: new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      cost: Math.round(cost * 100) / 100,
    }));

  // Service breakdown for pie chart
  const serviceData = Object.entries(costByService || summary?.cost_breakdown?.by_resource_type || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([name, value]) => ({ name: name.replace(/Amazon |AWS /g, ''), value: Math.round(value * 100) / 100 }));

  // Monthly trend data
  const trendData = (monthlyTrend || []).map((m) => ({
    month: new Date(m.month).toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
    cost: Math.round(m.cost * 100) / 100,
  }));

  const forecastTotal = forecast?.total_forecasted || 0;
  const totalSpend = summary?.total_monthly_spend ?? 0;
  const potentialSavings = summary?.total_potential_savings ?? 0;
  const optScore = summary?.optimization_score ?? 0;

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard
          label="Monthly Spend"
          value={formatCurrency(totalSpend)}
          icon={CurrencyDollarIcon}
          subtitle={`${summary?.total_resources ?? 0} resources`}
        />
        <KPICard
          label="Potential Savings"
          value={formatCurrency(potentialSavings)}
          icon={ArrowTrendingDownIcon}
          trend={totalSpend > 0 ? `${formatPercent(potentialSavings / totalSpend * 100)} of spend` : undefined}
          trendColor="text-emerald-400"
        />
        <KPICard
          label="Forecast (3 Mo)"
          value={forecastTotal > 0 ? formatCurrency(forecastTotal) : 'N/A'}
          icon={ArrowTrendingUpIcon}
          subtitle="Next quarter projection"
        />
        <KPICard
          label="Optimization Score"
          value={`${optScore}%`}
          icon={ChartBarSquareIcon}
          subtitle={`${summary?.open_recommendations ?? 0} open recommendations`}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Daily Cost Chart */}
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-200">Daily Spend (30 Days)</h2>
            <button onClick={() => exportService.costReport()} className="btn-ghost text-xs flex items-center gap-1">
              <ArrowDownTrayIcon className="h-3.5 w-3.5" /> Export
            </button>
          </div>
          {dailyChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={dailyChartData}>
                <defs>
                  <linearGradient id="dailyCostGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af' }} />
                <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={60}
                  tickFormatter={(v) => `$${v >= 1000 ? `${(v/1000).toFixed(1)}K` : v}`}
                />
                <Tooltip
                  contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 12, color: '#e5e7eb' }}
                  formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cost']}
                />
                <Area type="monotone" dataKey="cost" stroke="#6366f1" strokeWidth={2} fill="url(#dailyCostGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-gray-500">
              Connect a cloud account to see cost data
            </div>
          )}
        </div>

        {/* Service Breakdown */}
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">Cost by Service</h2>
          {serviceData.length > 0 ? (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={serviceData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} innerRadius={40} paddingAngle={2}>
                    {serviceData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 8, color: '#e5e7eb' }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, '']}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-1.5 mt-2">
                {serviceData.slice(0, 5).map((s, i) => (
                  <div key={s.name} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <div className="h-2.5 w-2.5 rounded-full" style={{ background: PIE_COLORS[i] }} />
                      <span className="text-gray-400">{s.name}</span>
                    </div>
                    <span className="text-gray-300 font-medium">${s.value.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="h-[280px] flex items-center justify-center text-gray-500 text-sm">No data</div>
          )}
        </div>
      </div>

      {/* Monthly Trend + Anomalies */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Monthly Trend */}
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">Monthly Trend</h2>
          {trendData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#2d3348" />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#9ca3af' }} />
                <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={55}
                  tickFormatter={(v) => `$${v >= 1000 ? `${(v/1000).toFixed(0)}K` : v}`}
                />
                <Tooltip contentStyle={{ background: '#1e2235', border: '1px solid #374151', borderRadius: 8, color: '#e5e7eb' }}
                  formatter={(v: number) => [`$${v.toFixed(2)}`, 'Cost']}
                />
                <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                  {trendData.map((_, i) => <Cell key={i} fill={i === trendData.length - 1 ? '#6366f1' : '#4338ca'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-gray-500 text-sm">No trend data</div>
          )}
        </div>

        {/* Anomalies & Recommendations */}
        <div className="card">
          <h2 className="text-base font-semibold text-gray-200 mb-4">Alerts & Savings</h2>
          <div className="space-y-3 max-h-[250px] overflow-y-auto">
            {(anomalies || []).slice(0, 3).map((a) => (
              <div key={a.anomaly_id} className="flex items-start gap-3 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20">
                <ExclamationTriangleIcon className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-rose-300">Cost Anomaly Detected</p>
                  <p className="text-xs text-gray-400">Impact: ${a.total_impact.toFixed(2)}</p>
                </div>
              </div>
            ))}
            {(summary?.top_savings_opportunities ?? []).slice(0, 5).map((rec) => (
              <div key={rec.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-200/50">
                <div className="flex items-center gap-3">
                  <LightBulbIcon className="h-4 w-4 text-amber-400" />
                  <span className="text-sm text-gray-300">{rec.title}</span>
                </div>
                <span className="text-sm font-semibold text-emerald-400">
                  {formatCurrency(rec.estimated_savings)}/mo
                </span>
              </div>
            ))}
            {!(anomalies?.length) && !(summary?.top_savings_opportunities?.length) && (
              <p className="text-sm text-gray-500 py-4 text-center">No alerts or recommendations</p>
            )}
          </div>
        </div>
      </div>

      {/* Floating Chat Widget */}
      <ChatWidget
        chatOpen={chatOpen}
        setChatOpen={setChatOpen}
        chatInput={chatInput}
        setChatInput={setChatInput}
        chatMessages={chatMessages}
        setChatMessages={setChatMessages}
        chatMutation={chatMutation}
        handleChat={handleChat}
      />
    </div>
  );
}

/* ── Quick-action suggestions for the chat ── */
const QUICK_ACTIONS = [
  { label: '💰 Top savings', prompt: 'What are my top savings opportunities?' },
  { label: '📊 Cost breakdown', prompt: 'Give me a cost breakdown by service' },
  { label: '⚠️ Idle resources', prompt: 'Which resources are idle or underutilized?' },
  { label: '🔄 Rightsizing', prompt: 'What rightsizing recommendations do you have?' },
  { label: '📈 Spend trend', prompt: 'How is my spending trending over the past months?' },
  { label: '🛡️ Reserved vs On-demand', prompt: 'Should I use reserved instances or savings plans?' },
];

/* ── Markdown components for dark-themed chat bubbles ── */
const mdComponents = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
  strong: ({ children }: { children?: React.ReactNode }) => <strong className="font-semibold text-white">{children}</strong>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li className="leading-relaxed">{children}</li>,
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="bg-surface-300/60 text-brand-300 px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>
  ),
  h1: ({ children }: { children?: React.ReactNode }) => <h1 className="text-sm font-bold text-white mb-1">{children}</h1>,
  h2: ({ children }: { children?: React.ReactNode }) => <h2 className="text-sm font-bold text-white mb-1">{children}</h2>,
  h3: ({ children }: { children?: React.ReactNode }) => <h3 className="text-sm font-semibold text-white mb-1">{children}</h3>,
  a: ({ children, href }: { children?: React.ReactNode; href?: string }) => (
    <a href={href} className="text-brand-400 underline hover:text-brand-300" target="_blank" rel="noreferrer">{children}</a>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="border-l-2 border-brand-500/50 pl-3 my-2 text-gray-400 italic">{children}</blockquote>
  ),
};

/* ── Typing dots animation ── */
function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 bg-surface-200 pl-4 pr-5 py-3 rounded-2xl rounded-bl-md">
        <SparklesIcon className="h-3.5 w-3.5 text-brand-400 animate-pulse" />
        <div className="flex gap-1">
          <span className="h-2 w-2 bg-gray-500 rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="h-2 w-2 bg-gray-500 rounded-full animate-bounce [animation-delay:150ms]" />
          <span className="h-2 w-2 bg-gray-500 rounded-full animate-bounce [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

/* ── Full Chat Widget Component ── */
function ChatWidget({
  chatOpen, setChatOpen, chatInput, setChatInput,
  chatMessages, setChatMessages, chatMutation, handleChat,
}: {
  chatOpen: boolean;
  setChatOpen: (v: boolean) => void;
  chatInput: string;
  setChatInput: (v: string) => void;
  chatMessages: Array<{ role: string; content: string }>;
  setChatMessages: React.Dispatch<React.SetStateAction<Array<{ role: string; content: string }>>>;
  chatMutation: ReturnType<typeof useMutation<{ response: string }, Error, string>>;
  handleChat: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, chatMutation.isPending]);

  const sendQuickAction = (prompt: string) => {
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: prompt }]);
    chatMutation.mutate(prompt);
  };

  return (
    <>
      {/* FAB button */}
      {!chatOpen && (
        <button
          onClick={() => setChatOpen(true)}
          className="fixed bottom-6 right-6 h-14 w-14 rounded-full bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-glow flex items-center justify-center hover:scale-105 transition-all z-50 group"
        >
          <ChatBubbleLeftRightIcon className="h-6 w-6 group-hover:scale-110 transition-transform" />
          <span className="absolute -top-1 -right-1 h-3.5 w-3.5 bg-emerald-500 rounded-full border-2 border-surface animate-pulse" />
        </button>
      )}

      {/* Chat panel */}
      {chatOpen && (
        <div className="fixed bottom-6 right-6 w-[420px] h-[560px] bg-surface-100/95 backdrop-blur-xl border border-gray-700/50 rounded-2xl shadow-2xl flex flex-col z-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700/50 bg-surface/80 backdrop-blur-sm">
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
                <SparklesIcon className="h-4 w-4 text-white" />
              </div>
              <div>
                <span className="font-semibold text-gray-200 text-sm">CloudPulse AI</span>
                <p className="text-[10px] text-emerald-400 flex items-center gap-1">
                  <span className="h-1.5 w-1.5 bg-emerald-400 rounded-full inline-block" /> Online
                </p>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {chatMessages.length > 0 && (
                <button
                  onClick={() => setChatMessages([])}
                  className="p-1.5 text-gray-500 hover:text-gray-300 rounded-lg hover:bg-surface-200 transition-colors"
                  title="Clear chat"
                >
                  <TrashIcon className="h-4 w-4" />
                </button>
              )}
              <button onClick={() => setChatOpen(false)} className="p-1.5 text-gray-500 hover:text-white rounded-lg hover:bg-surface-200 transition-colors">
                <XMarkIcon className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth">
            {chatMessages.length === 0 && (
              <div className="py-4 space-y-4">
                <div className="text-center">
                  <div className="h-12 w-12 mx-auto rounded-2xl bg-gradient-to-br from-brand-500/20 to-brand-700/20 border border-brand-500/30 flex items-center justify-center mb-3">
                    <SparklesIcon className="h-6 w-6 text-brand-400" />
                  </div>
                  <p className="text-sm text-gray-300 font-medium">How can I help optimize your costs?</p>
                  <p className="text-xs text-gray-500 mt-1">Powered by Ollama AI</p>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {QUICK_ACTIONS.map((qa) => (
                    <button
                      key={qa.label}
                      onClick={() => sendQuickAction(qa.prompt)}
                      className="text-left text-xs px-3 py-2.5 rounded-xl bg-surface-200/50 border border-gray-700/30 text-gray-400 hover:text-white hover:bg-surface-200 hover:border-gray-600/50 transition-all"
                    >
                      {qa.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {chatMessages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {m.role === 'assistant' && (
                  <div className="h-6 w-6 rounded-md bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shrink-0 mt-1 mr-2">
                    <SparklesIcon className="h-3 w-3 text-white" />
                  </div>
                )}
                <div className={`max-w-[80%] px-3.5 py-2.5 text-[13px] leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-brand-600 text-white rounded-2xl rounded-br-md'
                    : 'bg-surface-200/80 text-gray-300 rounded-2xl rounded-bl-md border border-gray-700/30'
                }`}>
                  {m.role === 'assistant' ? (
                    <ReactMarkdown components={mdComponents}>{m.content}</ReactMarkdown>
                  ) : (
                    m.content
                  )}
                </div>
              </div>
            ))}

            {chatMutation.isPending && <TypingIndicator />}
          </div>

          {/* Quick replies when conversation is active */}
          {chatMessages.length > 0 && !chatMutation.isPending && (
            <div className="px-3 pb-1 flex gap-1.5 overflow-x-auto scrollbar-thin">
              {QUICK_ACTIONS.slice(0, 3).map((qa) => (
                <button
                  key={qa.label}
                  onClick={() => sendQuickAction(qa.prompt)}
                  className="text-[11px] whitespace-nowrap px-2.5 py-1.5 rounded-full bg-surface-200/50 border border-gray-700/30 text-gray-500 hover:text-gray-300 hover:border-gray-600/50 transition-all shrink-0"
                >
                  {qa.label}
                </button>
              ))}
            </div>
          )}

          {/* Input */}
          <div className="px-3 py-3 border-t border-gray-700/50">
            <div className="flex gap-2">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleChat()}
                placeholder="Ask about your costs..."
                className="input flex-1 text-sm !rounded-xl !py-2.5"
              />
              <button
                onClick={handleChat}
                className="btn-primary !px-3 !rounded-xl"
                disabled={chatMutation.isPending || !chatInput.trim()}
              >
                <PaperAirplaneIcon className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
