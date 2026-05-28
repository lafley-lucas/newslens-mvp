// newslens Day 7~8 — 결과 화면 정식 UI (읽기/분석 모드 토글 + 마진점 + 아코디언)

// 백엔드 base URL — 환경별 매핑
// 1) window.NEWSLENS_API_BASE가 있으면 그걸 우선 (HTML에서 inline 주입 가능)
// 2) localhost/127.0.0.1이면 dev 백엔드 (http://localhost:8000)
// 3) 그 외 (GitHub Pages 등 배포)는 환경변수로 주입된 값 사용 — 없으면 같은 origin
function resolveApiBase() {
  if (typeof window.NEWSLENS_API_BASE === "string" && window.NEWSLENS_API_BASE) {
    return window.NEWSLENS_API_BASE.replace(/\/$/, "");
  }
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return "http://localhost:8000";
  }
  return ""; // 같은 origin — 백엔드와 함께 서빙되는 경우
}
const API_BASE = resolveApiBase();

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

  shareRow: $("share-row"),
  shareKakaoBtn: $("share-kakao-btn"),
  shareCopyBtn: $("share-copy-btn"),

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

  perspectivesBlock: $("perspectives-block"),
  perspectivesStatus: $("perspectives-status"),
  perspectivesTopic: $("perspectives-topic"),
  perspectivesList: $("perspectives-list"),
  perspectivesEmpty: $("perspectives-empty"),

  noticesBlock: $("notices-block"),
  feedbackToast: $("feedback-toast"),

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
let currentUrlHash = null; // Day 10: 피드백 식별자 (없으면 텍스트 입력 → 피드백 비활성)
const CATEGORY_LABELS = {
  FACT: "사실",
  CLAIM: "인용",
  OPINION: "의견",
  FRAMING: "프레이밍",
};

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
  if (sentenceEl.classList.contains("expanded")) {
    closeAllRationales();
    return;
  }
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

  // Day 10: 피드백 행 (URL 입력일 때만)
  const feedbackRow = buildFeedbackRow(sentence);
  if (feedbackRow) rationale.appendChild(feedbackRow);

  sentenceEl.insertAdjacentElement("afterend", rationale);
}

function categoryLabel(cat) {
  return CATEGORY_LABELS[cat] || cat;
}

// =========================================================================
// 피드백 (Day 10)
// =========================================================================
let toastTimer = null;
function showToast(message) {
  els.feedbackToast.textContent = message;
  els.feedbackToast.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.feedbackToast.classList.remove("show");
  }, 2200);
}

async function sendFeedback(payload) {
  try {
    const resp = await fetch(`${API_BASE}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showToast(err.detail || "피드백 전송에 실패했습니다");
      return false;
    }
    return true;
  } catch (e) {
    showToast(`네트워크 오류: ${e.message}`);
    return false;
  }
}

function buildFeedbackRow(sentence) {
  // URL 입력이 아니면 피드백 비활성 (백엔드가 hash 식별자 필요)
  if (!currentUrlHash) return null;

  const row = document.createElement("div");
  row.className = "feedback-row";

  const label = document.createElement("span");
  label.className = "feedback-label";
  label.textContent = "이 분류가 맞나요?";
  row.appendChild(label);

  const upBtn = document.createElement("button");
  upBtn.type = "button";
  upBtn.className = "feedback-btn";
  upBtn.textContent = "👍";
  upBtn.title = "분류가 맞다";
  upBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (upBtn.classList.contains("sent")) return;
    const ok = await sendFeedback({
      article_url_hash: currentUrlHash,
      sentence_index: sentence.index,
      original_category: sentence.category,
      feedback_type: "thumbs_up",
    });
    if (ok) { upBtn.classList.add("sent"); upBtn.textContent = "👍 전송됨"; showToast("피드백 감사합니다"); }
  });
  row.appendChild(upBtn);

  const downBtn = document.createElement("button");
  downBtn.type = "button";
  downBtn.className = "feedback-btn";
  downBtn.textContent = "👎";
  downBtn.title = "분류가 틀렸다";
  downBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (downBtn.classList.contains("sent")) return;
    const ok = await sendFeedback({
      article_url_hash: currentUrlHash,
      sentence_index: sentence.index,
      original_category: sentence.category,
      feedback_type: "thumbs_down",
    });
    if (ok) { downBtn.classList.add("sent"); downBtn.textContent = "👎 전송됨"; showToast("피드백 감사합니다"); }
  });
  row.appendChild(downBtn);

  const sep = document.createElement("span");
  sep.className = "feedback-label";
  sep.textContent = "또는";
  row.appendChild(sep);

  const select = document.createElement("select");
  select.className = "feedback-select";
  select.setAttribute("aria-label", "올바른 카테고리 제안");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "다른 분류 제안...";
  select.appendChild(placeholder);
  for (const cat of ["FACT", "CLAIM", "OPINION", "FRAMING"]) {
    if (cat === sentence.category) continue;
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = CATEGORY_LABELS[cat];
    select.appendChild(opt);
  }
  select.addEventListener("click", (e) => e.stopPropagation());
  select.addEventListener("change", async (e) => {
    e.stopPropagation();
    const suggested = select.value;
    if (!suggested) return;
    const ok = await sendFeedback({
      article_url_hash: currentUrlHash,
      sentence_index: sentence.index,
      original_category: sentence.category,
      feedback_type: "category_correction",
      suggested_category: suggested,
    });
    if (ok) {
      select.disabled = true;
      showToast(`'${CATEGORY_LABELS[suggested]}'로 제안 전송됨`);
    }
  });
  row.appendChild(select);

  return row;
}

// =========================================================================
// 결과 렌더링
// =========================================================================
function renderResult(data) {
  // 피드백용 hash 저장 (URL 입력일 때만 채워짐)
  currentUrlHash = data.article.url_hash || null;

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

  // notices 배너 (백엔드의 안내 메시지)
  els.noticesBlock.innerHTML = "";
  const notices = data.notices || [];
  if (notices.length === 0) {
    els.noticesBlock.classList.add("hidden");
  } else {
    els.noticesBlock.classList.remove("hidden");
    const isOpinion = data.article.type === "opinion";
    for (const n of notices) {
      const div = document.createElement("div");
      div.className = isOpinion ? "notice notice-opinion" : "notice";
      div.textContent = n;
      els.noticesBlock.appendChild(div);
    }
  }

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

  // 기능 B (빠진 관점) — 비동기로 백그라운드 호출. 메인 결과는 이미 표시됨.
  // URL 입력일 때만 (article_url_hash가 있어야 캐시·라우트 동작)
  if (data.article.url_hash) {
    fetchPerspectives({
      article_url_hash: data.article.url_hash,
      title: data.article.title || "(제목 없음)",
      source: data.article.source || null,
      source_domain: hostnameOf(data.article.url),
      core_facts: (data.analysis.fact_digest && data.analysis.fact_digest.core_facts) || [],
    });
  } else {
    // 텍스트 직접 입력 모드는 빠진 관점 분석 비활성 (URL hash가 없으면 검색 결과 비교의 의미가 약함)
    els.perspectivesBlock.classList.add("hidden");
  }
}

// =========================================================================
// 빠진 관점 분석 (PRD §2 기능 B) — 비동기
// =========================================================================
const PERSPECTIVE_TYPE_LABEL = {
  MISSING_FACT: "빠진 사실",
  MISSING_VIEWPOINT: "빠진 입장",
  DIFFERENT_FRAMING: "다른 프레이밍",
};

function hostnameOf(url) {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function showPerspectivesLoading() {
  els.perspectivesBlock.classList.remove("hidden");
  els.perspectivesStatus.classList.remove("hidden");
  els.perspectivesTopic.classList.add("hidden");
  els.perspectivesEmpty.classList.add("hidden");
  els.perspectivesList.innerHTML = "";
}

function hidePerspectives() {
  els.perspectivesBlock.classList.add("hidden");
}

function renderPerspectives(data) {
  els.perspectivesStatus.classList.add("hidden");
  els.perspectivesList.innerHTML = "";

  const block = data.perspectives || {};
  const items = block.missing_perspectives || [];

  if (block.topic_summary) {
    els.perspectivesTopic.textContent = block.topic_summary;
    els.perspectivesTopic.classList.remove("hidden");
  }

  if (items.length === 0) {
    els.perspectivesEmpty.classList.remove("hidden");
    if (data.search_results_count === 0) {
      els.perspectivesEmpty.textContent = "같은 주제를 다룬 다른 매체 기사를 찾지 못했습니다.";
    } else {
      els.perspectivesEmpty.textContent =
        `다른 매체 ${data.search_results_count}건과 비교했지만, 명확히 빠진 사실이나 관점은 발견되지 않았습니다.`;
    }
    return;
  }

  els.perspectivesEmpty.classList.add("hidden");
  for (const p of items) {
    const li = document.createElement("li");

    const badge = document.createElement("span");
    badge.className = `persp-type-badge persp-type-${p.type}`;
    badge.textContent = PERSPECTIVE_TYPE_LABEL[p.type] || p.type;
    li.appendChild(badge);

    const desc = document.createElement("span");
    desc.className = "persp-description";
    desc.textContent = p.description;
    li.appendChild(desc);

    const src = document.createElement("span");
    src.className = "persp-source";
    src.textContent = "출처: ";
    const a = document.createElement("a");
    a.href = p.source_url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = p.found_in;
    src.appendChild(a);
    li.appendChild(src);

    els.perspectivesList.appendChild(li);
  }
}

async function fetchPerspectives(payload) {
  showPerspectivesLoading();
  try {
    const resp = await fetch(`${API_BASE}/api/perspectives`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (resp.status === 501) {
      // 검색 API 키 미설정 — 카드 자체를 숨김 (조용히)
      hidePerspectives();
      return;
    }

    if (!resp.ok) {
      // 실패해도 메인 결과에는 영향 X. 카드에만 안내.
      els.perspectivesStatus.classList.add("hidden");
      els.perspectivesEmpty.classList.remove("hidden");
      const err = await resp.json().catch(() => ({}));
      els.perspectivesEmpty.textContent =
        `빠진 관점 분석을 가져오지 못했습니다 (${err.detail || `HTTP ${resp.status}`}).`;
      return;
    }

    const data = await resp.json();
    renderPerspectives(data);
  } catch (e) {
    els.perspectivesStatus.classList.add("hidden");
    els.perspectivesEmpty.classList.remove("hidden");
    els.perspectivesEmpty.textContent = `네트워크 오류로 빠진 관점을 가져오지 못했습니다: ${e.message}`;
  }
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
// 공유 (런치 전략 §5 — 친구 공유 동선)
// 의존성 없이: 모바일은 navigator.share (시스템 시트에 카톡 노출),
// 데스크탑은 클립보드 복사로 폴백.
// =========================================================================
const SHARE_LANDING_URL = (() => {
  try {
    const u = new URL("./", window.location.href);
    return u.toString();
  } catch {
    return window.location.origin + "/";
  }
})();

function buildShareText() {
  const title = (els.resultTitle && els.resultTitle.textContent) || "";
  const trimmed = title.length > 40 ? title.slice(0, 40) + "…" : title;
  if (trimmed) {
    return `"${trimmed}"\n이 기사, 어디가 사실이고 어디가 의견인지 색깔로 봤습니다.\nnewslens에서 직접 확인 →`;
  }
  return "이 기사, 어디가 사실이고 어디가 의견인지 색깔로 봤습니다.\nnewslens에서 직접 확인 →";
}

async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {}
  // execCommand 폴백
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

async function handleShareKakao() {
  const shareText = buildShareText();
  // navigator.share는 모바일(특히 안드로이드/iOS Safari)에서 카톡 옵션 포함된 시스템 시트를 띄움.
  if (navigator.share) {
    try {
      await navigator.share({
        title: "newslens — 사실과 의견을 색깔로",
        text: shareText,
        url: SHARE_LANDING_URL,
      });
      return;
    } catch (e) {
      // 사용자가 취소했거나 미지원 — 클립보드 폴백
    }
  }
  // 데스크탑 폴백: 텍스트+링크를 클립보드에 복사
  const ok = await copyToClipboard(`${shareText} ${SHARE_LANDING_URL}`);
  if (ok) {
    showToast("문구가 복사됐어요. 카톡에 붙여넣으세요");
  } else {
    showToast("복사 실패 — 주소창에서 URL을 직접 복사해주세요");
  }
}

async function handleShareCopy() {
  const ok = await copyToClipboard(SHARE_LANDING_URL);
  if (!ok) {
    showToast("복사 실패 — 주소창에서 URL을 직접 복사해주세요");
    return;
  }
  showToast("링크를 복사했습니다");
  if (els.shareCopyBtn) {
    const orig = els.shareCopyBtn.innerHTML;
    els.shareCopyBtn.classList.add("copied");
    els.shareCopyBtn.innerHTML = '<span aria-hidden="true">✓</span> 복사됨';
    setTimeout(() => {
      els.shareCopyBtn.classList.remove("copied");
      els.shareCopyBtn.innerHTML = orig;
    }, 1800);
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

if (els.shareKakaoBtn) els.shareKakaoBtn.addEventListener("click", handleShareKakao);
if (els.shareCopyBtn)  els.shareCopyBtn.addEventListener("click", handleShareCopy);

setState("idle");

// Day 14: 데이터 안내 배너 (첫 방문 시 1회) — localStorage에 dismiss 기록
(function initDataBanner() {
  const banner = document.getElementById("data-banner");
  const dismiss = document.getElementById("data-banner-dismiss");
  if (!banner || !dismiss) return;
  try {
    if (localStorage.getItem("cookie_notice_dismissed") === "1") return;
  } catch (e) {
    // localStorage 비활성 환경 — 그래도 배너는 표시
  }
  banner.classList.remove("hidden");
  dismiss.addEventListener("click", () => {
    try { localStorage.setItem("cookie_notice_dismissed", "1"); } catch (e) {}
    banner.classList.add("hidden");
  });
})();
