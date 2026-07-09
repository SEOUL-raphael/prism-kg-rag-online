import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { createClient } from "@supabase/supabase-js";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BookOpen,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  FileText,
  GitBranch,
  Layers,
  Loader2,
  LockKeyhole,
  LogOut,
  Network,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Workflow
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY || "";
const ONLINE_MODE = Boolean(SUPABASE_URL && SUPABASE_KEY);
const supabase = ONLINE_MODE ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;

async function localApi(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function normalizeRpcPayload(payload) {
  if (Array.isArray(payload) && payload.length === 1 && payload[0] && typeof payload[0] === "object") return payload[0];
  return payload || {};
}

async function loadOnlineDashboard() {
  const [kg, projects, operations] = await Promise.all([
    supabase.rpc("kg_summary"),
    supabase.rpc("project_summary"),
    supabase.rpc("operations_status")
  ]);
  for (const result of [kg, projects, operations]) {
    if (result.error) throw result.error;
  }
  const kgSummary = normalizeRpcPayload(kg.data);
  const projectSummary = normalizeRpcPayload(projects.data);
  const ops = normalizeRpcPayload(operations.data);
  return {
    status: {
      projects: ops.projects,
      files: ops.files,
      downloaded_files: ops.downloaded_files,
      converted_files: ops.converted_files,
      downloaded_waiting_conversion: ops.downloaded_waiting_conversion,
      convert_failed_files: ops.convert_failed_files,
      metadata_only_files: ops.metadata_only_files,
      prism_chunks: ops.chunks,
      kg_nodes: ops.kg_nodes,
      kg_edges: ops.kg_edges,
      api_calls_today: 0,
      conversion_rate: ops.conversion_rate,
      minimax: { configured: true },
      environment: { SUPABASE_URL: true, GITHUB_TOKEN: false }
    },
    kgSummary,
    projectSummary,
    operations: ops,
    failures: []
  };
}

async function loadLocalDashboard() {
  const [status, kgSummary, projectSummary, operations, failures] = await Promise.all([
    localApi("/api/status"),
    localApi("/api/analytics/kg-summary"),
    localApi("/api/analytics/project-summary"),
    localApi("/api/operations/status"),
    localApi("/api/failures?limit=20")
  ]);
  return { status, kgSummary, projectSummary, operations, failures };
}

function parseSseBlock(block) {
  const lines = block.split(/\r?\n/);
  let event = "message";
  const data = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return null;
  return { event, payload: JSON.parse(data.join("\n")) };
}

async function consumeSseResponse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\n\n/);
    buffer = parts.pop() || "";
    for (const part of parts) {
      const parsed = parseSseBlock(part.trim());
      if (parsed) onEvent(parsed.event, parsed.payload);
    }
  }
}

async function streamRag(payload, session, onEvent) {
  if (ONLINE_MODE) {
    const response = await fetch(`${SUPABASE_URL}/functions/v1/rag-query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "apikey": SUPABASE_KEY,
        "Authorization": `Bearer ${session?.access_token || ""}`
      },
      body: JSON.stringify({ ...payload, stream: true })
    });
    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({ error: response.statusText }));
      throw new Error(error.error || response.statusText);
    }
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("text/event-stream")) {
      await consumeSseResponse(response, onEvent);
      return;
    }
    const data = await response.json();
    onEvent("done", data);
    return;
  }

  const response = await fetch(`${API_BASE}/api/rag/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || response.statusText);
  }
  await consumeSseResponse(response, onEvent);
}

function App() {
  const [active, setActive] = useState("dashboard");
  const [session, setSession] = useState(null);
  const [authReady, setAuthReady] = useState(!ONLINE_MODE);
  const [state, setState] = useState({
    status: null,
    kgSummary: null,
    projectSummary: null,
    operations: null,
    failures: []
  });

  useEffect(() => {
    if (!ONLINE_MODE) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session || null);
      setAuthReady(true);
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession || null);
      setAuthReady(true);
    });
    return () => listener.subscription.unsubscribe();
  }, []);

  async function refreshAll() {
    const next = ONLINE_MODE ? await loadOnlineDashboard() : await loadLocalDashboard();
    setState(next);
  }

  useEffect(() => {
    if (!authReady) return;
    if (ONLINE_MODE && !session) return;
    refreshAll().catch(() => {});
  }, [authReady, session]);

  if (ONLINE_MODE && !authReady) {
    return <LoadingScreen />;
  }
  if (ONLINE_MODE && !session) {
    return <AuthGate />;
  }

  const tabs = [
    ["dashboard", "Dashboard", Database],
    ["projects", "Projects", Boxes],
    ["operations", "Operations", Activity],
    ["guide", "Pipeline Guide", BookOpen]
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><Network size={18} /></span>
          <div>
            <strong>PRISM KG-RAG</strong>
            <small>{ONLINE_MODE ? "Supabase Online" : "Local SQLite"}</small>
          </div>
        </div>
        <nav className="nav-tabs">
          {tabs.map(([id, label, Icon]) => (
            <button key={id} className={active === id ? "active" : ""} onClick={() => setActive(id)} title={label}>
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <RuntimePanel status={state.status} session={session} />
      </aside>
      <main className="content">
        <TopBar session={session} onRefresh={refreshAll} />
        {active === "dashboard" && <Dashboard {...state} session={session} onRefresh={refreshAll} />}
        {active === "projects" && <Projects />}
        {active === "operations" && <Operations operations={state.operations} failures={state.failures} onRefresh={refreshAll} />}
        {active === "guide" && <PipelineGuide />}
      </main>
    </div>
  );
}

function LoadingScreen() {
  return (
    <main className="auth-page">
      <Loader2 className="spin" size={24} />
    </main>
  );
}

function AuthGate() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function signIn(event) {
    event.preventDefault();
    setError("");
    const { error: authError } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.href }
    });
    if (authError) setError(authError.message);
    else setSent(true);
  }

  return (
    <main className="auth-page">
      <section className="auth-panel">
        <LockKeyhole size={28} />
        <h1>PRISM KG-RAG</h1>
        <p>이메일로 로그인 링크를 받아 접속합니다.</p>
        <form onSubmit={signIn} className="auth-form">
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="email@example.go.kr" required />
          <button className="icon-button labeled primary" disabled={!email}>
            <ShieldCheck size={17} />
            <span>Send Link</span>
          </button>
        </form>
        {sent && <p className="success-line">로그인 링크를 보냈습니다. 메일함을 확인하세요.</p>}
        {error && <p className="error-line">{error}</p>}
      </section>
    </main>
  );
}

function TopBar({ session, onRefresh }) {
  return (
    <header className="topbar">
      <div>
        <h1>PRISM 2025+ 연구자료 통합 대시보드</h1>
        <p>KG 분석, 변환 진행률, MiniMax 근거 질의를 한 화면에서 확인합니다.</p>
      </div>
      <div className="top-actions">
        {ONLINE_MODE && session?.user?.email && <span className="session-email">{session.user.email}</span>}
        <button className="icon-button labeled" onClick={() => onRefresh().catch(() => {})} title="상태 새로고침">
          <RefreshCw size={17} />
          <span>Refresh</span>
        </button>
        {ONLINE_MODE && (
          <button className="icon-button" onClick={() => supabase.auth.signOut()} title="로그아웃">
            <LogOut size={17} />
          </button>
        )}
      </div>
    </header>
  );
}

function RuntimePanel({ status, session }) {
  const minimax = status?.minimax || {};
  const env = status?.environment || {};
  return (
    <section className="runtime">
      <div className="runtime-row">
        {minimax.configured || ONLINE_MODE ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
        <span>MiniMax</span>
        <b>{minimax.configured || ONLINE_MODE ? "ready" : "fallback"}</b>
      </div>
      <div className="runtime-row">
        <ShieldCheck size={16} />
        <span>Supabase</span>
        <b>{ONLINE_MODE ? "online" : env.SUPABASE_URL ? "url set" : "local"}</b>
      </div>
      <div className="runtime-row">
        <GitBranch size={16} />
        <span>Access</span>
        <b>{ONLINE_MODE ? session?.user?.role || "auth" : "local"}</b>
      </div>
    </section>
  );
}

function Dashboard({ status, kgSummary, projectSummary, operations, session, onRefresh }) {
  const conversionRate = status?.conversion_rate || 0;
  return (
    <section className="page-block dashboard-page">
      <DashboardQuery session={session} onRefresh={onRefresh} />
      <div className="metric-grid">
        <Metric icon={Database} label="과제" value={status?.projects} />
        <Metric icon={FileText} label="변환 문서" value={status?.converted_files} />
        <Metric icon={Layers} label="Chunk" value={status?.prism_chunks} />
        <Metric icon={Workflow} label="KG 노드" value={status?.kg_nodes} />
        <Metric icon={Network} label="KG 관계" value={status?.kg_edges} />
        <Metric icon={Server} label="오늘 API" value={status?.api_calls_today} />
      </div>
      <div className="dashboard-grid">
        <section className="flat-panel">
          <PanelTitle icon={Workflow} title="KG 분석 현황" />
          <BarList rows={kgSummary?.node_kinds || []} valueKey="value" labelKey="label" />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Network} title="관계 유형" />
          <BarList rows={kgSummary?.edge_kinds || []} valueKey="value" labelKey="label" />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={BarChart3} title="기관별 과제" />
          <BarList rows={projectSummary?.top_orgs || []} valueKey="value" labelKey="label" />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Boxes} title="연구분야 분포" />
          <BarList rows={projectSummary?.top_fields || []} valueKey="value" labelKey="label" />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Activity} title="변환 진행" />
          <div className="progress-layout">
            <Donut value={conversionRate} label={`${conversionRate}%`} />
            <div className="progress-facts">
              <Fact label="변환 완료" value={operations?.converted_files} />
              <Fact label="변환 대기" value={operations?.downloaded_waiting_conversion} />
              <Fact label="변환 실패" value={operations?.convert_failed_files} />
              <Fact label="메타만 보관" value={operations?.metadata_only_files} />
            </div>
          </div>
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Clock} title="중심 노드" />
          <CompactNodes rows={kgSummary?.top_connected_nodes || []} />
        </section>
      </div>
    </section>
  );
}

function DashboardQuery({ session, onRefresh }) {
  const [question, setQuestion] = useState("지역경제 관련 정책연구의 핵심 근거를 요약해줘");
  const [limit, setLimit] = useState(6);
  const [useLlm, setUseLlm] = useState(true);
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState([]);
  const [plan, setPlan] = useState(null);
  const [kgResults, setKgResults] = useState([]);
  const [evidence, setEvidence] = useState([]);
  const [answer, setAnswer] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [done, setDone] = useState(null);
  const [error, setError] = useState("");

  const stageMap = useMemo(() => {
    const map = {};
    for (const item of events) if (item.event === "stage") map[item.stage] = item;
    return map;
  }, [events]);

  function reset() {
    setEvents([]);
    setPlan(null);
    setKgResults([]);
    setEvidence([]);
    setAnswer("");
    setReasoning("");
    setDone(null);
    setError("");
  }

  async function run() {
    reset();
    setRunning(true);
    try {
      await streamRag({ question, limit, use_llm: useLlm }, session, (event, payload) => {
        if (event === "stage") setEvents((prev) => [...prev, payload]);
        if (event === "plan") setPlan(payload.plan);
        if (event === "kg_results") setKgResults(payload.kg_results || []);
        if (event === "hits") setEvidence(payload.evidence || []);
        if (event === "reasoning_delta") setReasoning((prev) => prev + (payload.text || ""));
        if (event === "answer_delta") setAnswer((prev) => prev + (payload.text || ""));
        if (event === "done") {
          setDone(payload);
          if (payload.answer) setAnswer((current) => current || payload.answer);
          if (payload.plan) setPlan(payload.plan);
          if (payload.kg_results) setKgResults(payload.kg_results);
          if (payload.evidence) setEvidence(payload.evidence);
          onRefresh().catch(() => {});
        }
        if (event === "error") setError(payload.message || "스트리밍 중 오류가 발생했습니다.");
      });
    } catch (exc) {
      setError(exc.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="query-console">
      <div className="section-head">
        <PanelTitle icon={BrainCircuit} title="MiniMax RAG 질의" />
        <div className="inline-controls">
          <label>
            <input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
            MiniMax
          </label>
          <label>
            Limit
            <input className="small-input" type="number" min="1" max="20" value={limit} onChange={(event) => setLimit(Number(event.target.value))} />
          </label>
          <button className="icon-button labeled primary" onClick={run} disabled={running || !question.trim()} title="실시간 질의 실행">
            {running ? <Loader2 className="spin" size={17} /> : <Play size={17} />}
            <span>Run</span>
          </button>
        </div>
      </div>
      <textarea className="question-box" value={question} onChange={(event) => setQuestion(event.target.value)} />
      {error && <div className="error-line">{error}</div>}
      <div className="query-result-grid">
        <section className="flat-panel">
          <PanelTitle icon={Activity} title="실시간 진행" />
          <StageTimeline stageMap={stageMap} />
          {plan && <div className="chips">{(plan.terms || []).map((term) => <span key={term}>{term}</span>)}</div>}
        </section>
        <section className="flat-panel answer-panel">
          <PanelTitle icon={BrainCircuit} title="MiniMax 추론/답변" />
          {reasoning && (
            <details className="reasoning-box" open={running}>
              <summary>제공된 reasoning stream</summary>
              <pre>{reasoning}</pre>
            </details>
          )}
          <div className="answer-text">{answer || (running ? "답변 생성 중..." : "질문을 실행하면 답변이 여기에 표시됩니다.")}</div>
          {done?.timings && <Timing timings={done.timings} />}
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Workflow} title="KG 후보" />
          <KgResults items={kgResults} />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={FileText} title="본문 근거" />
          <EvidenceList evidence={evidence} />
        </section>
      </div>
    </section>
  );
}

function StageTimeline({ stageMap }) {
  const stages = [
    ["plan", "KG 계획 생성"],
    ["kg", "KG 검증"],
    ["body", "본문 검색"],
    ["llm", "MiniMax 답변"]
  ];
  return (
    <div className="stage-timeline">
      {stages.map(([id, label]) => {
        const item = stageMap[id] || {};
        return (
          <div key={id} className={`stage ${item.status || "idle"}`}>
            <span>{item.status === "complete" ? <CheckCircle2 size={15} /> : item.status === "running" ? <Loader2 className="spin" size={15} /> : <Clock size={15} />}</span>
            <b>{label}</b>
            <small>{item.message || "대기"}</small>
          </div>
        );
      })}
    </div>
  );
}

function Operations({ operations, failures, onRefresh }) {
  return (
    <section className="page-block">
      <div className="section-head">
        <h2>Operations</h2>
        <button className="icon-button labeled" onClick={() => onRefresh().catch(() => {})} title="작업 상태 새로고침">
          <RefreshCw size={17} />
          <span>Refresh</span>
        </button>
      </div>
      <div className="operations-grid">
        <section className="flat-panel">
          <PanelTitle icon={Activity} title="다운로드 보고서 변환 현황" />
          <StatusBars status={operations} />
        </section>
        <section className="flat-panel">
          <PanelTitle icon={Server} title="API/실패 상태" />
          <div className="progress-facts">
            <Fact label="오늘 API 호출" value={operations?.api_calls_today} />
            <Fact label="API 실패 기록" value={operations?.api_failures} />
            <Fact label="변환 대기 파일" value={operations?.downloaded_waiting_conversion} />
          </div>
        </section>
        <section className="flat-panel wide">
          <PanelTitle icon={AlertTriangle} title="최근 실패 목록" />
          <FailureList failures={failures || operations?.recent_failures || []} />
        </section>
      </div>
    </section>
  );
}

function Projects() {
  const [queryText, setQueryText] = useState("");
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [markdown, setMarkdown] = useState(null);
  const [loading, setLoading] = useState(false);

  async function searchProjects(nextQuery = queryText) {
    setLoading(true);
    try {
      if (ONLINE_MODE) {
        let query = supabase
          .from("projects")
          .select("research_id,research_name,organ_name,research_start_date,issued_year,research_outline")
          .order("research_start_date", { ascending: false, nullsFirst: false })
          .limit(60);
        if (nextQuery) {
          const term = `%${nextQuery}%`;
          query = query.or(`research_name.ilike.${term},organ_name.ilike.${term},research_outline.ilike.${term}`);
        }
        const { data, error } = await query;
        if (error) throw error;
        setProjects(data || []);
        if (!selected && data?.[0]) await openProject(data[0].research_id);
        return;
      }
      const rows = await localApi(`/api/projects?q=${encodeURIComponent(nextQuery)}&limit=60`);
      setProjects(rows);
      if (!selected && rows[0]) await openProject(rows[0].research_id);
    } finally {
      setLoading(false);
    }
  }

  async function openProject(researchId) {
    setMarkdown(null);
    if (ONLINE_MODE) {
      const [project, reports, files] = await Promise.all([
        supabase.from("projects").select("*").eq("research_id", researchId).single(),
        supabase.from("reports").select("*").eq("research_id", researchId).order("id"),
        supabase.from("files").select("*").eq("research_id", researchId).order("file_name")
      ]);
      for (const result of [project, reports, files]) if (result.error) throw result.error;
      setSelected({ project: project.data, reports: reports.data || [], contract: null, files: files.data || [] });
      return;
    }
    setSelected(await localApi(`/api/projects/${encodeURIComponent(researchId)}`));
  }

  async function openMarkdown(fileId) {
    if (ONLINE_MODE) {
      const { data, error } = await supabase
        .from("chunks")
        .select("document_id,research_id,title,organ_name,file_id,file_name,text,chunk_index")
        .eq("file_id", fileId)
        .order("chunk_index")
        .limit(300);
      if (error) throw error;
      const first = data?.[0] || {};
      setMarkdown({
        file_id: fileId,
        title: first.title || first.file_name || fileId,
        organ_name: first.organ_name || "",
        research_id: first.research_id || "",
        text: (data || []).map((row) => row.text).join("\n\n")
      });
      return;
    }
    setMarkdown(await localApi(`/api/files/${encodeURIComponent(fileId)}/markdown`));
  }

  useEffect(() => {
    searchProjects("").catch(() => {});
  }, []);

  return (
    <section className="page-block">
      <div className="section-head">
        <h2>Projects</h2>
        <form className="search-form" onSubmit={(event) => { event.preventDefault(); searchProjects().catch(() => {}); }}>
          <input value={queryText} onChange={(event) => setQueryText(event.target.value)} placeholder="과제명, 기관, 개요 검색" />
          <button className="icon-button labeled" disabled={loading} title="검색">
            {loading ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
            <span>Search</span>
          </button>
        </form>
      </div>
      <div className="project-layout">
        <div className="project-list">
          {projects.map((item) => (
            <button key={item.research_id} onClick={() => openProject(item.research_id).catch(() => {})} className={selected?.project?.research_id === item.research_id ? "selected" : ""}>
              <strong>{item.research_name || item.research_id}</strong>
              <span>{item.organ_name} · {item.research_start_date || item.issued_year || "-"}</span>
            </button>
          ))}
        </div>
        <ProjectDetail selected={selected} markdown={markdown} onOpenMarkdown={openMarkdown} />
      </div>
    </section>
  );
}

function ProjectDetail({ selected, markdown, onOpenMarkdown }) {
  if (!selected?.project) return <div className="project-detail muted">과제를 선택하세요.</div>;
  const p = selected.project;
  return (
    <div className="project-detail">
      <h3>{p.research_name}</h3>
      <dl className="meta-grid">
        <dt>기관</dt><dd>{p.organ_name || "-"}</dd>
        <dt>부서</dt><dd>{p.charge_person_department || "-"}</dd>
        <dt>전화</dt><dd>{p.charge_person_phone_no || "-"}</dd>
        <dt>기간</dt><dd>{p.research_start_date || "-"} ~ {p.research_end_date || ""}</dd>
        <dt>분야</dt><dd>{p.brm_biz_name || p.biz_name || "-"}</dd>
      </dl>
      {p.research_outline && <p className="outline">{p.research_outline}</p>}
      <h4>보고서</h4>
      <SimpleRows rows={selected.reports || []} keys={["title", "keyword", "issued_year"]} />
      <h4>계약</h4>
      <SimpleRows rows={selected.contract ? [selected.contract] : []} keys={["research_organ_type_name", "researcher_name", "contract_date", "contract_type_name", "contract_cost"]} />
      <h4>파일 및 Markdown</h4>
      <div className="file-list">
        {(selected.files || []).map((file) => (
          <div className="file-row" key={file.id}>
            <span>{file.file_name || file.id}</span>
            <b>{file.status || "-"}</b>
            <button className="icon-button" disabled={ONLINE_MODE ? file.status !== "converted" : !file.document_id} onClick={() => onOpenMarkdown(file.id)} title="Markdown 열기">
              <FileText size={16} />
            </button>
          </div>
        ))}
      </div>
      {markdown && (
        <section className="markdown-inline">
          <div className="markdown-meta">
            <strong>{markdown.title || markdown.file_name || markdown.file_id}</strong>
            <span>{markdown.organ_name} · {markdown.research_id}</span>
          </div>
          <pre className="markdown-body">{markdown.text || markdown.message || "내용이 없습니다."}</pre>
        </section>
      )}
    </div>
  );
}

function PipelineGuide() {
  const [guide, setGuide] = useState(null);
  useEffect(() => {
    if (ONLINE_MODE) {
      setGuide({
        title: "PRISM KG-RAG 파이프라인",
        summary: "PRISM 정책연구 과제 메타데이터, KG, Markdown chunk를 Supabase에 공유하고 Edge Function에서 MiniMax 답변을 생성합니다.",
        sections: [
          { title: "1. 수집과 변환", body: "로컬에서 PRISM API와 공개 백엔드로 과제를 수집하고 PDF/HWP를 Markdown chunk로 변환합니다." },
          { title: "2. 온라인 공유", body: "원본 파일은 올리지 않고 Supabase에는 메타데이터, KG, chunk만 적재합니다." },
          { title: "3. 질의", body: "사용자는 로그인 후 Edge Function을 통해 KG 검색, 본문 검색, MiniMax 답변을 실행합니다." }
        ]
      });
      return;
    }
    localApi("/api/pipeline-guide").then(setGuide).catch(() => {});
  }, []);
  if (!guide) return <section className="page-block"><Loader2 className="spin" /></section>;
  return (
    <section className="page-block guide">
      <h2>{guide.title}</h2>
      <p className="guide-summary">{guide.summary}</p>
      <div className="guide-sections">
        {guide.sections.map((section) => (
          <section className="guide-section" key={section.title}>
            <h3>{section.title}</h3>
            <p>{section.body}</p>
          </section>
        ))}
      </div>
    </section>
  );
}

function Metric({ icon: Icon, label, value }) {
  return (
    <div className="metric">
      <Icon size={17} />
      <span>{label}</span>
      <strong>{formatNumber(value)}</strong>
    </div>
  );
}

function PanelTitle({ icon: Icon, title }) {
  return (
    <h3 className="panel-title">
      <Icon size={17} />
      <span>{title}</span>
    </h3>
  );
}

function BarList({ rows, labelKey, valueKey }) {
  if (!rows.length) return <p className="muted">표시할 데이터가 없습니다.</p>;
  const max = Math.max(...rows.map((row) => row[valueKey] || 0), 1);
  return (
    <div className="bar-list">
      {rows.map((row) => (
        <div className="bar-item" key={`${row[labelKey]}-${row[valueKey]}`}>
          <span>{row[labelKey]}</span>
          <div className="bar-track"><i style={{ width: `${Math.max(3, ((row[valueKey] || 0) / max) * 100)}%` }} /></div>
          <b>{formatNumber(row[valueKey])}</b>
        </div>
      ))}
    </div>
  );
}

function CompactNodes({ rows }) {
  if (!rows.length) return <p className="muted">표시할 노드가 없습니다.</p>;
  return (
    <div className="compact-list">
      {rows.map((item) => (
        <div key={item.id} className="compact-row">
          <b>{item.kind}</b>
          <span>{item.label}</span>
          <em>{formatNumber(item.degree)}</em>
        </div>
      ))}
    </div>
  );
}

function Donut({ value, label }) {
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className="donut" style={{ background: `conic-gradient(#1f7668 ${safe}%, #dce4e9 0)` }}>
      <span>{label}</span>
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <b>{formatNumber(value)}</b>
    </div>
  );
}

function StatusBars({ status }) {
  const files = Math.max(status?.files || 0, 1);
  const rows = [
    ["downloaded_files", "다운로드", "#1f7668"],
    ["converted_files", "Markdown", "#3867a8"],
    ["downloaded_waiting_conversion", "변환 대기", "#8f6b1f"],
    ["metadata_only_files", "메타만", "#9c6b23"],
    ["convert_failed_files", "변환 실패", "#b43c46"]
  ];
  return (
    <div className="bars">
      {rows.map(([key, label, color]) => {
        const value = status?.[key] || 0;
        return (
          <div className="bar-row" key={key}>
            <span>{label}</span>
            <div className="bar-track"><i style={{ width: `${Math.min(100, (value / files) * 100)}%`, background: color }} /></div>
            <b>{formatNumber(value)}</b>
          </div>
        );
      })}
    </div>
  );
}

function FailureList({ failures }) {
  if (!failures?.length) return <p className="muted">기록된 실패가 없습니다.</p>;
  return (
    <div className="list-table">
      {failures.map((item) => (
        <div className="table-row" key={item.id}>
          <b>{item.endpoint}</b>
          <span>{item.status}</span>
          <span>{item.message || item.error_code || "-"}</span>
          <time>{item.created_at}</time>
        </div>
      ))}
    </div>
  );
}

function KgResults({ items }) {
  if (!items.length) return <p className="muted">KG 후보가 없습니다.</p>;
  return (
    <div className="compact-list">
      {items.slice(0, 12).map((item) => (
        <div key={item.id} className="compact-row">
          <b>{item.kind}</b>
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function EvidenceList({ evidence }) {
  if (!evidence.length) return <p className="muted">본문 근거가 없습니다.</p>;
  return (
    <div className="evidence-list">
      {evidence.map((item) => (
        <article className="evidence-item" key={`${item.chunk_id}-${item.file_name}`}>
          <strong>{item.title || item.research_id}</strong>
          <p>{item.organ_name} · {item.research_id} · chunk {item.chunk_id}</p>
          <pre>{item.excerpt}</pre>
        </article>
      ))}
    </div>
  );
}

function Timing({ timings }) {
  return (
    <div className="timings">
      {Object.entries(timings).map(([key, value]) => <span key={key}>{key}: {value}ms</span>)}
    </div>
  );
}

function SimpleRows({ rows, keys }) {
  if (!rows.length) return <p className="muted">기록 없음</p>;
  return (
    <div className="simple-rows">
      {rows.map((row, index) => (
        <div key={row.id || row.research_id || index}>
          {keys.map((key) => row[key] ? <span key={key}>{row[key]}</span> : null)}
        </div>
      ))}
    </div>
  );
}

function formatNumber(value) {
  if (value === undefined || value === null) return "-";
  return Number(value).toLocaleString("ko-KR");
}

createRoot(document.getElementById("root")).render(<App />);
