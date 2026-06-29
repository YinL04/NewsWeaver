const state = { topics: [], reports: [], config: {}, preview: null, report: null, selectedPreset: null, working: false };
const presets = [
  ["AI 大模型", "大模型, GPT, OpenAI, DeepSeek, Qwen, LLM", "教程, 招聘", "模型发布、价格与行业变化"],
  ["芯片半导体", "NVIDIA, AMD, 芯片, 半导体, AI 加速器", "游戏, 显卡评测", "算力、供应链与厂商动向"],
  ["互联网公司", "字节跳动, 腾讯, 阿里, 美团, 百度", "八卦, 游戏攻略", "大厂业务、组织与产品"],
  ["新能源车", "新能源车, 比亚迪, 特斯拉, 小鹏, 理想, 蔚来", "二手车, 车主论坛", "新品、销量与产业链"],
  ["出海公司", "出海, 跨境, TikTok, SHEIN, Temu", "代运营, 培训", "全球化与商业机会"],
  ["金融科技", "金融科技, 支付, 稳定币, 跨境支付, 数字银行", "贷款广告, 培训", "支付、结算与监管变化"],
].map(([name, keywords, exclude_words, description]) => ({ name, keywords, exclude_words, description }));
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let data = {};
  try { data = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) { const error = new Error(data.error || `请求失败 (${response.status})`); error.data = data; error.status = response.status; throw error; }
  return data;
}

function setStatus(text, kind = "") { $("statusPill").textContent = text; $("statusPill").className = `status-pill ${kind}`; }
function setWorking(value, text = "") {
  state.working = value;
  ["nextActionBtn", "previewBtn", "generateBtn", "deleteTopicBtn", "loadReportBtn", "editTopicBtn", "rewriteBtn"].forEach(id => { if ($(id)) $(id).disabled = value; });
  if (value && text) setStatus(text);
}

async function loadState() { setStatus("正在检查..."); applyState(await api("/api/state")); setStatus("可以开始", "ok"); }
function applyState(data) { state.topics = data.topics || []; state.reports = data.reports || []; state.config = data.config || {}; renderAll(); }
function renderAll() { renderConfig(); renderPresets(); renderTopics(); renderReports(); renderGuide(); renderNextAction(); }

function renderConfig() {
  const llm = state.config.llm || {}, search = state.config.search || {}, form = $("configForm");
  form.base_url.value = llm.base_url || "https://api.openai.com/v1"; form.model.value = llm.model || "gpt-4o-mini";
  form.default_limit.value = search.default_limit || 10; form.days_back.value = search.days_back || 1;
  form.api_key.placeholder = llm.has_api_key ? "已保存，留空不修改" : "粘贴 API Key";
  $("topicMetric").textContent = state.topics.length; $("reportMetric").textContent = state.reports.length; $("modelMetric").textContent = llm.has_api_key ? "已连接" : "未连接";
  $("modelTag").textContent = llm.has_api_key ? "已连接" : "未连接"; $("modelTag").className = `panel-tag ${llm.has_api_key ? "ok" : ""}`;
}
function renderPresets() {
  $("presetGrid").innerHTML = presets.map(p => `<button class="preset-card ${state.selectedPreset === p.name ? "selected" : ""}" type="button" data-preset="${escapeHtml(p.name)}"><strong>${escapeHtml(p.name)}</strong><span>${escapeHtml(p.description)}</span></button>`).join("");
  document.querySelectorAll(".preset-card").forEach(button => button.onclick = () => choosePreset(button.dataset.preset));
}
function renderTopics() {
  const old = $("topicSelect").value; $("topicSelect").innerHTML = state.topics.length ? state.topics.map(t => `<option>${escapeHtml(t.name)}</option>`).join("") : '<option value="">还没有主题</option>';
  if (state.topics.some(t => t.name === old)) $("topicSelect").value = old;
  $("topicChips").innerHTML = state.topics.length ? state.topics.map(t => `<button class="chip" data-topic="${escapeHtml(t.name)}">${escapeHtml(t.name)}</button>`).join("") : '<span class="chip">暂无主题</span>';
  document.querySelectorAll("[data-topic]").forEach(node => node.onclick = () => { $("topicSelect").value = node.dataset.topic; onTopicChange(); });
}
function renderReports() { $("reportSelect").innerHTML = state.reports.length ? state.reports.map(r => `<option value="${escapeHtml(r.name)}">${escapeHtml(r.name)}</option>`).join("") : '<option value="">暂无报告</option>'; }
function renderGuide() {
  const key = Boolean(state.config.llm?.has_api_key), topic = state.topics.length > 0;
  setStep("stepModel", key ? "done" : "active"); setStep("stepTopic", topic ? "done" : key ? "active" : ""); setStep("stepRun", key && topic ? "active" : "");
  $("modelHint").textContent = key ? "连接已保存" : "先保存 API Key"; $("topicHint").textContent = topic ? `${state.topics.length} 个主题` : "从模板开始"; $("runHint").textContent = key && topic ? "可体检并生成" : "完成前两步";
}
function setStep(id, mode) { $(id).className = `step-item ${mode}`; }
function renderNextAction() {
  const key = Boolean(state.config.llm?.has_api_key), topic = state.topics.length > 0, button = $("nextActionBtn");
  if (!key) return next("先连接模型", "保存 API Key 后即可开始。", "去连接", () => { $("modelSection").scrollIntoView({behavior:"smooth"}); $("configForm").api_key.focus(); });
  if (!topic) return next("创建关注主题", "模板负责起步，精细控制决定结果。", "选择模板", () => $("topicSection").scrollIntoView({behavior:"smooth"}));
  if (!state.preview) return next("体检真实素材", "提取正文、去重并构建证据包。", "体检素材", () => preview().catch(showError));
  const ready = state.preview.quality?.ready;
  next(ready ? "生成可信报告" : "素材存在风险", ready ? "生成将复用刚刚体检的同一批证据。" : "检查风险后可明确选择继续。", ready ? "生成报告" : "查看质量", ready ? () => generate(false).catch(showError) : () => $("qualityBox").scrollIntoView({behavior:"smooth"}));
  function next(title, desc, label, action) { $("nextTitle").textContent = title; $("nextDescription").textContent = desc; button.textContent = label; button.onclick = action; }
}

function choosePreset(name) { const p = presets.find(item => item.name === name); if (!p) return; resetTopicForm(); state.selectedPreset = name; const f = $("topicForm"); f.name.value = p.name; f.keywords.value = p.keywords; f.exclude_words.value = p.exclude_words; f.sources.value = "rss"; renderPresets(); setStatus(`已选择：${name}`, "ok"); }
async function saveConfig(event) { event.preventDefault(); setWorking(true, "保存设置..."); try { const data = await api("/api/config", {method:"POST", body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); event.currentTarget.api_key.value = ""; applyState(data.state); setStatus("模型设置已保存", "ok"); } finally { setWorking(false); } }
async function saveTopic(event) {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget)); const editing = Boolean(body.original_name); setWorking(true, editing ? "更新主题..." : "创建主题...");
  try { const data = await api(editing ? "/api/topics/update" : "/api/topics", {method:"POST", body:JSON.stringify(body)}); applyState(data.state); $("topicSelect").value = data.topic.name; resetTopicForm(); clearPreview(); setStatus(editing ? "主题已更新" : "主题已创建", "ok"); } finally { setWorking(false); }
}
function editTopic() {
  const topic = state.topics.find(t => t.name === $("topicSelect").value); if (!topic) return;
  const f = $("topicForm"), prefs = topic.preferences || {}; f.original_name.value = topic.name; f.name.value = topic.name; f.keywords.value = (topic.keywords || []).join(", "); f.exclude_words.value = (topic.exclude_words || []).join(", "); f.required_words.value = (topic.required_words || []).join(", "); f.sources.value = (topic.sources || []).map(s => s.startsWith("rss:http") ? s.slice(4) : s).join(", "); f.audience.value = prefs.audience || ""; f.style.value = prefs.style || "深度分析"; f.length.value = prefs.length || "中等";
  $("topicSubmitBtn").textContent = "保存主题"; $("cancelEditBtn").classList.remove("hidden"); $("topicSection").scrollIntoView({behavior:"smooth"});
}
function resetTopicForm() { $("topicForm").reset(); $("topicForm").original_name.value = ""; $("topicSubmitBtn").textContent = "创建主题"; $("cancelEditBtn").classList.add("hidden"); state.selectedPreset = null; renderPresets(); }
async function deleteTopic() { const name = $("topicSelect").value; if (!name || !confirm(`删除主题「${name}」及其记忆？`)) return; setWorking(true, "删除主题..."); try { const data = await api("/api/topics/delete", {method:"POST", body:JSON.stringify({name})}); applyState(data.state); clearPreview(); setStatus("主题已删除", "ok"); } finally { setWorking(false); } }

async function preview() {
  const topic = $("topicSelect").value; if (!topic) throw new Error("请先创建主题"); setWorking(true, "正在采集并提取正文..."); showProgress("正在建立证据包", 20);
  try { const data = await api("/api/preview", {method:"POST", body:JSON.stringify({topic})}); state.preview = data; renderPreview(); renderNextAction(); showProgress("素材体检完成", 100); setTimeout(hideProgress, 800); setStatus(data.quality.ready ? "素材可生成" : "素材需确认", data.quality.ready ? "ok" : "error"); }
  finally { setWorking(false); }
}
function clearPreview() { state.preview = null; renderPreview(); renderNextAction(); }
function renderPreview() {
  const data = state.preview, box = $("qualityBox"), list = $("articleList");
  if (!data) { box.className = "quality-box empty-state"; box.textContent = "还没有体检素材。体检会提取正文并建立可复用证据包。"; list.className = "article-list empty-state"; list.textContent = "暂无素材"; $("articleCount").textContent = "0 篇"; return; }
  const q = data.quality || {}, blockers = q.blockers || [], warnings = q.warnings || [];
  box.className = `quality-box ${q.ready ? "ready" : "blocked"}`; box.innerHTML = `<div class="quality-score ${q.ready ? "" : "warn"}">${q.score || 0}</div><div><h3>${q.ready ? "达到生成门槛" : "需要人工确认"}</h3><p>${q.article_count} 篇文章 · ${q.source_count} 个来源 · ${q.full_text_count} 篇正文</p>${blockers.length ? `<ul>${blockers.map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}${warnings.length ? `<small>${warnings.map(translateWarning).join("；")}</small>` : ""}</div>`;
  $("articleCount").textContent = `${data.articles.length} 篇`; list.className = "article-list"; list.innerHTML = data.articles.map((a,i) => `<article class="article-card"><div class="article-index">${String(i+1).padStart(2,"0")}</div><div><h4>${escapeHtml(a.title)}</h4><div class="article-meta"><span>${escapeHtml(a.source || "未知")}</span><span>${formatDate(a.published_at)}</span><span>相关性 ${a.relevance_score || 0}</span><span>${a.full_text && a.full_text.length > (a.summary||"").length ? "✓ 正文" : "仅摘要"}</span></div><a href="${safeUrl(a.url)}" target="_blank" rel="noreferrer">查看原文</a></div></article>`).join("");
}

async function generate(force) {
  if (!state.preview) return preview(); const topic = $("topicSelect").value; setWorking(true, "正在创建任务..."); showProgress("提交生成任务", 5);
  try {
    let data;
    try { data = await api("/api/generate", {method:"POST", body:JSON.stringify({topic, preview_id:state.preview.preview_id, force})}); }
    catch (error) { if (error.status === 409 && error.data.requires_confirmation && confirm(`${error.data.quality.blockers.join("；")}。仍然生成？`)) return generate(true); throw error; }
    await pollJob(data.job_id);
  } finally { setWorking(false); }
}
async function pollJob(id) {
  while (true) {
    const job = await api(`/api/job?id=${encodeURIComponent(id)}`); showProgress(job.message, job.percent || 0);
    if (job.status === "complete") { applyState(await api("/api/state")); $("reportSelect").value = job.report; await loadReport(); activateTab("report"); setStatus("报告已生成", "ok"); setTimeout(hideProgress, 1000); return; }
    if (job.status === "failed") throw new Error(job.error || "生成失败");
    await delay(700);
  }
}
function showProgress(message, percent) { $("progressPanel").classList.remove("hidden"); $("progressMessage").textContent = message; $("progressPercent").textContent = `${percent}%`; $("progressBar").style.width = `${percent}%`; }
function hideProgress() { $("progressPanel").classList.add("hidden"); }

async function loadReport() { const name = $("reportSelect").value; if (!name) throw new Error("暂无报告"); setStatus("打开报告..."); state.report = await api(`/api/report?name=${encodeURIComponent(name)}`); renderReport(); setStatus("报告已打开", "ok"); }
function renderReport() {
  const r = state.report; if (!r) return; $("reportView").className = "report-view"; $("reportView").innerHTML = renderMarkdown(r.content); $("reportEditor").value = r.content; renderEvidence(r.facts?.facts || []); renderAudit(r.audit || {}); renderHeadings(r.content); renderVersions(r.versions || []); $("versionHint").textContent = `${(r.versions || []).length} 个历史版本`;
  document.querySelectorAll("[data-fact]").forEach(node => node.onclick = () => document.getElementById(`fact-${node.dataset.fact}`)?.scrollIntoView({behavior:"smooth", block:"center"}));
}
function toggleEdit() { const editing = !$("reportEditor").classList.contains("hidden"); $("reportEditor").classList.toggle("hidden", editing); $("reportView").classList.toggle("hidden", !editing); $("saveReportBtn").classList.toggle("hidden", editing); $("editReportBtn").textContent = editing ? "编辑" : "取消编辑"; }
async function saveReport() { if (!state.report) return; setWorking(true, "保存新版本..."); try { const data = await api("/api/report/save", {method:"POST", body:JSON.stringify({name:state.report.name, content:$("reportEditor").value})}); state.report.content = $("reportEditor").value; state.report.audit = data.audit; state.report.versions = data.versions; toggleEdit(); renderReport(); setStatus("已保存新版本", "ok"); } finally { setWorking(false); } }
async function rewriteSection() { if (!state.report) throw new Error("请先打开报告"); const heading = $("rewriteHeading").value, instruction = $("rewriteInstruction").value.trim(); if (!heading || !instruction) throw new Error("请选择章节并填写改写要求"); setWorking(true, "正在局部改写..."); try { const data = await api("/api/report/rewrite", {method:"POST", body:JSON.stringify({name:state.report.name, heading, instruction})}); state.report.content = data.content; state.report.audit = data.audit; state.report.versions = data.versions; renderReport(); setStatus("章节已改写并保存版本", "ok"); } finally { setWorking(false); } }
function renderVersions(versions) { $("versionSelect").innerHTML = versions.length ? '<option value="">选择历史版本</option>' + versions.map(v => `<option value="${escapeHtml(v.name)}">${escapeHtml(v.name.replace('.md',''))}</option>`).join("") : '<option value="">暂无历史版本</option>'; }
async function restoreVersion() { if (!state.report) throw new Error("请先打开报告"); const version = $("versionSelect").value; if (!version) throw new Error("请选择历史版本"); if (!confirm("恢复后，当前内容会先自动保存为一个版本。继续吗？")) return; setWorking(true, "正在恢复版本..."); try { const data = await api("/api/report/restore", {method:"POST", body:JSON.stringify({name:state.report.name, version})}); state.report.content = data.content; state.report.audit = data.audit; state.report.versions = data.versions; renderReport(); setStatus("历史版本已恢复", "ok"); } finally { setWorking(false); } }
function renderEvidence(facts) { $("evidenceCount").textContent = `${facts.length} 条`; $("evidenceList").className = facts.length ? "evidence-list" : "evidence-list empty-state"; $("evidenceList").innerHTML = facts.length ? facts.map(f => `<article class="evidence-card" id="fact-${escapeHtml(f.id)}"><strong>${escapeHtml(f.id)}</strong><p>${escapeHtml(f.claim)}</p><small>${escapeHtml(f.source)} · ${formatDate(f.published_at)}</small><a href="${safeUrl(f.url)}" target="_blank" rel="noreferrer">原文 ↗</a></article>`).join("") : "暂无证据"; }
function renderAudit(audit) { const warnings = audit.warnings || []; $("auditBox").className = `audit-box ${audit.valid ? "valid" : warnings.length ? "warn" : "empty-state"}`; $("auditBox").innerHTML = audit.citation_coverage == null ? "暂无引用审计" : `<strong>${audit.valid ? "✓ 引用审计通过" : "⚠ 需要复核"}</strong><span>证据覆盖 ${audit.citation_coverage}% · 已引用 ${(audit.cited_ids||[]).length} 条</span>${warnings.length ? `<small>${warnings.join("；")}</small>` : ""}`; }
function renderHeadings(content) { const headings = [...content.matchAll(/^##\s+(.+)$/gm)].map(m => m[1].trim()); $("rewriteHeading").innerHTML = '<option value="">选择章节</option>' + headings.map(h => `<option value="${escapeHtml(h)}">${escapeHtml(h)}</option>`).join(""); }

async function loadTrend() { const topic = $("topicSelect").value; if (!topic) return; const t = await api(`/api/trend?topic=${encodeURIComponent(topic)}`), change = t.change_since_last_period || {}; $("trendView").className = "trend-grid"; $("trendView").innerHTML = `<article class="trend-hero"><span>趋势判断</span><h3>${escapeHtml(t.trend_conclusion || "暂无足够数据")}</h3><p>L2 ${t.memory_depth?.recent_entries || 0} 条 · L3 ${t.memory_depth?.weekly_trends || 0} 周</p></article>${trendCard("本期热点", t.current_hotspots)}${trendCard("反复玩家", t.recurring_players)}${trendCard("新出现", change.new_players)}${trendCard("降温玩家", change.fading_players)}${trendCard("拐点信号", t.turning_points)}`; }
function trendCard(title, items=[]) { return `<article class="trend-card"><span>${escapeHtml(title)}</span>${items.length ? `<ul>${items.map(x => `<li>${escapeHtml(x)}</li>`).join("")}</ul>` : "<p>暂无数据</p>"}</article>`; }

function activateTab(name) { document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name)); document.querySelectorAll(".tab-page").forEach(p => p.classList.remove("active")); $(`${name}Tab`).classList.add("active"); if (name === "trend") loadTrend().catch(showError); }
function onTopicChange() { clearPreview(); if ($("trendTab").classList.contains("active")) loadTrend().catch(showError); }

function renderMarkdown(md) {
  const lines = String(md || "").split("\n"), out = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) { const level = heading[1].length; out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); index += 1; continue; }
    if (line.startsWith("> ")) { out.push(`<blockquote>${inlineMarkdown(line.slice(2))}</blockquote>`); index += 1; continue; }
    if (line.startsWith("- ")) { const items = []; while (index < lines.length && lines[index].trim().startsWith("- ")) { items.push(`<li>${inlineMarkdown(lines[index].trim().slice(2))}</li>`); index += 1; } out.push(`<ul>${items.join("")}</ul>`); continue; }
    if (line.includes("|") && index + 1 < lines.length && /^\s*\|?\s*:?-+/.test(lines[index + 1])) {
      const bodyRows = []; let cursor = index + 2;
      while (cursor < lines.length && lines[cursor].includes("|") && lines[cursor].trim()) { bodyRows.push(lines[cursor]); cursor += 1; }
      const cells = row => row.replace(/^\||\|$/g, "").split("|").map(cell => inlineMarkdown(cell.trim()));
      out.push(`<table><thead><tr>${cells(line).map(cell => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${bodyRows.map(row => `<tr>${cells(row).map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      index = cursor; continue;
    }
    const paragraph = [line]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,3})\s+|^> |^- /.test(lines[index].trim())) { if (lines[index].includes("|") && index + 1 < lines.length && /^\s*\|?\s*:?-+/.test(lines[index + 1])) break; paragraph.push(lines[index].trim()); index += 1; }
    out.push(`<p>${paragraph.map(inlineMarkdown).join("<br>")}</p>`);
  }
  return out.join("");
}
function inlineMarkdown(value) { return escapeHtml(value).replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noreferrer">$1</a>').replace(/\[(F\d{3})\]/g,'<button class="fact-ref" data-fact="$1">[$1]</button>'); }
function escapeHtml(v) { return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;"); }
function safeUrl(v) { try { const u = new URL(v); return ["http:","https:"].includes(u.protocol) ? escapeHtml(u.href) : "#"; } catch (_) { return "#"; } }
function formatDate(v) { return v ? String(v).slice(0,10) : "未知时间"; }
function translateWarning(v) { const map = {"Too few articles; the report may be shallow.":"文章较少，报告可能偏浅","Only one source family is represented.":"来源过于单一","Many articles only have summaries, not extracted full text.":"部分文章只有摘要"}; return map[v] || escapeHtml(v); }
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
function showError(error) { setWorking(false); hideProgress(); setStatus(error.message || String(error), "error"); }

window.addEventListener("DOMContentLoaded", () => {
  $("configForm").onsubmit = e => saveConfig(e).catch(showError); $("topicForm").onsubmit = e => saveTopic(e).catch(showError); $("cancelEditBtn").onclick = resetTopicForm;
  $("editTopicBtn").onclick = editTopic; $("previewBtn").onclick = () => preview().catch(showError); $("generateBtn").onclick = () => generate(false).catch(showError); $("deleteTopicBtn").onclick = () => deleteTopic().catch(showError);
  $("topicSelect").onchange = onTopicChange; $("loadReportBtn").onclick = () => loadReport().then(() => activateTab("report")).catch(showError); $("editReportBtn").onclick = toggleEdit; $("saveReportBtn").onclick = () => saveReport().catch(showError); $("rewriteBtn").onclick = () => rewriteSection().catch(showError); $("restoreBtn").onclick = () => restoreVersion().catch(showError);
  document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => activateTab(tab.dataset.tab)); loadState().catch(showError);
});
