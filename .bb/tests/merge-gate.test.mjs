import assert from "node:assert/strict";
import test from "node:test";
import { evaluate, reviewInventoryHash, readSnapshot, changedPathsHash, verifyOwnerMaintenance } from "../automation/merge-gate.mjs";
const head = "a".repeat(40);
const base = "b".repeat(40);
const now = Date.parse("2026-10-27T12:00:00Z");
const required = [
  ...["3.10", "3.11", "3.12", "3.13", "3.14", "3.14t", "3.15", "3.15t"].map(v => `Lint & Tests (Python ${v})`),
  ...["3.14", "3.15", "3.15t"].flatMap(version =>
    ["FastAPI", "aiohttp", "Celery", "Litestar", "Flask", "Typer"].map(framework =>
      `E2E ${framework} (Docker Compose, Python ${version})`)),
  "Docs Build", "Docs Build (Python 3.15)", "Docs Build (Python 3.15t)",
];
function fixture() {
  const snapshot = {
    pr: {headRefOid: head, baseRefOid: base, baseRefName: "main", state: "OPEN", isDraft: false, mergeable: "MERGEABLE", reviewDecision: ""},
    currentMain: base, baseComparison: {status: "ahead"}, headPushedAt: "2026-10-27T11:40:00Z", reviewNotBefore: "2026-10-27T11:50:00Z",
    checks: required.map(name => ({name, status: "completed", conclusion: "success"})),
    statuses: [{context: "CodeRabbit", state: "success"}],
    reviews: [{id: "review1", author: {login: "coderabbitai"}, commit: {oid: head}, state: "APPROVED"}],
    comments: [{id: "comment1"}], threads: [{isResolved: true, comments: [{id: "inline1"}]}],
    measurementRun: {headSha: head, status: "completed", conclusion: "success", workflowPath: ".github/workflows/bb-performance.yaml", event: "workflow_dispatch"},
    measurementArtifactsVerified: true,
    measurementDecision: {status: "accepted", identical_source: false, base_sha: base, candidate_sha: head, protocol_sha256: "d".repeat(64)},
  };
  const evidence = {review_not_before: "2026-10-27T11:50:00Z", head_sha: head, base_sha: base, measurement: {outcome: "accepted", candidate_sha: head, base_sha: base, run_url: "https://github.com/maksimzayats/diwire/actions/runs/123", protocol_sha256: "d".repeat(64)}, fastapi_e2e_head: head, evidence_directory: "/proof", reviewed_comment_ids: ["comment1", "inline1"], reviewed_review_ids: ["review1"]};
  for (const key of ["semantic_review", "measurement_review", "lint", "tests", "api_signatures", "fastapi_e2e", "all_review_comments_read", "all_findings_addressed"]) evidence[key] = "passed";
  evidence.review_inventory_sha256 = reviewInventoryHash(snapshot);
  return {snapshot, evidence};
}
test("complete exact-head evidence passes", () => {
  const {snapshot, evidence} = fixture();
  assert.deepEqual(evaluate(snapshot, evidence, head, now).errors, []);
});
for (const [name, mutate] of [
  ["new push", f => {f.snapshot.pr.headRefOid = "c".repeat(40);}],
  ["new main", f => {f.snapshot.currentMain = "c".repeat(40);}],
  ["unresolved thread", f => {f.snapshot.threads[0].isResolved = false;}],
  ["edited comment", f => {f.snapshot.comments[0].body = "new issue";}],
  ["new unread comment", f => {f.snapshot.comments.push({id: "new"});}],
  ["queued AI review", f => {f.snapshot.reviews = []; f.snapshot.statuses[0].state = "pending";}],
  ["missing CI", f => {f.snapshot.checks.pop();}],
  ["skipped E2E", f => {f.snapshot.checks[9].conclusion = "skipped";}],
  ["waiting period", f => {f.snapshot.reviewNotBefore = "2026-10-27T12:05:00Z"; f.evidence.review_not_before = f.snapshot.reviewNotBefore;}],
  ["stale measurement", f => {f.evidence.measurement.candidate_sha = base;}],
  ["ordinary CI used as measurement", f => {f.snapshot.measurementRun.workflowPath = ".github/workflows/ci.yaml";}],
  ["missing artifact proof", f => {f.snapshot.measurementArtifactsVerified = false;}],
  ["nonaccepted remote decision", f => {f.snapshot.measurementDecision.status = "inconclusive";}],
  ["different protocol", f => {f.snapshot.measurementDecision.protocol_sha256 = "e".repeat(64);} ],
  ["failed measurement run", f => {f.snapshot.measurementRun.conclusion = "failure";}],
  ["unresolved change request", f => {f.snapshot.reviews.push({id: "r2", author: {login: "human"}, state: "CHANGES_REQUESTED"});}],
]) test(`${name} prevents merge`, () => {
  const f = fixture(); mutate(f);
  assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
});
for (const name of required) {
  test(`missing ${name} prevents merge`, () => {
    const {snapshot, evidence} = fixture();
    snapshot.checks = snapshot.checks.filter(check => check.name !== name);
    assert.equal(evaluate(snapshot, evidence, head, now).ready, false);
  });
}
test("documented conditional skips are allowed", () => {
  const {snapshot, evidence} = fixture();
  snapshot.checks.push({name: "dependabot-auto-merge", status: "completed", conclusion: "skipped"});
  assert.equal(evaluate(snapshot, evidence, head, now).ready, true);
});

test("review comments are fully paged even in a resolved thread", () => {
  const connection = (nodes, more = false) => ({nodes, pageInfo: {hasNextPage: more, endCursor: more ? "next-page" : null}});
  const request = args => {
    if (args[0] === "pr") return fixture().snapshot.pr;
    if (args[1].endsWith("/commits/main")) return {sha: base};
    if (args[1].includes("/compare/")) return {status: "ahead"};
    if (args[1].includes("check-runs")) return [{check_runs: []}];
    if (args[1].includes("/statuses")) return [[]];
    const query = args.find(a => a.startsWith("query="));
    if (query.includes("node(id:")) {
      const second = args.includes("cursor=next-page");
      return {data: {node: {comments: connection(second ? [{id: "last"}] : Array.from({length:100}, (_,i) => ({id: String(i)})), !second)}}};
    }
    if (query.includes("reviewThreads(")) return {data: {repository: {pullRequest: {reviewThreads: connection([{id: "thread", isResolved: true, comments: connection([], true)}])}}}};
    const field = query.includes("reviews(") ? "reviews" : "comments";
    return {data: {repository: {pullRequest: {[field]: connection([])}}}};
  };
  const snapshot = readSnapshot("maksimzayats/diwire", 123, head, undefined, "2026-10-27T11:50:00Z", request);
  assert.equal(snapshot.threads[0].comments.length, 101);
  assert.equal(snapshot.threads[0].comments[100].id, "last");
});

test("a successful rate-limit status is not a completed AI review",()=>{
  const {snapshot,evidence}=fixture();
  snapshot.reviews=[];
  snapshot.statuses[0].description="Review rate limited";
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  assert.equal(evaluate(snapshot,evidence,head,now).ready,false);
});
test("a verified independent review can replace a rate-limited configured review",()=>{
  const {snapshot,evidence}=fixture();
  snapshot.reviews=[];
  snapshot.statuses[0].description="Review rate limited";
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  snapshot.independentReviewVerified=true;
  snapshot.independentReview={head_sha:head,base_sha:base,review_inventory_sha256:reviewInventoryHash(snapshot)};
  assert.equal(evaluate(snapshot,evidence,head,now).ready,true);
  snapshot.independentReview.head_sha=base;
  assert.equal(evaluate(snapshot,evidence,head,now).ready,false);
});
test("an explicit completed-review status is accepted",()=>{
  const {snapshot,evidence}=fixture();
  snapshot.reviews=[];
  snapshot.statuses[0].description="Review completed";
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  assert.equal(evaluate(snapshot,evidence,head,now).ready,true);
});
test("a successful status without review evidence cannot approve",()=>{
  const {snapshot,evidence}=fixture();
  snapshot.reviews=[];
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  assert.equal(evaluate(snapshot,evidence,head,now).ready,false);
});

test("a negated completion description cannot approve",()=>{
  const {snapshot,evidence}=fixture();snapshot.reviews=[];
  snapshot.statuses[0].description="Review could not be completed";
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  assert.equal(evaluate(snapshot,evidence,head,now).ready,false);
});

test("a reply-only review does not replace a rate-limited full review",()=>{
  const {snapshot,evidence}=fixture();
  snapshot.reviews[0].state="COMMENTED";
  snapshot.reviews[0].body="";
  snapshot.statuses[0].description="Review rate limited";
  evidence.review_inventory_sha256=reviewInventoryHash(snapshot);
  assert.equal(evaluate(snapshot,evidence,head,now).ready,false);
});

function exampleFixture() {
  const f = fixture();
  f.snapshot.baseComparison.files = [
    {filename: "examples/ex_04_scopes_and_cleanup/05_unit_of_work.py"},
    {filename: "docs/howto/patterns/unit-of-work.rst"},
    {filename: "tests/examples/test_examples_expected_output.py"},
  ];
  Object.assign(f.evidence, {change_kind: "non_runtime", example_validation: "passed", measurement_review: "not_applicable"});
  delete f.evidence.measurement;
  delete f.snapshot.measurementRun;
  delete f.snapshot.measurementDecision;
  delete f.snapshot.measurementArtifactsVerified;
  return f;
}
test("verified non-runtime example uses runnable evidence instead of speed claims", () => {
  const f = exampleFixture();
  assert.deepEqual(evaluate(f.snapshot, f.evidence, head, now).errors, []);
});
for (const path of ["src/diwire/__init__.py", "uv.lock", "pyproject.toml", ".github/workflows/ci.yaml", "tools/unknown.py", "tools/bb_perf_dispatch.py", ".bb/automation/merge-gate.mjs", ".bb/workflows/daily-perf.js"]) {
  test(`non-runtime declaration cannot hide ${path}`, () => {
    const f = exampleFixture();
    f.snapshot.baseComparison.files.push({filename: path});
    assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
  });
}
test("renaming runtime source into an example still requires measurement", () => {
  const f = exampleFixture();
  f.snapshot.baseComparison.files[0].previous_filename = "src/diwire/__init__.py";
  assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
});
for (const files of [undefined, [], Array.from({length:300}, () => ({filename: "docs/guide.rst"}))]) {
  test(`missing or truncated non-runtime scope cannot waive measurements (${files?.length})`, () => {
    const f = exampleFixture(); f.snapshot.baseComparison.files = files;
    assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
  });
}
test("non-runtime declaration still needs runnable example validation", () => {
  const f = exampleFixture(); delete f.evidence.example_validation;
  assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
});
test("non-runtime declaration keeps review, CI, base and E2E gates", () => {
  for (const mutate of [
    f => {f.snapshot.checks.pop();},
    f => {f.evidence.fastapi_e2e_head = base;},
    f => {f.snapshot.threads[0].isResolved = false;},
    f => {f.snapshot.currentMain = "c".repeat(40);},
  ]) {
    const f = exampleFixture(); mutate(f);
    assert.equal(evaluate(f.snapshot, f.evidence, head, now).ready, false);
  }
});

function maintenanceFixture() {
  const f=exampleFixture();
  f.evidence.change_kind="automation_maintenance";
  f.snapshot.baseComparison.files.push({filename:".bb/automation/merge-gate.mjs"},{filename:"tools/bb_perf_dispatch.py"});
  f.snapshot.ownerMaintenanceVerified=true;
  f.snapshot.ownerMaintenanceAuthorization={head_sha:head,base_sha:base,changed_paths_sha256:changedPathsHash(f.snapshot.baseComparison.files),verifier_sha256:"e".repeat(64)};
  f.snapshot.independentReviewVerified=true;
  f.snapshot.independentReview={head_sha:head,base_sha:base,review_inventory_sha256:reviewInventoryHash(f.snapshot),automation_maintenance_review:"passed",acceptance_verifier_sha256:"e".repeat(64)};
  return f;
}
test("an explicit pinned owner update keeps the common gates",()=>{
  const f=maintenanceFixture();
  assert.deepEqual(evaluate(f.snapshot,f.evidence,head,now).errors,[]);
});
for(const [name,mutate] of [
  ["no owner verification",f=>{f.snapshot.ownerMaintenanceVerified=false;}],
  ["stale authorized head",f=>{f.snapshot.ownerMaintenanceAuthorization.head_sha=base;}],
  ["stale authorized base",f=>{f.snapshot.ownerMaintenanceAuthorization.base_sha=head;}],
  ["changed file inventory",f=>{f.snapshot.ownerMaintenanceAuthorization.changed_paths_sha256="0".repeat(64);}],
  ["unreviewed verifier",f=>{f.snapshot.independentReview.acceptance_verifier_sha256="0".repeat(64);}],
  ["missing independent control review",f=>{delete f.snapshot.independentReview.automation_maintenance_review;}],
  ["stale independent review",f=>{f.snapshot.independentReview.head_sha=base;}],
  ["runtime edit",f=>{f.snapshot.baseComparison.files.push({filename:"src/diwire/__init__.py"});}],
  ["failed normal CI",f=>{f.snapshot.checks[0].conclusion="failure";}],
]) test(`owner maintenance rejects ${name}`,()=>{
  const f=maintenanceFixture();mutate(f);assert.equal(evaluate(f.snapshot,f.evidence,head,now).ready,false);
});
