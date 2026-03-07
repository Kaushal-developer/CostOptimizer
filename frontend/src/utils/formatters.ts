/** Convert snake_case/camelCase keys to human-readable labels */
const SPECIAL_TERMS: Record<string, string> = {
  aws: 'AWS',
  gcp: 'GCP',
  arn: 'ARN',
  vpc: 'VPC',
  ec2: 'EC2',
  rds: 'RDS',
  ebs: 'EBS',
  elb: 'ELB',
  s3: 'S3',
  iam: 'IAM',
  ip: 'IP',
  az: 'AZ',
  cpu: 'CPU',
  gpu: 'GPU',
  gb: 'GB',
  tb: 'TB',
  mb: 'MB',
  iops: 'IOPS',
  id: 'ID',
  ssl: 'SSL',
  dns: 'DNS',
  http: 'HTTP',
  https: 'HTTPS',
  api: 'API',
  url: 'URL',
  uri: 'URI',
  sql: 'SQL',
  db: 'DB',
  ri: 'RI',
  sp: 'SP',
  ami: 'AMI',
  nat: 'NAT',
  waf: 'WAF',
};

export function humanizeKey(key: string): string {
  // Replace underscores and hyphens with spaces
  const words = key.replace(/[_-]/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').split(/\s+/);
  return words
    .map((w) => {
      const lower = w.toLowerCase();
      if (SPECIAL_TERMS[lower]) return SPECIAL_TERMS[lower];
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    })
    .join(' ');
}

export function formatCurrency(value: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatNumber(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(value < 10 ? 2 : 0);
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
