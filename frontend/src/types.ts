export type SourceKind =
  | 'cfpb_public_snapshot'
  | 'cfpb_api_snapshot'
  | 'synthetic_offline_demo'
  | 'unknown'
  | (string & {});

export interface SourceMeta {
  sourceKind: SourceKind;
  snapshotId: string | null;
  generatedAt: string | null;
  isDemo: boolean;
  isVerifiedPublicData: boolean;
  dataMode: string;
  persistenceMode: string;
}

export type CasePriority = 'urgent' | 'high' | 'standard' | 'low';
export type CaseStatus = 'new' | 'in_review' | 'routed' | 'closed';

export interface CaseRecord {
  id: string;
  complaintId: string;
  dateReceived: string;
  product: string;
  issue: string;
  subProduct: string | null;
  subIssue: string | null;
  company: string;
  state: string | null;
  narrative: string | null;
  companyResponse: string | null;
  timelyResponse: boolean | null;
  submissionChannel: string | null;
  predictedRoute: string | null;
  predictedProduct: string | null;
  predictedIssue: string | null;
  confidence: number | null;
  abstained: boolean;
  manualAttention: boolean;
  attentionReasons: string[];
  priority: CasePriority;
  status: CaseStatus;
  ageDays: number | null;
  sourceKind: SourceKind;
}

export interface CaseQueue {
  cases: CaseRecord[];
  total: number;
  source: SourceMeta;
}

export interface TimePoint {
  period: string;
  count: number;
  timelyRate: number | null;
}

export interface CategoryVolume {
  label: string;
  count: number;
  share: number | null;
}

export interface OperationsOverview {
  totalComplaints: number;
  newComplaints: number;
  manualAttention: number;
  timelyRate: number | null;
  abstentionRate: number | null;
  medianAgeDays: number | null;
  volumeChange: number | null;
  periodLabel: string;
  series: TimePoint[];
  products: CategoryVolume[];
  source: SourceMeta;
}

export interface TrendAnomaly {
  id: string;
  period: string;
  product: string;
  issue: string;
  observed: number;
  expected: number | null;
  zScore: number | null;
  direction: 'up' | 'down';
  severity: 'high' | 'medium' | 'watch';
  explanation: string;
}

export interface AnomalyReport {
  anomalies: TrendAnomaly[];
  source: SourceMeta;
}

export interface CalibrationBin {
  lower: number;
  upper: number;
  meanConfidence: number;
  accuracy: number;
  count: number;
}

export interface FalseRoutePattern {
  actual: string;
  predicted: string;
  count: number;
  share: number | null;
}

export interface DriftPoint {
  period: string;
  product: string;
  macroF1: number | null;
  abstentionRate: number | null;
  driftScore: number | null;
  status: 'stable' | 'watch' | 'alert' | 'unknown';
}

export interface ModelMetrics {
  modelName: string;
  modelVersion: string;
  target: string;
  validationWindow: string;
  macroF1: number | null;
  accuracy: number | null;
  expectedCalibrationError: number | null;
  coverage: number | null;
  abstentionRate: number | null;
  abstentionThreshold: number | null;
  evaluatedRows: number;
  falseRoutes: FalseRoutePattern[];
  calibration: CalibrationBin[];
  drift: DriftPoint[];
  summaryFactuality: number | null;
  summaryClaimsSupportedRate: number | null;
  summaryQuotesExactRate: number | null;
  summaryReviewedN: number;
  latencyP50Ms: number | null;
  latencyP95Ms: number | null;
  meanApiCostUsd: number | null;
  systemFailures: number;
  refusalRate: number | null;
  source: SourceMeta;
}

export interface SummaryDraft {
  id: string;
  caseId: string;
  overview: string;
  keyPoints: string[];
  quotedEvidence: string[];
  suggestedActions: string[];
  caveats: string[];
  status: 'draft' | 'approved' | 'rejected';
  provider: string | null;
  model: string | null;
  latencyMs: number | null;
  estimatedCostUsd: number | null;
  refusalReason: string | null;
  reviewer: string | null;
  evidenceChecked: boolean;
  reviewedAt: string | null;
  source: SourceMeta;
}

export interface SummaryReview {
  id: string;
  status: 'approved' | 'rejected' | 'draft';
  reviewer: string | null;
  evidenceChecked: boolean;
  reviewedAt: string | null;
  simulated?: boolean;
}

export interface RouteDecision {
  caseId: string;
  route: string;
  status: CaseStatus;
  reviewer: string;
  reviewedAt: string | null;
  simulated?: boolean;
}

export type LoadState<T> =
  | { status: 'loading'; data: null; message: null }
  | { status: 'ready'; data: T; message: string | null }
  | { status: 'error'; data: null; message: string };
