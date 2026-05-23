// newslens Day 7~8 — 결과 화면 정식 UI (읽기/분석 모드 토글 + 마진점 + 아코디언)

const API_BASE =
  window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8000"
    : "";

const DEBOUNCE_MS = 5000;

const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  input: $("input-section"),
  loading: $("loading-section"),
  error: $("error-section"),
  result: $("result-section"),

  form: $("analyze-form"),
  urlInput: $("url-input"),
  textInput: $("text-input"),
  sourceInput: $("source-input"),
  analyzeBtn: $("analyze-btn"),

  loadingSteps: $("loading-steps"),

  errorMsg: $("error-message"),
  errorRetry: $("error-retry"),

  resultTitle: $("result-heading"),
  cachedBadge: $("cached-badge"),
  resultSource: $("result-source"),
  resultAuthor: $("result-author"),
  resultDate: $("result-date"),

  ratioFactSeg: $("ratio-fact-seg"),
  ratioClaimSeg: $("ratio-claim-seg"),
  ratioOpinionSeg: $("ratio-opinion-seg"),
  ratioFramingSeg: $("ratio-framing-seg"),
  cntFact: $("cnt-fact"),
  cntClaim: $("cnt-claim"),
  cntOpinion: $("cnt-opinion"),
  cntFraming: $("cnt-framing"),

  factDigestList: $("fact-digest-list"),
  factDigestBlock: $("fact-digest-block"),

  modeButtons: $$(".mode-btn"),
  analyzeHint: $("analyze-hint"),
  articleBody: $("article-body"),

  newAnalyzeBtn: $("new-analyze-btn"),
};

// =========================================================================
// 상태 머신
// =========================================================================
function showOnly(sectionId) {
  for (const s of [els.input, els.loading, els.error, els.result]) {
    s.classList.toggle("hidden", s.id !== sectionId);
  }
}

function setState(state) {
  switch (state) {
    case "idle":
      showOnly("input-section");
      stopLoadingSteps();
      els.analyzeBtn.disabled = false;
      break;
    case "loading":
      showOnly("loading-section");
      startLoadingSteps();
      break;
    case "result":
      showOnly("result-section");
      stopLoadingSteps();
      els.analyzeBtn.disabled = false;
      window.scrollTo({ top: 0, behavior: "smooth" });
      break;
    case "error":
      showOnly("error-section");
      stopLoadingSteps();
      els.analyzeBtn.disabled = false;
      break;
  }
}

// =========================================================================
// 로딩 단계 (호출 1회로 통합 — 2단계로 단순화)
// =========================================================================
let stepTimers = [];

function setStepState(name, state) {
  const li = els.loadingSteps.querySelector(`[data-step="${name}"]`);
  if (li) li.dataset.state = state;
}

function startLoadingSteps() {
  stopLoadingSteps();
  setStepState("fetch", "active");
  setStepState("analyze", "pending");

  // 3초 후 추출 완료 추정, 분류·요약 단계로 전환
  stepTimers.push(setTimeout(() => {
    setStepState("fetch", "done");
    setStepState("analyze", "active");
  }, 3000));
}

function stopLoadingSteps() {
  for (const t of stepTimers) clearTimeout(t);
  stepTimers = [];
}

// =========================================================================
// 읽기 / 분석 모드
// =========================================================================
let currentMode = "read";

function setMode(mode) {
  currentMode = mode;
  els.articleBody.dataset.mode = mode;
  els.analyzeHint.classList.toggle("hidden", mode !== "analyze");

  for (const btn of els.modeButtons) {
    const active = btn.dataset.mode === mode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  }

  // 모드 전환 시 열려있던 rationale 모두 닫기
  closeAllRationales();
}

function closeAllRationales() {
  for (const r of els.articleBody.querySelectorAll(".rationale")) {
    r.remove();
  }
  for (const s of els.articleBody.querySelectorAll(".sentence.expanded")) {
    s.classList.remove("expanded");
  }
}

function toggleRationale(sentenceEl, sentence) {
  // 같은 문장 재클릭 → 닫기
  if (sentenceEl.classList.contains("expanded")) {
    closeAllRationales();
    return;
  }
  // 다른 문장 클릭 → 기존 닫고 새로 열기
  closeAllRationales();
  sentenceEl.classList.add("expanded");

  const rationale = document.createElement("div");
  rationale.className = "rationale";

  const label = document.createElement("span");
  label.className = "rationale-label";
  label.dataset.category = sentence.category;
  label.textContent = categoryLabel(sentence.category);
  rationale.appendChild(label);

  rationale.appendChild(document.createTextNode(sentence.rationale || "(분류 이유가 제공되지 않음)"));

  sentenceEl.insertAdjacentElement("afterend", rationale);
}

function categoryLabel(cat) {
  return {
    FACT: "사실",
    CLAIM: "인용",
    OPINION: "의견",
    FRAMING: "프레이밍",
  }[cat] || cat;
}

// =========================================================================
// 결과 렌더링
// =========================================================================
function renderResult(data) {
  els.resultTitle.textContent = data.article.title || "(제목 없음)";
  els.resultSource.textContent = data.article.source || "";
  els.resultAuthor.textContent = data.article.author || "";
  els.resultDate.textContent = data.article.date || "";

  els.cachedBadge.classList.toggle("hidden", !data.cached);

  // 비율 바 + 범례
  const s = data.analysis.summary;
  const total = s.total_sentences || 1;
  const pct = (n) => `${(n / total * 100).toFixed(1)}%`;
  els.ratioFactSeg.style.width = pct(s.fact_count);
  els.ratioClaimSeg.style.width = pct(s.claim_count);
  els.ratioOpinionSeg.style.width = pct(s.opinion_count);
  els.ratioFramingSeg.style.width = pct(s.framing_count);
  els.cntFact.textContent = s.fact_count;
  els.cntClaim.textContent = s.claim_count;
  els.cntOpinion.textContent = s.opinion_count;
  els.cntFraming.textContent = s.framing_count;

  // 핵심 사실 카드
  els.factDigestList.innerHTML = "";
  const facts = data.analysis.fact_digest.core_facts || [];
  if (facts.length === 0) {
    els.factDigestBlock.classList.add("hidden");
  } else {
    els.factDigestBlock.classList.remove("hidden");
    for (const f of facts) {
      const li = document.createElement("li");
      li.textContent = f;
      els.factDigestList.appendChild(li);
    }
  }

  // 본문 — 각 문장을 <p class="sentence"> 로 (마진점·아코디언 대상)
  els.articleBody.innerHTML = "";
  for (const sentence of data.analysis.sentences) {
    const p = document.createElement("p");
    p.className = "sentence";
    p.dataset.index = sentence.index;
    p.dataset.category = sentence.category;
    p.dataset.significant = sentence.significant ? "true" : "false";
    p.textContent = sentence.text;
    if (sentence.significant) {
      p.setAttribute("role", "button");
      p.setAttribute("tabindex", "0");
      p.title = "탭하면 분석 이유가 보입니다";
      p.addEventListener("click", () => toggleRationale(p, sentence));
      p.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleRationale(p, sentence);
        }
      });
    }
    els.articleBody.appendChild(p);
  }

  // 기본 모드: 읽기
  setMode("read");
  setState("result");
}

function renderError(message) {
  els.errorMsg.textContent = message;
  setState("error");
}

// =========================================================================
// 분석 호출
// =========================================================================
let lastSubmitAt = 0;
let inFlight = false;

async function analyze() {
  if (inFlight) return;

  const url = els.urlInput.value.trim();
  const text = els.textInput.value.trim();
  const source = els.sourceInput.value.trim();

  if (!url && !text) {
    renderError("URL 또는 본문 텍스트를 입력해주세요.");
    return;
  }

  const now = Date.now();
  const wait = DEBOUNCE_MS - (now - lastSubmitAt);
  if (wait > 0) {
    renderError(`너무 빠른 요청입니다. ${Math.ceil(wait / 1000)}초 후 다시 시도해주세요.`);
    return;
  }
  lastSubmitAt = now;

  const payload = {};
  if (url) payload.url = url;
  if (text) payload.text = text;
  if (source) payload.source = source;

  inFlight = true;
  els.analyzeBtn.disabled = true;
  setState("loading");

  try {
    const resp = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const detail = err.detail;
      const msg = typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join(", ")
          : `요청 실패 (HTTP ${resp.status})`;
      renderError(msg);
      return;
    }

    const data = await resp.json();
    renderResult(data);
  } catch (e) {
    renderError(`네트워크 오류: ${e.message}. 백엔드가 실행 중인지 확인해주세요.`);
  } finally {
    inFlight = false;
    els.analyzeBtn.disabled = false;
  }
}

// =========================================================================
// 이벤트 바인딩
// =========================================================================
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  analyze();
});

els.errorRetry.addEventListener("click", () => setState("idle"));

els.newAnalyzeBtn.addEventListener("click", () => {
  els.urlInput.value = "";
  els.textInput.value = "";
  els.sourceInput.value = "";
  setState("idle");
  els.urlInput.focus();
});

for (const btn of els.modeButtons) {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
}

setState("idle");
