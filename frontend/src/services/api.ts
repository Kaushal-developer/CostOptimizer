import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const accountId = sessionStorage.getItem('selected_account_id');
  if (accountId) config.headers['X-Cloud-Account-Id'] = accountId;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      try {
        const rt = localStorage.getItem('refresh_token');
        const { data } = await axios.post('/api/v1/auth/refresh', { refresh_token: rt });
        localStorage.setItem('access_token', data.access_token);
        if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token);
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original);
      } catch {
        localStorage.clear();
        window.location.href = '/login';
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  },
);

// ── Auth ──
export interface LoginPayload { email: string; password: string }
export interface RegisterPayload { email: string; password: string; full_name: string; tenant_name: string }
export interface TokenResponse { access_token: string; refresh_token: string; token_type: string }
export interface UserInfo { id: number; tenant_id: number; email: string; full_name: string; role: string; is_active: boolean }

export const authService = {
  login: async (p: LoginPayload) => {
    const { data: tokens } = await api.post<TokenResponse>('/auth/login', p);
    localStorage.setItem('access_token', tokens.access_token);
    const { data: user } = await api.get<UserInfo>('/auth/me');
    return { tokens, user };
  },
  register: async (p: RegisterPayload) => {
    await api.post('/auth/register', p);
    return authService.login({ email: p.email, password: p.password });
  },
  me: () => api.get<UserInfo>('/auth/me').then((r) => r.data),
};

// ── Cloud Accounts ──
export interface CloudAccount {
  id: number; provider: 'aws' | 'azure' | 'gcp'; account_id: string; display_name: string;
  status: string; is_remediation_enabled: boolean;
  aws_role_arn: string | null; aws_external_id: string | null;
  aws_access_key_id: string | null; aws_region: string | null;
  azure_subscription_id: string | null; azure_tenant_id: string | null;
  gcp_project_id: string | null; last_sync_at: string | null; last_error: string | null; created_at: string;
}
export interface CloudAccountCreate {
  provider: 'aws' | 'azure' | 'gcp'; account_id: string; display_name: string;
  aws_role_arn?: string; aws_external_id?: string;
  aws_access_key_id?: string; aws_secret_access_key?: string; aws_region?: string;
  azure_subscription_id?: string; azure_tenant_id?: string; gcp_project_id?: string;
  [key: string]: string | undefined;
}
interface Paginated<T> { items: T[]; total: number; page: number; page_size: number }

export const cloudAccountsService = {
  list: (page = 1) => api.get<Paginated<CloudAccount>>('/cloud-accounts', { params: { page } }).then((r) => r.data),
  create: (d: CloudAccountCreate) => api.post<CloudAccount>('/cloud-accounts', d).then((r) => r.data),
  delete: (id: number) => api.delete(`/cloud-accounts/${id}`),
  sync: (id: number) => api.post(`/cloud-accounts/${id}/sync`),
};

// ── Resources ──
export interface Resource {
  id: number; resource_id: string; resource_type: string; provider_resource_type: string;
  region: string; status: string; name: string | null; instance_type: string | null;
  vcpus: number | null; memory_gb: number | null; storage_gb: number | null;
  monthly_cost: number; currency: string; tags: Record<string, string> | null;
  metadata: Record<string, unknown> | null;
  last_seen_at: string; created_at: string;
}

export interface ResourceMetric {
  id: number; metric_name: string;
  avg_value: number; max_value: number; min_value: number; p95_value: number | null;
  period_days: number; collected_at: string;
}

export interface ResourceDetail extends Resource {
  metrics: ResourceMetric[];
}

export interface ResourceMetricHistoryPoint {
  collected_at: string; avg_value: number; max_value: number; min_value: number; p95_value: number | null;
}

export interface ResourceMetricHistory {
  metric_name: string; period_days: number; datapoints: ResourceMetricHistoryPoint[];
}

export interface ResourceFilters { resource_type?: string; status?: string; region?: string; page?: number; page_size?: number }

export interface ResourceRecommendation {
  id: number; type: string; priority: string; status: string;
  title: string; description: string; ai_explanation: string | null;
  current_monthly_cost: number; estimated_monthly_cost: number; estimated_savings: number;
  confidence_score: number; recommended_config: Record<string, unknown> | null;
  created_at: string;
}

export const resourcesService = {
  list: (p?: ResourceFilters) => api.get<Paginated<Resource>>('/resources', { params: p }).then((r) => r.data),
  get: (id: number) => api.get<ResourceDetail>(`/resources/${id}`).then((r) => r.data),
  getMetrics: (id: number) => api.get<ResourceMetric[]>(`/resources/${id}/metrics`).then((r) => r.data),
  getMetricsHistory: (id: number, metricName: string, days = 30) =>
    api.get<ResourceMetricHistory>(`/resources/${id}/metrics/history`, { params: { metric_name: metricName, days } }).then((r) => r.data),
  getRecommendations: (id: number) =>
    api.get<ResourceRecommendation[]>(`/resources/${id}/recommendations`).then((r) => r.data),
};

// ── Recommendations ──
export interface Recommendation {
  id: number; type: string; priority: 'critical' | 'high' | 'medium' | 'low';
  status: string; title: string; description: string; ai_explanation: string | null;
  current_monthly_cost: number; estimated_monthly_cost: number; estimated_savings: number;
  confidence_score: number; created_at: string;
}

export const recommendationsService = {
  list: (p?: Record<string, unknown>) => api.get<Paginated<Recommendation>>('/recommendations', { params: p }).then((r) => r.data),
  action: (id: number, action: 'accept' | 'reject' | 'apply') => api.post(`/recommendations/${id}/action`, { action }).then((r) => r.data),
  whatIf: (ids: number[]) => api.post('/recommendations/what-if', { recommendation_ids: ids }).then((r) => r.data),
};

// ── Dashboard ──
export interface DashboardSummary {
  total_cloud_accounts: number; total_resources: number; total_monthly_spend: number;
  total_potential_savings: number; open_recommendations: number; critical_recommendations: number;
  optimization_score: number;
  cost_breakdown: { by_provider: Record<string, number>; by_resource_type: Record<string, number>; by_region: Record<string, number> };
  top_savings_opportunities: Array<{ id: number; title: string; estimated_savings: number; priority: string }>;
}
export interface NLQueryResponse { query: string; answer: string }

export const dashboardService = {
  summary: () => api.get<DashboardSummary>('/dashboard/summary').then((r) => r.data),
  savings: () => api.get('/dashboard/savings').then((r) => r.data),
  query: (q: string) => api.post<NLQueryResponse>('/dashboard/query', { query: q }).then((r) => r.data),
  dailyCosts: (days = 30) => api.get<Array<{ date: string; service?: string; key?: string; cost: number }>>('/dashboard/daily-costs', { params: { days } }).then((r) => r.data),
  costByService: (days = 30) => api.get<Record<string, number>>('/dashboard/cost-by-service', { params: { days } }).then((r) => r.data),
  costByRegion: (days = 30) => api.get<Record<string, number>>('/dashboard/cost-by-region', { params: { days } }).then((r) => r.data),
  monthlyTrend: (months = 12) => api.get<Array<{ month: string; cost: number }>>('/dashboard/monthly-trend', { params: { months } }).then((r) => r.data),
  costSummary: (days = 30) => api.get<{ current_period_cost: number; previous_period_cost: number; change_percentage: number }>('/dashboard/cost-summary', { params: { days } }).then((r) => r.data),
  anomalies: () => api.get<Array<{ anomaly_id: string; start_date: string; end_date: string; total_impact: number; root_causes: unknown[] }>>('/dashboard/anomalies').then((r) => r.data),
  forecast: (months = 3) => api.get<{ total_forecasted: number; periods: Array<{ period_start: string; period_end: string; mean: number; lower: number; upper: number }> }>('/dashboard/forecast', { params: { months } }).then((r) => r.data),
  savingsPlans: () => api.get<{ plans: unknown[]; coverage: Record<string, unknown>; utilization: Record<string, unknown>; purchase_recommendations: unknown[] }>('/dashboard/savings-plans').then((r) => r.data),
};

// ── Chat ──
export interface ChatResponse { response: string; context: Record<string, unknown> | null }

export const chatService = {
  sendMessage: (message: string) => api.post<ChatResponse>('/chat/message', { message }).then((r) => r.data),
  history: (limit = 50) => api.get<Array<{ id: number; role: string; content: string; created_at: string }>>('/chat/history', { params: { limit } }).then((r) => r.data),
};

// ── Exports ──
export const exportService = {
  download: async (endpoint: string, filename: string) => {
    const resp = await api.get(endpoint, { responseType: 'blob' });
    const url = window.URL.createObjectURL(new Blob([resp.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  },
  resources: () => exportService.download('/exports/resources', 'resources.csv'),
  recommendations: () => exportService.download('/exports/recommendations', 'recommendations.csv'),
  utilization: () => exportService.download('/exports/utilization', 'utilization.csv'),
  costReport: () => exportService.download('/exports/cost-report', 'cost_report.csv'),
};

// ── Settings / Integrations ──
export interface IntegrationConfig {
  id: number; type: string; name: string; is_enabled: boolean; config: Record<string, unknown>; created_at: string;
}

export const settingsService = {
  listIntegrations: () => api.get<IntegrationConfig[]>('/settings/integrations').then((r) => r.data),
  createIntegration: (d: { type: string; name: string; config: Record<string, unknown> }) => api.post('/settings/integrations', d).then((r) => r.data),
  updateIntegration: (id: number, d: Partial<IntegrationConfig>) => api.put(`/settings/integrations/${id}`, d).then((r) => r.data),
  deleteIntegration: (id: number) => api.delete(`/settings/integrations/${id}`),
};

// ── JIRA ──
export const jiraService = {
  createTicket: (d: { recommendation_id: number; summary?: string; priority?: string }) =>
    api.post('/jira/tickets', d).then((r) => r.data),
  getTickets: (recId: number) => api.get(`/jira/tickets/${recId}`).then((r) => r.data),
};

// ── Compliance ──
export interface ComplianceFramework { id: number; name: string; version: string; score: number }
export interface ComplianceFinding {
  id: number; framework_id: number; rule_id: string; status: string; severity: string;
  title: string; description: string; remediation: string | null;
  resource_id: string | null; details: Record<string, unknown> | null; found_at: string;
}

export const complianceService = {
  frameworks: () => api.get<ComplianceFramework[]>('/compliance/frameworks').then((r) => r.data),
  scan: () => api.post<{ frameworks: Array<{ framework: string; score: number; passed: number; failed: number; total_rules: number }>; total_findings: number; findings: ComplianceFinding[] }>('/compliance/scan').then((r) => r.data),
  findings: (params?: { framework_id?: number; severity?: string }) =>
    api.get<ComplianceFinding[]>('/compliance/findings', { params }).then((r) => r.data),
};

// ── Security ──
export interface SecurityAlert {
  id: number; category: string; severity: string; status: string; title: string;
  description: string; resource_id: string | null; resource_type: string | null;
  region: string | null; remediation: string | null; risk_score: number; detected_at: string;
}

export const securityService = {
  scan: (accountId?: number) => api.post('/security/scan', null, { params: accountId ? { cloud_account_id: accountId } : {} }).then((r) => r.data),
  alerts: (params?: { status?: string; severity?: string }) => api.get<SecurityAlert[]>('/security/alerts', { params }).then((r) => r.data),
  updateAlertStatus: (id: number, status: string) => api.put(`/security/alerts/${id}/status`, { status }).then((r) => r.data),
  summary: () => api.get<{ total_alerts: number; by_severity: Record<string, number>; by_status: Record<string, number>; risk_score: number }>('/security/summary').then((r) => r.data),
};

// ── Budgets ──
export interface BudgetItem {
  id: number; name: string; amount: number; period: string; status: string;
  actual_spend: number; forecasted_spend: number; utilization_pct: number;
  warning_threshold: number; critical_threshold: number; created_at: string;
}

export const budgetService = {
  list: () => api.get<BudgetItem[]>('/budgets').then((r) => r.data),
  create: (d: { name: string; amount: number; period?: string; warning_threshold?: number; critical_threshold?: number }) =>
    api.post('/budgets', d).then((r) => r.data),
  update: (id: number, d: Partial<BudgetItem>) => api.put(`/budgets/${id}`, d).then((r) => r.data),
  delete: (id: number) => api.delete(`/budgets/${id}`),
  alerts: (id: number) => api.get<Array<{ id: number; threshold_percentage: number; actual_percentage: number; message: string; triggered_at: string }>>(`/budgets/${id}/alerts`).then((r) => r.data),
};

// ── Reservations ──
export const reservationService = {
  analyze: (monthlyCost: number, commitmentPct?: number) =>
    api.get('/reservations/analyze', { params: { monthly_cost: monthlyCost, commitment_pct: commitmentPct || 100 } }).then((r) => r.data),
};

// ── Load Balancing ──
export const loadBalancingService = {
  analysis: () => api.get('/load-balancing/analysis').then((r) => r.data),
};

export default api;
