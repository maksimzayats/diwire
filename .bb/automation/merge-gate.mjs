import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync, rmSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, sep, isAbsolute, dirname, basename } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const requiredChecks = [
  ...["3.10", "3.11", "3.12", "3.13", "3.14", "3.14t", "3.15", "3.15t"].map(v => `Lint & Tests (Python ${v})`),
  ...["3.14", "3.15", "3.15t"].flatMap(version =>
    ["FastAPI", "aiohttp", "Celery", "Litestar", "Flask", "Typer"].map(framework =>
      `E2E ${framework} (Docker Compose, Python ${version})`)),
  "Docs Build", "Docs Build (Python 3.15)", "Docs Build (Python 3.15t)",
];
const conditionalSkips = new Set(["dependabot-auto-merge", "H005 calibrated allocation experiment (Python 3.14.6)"]);
const shaPattern = /^[0-9a-f]{40}$/;
export function reviewInventoryHash(snapshot) {
  return createHash("sha256").update(JSON.stringify({comments: snapshot.comments, reviews: snapshot.reviews, threads: snapshot.threads})).digest("hex");
}
export function nonRuntimeScope(files, maintenance = false) {
  const eligible = path => typeof path === "string" &&
    (/^(examples|docs|tests)\//.test(path) || path === "README.md" ||
      (maintenance && (path.startsWith(".bb/") || path === "tools/bb_perf_dispatch.py")));
  return Array.isArray(files) && files.length > 0 && files.length < 300 &&
    files.every(file => eligible(file.filename) && (!file.previous_filename || eligible(file.previous_filename)));
}
export function changedPathsHash(files) {
  const paths = [...new Set(files.flatMap(file => [file.filename, ...(file.previous_filename ? [file.previous_filename] : [])]))].sort();
  return createHash("sha256").update(JSON.stringify(paths)).digest("hex");
}
export function verifyOwnerMaintenance(path, context = {threadId:process.env.BB_THREAD_ID,threadStorage:process.env.BB_THREAD_STORAGE,verifierPath:fileURLToPath(import.meta.url)}) {
  if (!isAbsolute(path) || !context.threadId || !context.threadStorage) throw new Error("Owner maintenance needs an absolute root-owned authorization receipt");
  const canonical = realpathSync(path);
  const storage = realpathSync(context.threadStorage);
  const verifier = realpathSync(context.verifierPath);
  const workspace = realpathSync(context.workspace ?? JSON.parse(execFileSync("bb", ["thread","show",context.threadId,"--json"], {encoding:"utf8",maxBuffer:1024*1024})).environment.path);
  const authorization = JSON.parse(readFileSync(canonical,"utf8"));
  const verified = basename(storage) === context.threadId && canonical.startsWith(storage + sep) && !verifier.startsWith(workspace + sep) &&
    authorization.kind === "owner_authorized_automation_maintenance" && authorization.root_thread_id === context.threadId &&
    typeof authorization.owner_request === "string" && authorization.owner_request.trim().length > 0 &&
    authorization.verifier_sha256 === createHash("sha256").update(readFileSync(verifier)).digest("hex");
  return {authorization,verified};
}
export function evaluate(snapshot, evidence, expectedHead, now = Date.now()) {
  const errors = [];
  const pr = snapshot.pr;
  if (!shaPattern.test(expectedHead) || pr.headRefOid !== expectedHead) errors.push("PR head changed or expected SHA is invalid");
  if (pr.state !== "OPEN" || pr.isDraft) errors.push("PR is closed or draft");
  if (pr.baseRefName !== "main" || pr.baseRefOid !== snapshot.currentMain) errors.push("PR base is not current main");
  if (snapshot.baseComparison?.status !== "ahead" && snapshot.baseComparison?.status !== "identical") errors.push("Candidate does not contain current main");
  if (pr.mergeable !== "MERGEABLE") errors.push("Mergeability is not confirmed");
  if (pr.reviewDecision === "CHANGES_REQUESTED") errors.push("Review requests changes");
  if (!Number.isFinite(Date.parse(snapshot.reviewNotBefore)) || evidence.review_not_before !== snapshot.reviewNotBefore || now < Date.parse(snapshot.reviewNotBefore)) errors.push("Dispatcher review wait is incomplete or its receipt is missing");
  for (const name of requiredChecks) {
    const check = snapshot.checks.find(c => c.name === name);
    if (!check || check.status !== "completed" || check.conclusion !== "success") errors.push(`Required check is not green: ${name}`);
  }
  for (const check of snapshot.checks) {
    if (check.status !== "completed" || (check.conclusion !== "success" && !(check.conclusion === "skipped" && conditionalSkips.has(check.name)))) errors.push(`Observed check is not green: ${check.name}`);
  }
  for (const status of snapshot.statuses) if (status.state !== "success") errors.push(`Status is not green: ${status.context}`);
  const coderabbit = snapshot.statuses.find(c => c.context === "CodeRabbit");
  const review = snapshot.reviews.find(r => r.commit?.oid === expectedHead && /coderabbit/i.test(r.author?.login ?? "") && r.state === "APPROVED");
  const completedStatus = coderabbit?.state === "success" && ["review completed", "review completed successfully"].includes((coderabbit.description ?? "").trim().toLowerCase());
  const fallback = snapshot.independentReviewVerified && snapshot.independentReview?.head_sha === expectedHead && snapshot.independentReview?.base_sha === snapshot.currentMain && snapshot.independentReview?.review_inventory_sha256 === reviewInventoryHash(snapshot);
  if (!review && !completedStatus && !fallback) errors.push("No completed configured or verified independent AI review for this exact head");
  if (snapshot.threads.some(t => !t.isResolved)) errors.push("Unresolved review threads remain");
  const latestReviews = new Map();
  for (const r of snapshot.reviews) if (["APPROVED", "CHANGES_REQUESTED", "DISMISSED"].includes(r.state)) latestReviews.set(r.author?.login, r);
  if ([...latestReviews.values()].some(r => r.state === "CHANGES_REQUESTED")) errors.push("A reviewer still requests changes");
  if (evidence.head_sha !== expectedHead || evidence.base_sha !== snapshot.currentMain) errors.push("Evidence is stale for head or base");
  const maintenance = evidence.change_kind === "automation_maintenance";
  const nonRuntime = evidence.change_kind === "non_runtime" || maintenance;
  for (const key of ["semantic_review", "lint", "tests", "api_signatures", "fastapi_e2e", "all_review_comments_read", "all_findings_addressed"]) {
    if (evidence[key] !== "passed") errors.push(`Evidence missing: ${key}`);
  }
  if (nonRuntime) {
    if (!nonRuntimeScope(snapshot.baseComparison?.files, maintenance)) errors.push("Non-runtime diff contains ineligible paths or is incomplete");
    if (evidence.example_validation !== "passed" || evidence.measurement_review !== "not_applicable") errors.push("Runnable example validation or non-runtime review is missing");
    if (maintenance) {
      const approval = snapshot.ownerMaintenanceAuthorization;
      if (!snapshot.ownerMaintenanceVerified || approval?.head_sha !== expectedHead || approval?.base_sha !== snapshot.currentMain ||
          !nonRuntimeScope(snapshot.baseComparison?.files, true) || approval?.changed_paths_sha256 !== changedPathsHash(snapshot.baseComparison.files) ||
          !fallback || snapshot.independentReview?.automation_maintenance_review !== "passed" ||
          snapshot.independentReview?.acceptance_verifier_sha256 !== approval?.verifier_sha256)
        errors.push("Explicit owner authorization, pinned verifier or independent control review is missing");
    }
  } else {
    if (evidence.measurement_review !== "passed") errors.push("Evidence missing: measurement_review");
    if (evidence.measurement?.outcome !== "accepted" || evidence.measurement?.candidate_sha !== expectedHead || evidence.measurement?.base_sha !== snapshot.currentMain || !/^https:\/\/github.com\/maksimzayats\/diwire\/actions\/runs\/\d+$/.test(evidence.measurement?.run_url ?? "")) errors.push("Accepted exact-head Linux comparison receipt is missing");
    if (snapshot.measurementRun?.headSha !== expectedHead || snapshot.measurementRun?.status !== "completed" || snapshot.measurementRun?.conclusion !== "success") errors.push("Remote measurement run is not green for this exact head");
    if (snapshot.measurementRun?.workflowPath !== ".github/workflows/bb-performance.yaml" || snapshot.measurementRun?.event !== "workflow_dispatch") errors.push("Measurement receipt is not the performance workflow");
    const decision = snapshot.measurementDecision;
    if (!snapshot.measurementArtifactsVerified || decision?.status !== "accepted" || decision?.identical_source !== false || decision?.base_sha !== snapshot.currentMain || decision?.candidate_sha !== expectedHead || !/^[0-9a-f]{64}$/.test(evidence.measurement?.protocol_sha256 ?? "") || decision?.protocol_sha256 !== evidence.measurement?.protocol_sha256) errors.push("Remote performance decision or artifact hashes are not accepted for these inputs");
  }
  if (evidence.fastapi_e2e_head !== expectedHead || !evidence.evidence_directory) errors.push("Final exact-head E2E receipt is missing");
  if (!Array.isArray(evidence.reviewed_comment_ids) || !Array.isArray(evidence.reviewed_review_ids)) errors.push("Review-read inventory is missing");
  if (evidence.review_inventory_sha256 !== reviewInventoryHash(snapshot)) errors.push("Review content changed or its read receipt is missing");
  const commentIds = new Set(evidence.reviewed_comment_ids ?? []);
  const reviewIds = new Set(evidence.reviewed_review_ids ?? []);
  for (const item of snapshot.comments) if (!commentIds.has(item.id)) errors.push(`Comment was not included in review receipt: ${item.id}`);
  for (const item of snapshot.reviews) if (!reviewIds.has(item.id)) errors.push(`Review was not included in review receipt: ${item.id}`);
  for (const thread of snapshot.threads) for (const item of thread.comments) if (!commentIds.has(item.id)) errors.push(`Inline comment was not included in review receipt: ${item.id}`);
  return { ready: errors.length === 0, errors, head_sha: expectedHead, base_sha: snapshot.currentMain };
}
const gh = args => JSON.parse(execFileSync("gh", args, {encoding: "utf8", maxBuffer: 32 * 1024 * 1024}));
function pages(query, select, request = gh) {
  let cursor = null;
  const items = [];
  do {
    const value = request(["api", "graphql", "-f", `query=${query}`, ...(cursor ? ["-F", `cursor=${cursor}`] : [])]);
    const connection = select(value);
    items.push(...connection.nodes);
    cursor = connection.pageInfo.hasNextPage ? connection.pageInfo.endCursor : null;
    if (items.length > 10000) throw new Error("Review inventory exceeds limit; inspect manually");
  } while (cursor);
  return items;
}
export function readSnapshot(repo, number, expectedHead, measurementUrl, reviewNotBefore, request = gh, independentReviewPath, ownerAuthorizationPath) {
  if (repo !== "maksimzayats/diwire" || !Number.isSafeInteger(number) || number <= 0 || !shaPattern.test(expectedHead)) throw new Error("Invalid repository, PR or head");
  const pr = request(["pr", "view", String(number), "--repo", repo, "--json", "state,isDraft,headRefOid,baseRefOid,baseRefName,mergeable,reviewDecision"]);
  const currentMain = request(["api", `repos/${repo}/commits/main`]).sha;
  const baseComparison = request(["api", `repos/${repo}/compare/${currentMain}...${expectedHead}`]);
  const queryFor = (field, fields) => `query($cursor:String){repository(owner:"maksimzayats",name:"diwire"){pullRequest(number:${number}){${field}(first:100,after:$cursor){nodes{${fields}}pageInfo{hasNextPage endCursor}}}}}`;
  const comments = pages(queryFor("comments", "id body author{login} updatedAt"), d => d.data.repository.pullRequest.comments, request);
  const reviews = pages(queryFor("reviews", "id body state submittedAt author{login} commit{oid}"), d => d.data.repository.pullRequest.reviews, request);
  const threads = pages(queryFor("reviewThreads", "id isResolved comments(first:100){nodes{id body author{login} updatedAt}pageInfo{hasNextPage endCursor}}"), d => d.data.repository.pullRequest.reviewThreads, request);
  for (const t of threads) {
    if (t.comments.pageInfo.hasNextPage) {
      const query = `query($cursor:String){node(id:${JSON.stringify(t.id)}){...on PullRequestReviewThread{comments(first:100,after:$cursor){nodes{id body author{login} updatedAt}pageInfo{hasNextPage endCursor}}}}}`;
      t.comments = pages(query, d => d.data.node.comments, request);
    } else t.comments = t.comments.nodes;
  }
  const checkPages = request(["api", `repos/${repo}/commits/${expectedHead}/check-runs?per_page=100&filter=latest`, "--paginate", "--slurp"]);
  const checks = checkPages.flatMap(x => x.check_runs);
  const statusPages = request(["api", `repos/${repo}/commits/${expectedHead}/statuses?per_page=100`, "--paginate", "--slurp"]);
  const byContext = new Map();
  for (const s of statusPages.flat()) if (!byContext.has(s.context)) byContext.set(s.context, s);
  const statuses = [...byContext.values()];
  // Keep observed event times for audit. The review clock comes from the
  // dispatcher and does not move when a status or check completes.
  const headPushedAt = [...checks.map(x => x.started_at), ...statuses.map(x => x.created_at)].filter(Boolean).sort().at(-1);
  const match = /^https:\/\/github.com\/maksimzayats\/diwire\/actions\/runs\/(\d+)$/.exec(measurementUrl ?? "");
  const run = match ? gh(["api", `repos/${repo}/actions/runs/${match[1]}`]) : null;
  const measurementRun = run ? {headSha: run.head_sha, status: run.status, conclusion: run.conclusion, workflowPath: run.path, event: run.event, url: run.html_url} : null;
  let measurementDecision = null;
  let measurementArtifactsVerified = false;
  if (run?.conclusion === "success" && run.path === ".github/workflows/bb-performance.yaml" && run.head_sha === expectedHead) {
    const temp = mkdtempSync(join(tmpdir(), "diwire-merge-proof-"));
    try {
      execFileSync("gh", ["run", "download", String(run.id), "--repo", repo, "--name", `bb-performance-${run.id}-${run.run_attempt}`, "--dir", temp], {encoding: "utf8", maxBuffer: 1024 * 1024});
      const directory = join(temp, "comparison");
      measurementDecision = JSON.parse(readFileSync(join(directory, "decision.json"), "utf8"));
      const hashes = measurementDecision.evidence_sha256;
      if (!hashes || Object.keys(hashes).length === 0) throw new Error("Performance artifact hash inventory is missing");
      for (const [path, hash] of Object.entries(hashes)) {
        const file = resolve(directory, path);
        if (!file.startsWith(directory + sep) || createHash("sha256").update(readFileSync(file)).digest("hex") !== hash) throw new Error("Performance artifact hash mismatch: " + path);
      }
      measurementArtifactsVerified = true;
    } finally { rmSync(temp, {recursive: true, force: true}); }
  }
  const independent = independentReviewPath ? verifyIndependentReview(independentReviewPath) : {report:null,verified:false};
  const independentReview = independent.report;
  const independentReviewVerified = independent.verified;
  const owner = ownerAuthorizationPath ? verifyOwnerMaintenance(ownerAuthorizationPath) : {authorization:null,verified:false};
  return {ownerMaintenanceAuthorization:owner.authorization,ownerMaintenanceVerified:owner.verified,pr, currentMain, baseComparison, comments, reviews, threads, checks, statuses, headPushedAt, reviewNotBefore, measurementRun, measurementDecision, measurementArtifactsVerified, independentReview, independentReviewVerified};
}
export function verifyIndependentReview(path, request = args => JSON.parse(execFileSync("bb", args, {encoding:"utf8",maxBuffer:1024*1024})), context = {threadId:process.env.BB_THREAD_ID,threadStorage:process.env.BB_THREAD_STORAGE}) {
  if (!isAbsolute(path) || !context.threadId || !context.threadStorage) throw new Error("Independent verification requires an absolute report and BB thread context");
  const callerRoot = realpathSync(context.threadStorage);
  if (basename(callerRoot) !== context.threadId) throw new Error("Caller storage does not match its BB thread");
  const base = dirname(callerRoot);
  const report = JSON.parse(readFileSync(path,"utf8"));
  const id = report.reviewer_thread_id;
  if (!/^thr_[a-z0-9]+$/.test(id ?? "") || id === context.threadId) throw new Error("A separate BB reviewer thread is required");
  const expectedRoot = join(base,id);
  const canonicalRoot = realpathSync(expectedRoot);
  const canonicalReport = realpathSync(path);
  if (dirname(canonicalRoot) !== base || basename(canonicalRoot) !== id || !canonicalReport.startsWith(canonicalRoot + sep)) throw new Error("Report is outside canonical reviewer storage");
  const info = request(["thread","show",id,"--json"]);
  const catalog = request(["thread","list","--project","proj_hypmgayr8j","--json"]);
  const row = Array.isArray(catalog) ? catalog.find(x => x.id === id) : null;
  const noActivity = row && row.activity && Object.values(row.activity).every(x => !x);
  const verified = info.thread.projectId === "proj_hypmgayr8j" && info.thread.status === "idle" && !!info.thread.providerId && !info.thread.activeBackgroundAgentCount && !info.thread.queuedMessageCount && noActivity && report.verdict === "passed" && Array.isArray(report.blocking_findings) && report.blocking_findings.length === 0;
  return {report,verified:!!verified};
}
export function main(argv) {
  const values = new Map();
  for (let i = 0; i < argv.length; i += 2) {
    if (argv[i] === "--merge") { values.set("--merge", true); i -= 1; continue; }
    if (!argv[i]?.startsWith("--") || !argv[i + 1]) throw new Error("Use --repo, --pr, --head, --evidence, --output and optional --merge");
    values.set(argv[i], argv[i + 1]);
  }
  const evidence = JSON.parse(readFileSync(values.get("--evidence"), "utf8"));
  const snapshot = readSnapshot(values.get("--repo"), Number(values.get("--pr")), values.get("--head"), evidence.measurement?.run_url, values.get("--review-not-before"), undefined, evidence.independent_ai_review_path, evidence.owner_authorization_path);
  const verdict = evaluate(snapshot, evidence, values.get("--head"));
  const output = values.get("--output");
  if (!output) throw new Error("An output receipt path is required");
  writeFileSync(output, JSON.stringify({checked_at: new Date().toISOString(), verdict, review_inventory_sha256: reviewInventoryHash(snapshot), snapshot}, null, 2) + "\n", {flag: "wx"});
  if (!verdict.ready) { process.stdout.write(JSON.stringify(verdict) + "\n"); return 1; }
  if (values.get("--merge")) {
    // Re-read after the inventory/evidence checks. The SHA fence below also
    // prevents a push racing the merge from changing the accepted head.
    const final = readSnapshot(values.get("--repo"), Number(values.get("--pr")), values.get("--head"), evidence.measurement?.run_url, values.get("--review-not-before"), undefined, evidence.independent_ai_review_path, evidence.owner_authorization_path);
    const gate = evaluate(final, evidence, values.get("--head"));
    if (!gate.ready) throw new Error("Merge conditions changed: " + gate.errors.join("; "));
    execFileSync("gh", ["pr", "merge", values.get("--pr"), "--repo", values.get("--repo"), "--squash", "--match-head-commit", values.get("--head")], {stdio: "inherit"});
  }
  process.stdout.write(JSON.stringify(verdict) + "\n");
  return 0;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { process.exitCode = main(process.argv.slice(2)); }
  catch (error) { process.stderr.write(String(error) + "\n"); process.exitCode = 2; }
}
