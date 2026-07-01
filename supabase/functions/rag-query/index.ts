import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, accept",
  "Access-Control-Allow-Methods": "POST, OPTIONS"
};

const MINIMAX_URL = Deno.env.get("MINIMAX_API_URL") || "https://api.minimaxi.chat/v1/chat/completions";
const MINIMAX_MODEL = Deno.env.get("MINIMAX_MODEL") || "MiniMax-Text-01";

serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (req.method !== "POST") return jsonResponse({ error: "method not allowed" }, 405);

  try {
    const authHeader = req.headers.get("Authorization") || "";
    if (!authHeader.startsWith("Bearer ")) return jsonResponse({ error: "authorization required" }, 401);

    const supabaseUrl = requireEnv("SUPABASE_URL");
    const publishableKey = Deno.env.get("SUPABASE_PUBLISHABLE_KEY") || Deno.env.get("SUPABASE_ANON_KEY") || "";
    if (!publishableKey) throw new Error("SUPABASE_PUBLISHABLE_KEY is not configured");

    const supabase = createClient(supabaseUrl, publishableKey, {
      global: { headers: { Authorization: authHeader } }
    });
    const { data: userData, error: userError } = await supabase.auth.getUser();
    if (userError || !userData.user) return jsonResponse({ error: "invalid user token" }, 401);

    const body = await req.json();
    const question = String(body.question || "").trim();
    const limit = clamp(Number(body.limit || 8), 1, 20);
    const useLlm = body.use_llm !== false;
    if (!question) return jsonResponse({ error: "question is required" }, 400);

    const wantsStream = body.stream !== false || (req.headers.get("Accept") || "").includes("text/event-stream");
    if (!wantsStream) {
      const result = await runRag(supabase, question, limit, useLlm);
      await logQuery(supabase, userData.user.id, question, result.answer, result.evidence.length);
      return jsonResponse(result);
    }

    const stream = new ReadableStream({
      async start(controller) {
        const writer = (event: string, payload: Record<string, unknown>) => {
          controller.enqueue(encodeSse(event, payload));
        };
        try {
          const result = await runRagStream(supabase, question, limit, useLlm, writer);
          await logQuery(supabase, userData.user.id, question, result.answer, result.evidence.length);
          writer("done", result);
        } catch (error) {
          writer("error", { event: "error", message: error instanceof Error ? error.message : String(error) });
        } finally {
          controller.close();
        }
      }
    });

    return new Response(stream, {
      headers: {
        ...corsHeaders,
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive"
      }
    });
  } catch (error) {
    return jsonResponse({ error: error instanceof Error ? error.message : String(error) }, 500);
  }
});

async function runRag(supabase: ReturnType<typeof createClient>, question: string, limit: number, useLlm: boolean) {
  const started = performance.now();
  const terms = tokenize(question);
  const { kgResults, researchIds } = await kgStep(supabase, terms);
  const hits = await chunkStep(supabase, question, limit, researchIds);
  const evidence = evidenceFromHits(hits);
  const errors: Array<Record<string, string>> = [];
  let answer = "";
  if (useLlm) {
    try {
      answer = await minimaxAnswer(question, kgResults, hits);
    } catch (error) {
      errors.push({ stage: "answer", message: error instanceof Error ? error.message : String(error) });
    }
  }
  return {
    question,
    answer,
    plan: { terms, source: "edge-function" },
    kg_results: kgResults,
    verified_research_ids: researchIds,
    hits,
    evidence,
    timings: { total_ms: Math.round((performance.now() - started) * 100) / 100 },
    errors
  };
}

async function runRagStream(
  supabase: ReturnType<typeof createClient>,
  question: string,
  limit: number,
  useLlm: boolean,
  write: (event: string, payload: Record<string, unknown>) => void
) {
  const started = performance.now();
  const terms = tokenize(question);
  const errors: Array<Record<string, string>> = [];

  write("stage", { event: "stage", stage: "plan", status: "complete", message: "KG 검색 계획을 생성했습니다." });
  const plan = { terms, source: "edge-function" };
  write("plan", { event: "plan", plan });

  write("stage", { event: "stage", stage: "kg", status: "running", message: "Supabase KG에서 후보를 찾습니다." });
  const { kgResults, researchIds } = await kgStep(supabase, terms);
  write("kg_results", { event: "kg_results", kg_results: kgResults, verified_research_ids: researchIds });
  write("stage", { event: "stage", stage: "kg", status: "complete", message: "KG 후보 검증을 완료했습니다." });

  write("stage", { event: "stage", stage: "body", status: "running", message: "Markdown chunk를 검색합니다." });
  const hits = await chunkStep(supabase, question, limit, researchIds);
  const evidence = evidenceFromHits(hits);
  write("hits", { event: "hits", hits, evidence });
  write("stage", { event: "stage", stage: "body", status: "complete", message: "본문 근거 검색을 완료했습니다." });

  let answer = "";
  if (useLlm) {
    write("stage", { event: "stage", stage: "llm", status: "running", message: "MiniMax가 근거 기반 답변을 생성합니다." });
    try {
      for await (const item of minimaxAnswerStream(question, kgResults, hits)) {
        if (item.event === "answer_delta") answer += String(item.text || "");
        write(item.event, item);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      errors.push({ stage: "answer", message });
      write("error", { event: "error", stage: "answer", message });
    }
    write("stage", { event: "stage", stage: "llm", status: "complete", message: "MiniMax 답변 생성을 마쳤습니다." });
  } else {
    write("stage", { event: "stage", stage: "llm", status: "skipped", message: "MiniMax를 사용하지 않고 근거만 반환합니다." });
  }

  return {
    event: "done",
    question,
    answer,
    plan,
    kg_results: kgResults,
    verified_research_ids: researchIds,
    hits,
    evidence,
    timings: { total_ms: Math.round((performance.now() - started) * 100) / 100 },
    errors
  };
}

async function kgStep(supabase: ReturnType<typeof createClient>, terms: string[]) {
  const { data, error } = await supabase.rpc("kg_search", { terms, kinds: null, match_limit: 20 });
  if (error) throw error;
  const kgResults = data || [];
  const researchIds = Array.from(
    new Set(
      kgResults
        .map((item: Record<string, unknown>) => {
          const nodeData = item.data as Record<string, unknown> | undefined;
          return typeof nodeData?.research_id === "string" ? nodeData.research_id : "";
        })
        .filter(Boolean)
    )
  );
  return { kgResults, researchIds };
}

async function chunkStep(supabase: ReturnType<typeof createClient>, question: string, limit: number, researchIds: string[]) {
  const { data, error } = await supabase.rpc("search_chunks", {
    query_text: question,
    match_limit: limit,
    research_ids: researchIds.length ? researchIds : null
  });
  if (error) throw error;
  return data || [];
}

function evidenceFromHits(hits: Array<Record<string, unknown>>) {
  return hits.map((hit) => ({
    chunk_id: hit.id,
    document_id: hit.document_id,
    chunk_index: hit.chunk_index,
    research_id: hit.research_id,
    title: hit.title,
    organ_name: hit.organ_name,
    file_id: hit.file_id,
    file_name: hit.file_name,
    score: hit.score,
    excerpt: String(hit.text || "").slice(0, 900)
  }));
}

async function minimaxAnswer(question: string, kgResults: Array<Record<string, unknown>>, hits: Array<Record<string, unknown>>) {
  let answer = "";
  for await (const item of minimaxAnswerStream(question, kgResults, hits)) {
    if (item.event === "answer_delta") answer += String(item.text || "");
  }
  return answer;
}

async function* minimaxAnswerStream(question: string, kgResults: Array<Record<string, unknown>>, hits: Array<Record<string, unknown>>) {
  const apiKey = requireEnv("MINIMAX_API_KEY");
  const evidence = [
    ...kgResults.slice(0, 10).map((item) => `[KG] ${item.kind || ""} ${item.label || ""}`),
    ...hits.slice(0, 8).map((hit, index) => {
      const citation = `${hit.organ_name || ""} ${hit.research_id || ""} ${hit.title || ""}`.trim();
      return `[본문 ${index + 1}] ${citation}\n${String(hit.text || "").slice(0, 1400)}`;
    })
  ].join("\n\n");

  const response = await fetch(MINIMAX_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "Accept": "text/event-stream"
    },
    body: JSON.stringify({
      model: MINIMAX_MODEL,
      temperature: 0.2,
      max_tokens: 1600,
      stream: true,
      reasoning_split: true,
      messages: [
        { role: "system", content: "아래 검증된 KG 결과와 본문 근거만 사용해 한국어로 답하세요. 모르면 모른다고 답하세요." },
        { role: "user", content: `질문: ${question}\n\n근거:\n${evidence}` }
      ]
    })
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error?.message || payload?.message || "MiniMax request failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith(":")) continue;
      const dataLine = line.startsWith("data:") ? line.slice(5).trim() : line;
      if (!dataLine || dataLine === "[DONE]") continue;
      let chunk: Record<string, unknown>;
      try {
        chunk = JSON.parse(dataLine);
      } catch {
        continue;
      }
      for (const item of minimaxEventsFromChunk(chunk)) {
        yield item;
        if (item.event === "finish") return;
      }
    }
  }
}

function* minimaxEventsFromChunk(chunk: Record<string, unknown>) {
  const choices = (chunk.choices as Array<Record<string, unknown>> | undefined) || [];
  for (const choice of choices) {
    const delta = (choice.delta || choice.message || {}) as Record<string, unknown>;
    if (typeof delta.reasoning_content === "string" && delta.reasoning_content) {
      yield { event: "reasoning_delta", text: delta.reasoning_content };
    }
    if (delta.reasoning_details) {
      yield { event: "reasoning_details", details: delta.reasoning_details };
    }
    const content = typeof delta.content === "string" ? delta.content : typeof choice.text === "string" ? choice.text : "";
    if (content) yield { event: "answer_delta", text: content };
    if (choice.finish_reason) yield { event: "finish", finish_reason: choice.finish_reason };
  }
}

async function logQuery(supabase: ReturnType<typeof createClient>, userId: string, question: string, answer: string, evidenceCount: number) {
  await supabase.from("rag_query_logs").insert({
    user_id: userId,
    question,
    answer_chars: answer.length,
    evidence_count: evidenceCount
  });
}

function tokenize(text: string) {
  const matches = text.match(/[0-9A-Za-z가-힣]{2,}/g) || [];
  return Array.from(new Set(matches)).slice(0, 12);
}

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function requireEnv(name: string) {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function encodeSse(event: string, payload: Record<string, unknown>) {
  return new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`);
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json; charset=utf-8" }
  });
}
