const state = {
  topics: [],
  reports: [],
  config: null,
  preview: null,
  selectedPreset: null,
};

const presets = [
  {
    name: "AI 大模型",
    keywords: "大模型, GPT, OpenAI, DeepSeek, Qwen, LLM",
    exclude_words: "教程, 招聘",
    description: "模型发布、价格、产品和行业变化",
  },
  {
    name: "芯片半导体",
    keywords: "NVIDIA, AMD, 芯片, 半导体, AI 加速器",
    exclude_words: "游戏, 显卡评测",
    description: "算力、供应链、厂商动向",
  },
  {
    name: "互联网公司",
    keywords: "字节跳动, 腾讯, 阿里, 美团, 百度, 互联网",
    exclude_words: "八卦, 游戏攻略",
    description: "大厂业务、组织和产品变化",
  },
  {
    name: "新能源车",
    keywords: "新能源车, 比亚迪, 特斯拉, 小鹏, 理想, 蔚来",
    exclude_words: "二手车, 车主论坛",
    description: "车企新品、销量和产业链",
  },
  {
    name: "出海公司",
    keywords: "出海, 跨境, TikTok, SHEIN, Temu, 全球化",
    exclude_words: "代运营, 培训",
    description: "中国公司全球化和商业机会",
  },
];

const $ = (id) => document.getElementById(id);

function setStatus(text, kind = "") {
  const node = $("statusPill");
  node.textContent = text;
  node.className = `status-pill ${kind}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

async function loadState() {
  setStatus("正在检查...");
  const data = await api("/api/state");
  applyState(data);
  setStatus("可以开始", "ok");
}

function applyState(data) {
  state.topics = data.topics || [];
  state.reports = data.reports || [];
  state.config = data.config || {};
  renderAll();
}

function renderAll() {
  renderConfig();
  renderPresets();
  renderTopics();
  renderReports();
  renderGuide();
  renderNextAction();
}

function renderConfig() {
  const config = state.config || {};
  const llm = config.llm || {};
  const search = config.search || {};
  const form = $("configForm");
  form.base_url.value = llm.base_url || "https://api.openai.com/v1";
  form.model.value = llm.model || "gpt-4o-mini";
  form.default_limit.value = search.default_limit || 10;
  form.days_back.value = search.days_back || 1;
  form.api_key.placeholder = llm.has_api_key ? "已保存，留空不修改" : "粘贴你的 API Key";
  $("topicMetric").textContent = state.topics.length;
  $("reportMetric").textContent = state.reports.length;
  $("modelMetric").textContent = llm.has_api_key ? "已连接" : "未连接";
  const modelTag = $("modelTag");
  modelTag.textContent = llm.has_api_key ? "已连接" : "未连接";
  modelTag.className = `panel-tag ${llm.has_api_key ? "ok" : ""}`;
}

function renderPresets() {
  const grid = $("presetGrid");
  grid.innerHTML = presets
    .map(
      (preset) => `
        <button class="preset-card ${state.selectedPreset === preset.name ? "selected" : ""}"
          type="button"
          data-preset="${escapeHtml(preset.name)}">
          <strong>${escapeHtml(preset.name)}</strong>
          <span>${escapeHtml(preset.description)}</span>
        </button>
      `
    )
    .join("");

  grid.querySelectorAll(".preset-card").forEach((button) => {
    button.addEventListener("click", () => choosePreset(button.dataset.preset));
  });
}

function renderTopics() {
  const select = $("topicSelect");
  select.innerHTML = "";
  if (!state.topics.length) {
    select.append(new Option("还没有主题", ""));
  } else {
    state.topics.forEach((topic) => select.append(new Option(topic.name, topic.name)));
  }

  const chips = $("topicChips");
  if (!state.topics.length) {
    chips.innerHTML = '<span class="chip">暂无，先点上面的模板</span>';
  } else {
    chips.innerHTML = state.topics
      .map((topic) => `<span class="chip">${escapeHtml(topic.name)}</span>`)
      .join("");
  }
}

function renderReports() {
  const select = $("reportSelect");
  select.innerHTML = "";
  if (!state.reports.length) {
    select.append(new Option("暂无报告", ""));
  } else {
    state.reports.forEach((report) => select.append(new Option(report.name, report.name)));
  }
}

function renderGuide() {
  const hasKey = Boolean(state.config?.llm?.has_api_key);
  const hasTopic = state.topics.length > 0;
  setStep("stepModel", hasKey ? "done" : "active");
  setStep("stepTopic", hasTopic ? "done" : hasKey ? "active" : "");
  setStep("stepRun", hasKey && hasTopic ? "active" : "");
  $("modelHint").textContent = hasKey ? "模型已经连接，可以继续。" : "先保存 API Key，只需要一次。";
  $("topicHint").textContent = hasTopic ? `已有 ${state.topics.length} 个主题。` : "点一个模板就能创建主题。";
  $("runHint").textContent = hasKey && hasTopic ? "现在可以体检素材并生成报告。" : "前两步完成后这里会亮起来。";
}

function setStep(id, mode) {
  const node = $(id);
  node.className = `step-item ${mode}`;
}

function renderNextAction() {
  const hasKey = Boolean(state.config?.llm?.has_api_key);
  const hasTopic = state.topics.length > 0;
  const button = $("nextActionBtn");

  if (!hasKey) {
    $("nextTitle").textContent = "先连接模型";
    $("nextDescription").textContent = "把 API Key 粘贴进去并保存。高级设置已经折叠，新手可以忽略。";
    button.textContent = "去填 API Key";
    button.onclick = () => focusModel();
    return;
  }

  if (!hasTopic) {
    $("nextTitle").textContent = "选一个关注方向";
    $("nextDescription").textContent = "从模板库点一个方向，会自动填好主题名、关键词和排除词。";
    button.textContent = "选择模板";
    button.onclick = () => scrollToSection("topicSection");
    return;
  }

  if (!state.preview) {
    $("nextTitle").textContent = "体检今天的素材";
    $("nextDescription").textContent = "先看文章数、来源数和正文覆盖率，再决定是否生成。";
    button.textContent = "体检素材";
    button.onclick = () => preview().catch(showError);
    return;
  }

  $("nextTitle").textContent = "生成今日报告";
  $("nextDescription").textContent = "素材已完成质量检查，可以生成带事实包和评分文件的报告。";
  button.textContent = "生成报告";
  button.onclick = () => generate().catch(showError);
}

function choosePreset(name) {
  const preset = presets.find((item) => item.name === name);
  if (!preset) return;
  state.selectedPreset = name;
  const form = $("topicForm");
  form.name.value = preset.name;
  form.keywords.value = preset.keywords;
  form.exclude_words.value = preset.exclude_words;
  renderPresets();
  setStatus(`已选择模板：${name}`, "ok");
}

async function saveConfig(event) {
  event.preventDefault();
  setStatus("保存模型设置...");
  const body = Object.fromEntries(new FormData(event.currentTarget).entries());
  const data = await api("/api/config", { method: "POST", body: JSON.stringify(body) });
  event.currentTarget.api_key.value = "";
  applyState(data.state);
  setStatus("模型设置已保存", "ok");
}

async function addTopic(event) {
  event.preventDefault();
  setStatus("创建主题...");
  const body = Object.fromEntries(new FormData(event.currentTarget).entries());
  const data = await api("/api/topics", { method: "POST", body: JSON.stringify(body) });
  applyState(data.state);
  $("topicSelect").value = data.topic.name;
  state.preview = null;
  renderPreview(null);
  event.currentTarget.reset();
  state.selectedPreset = null;
  renderAll();
  setStatus("主题已创建", "ok");
}

async function preview() {
  const topic = $("topicSelect").value;
  if (!topic) {
    setStatus("请先创建主题", "error");
    scrollToSection("topicSection");
    return;
  }
  setWorking(true, "正在体检素材...");
  try {
    const data = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ topic }),
    });
    state.preview = data;
    renderPreview(data);
    renderNextAction();
    setStatus("素材体检完成", "ok");
  } finally {
    setWorking(false);
  }
}

function renderPreview(data) {
  const qualityBox = $("qualityBox");
  const list = $("articleList");
  const count = $("articleCount");

  if (!data) {
    qualityBox.className = "quality-box empty-state";
    qualityBox.textContent = "还没有体检素材。点击“体检素材”看看今天能抓到什么。";
    list.className = "article-list empty-state";
    list.textContent = "暂无素材";
    count.textContent = "0 篇";
    return;
  }

  const quality = data.quality || {};
  const warnings = quality.warnings || [];
  const scoreClass = quality.score >= 70 ? "" : "warn";
  qualityBox.className = "quality-box";
  qualityBox.innerHTML = `
    <div class="quality-score ${scoreClass}">${quality.score || 0}</div>
    <div>
      <h3>${quality.score >= 70 ? "素材基础不错" : "素材偏少，谨慎生成"}</h3>
      <p>${quality.article_count || 0} 篇文章，${quality.source_count || 0} 个来源，${quality.full_text_count || 0} 篇有正文。${warnings.length ? warnings.join("；") : "可以进入生成。"}</p>
    </div>
  `;

  const articles = data.articles || [];
  count.textContent = `${articles.length} 篇`;
  if (!articles.length) {
    list.className = "article-list empty-state";
    list.textContent = "没有抓到文章。换一个模板或放宽关键词试试。";
    return;
  }

  list.className = "article-list";
  list.innerHTML = articles
    .map(
      (article, index) => `
        <div class="article-card">
          <h4>${index + 1}. ${escapeHtml(article.title)}</h4>
          <div class="article-meta">
            <span>${escapeHtml(article.source || "未知来源")}</span>
            <span>${formatDate(article.published_at)}</span>
            <span>相关性 ${article.relevance_score || 0}</span>
          </div>
          <a href="${article.url}" target="_blank" rel="noreferrer">${escapeHtml(article.url)}</a>
        </div>
      `
    )
    .join("");
}

async function generate() {
  const topic = $("topicSelect").value;
  if (!topic) {
    setStatus("请先创建主题", "error");
    scrollToSection("topicSection");
    return;
  }
  setWorking(true, "正在生成报告...");
  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ topic }),
    });
    applyState(data.state);
    setStatus("报告已生成", "ok");
    await loadNewestReport();
  } finally {
    setWorking(false);
  }
}

async function deleteTopic() {
  const name = $("topicSelect").value;
  if (!name) return setStatus("暂无主题", "error");
  if (!window.confirm(`删除主题「${name}」及其关联记忆？`)) return;
  setWorking(true, "正在删除主题...");
  try {
    const data = await api("/api/topics/delete", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.preview = null;
    applyState(data.state);
    renderPreview(null);
    setStatus("主题已删除", "ok");
  } finally {
    setWorking(false);
  }
}

async function loadNewestReport() {
  if (!state.reports.length) return;
  $("reportSelect").value = state.reports[0].name;
  await loadReport();
}

async function loadReport() {
  const name = $("reportSelect").value;
  if (!name) return setStatus("暂无报告", "error");
  setStatus("正在打开报告...");
  const data = await api(`/api/report?name=${encodeURIComponent(name)}`);
  const view = $("reportView");
  view.className = "report-view";
  view.textContent = data.content;
  setStatus("报告已打开", "ok");
}

function setWorking(isWorking, text = "") {
  ["nextActionBtn", "previewBtn", "generateBtn", "deleteTopicBtn", "loadReportBtn"].forEach((id) => {
    $(id).disabled = isWorking;
  });
  if (isWorking && text) setStatus(text);
}

function focusModel() {
  scrollToSection("modelSection");
  $("configForm").api_key.focus();
}

function scrollToSection(id) {
  $(id).scrollIntoView({ behavior: "smooth", block: "start" });
}

function formatDate(value) {
  if (!value) return "未知时间";
  return String(value).slice(0, 10);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showError(error) {
  setWorking(false);
  setStatus(error.message || String(error), "error");
}

window.addEventListener("DOMContentLoaded", () => {
  $("configForm").addEventListener("submit", (event) => saveConfig(event).catch(showError));
  $("topicForm").addEventListener("submit", (event) => addTopic(event).catch(showError));
  $("previewBtn").addEventListener("click", () => preview().catch(showError));
  $("generateBtn").addEventListener("click", () => generate().catch(showError));
  $("deleteTopicBtn").addEventListener("click", () => deleteTopic().catch(showError));
  $("loadReportBtn").addEventListener("click", () => loadReport().catch(showError));
  $("topicSelect").addEventListener("change", () => {
    state.preview = null;
    renderPreview(null);
    renderNextAction();
  });
  loadState().catch(showError);
});
