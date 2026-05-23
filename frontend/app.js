// newslens Day 6 — 메인/로딩/결과 화면 상태 머신 + /api/analyze 호출

const API_BASE =
  window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8000"
    : ""; // 같은 origin에서 서빙되면 상대경로

const DEBOUNCE_MS = 5000;

// =========================================================================
// DOM 캐시
// =========================================================================
const $ = (id) => document.getElementById(id);

const els = {
  // sections
  input: $("input-section"),
  loading: $("loading-section"),
  error: $("error-section"),
  result: $("result-section"),
  // input form
  form: $("analyze-form"),
  urlInput: $("url-input"),
  textInput: $("text-input"),
  sourceInput: $("source-input"),
  analyzeBtn: $("analyze-btn"),
  // loading
  loadingSteps: $("loading-steps"),
  // error
  errorMsg: $("error-message"),
  errorRetry: $("error-retry"),
  // result
  resultTitle: $("result-heading"),
  cachedBadge: $("cached-badge"),
  resultSource: $("result-source"),
  resultAuthor: $("result-author"),
  resultDate: $("result-date"),
  cntFact: $("cnt-fact"),
  cntClaim: $("cnt-claim"),
  cntOpinion: $("cnt-opinion"),
  cntFraming: $("cnt-framing"),
  factDigestList: $("fact-digest-list"),
  factDigestBlock: $("fact-digest-block"),
  sentenceList: $("sentence-list"),
  newAnalyzeBtn: $("new-analyze-btn"),
};

// =========================================================================
// 상태 머신: idle | loading | result | error
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
      break;
    case "error":
      showOnly("error-section");
      stopLoadingSteps();
      els.analyzeBtn.disabled = false;
      break;
  }
}

// =========================================================================
// 로딩 단계 시뮬레이션 — 응답 시간을 정확히 모르므로 시간 기반 추정
// 실제 응답 도착 시 stop 호출되어 즉시 결과로 전환됨
// =========================================================================
let stepTimers = [];

function setStepState(name, state) {
  const li = els.loadingSteps.querySelector(`[data-step="${name}"]`);
  if (li) li.dataset.state = state;
}

function startLoadingSteps() {
  stopLoadingSteps();
  setStepState("fetch", "active");
  setStepState("classify", "pending");
  setStepState("digest", "pending");

  // 3초 후 fetch 완료, classify 시작
  stepTimers.push(setTimeout(() => {
    setStepState("fetch", "done");
    setStepState("classify", "active");
  }, 3000));

  // 18초 후 classify 완료, digest 시작
  stepTimers.push(setTimeout(() => {
    setStepState("classify", "done");
    setStepState("digest", "active");
  }, 18000));
}

function stopLoadingSteps() {
  for (const t of stepTimers) clearTimeout(t);
  stepTimers = [];
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

  const s = data.analysis.summary;
  els.cntFact.textContent = s.fact_count;
  els.cntClaim.textContent = s.claim_count;
  els.cntOpinion.textContent = s.opinion_count;
  els.cntFraming.textContent = s.framing_count;

  // Fact digest
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

  // 분류된 문장 (임시 — Day 7~8 정식 UI 예정)
  els.sentenceList.innerHTML = "";
  for (const sentence of data.analysis.sentences) {
    const li = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = `[${sentence.category}] `;
    label.style.color = ({
      FACT: "var(--color-fact)",
      CLAIM: "var(--color-claim)",
      OPINION: "var(--color-opinion)",
      FRAMING: "var(--color-framing)",
    })[sentence.category] || "inherit";
    li.appendChild(label);
    li.appendChild(document.createTextNode(sentence.text));
    if (sentence.significant) {
      const star = document.createElement("span");
      star.textContent = " ★";
      star.title = "독자가 인지하기 어려운 비사실";
      star.style.color = "var(--color-accent)";
      li.appendChild(star);
    }
    els.sentenceList.appendChild(li);
  }

  setState("result");
}

// =========================================================================
// 에러 표시
// =========================================================================
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

  // 디바운스 (Day 2)
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

// 초기 상태
setState("idle");
