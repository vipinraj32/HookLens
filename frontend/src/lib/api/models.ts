/**
 * Runtime-validated response models.
 *
 * The OpenAPI-generated `schema.d.ts` types request bodies; these Zod schemas check the
 * fields the UI depends on at runtime. Objects are "loose" so additive backend fields
 * never break the client, but a missing or mistyped required field surfaces as an
 * explicit `invalid_response` error instead of rendering garbage.
 */
import { z } from "zod";

const nstr = z.string().nullable().optional();
const anyRecord = z.record(z.string(), z.unknown());

export const SEVERITIES = ["critical", "high", "medium", "low", "informational", "unknown"] as const;
export type Severity = (typeof SEVERITIES)[number];

export const JobEvent = z.looseObject({
  ts: z.string(),
  stage: z.string(),
  progress: z.number(),
  message: z.string(),
  level: z.string().optional(),
  data: anyRecord.nullable().optional(),
});
export type JobEvent = z.infer<typeof JobEvent>;

export const Job = z.looseObject({
  id: z.string(),
  kind: z.string(),
  subject_id: nstr,
  status: z.string(),
  stage: z.string(),
  progress: z.number(),
  events: z.array(JobEvent),
  cancel_requested: z.boolean(),
  attempts: z.number(),
  max_attempts: z.number(),
  timeout_s: z.number(),
  error: anyRecord.nullable().optional(),
  created_at: z.string(),
  started_at: nstr,
  finished_at: nstr,
});
export type Job = z.infer<typeof Job>;

export const TokenInfo = z.looseObject({
  address: z.string().nullable().optional(),
  native: z.boolean().optional(),
  decimals: z.number().nullable().optional(),
  decimals_source: nstr,
  symbol: nstr,
});
export type TokenInfo = z.infer<typeof TokenInfo>;

export const PoolState = z.looseObject({
  initialized: z.boolean(),
  sqrt_price_x96: z.string().optional(),
  tick: z.number().optional(),
  protocol_fee: z.number().optional(),
  lp_fee: z.number().optional(),
  liquidity: z.string().optional(),
  block_number: z.number().optional(),
});

export const Pool = z.looseObject({
  pool_id: z.string(),
  currency0: z.string(),
  currency1: z.string(),
  fee: z.number(),
  dynamic_fee: z.boolean().optional(),
  tick_spacing: z.number(),
  hooks: z.string().optional(),
  init_block: z.number().nullable().optional(),
  init_tx: nstr,
  state: PoolState.nullable().optional(),
  token0: TokenInfo.nullable().optional(),
  token1: TokenInfo.nullable().optional(),
});
export type Pool = z.infer<typeof Pool>;

export const PermissionFlag = z.looseObject({
  flag: z.string(),
  bit: z.number(),
  callback: z.string(),
  signature: z.string(),
  selector: z.string(),
  enabled: z.boolean(),
  is_return_delta: z.boolean(),
  explanation: z.string().optional(),
});
export type PermissionFlag = z.infer<typeof PermissionFlag>;

export const Permissions = z.looseObject({
  v4_core_commit: z.string().optional(),
  hooks_sol_sha256: z.string().optional(),
  bits: z.string(),
  flags: z.array(PermissionFlag).optional(),
  enabled_flags: z.array(z.string()),
  callbacks: z.array(z.string()).optional(),
  affected_operations: z.array(z.string()).optional(),
  return_delta_flags: z.array(z.string()).optional(),
  can_affect_withdrawals: z.boolean().optional(),
  note: z.string().optional(),
});
export type Permissions = z.infer<typeof Permissions>;

export const Contract = z.looseObject({
  id: z.string(),
  chain_id: z.number(),
  address: z.string(),
  block_number: z.number(),
  block_hash: z.string(),
  runtime_code_hash: z.string(),
  code_size: z.number(),
  is_proxy: z.boolean(),
  proxy_kind: nstr,
  implementation_address: nstr,
  implementation_code_hash: nstr,
  proxy_admin: nstr,
  source_status: z.string(),
  source_provider: nstr,
  contract_name: nstr,
  compiler_version: nstr,
  provenance: anyRecord.optional(),
});
export type Contract = z.infer<typeof Contract>;

export const ScanSummaryCounts = z.looseObject({
  finding_count: z.number().optional(),
  evidence_count: z.number().optional(),
  by_severity: z.record(z.string(), z.number()).optional(),
  top: z.array(z.looseObject({ finding_id: z.string(), title: z.string(), severity: z.string() })).optional(),
});

export const ScanSummary = z.looseObject({
  id: z.string(),
  chain_id: z.number(),
  hook_address: z.string(),
  requested_pool_id: nstr,
  block_number: z.number().nullable().optional(),
  status: z.string(),
  job_id: nstr,
  summary: ScanSummaryCounts,
  error: anyRecord.nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ScanSummary = z.infer<typeof ScanSummary>;

export const AnalyzerRun = z.looseObject({
  analyzer_id: z.string(),
  status: z.string(),
  reason: nstr,
  duration_ms: z.number().nullable().optional(),
  findings: z.number().optional(),
});
export type AnalyzerRun = z.infer<typeof AnalyzerRun>;

export const Scan = ScanSummary.extend({
  options: anyRecord,
  permissions: Permissions.nullable().optional(),
  pools: z.array(Pool),
  analysis: z.looseObject({
    analyzer_version: z.string().optional(),
    runs: z.array(AnalyzerRun).optional(),
    facts: anyRecord.optional(),
    bytecode: anyRecord.nullable().optional(),
    discovery: anyRecord.nullable().optional(),
    source: anyRecord.nullable().optional(),
    capabilities: anyRecord.nullable().optional(),
    provenance: anyRecord.nullable().optional(),
  }),
  contract: Contract.nullable().optional(),
});
export type Scan = z.infer<typeof Scan>;

export const Finding = z.looseObject({
  finding_id: z.string(),
  scan_id: z.string(),
  simulation_id: nstr,
  analyzer_id: z.string(),
  rule_id: z.string(),
  category: z.string(),
  title: z.string(),
  severity: z.string(),
  severity_rationale: z.string(),
  confidence_basis: z.string(),
  status: z.string(),
  description: z.string(),
  affected_functions: z.array(z.string()),
  evidence_ids: z.array(z.string()),
  related_scenarios: z.array(z.string()),
  lp_implications: z.string(),
  remediation: z.string(),
  limitations: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Finding = z.infer<typeof Finding>;

export const Evidence = z.looseObject({
  evidence_id: z.string(),
  scan_id: z.string(),
  simulation_id: nstr,
  kind: z.string(),
  title: z.string(),
  source_file: nstr,
  line_start: z.number().nullable().optional(),
  line_end: z.number().nullable().optional(),
  function_name: nstr,
  basis: z.string(),
  data: anyRecord,
  created_at: z.string(),
});
export type Evidence = z.infer<typeof Evidence>;

export const page = <T extends z.ZodType>(item: T) =>
  z.looseObject({ items: z.array(item), total: z.number(), limit: z.number(), offset: z.number() });

export const ScenarioDef = z.looseObject({
  scenario_id: z.string(),
  title: z.string(),
  description: z.string(),
  executes: z.array(z.string()),
});
export type ScenarioDef = z.infer<typeof ScenarioDef>;

export interface DecodedRevertT {
  kind: string;
  message?: string;
  name?: string | null;
  selector?: string | null;
  function?: string | null;
  target?: string | null;
  signature?: string | null;
  args?: Record<string, unknown> | null;
  inner?: DecodedRevertT | null;
  details?: DecodedRevertT | null;
}

export const DecodedRevert: z.ZodType<DecodedRevertT> = z.lazy(() =>
  z.looseObject({
    kind: z.string(),
    message: z.string().optional(),
    name: nstr,
    selector: nstr,
    function: nstr,
    target: nstr,
    signature: nstr,
    args: anyRecord.nullable().optional(),
    inner: DecodedRevert.nullable().optional(),
    details: DecodedRevert.nullable().optional(),
  }),
);

export const RevertFrame = z.looseObject({
  idx: z.number(),
  address: z.string(),
  label: nstr,
  function: nstr,
  selector: nstr,
  revert: DecodedRevert.nullable().optional(),
});

export const Step = z.looseObject({
  name: z.string(),
  phase: z.string(),
  condition: z.string(),
  lp_expectation: z.string(),
  observed: z.string(),
  expectation_met: z.boolean(),
  privileged: z.boolean(),
  revert_data: z.string().optional(),
  amount0: z.string().optional(),
  amount1: z.string().optional(),
  gas_used: z.number().optional(),
  block_timestamp: z.number().optional(),
  note: z.string().optional(),
  step_status: z.string(),
  revert: DecodedRevert.nullable().optional(),
  trace_nodes: z.array(z.number()).optional(),
  revert_chain: z.array(RevertFrame).optional(),
});
export type Step = z.infer<typeof Step>;

export const TraceNode = z.looseObject({
  idx: z.number(),
  parent: z.number().nullable(),
  depth: z.number(),
  kind: z.string(),
  caller: z.string().optional(),
  caller_label: nstr,
  address: z.string(),
  label: nstr,
  selector: nstr,
  function: nstr,
  value: z.string().optional(),
  success: z.boolean(),
  status: z.string().optional(),
  gas_used: z.number().optional(),
  data: z.string().optional(),
  data_truncated: z.boolean().optional(),
  log_count: z.number().optional(),
  revert: DecodedRevert.nullable().optional(),
  children: z.array(z.number()).optional(),
});
export type TraceNode = z.infer<typeof TraceNode>;

export const Trace = z.looseObject({
  format: z.string().optional(),
  root: z.number().nullable().optional(),
  nodes: z.array(TraceNode).optional(),
  steps: z.record(z.string(), z.array(z.number())).optional(),
  unattributed: z.array(z.number()).optional(),
  pruned_cheatcode_calls: z.number().optional(),
  total_nodes: z.number().optional(),
  truncated: z.boolean().optional(),
  setup_nodes: z.number().optional(),
});
export type Trace = z.infer<typeof Trace>;

export const ScenarioRunSummary = z.looseObject({
  id: z.string(),
  scenario_id: z.string(),
  status: z.string(),
  status_reason: z.string(),
  parameters: anyRecord,
  repro_command: z.string(),
  forge_status: nstr,
  duration_ms: z.number().nullable().optional(),
  result_meta: anyRecord,
  error: anyRecord.nullable().optional(),
});
export type ScenarioRunSummary = z.infer<typeof ScenarioRunSummary>;

export const ScenarioRun = ScenarioRunSummary.extend({ steps: z.array(Step), trace: Trace });
export type ScenarioRun = z.infer<typeof ScenarioRun>;

export const Simulation = z.looseObject({
  id: z.string(),
  scan_id: z.string(),
  job_id: nstr,
  status: z.string(),
  chain_id: z.number(),
  pool_id: nstr,
  fork_block: z.number().nullable().optional(),
  fork_block_hash: nstr,
  harness_version: nstr,
  harness_commit: nstr,
  spec: anyRecord,
  summary: anyRecord,
  error: anyRecord.nullable().optional(),
  created_at: z.string(),
  finished_at: nstr,
  runs: z.array(ScenarioRunSummary).optional(),
});
export type Simulation = z.infer<typeof Simulation>;

export const Tagged = z.looseObject({
  value: z.union([z.string(), z.number(), z.null()]),
  tag: z.string(),
  basis: z.string(),
  raw: z.string().optional(),
});
export type Tagged = z.infer<typeof Tagged>;

export const PriceScenario = z.looseObject({
  price_move: z.number(),
  assumption: z.string(),
  tag: z.string(),
  price: z.string(),
  tick: z.number(),
  range_state: z.string(),
  amount0: z.string(),
  amount1: z.string(),
  lp_value_token1: z.string(),
  hold_value_token1: z.string(),
  divergence_token1: z.string(),
  divergence_pct: z.string().nullable().optional(),
});
export type PriceScenario = z.infer<typeof PriceScenario>;

export const BlockedWithdrawal = z.looseObject({
  condition: z.string(),
  scenario: z.string(),
  step: z.string(),
  revert: z.string().nullable().optional(),
  tag: z.string(),
  position_value_unwithdrawable_token1: z.string().nullable().optional(),
  value_basis: z.string().optional(),
});
export type BlockedWithdrawal = z.infer<typeof BlockedWithdrawal>;

export const SimulationEffects = z.looseObject({
  // When no simulation was selected the backend returns {tag: "unavailable", reason}.
  tag: z.string().optional(),
  reason: z.string().optional(),
  simulation_id: z.string().optional(),
  status: z.string().optional(),
  fork_block: z.number().nullable().optional(),
  simulated_position: z
    .looseObject({ tick_lower: z.number(), tick_upper: z.number(), liquidity: z.string() })
    .nullable()
    .optional(),
  same_range_as_simulation: z.boolean().optional(),
  withdrawal_blocked_under: z.array(BlockedWithdrawal).optional(),
  withdrawal_succeeded_under: z.array(z.string()).optional(),
  round_trip: anyRecord.nullable().optional(),
  accounting: anyRecord.nullable().optional(),
  fee: z
    .looseObject({
      tag: z.string(),
      baseline_fee_pips: z.number().nullable().optional(),
      max_fee_after_owner_change_pips: z.number().nullable().optional(),
      basis: z.string().optional(),
    })
    .nullable()
    .optional(),
});
export type SimulationEffects = z.infer<typeof SimulationEffects>;

export const Compare = z.looseObject({
  position_id: z.string(),
  calculation_version: z.string(),
  pool: z.looseObject({
    pool_id: z.string(),
    token0: TokenInfo,
    token1: TokenInfo,
    fee: z.number(),
    tick_spacing: z.number(),
    state: PoolState,
    block_number: z.number().nullable().optional(),
  }),
  position: z.looseObject({ tick_lower: z.number(), tick_upper: z.number(), liquidity: z.string() }),
  notes: z.array(z.string()),
  baseline: z.record(z.string(), Tagged),
  price_scenarios: z.array(PriceScenario),
  simulation_effects: SimulationEffects.nullable().optional(),
  disclaimer: z.string(),
});
export type Compare = z.infer<typeof Compare>;

export const Report = z.looseObject({
  id: z.string(),
  scan_id: z.string(),
  simulation_id: nstr,
  position_id: nstr,
  status: z.string(),
  report_version: z.string(),
  content_hash: z.string(),
  pdf_available: z.boolean(),
  error: anyRecord.nullable().optional(),
  created_at: z.string(),
  content: anyRecord.optional(),
});
export type Report = z.infer<typeof Report>;

export const WorkspaceReport = Report.extend({ chain_id: z.number(), hook_address: z.string() });
export type WorkspaceReport = z.infer<typeof WorkspaceReport>;

export const Explanation = z.looseObject({
  id: z.string(),
  scan_id: z.string(),
  finding_id: z.string(),
  status: z.string(),
  model: nstr,
  content: anyRecord.nullable().optional(),
  validation: anyRecord.nullable().optional(),
  created_at: z.string(),
  job_id: nstr,
});
export type Explanation = z.infer<typeof Explanation>;

export const Chain = z.looseObject({
  chain_id: z.number(),
  name: z.string(),
  short_name: z.string(),
  pool_manager: z.string(),
  explorer_url: nstr,
  is_local: z.boolean(),
  rpc_configured: z.boolean(),
  source_verification: z.string().optional(),
  notes: z.array(z.string()).optional(),
});
export type Chain = z.infer<typeof Chain>;

export const WorkerHealth = z.looseObject({
  dispatcher: z.looseObject({ backend: z.string(), ok: z.boolean() }),
  forge: z.looseObject({ available: z.boolean() }),
  ai: z.looseObject({ enabled: z.boolean(), model: nstr }),
});
export type WorkerHealth = z.infer<typeof WorkerHealth>;
