// newslens Day 1 — URL/텍스트 입력 → /api/extract 호출 → 문장 리스트 표시

const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
  ? "http://localhost:8000"
  : ""; // 같은 origin에서 서빙되면 상대경로 사용

const els = {
  urlInput: document.getElementById("url-input"),
  textInput: document.getElementById("text-input"),
  sourceInput: document.getElementById("source-input"),
  analyzeBtn: document.getElementById("analyze-btn"),
  status: document.getElementById("status"),
  result: document.getElementById("result"),
  articleTitle: document.getElementById("article-title"),
  articleSource: document.getElementById("article-source"),
  articleAuthor: document.getElementById("article-author"),
  articleDate: document.getElementById("article-date"),
  parserUsed: document.getElementById("parser-used"),
  sentenceCount: document.getElementById("sentence-count"),
  sentenceList: document.getElementById("sentence-list"),
};

function showStatus(message, kind) {
  els.status.textContent = message;
  els.status.className = `status ${kind}`;
}

function clearStatus() {
  els.status.className = "status hidden";
  els.status.textContent = "";
}

function clearResult() {
  els.result.classList.add("hidden");
  els.sentenceList.innerHTML = "";
}

function renderResult(data) {
  els.articleTitle.textContent = data.article.title || "(제목 없음)";
  els.articleSource.textContent = data.article.source || "";
  els.articleAuthor.textContent = data.article.author || "";
  els.articleDate.textContent = data.article.date || "";
  els.parserUsed.textContent = data.parser;
  els.sentenceCount.textContent = data.total_sentences;

  els.sentenceList.innerHTML = "";
  for (const s of data.sentences) {
    const li = document.createElement("li");
    li.textContent = s.text;
    els.sentenceList.appendChild(li);
  }
  els.result.classList.remove("hidden");
}

const DEBOUNCE_MS = 5000;
let lastSubmitAt = 0;

async function analyze() {
  const url = els.urlInput.value.trim();
  const text = els.textInput.value.trim();
  const source = els.sourceInput.value.trim();

  if (!url && !text) {
    showStatus("URL 또는 본문 텍스트를 입력해주세요.", "error");
    return;
  }

  const now = Date.now();
  const wait = DEBOUNCE_MS - (now - lastSubmitAt);
  if (wait > 0) {
    showStatus(`너무 빠른 요청입니다. ${Math.ceil(wait / 1000)}초 후 다시 시도해주세요.`, "error");
    return;
  }
  lastSubmitAt = now;

  clearResult();
  showStatus("기사를 분석하고 있습니다...", "loading");
  els.analyzeBtn.disabled = true;

  const payload = {};
  if (url) payload.url = url;
  if (text) payload.text = text;
  if (source) payload.source = source;

  try {
    const resp = await fetch(`${API_BASE}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      const msg = err.detail || `요청 실패 (HTTP ${resp.status})`;
      showStatus(msg, "error");
      return;
    }

    const data = await resp.json();
    clearStatus();
    renderResult(data);
  } catch (e) {
    showStatus(`네트워크 오류: ${e.message}. 백엔드가 실행 중인지 확인해주세요.`, "error");
  } finally {
    els.analyzeBtn.disabled = false;
  }
}

els.analyzeBtn.addEventListener("click", analyze);
els.urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyze();
});
