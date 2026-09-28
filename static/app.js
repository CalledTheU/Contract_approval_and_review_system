const $ = (selector) => document.querySelector(selector);
const state = { tasks: [], selected: null, risks: [], toastTimer: null, token: localStorage.getItem('contract-review-token'), user: null };
const labels = { completed: '审查完成', blocked: '需处理', HIGH: '高风险', MEDIUM: '中风险', LOW: '低风险' };
const statusLabels = { pending: '\u7b49\u5f85\u89e3\u6790', parsing: '\u6587\u6863\u89e3\u6790\u4e2d', reviewing: '\u98ce\u9669\u5ba1\u67e5\u4e2d', completed: '\u5ba1\u67e5\u5b8c\u6210', blocked: '\u9700\u5904\u7406' };
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set('Authorization', `Bearer ${state.token}`);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch {}
    if (response.status === 401 && !url.includes('/api/auth/login')) showLogin();
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('visible');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => node.classList.remove('visible'), 3000);
}

function badge(level, label = labels[level] || level) {
  if (statusLabels[level]) label = statusLabels[level];
  const kind = ({ HIGH: 'high', MEDIUM: 'medium', LOW: 'low', completed: 'completed', blocked: 'blocked' })[level] || 'neutral';
  return `<span class="badge ${kind}">${esc(label)}</span>`;
}

function counts() {
  $('#metric-total').textContent = state.tasks.length;
  $('#metric-completed').textContent = state.tasks.filter((task) => task.status === 'completed').length;
  $('#metric-writeback').textContent = state.tasks.filter((task) => task.writeback_status === 'success').length;
  $('#metric-high').textContent = state.tasks.reduce((sum, task) => sum + (task.high_count || 0), 0);
}

async function refreshTasks(keepSelection = true) {
  state.tasks = await api('/api/review/tasks');
  counts();
  drawTasks();
  if (!keepSelection || !state.selected || !state.tasks.some((task) => task.id === state.selected)) {
    if (state.tasks.length) await openTask(state.tasks[0].id);
    else clearTask();
  } else {
    await openTask(state.selected);
  }
}

async function watchTask(taskId) {
  for (;;) {
    const result = await api(`/api/review/tasks/${encodeURIComponent(taskId)}`);
    if (result.task.status === 'completed' || result.task.status === 'blocked') {
      await refreshTasks(false);
      await openTask(taskId);
      toast(result.task.status === 'blocked' ? '合同解析受阻，请查看原因' : '合同审查已完成');
      return;
    }
    await openTask(taskId);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

function drawTasks() {
  const query = $('#search-input').value.trim().toLowerCase();
  const status = $('#status-filter').value;
  const risk = $('#risk-filter').value;
  const visible = state.tasks.filter((task) => (!status || task.status === status) && (!risk || (task.risk_levels || '').split(',').includes(risk)) && `${task.name} ${task.filename}`.toLowerCase().includes(query));
  $('#task-count').textContent = `${state.tasks.length} 项`;
  $('#visible-count').textContent = visible.length;
  $('#task-list').innerHTML = visible.length ? visible.map((task) => `
    <button type="button" class="task-row ${task.id === state.selected ? 'selected' : ''}" data-task="${esc(task.id)}">
      <span class="task-name">${esc(task.name)}</span>
      <span class="task-sub"><span>${esc(task.filename)}</span><span>${date(task.created_at)}</span></span>
      <span class="task-badges">${badge(task.status)}${task.top_level ? badge(task.top_level) : '<span class="badge neutral">未发现规则命中</span>'}</span>
    </button>`).join('') : '<div class="empty-state">没有匹配的合同</div>';
}

function date(value) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? '' : parsed.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function clearTask() {
  state.selected = null;
  state.risks = [];
  $('#document-empty').hidden = false;
  $('#document-content').hidden = true;
  $('#review-actions').hidden = true;
  $('#risk-list').innerHTML = '<div class="empty-state compact">暂无风险项</div>';
  $('#risk-summary').textContent = '选择一份合同查看风险';
  $('#risk-total').textContent = '—';
  drawTasks();
}

async function openTask(id) {
  const result = await api(`/api/review/tasks/${encodeURIComponent(id)}`);
  state.selected = id;
  state.risks = result.risks;
  const task = result.task;
  const meta = task.metadata || {};
  $('#document-empty').hidden = true;
  $('#document-content').hidden = false;
  const canReview = ['legal', 'admin'].includes(state.user?.role);
  $('#review-actions').hidden = task.status !== 'completed' || !canReview;
  $('#document-name').textContent = task.name;
  $('#document-meta').textContent = `${task.filename} · ${statusLabels[task.status] || task.status}`;
  $('#file-type').textContent = (task.filename.split('.').pop() || 'FILE').slice(0, 4).toUpperCase();
  $('#retry-button').hidden = task.status !== 'blocked' || state.user?.role !== 'admin';
  $('#blocked-message').hidden = task.status !== 'blocked';
  $('#blocked-message').textContent = task.blocked_reason || '';
  $('#document-facts').innerHTML = [
    ['合同编号', meta.contract_number || '未识别'], ['合同金额', meta.amount || '未识别'], ['履行期限', meta.period || '未识别'],
  ].map(([name, value]) => `<div class="fact"><span>${name}</span><strong title="${esc(value)}">${esc(value)}</strong></div>`).join('');
  $('#source-page').textContent = `${meta.pages || 1} 页 · ${task.text.length.toLocaleString()} 字`;
  renderSource(task.text || '无法显示正文内容', state.risks);
  renderRisks();
  if (!task.text && task.status !== 'blocked') renderSource('\u6b63\u5728\u89e3\u6790\u6587\u6863\uff0c\u8bf7\u7a0d\u5019...', state.risks);
  $('#legal-comment').value = task.comments || '';
  $('#writeback-state').textContent = task.writeback_status === 'success' ? '已回写到模拟审批系统' : task.writeback_status === 'failed' ? '回写失败，可重试' : '尚未回写';
  $('#markdown-link').href = `/api/review/tasks/${encodeURIComponent(id)}/report/markdown`;
  $('#pdf-link').href = `/api/review/tasks/${encodeURIComponent(id)}/report/pdf`;
  drawTasks();
}

function renderSource(text, risks) {
  const matches = risks.filter((risk) => Number.isInteger(risk.start) && risk.end > risk.start).sort((a, b) => a.start - b.start);
  const segments = [];
  let cursor = 0;
  for (const risk of matches) {
    if (risk.start < cursor || risk.end > text.length) continue;
    segments.push(esc(text.slice(cursor, risk.start)));
    segments.push(`<mark id="evidence-${esc(risk.id)}" data-risk="${esc(risk.id)}">${esc(text.slice(risk.start, risk.end))}</mark>`);
    cursor = risk.end;
  }
  segments.push(esc(text.slice(cursor)));
  $('#contract-text').innerHTML = segments.join('');
}

function renderRisks() {
  const list = $('#risk-list');
  const order = { HIGH: 0, MEDIUM: 1, LOW: 2 };
  state.risks.sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3) || a.start - b.start);
  const total = state.risks.length;
  $('#risk-total').textContent = total;
  const high = state.risks.filter((risk) => risk.level === 'HIGH').length;
  $('#risk-summary').textContent = total ? `${high ? `${high} 项高风险 · ` : ''}${total} 项待复核` : '内置规则未发现明显风险';
  list.innerHTML = total ? state.risks.map((risk) => `
    <article class="risk-card ${risk.level.toLowerCase()}" data-card="${esc(risk.id)}">
      <button class="risk-open" type="button" data-open-risk="${esc(risk.id)}"><span class="risk-title">${esc(risk.title)}</span><span class="risk-level ${risk.level.toLowerCase()}">${esc(labels[risk.level] || risk.level)}</span></button>
      <p class="risk-evidence">${esc(risk.original_text)}</p>
      <div class="risk-detail" data-detail="${esc(risk.id)}" hidden>
        <p><strong>风险原因：</strong>${esc(risk.reason)}</p><p><strong>审查依据：</strong>${esc(risk.legal_basis)}</p><p><strong>处理建议：</strong>${esc(risk.suggestion)}</p>
        <textarea aria-label="修改建议条款" data-suggestion="${esc(risk.id)}">${esc(risk.suggested_text)}</textarea>
        <div class="risk-footer"><label><input type="checkbox" data-accepted="${esc(risk.id)}" ${risk.accepted ? 'checked' : ''} ${['legal', 'admin'].includes(state.user?.role) ? '' : 'disabled'}> 采纳建议</label>${['legal', 'admin'].includes(state.user?.role) ? `<button class="mini-button" type="button" data-save-risk="${esc(risk.id)}">保存修改</button>` : ''}</div>
      </div>
    </article>`).join('') : '<div class="empty-state compact">未发现规则命中，仍建议人工复核。</div>';
}

$('#task-list').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-task]');
  if (!button) return;
  try { await openTask(button.dataset.task); } catch (error) { toast(error.message); }
});

$('#risk-list').addEventListener('click', async (event) => {
  const open = event.target.closest('[data-open-risk]');
  if (open) {
    const id = open.dataset.openRisk;
    document.querySelectorAll('.risk-detail').forEach((node) => { node.hidden = node.dataset.detail !== id; });
    document.querySelectorAll('.risk-card').forEach((node) => node.classList.toggle('active', node.dataset.card === id));
    document.querySelectorAll('.contract-text mark').forEach((node) => node.classList.toggle('active', node.dataset.risk === id));
    $('#evidence-' + CSS.escape(id))?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    return;
  }
  const save = event.target.closest('[data-save-risk]');
  if (save) {
    const id = save.dataset.saveRisk;
    const accepted = $(`[data-accepted="${CSS.escape(id)}"]`).checked;
    const suggested_text = $(`[data-suggestion="${CSS.escape(id)}"]`).value;
    try {
      const result = await api(`/api/risks/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepted, suggested_text }) });
      Object.assign(state.risks.find((risk) => risk.id === id), result);
      toast('建议已保存');
    } catch (error) { toast(error.message); }
  }
});

$('#search-input').addEventListener('input', drawTasks);
$('#status-filter').addEventListener('change', drawTasks);
$('#risk-filter').addEventListener('change', drawTasks);

async function loadDemo(kind) {
  try {
    const result = await api(`/api/demo?kind=${kind}`, { method: 'POST' });
    await refreshTasks(false);
    await openTask(result.task.id);
    toast(kind === 'risk' ? '风险合同示例已载入' : '正常合同示例已载入');
  } catch (error) { toast(error.message); }
}
$('#demo-button').addEventListener('click', () => loadDemo('risk'));
$('#normal-demo-button').addEventListener('click', () => loadDemo('normal'));

$('#contract-file').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const result = await api('/api/contracts/upload', { method: 'POST', body: form });
    await refreshTasks(false);
    await openTask(result.task.id);
    toast('合同已接收，正在解析与审查');
    await watchTask(result.task.id);
  } catch (error) { toast(error.message); }
  event.target.value = '';
});

$('#empty-upload').addEventListener('click', () => $('#contract-file').click());
$('#retry-button').addEventListener('click', async () => {
  try {
    await api(`/api/review/tasks/${encodeURIComponent(state.selected)}/retry`, { method: 'POST' });
    await refreshTasks();
    toast('已重新执行解析与审查');
  } catch (error) { toast(error.message); }
});

$('#save-comment').addEventListener('click', async () => {
  const comment = $('#legal-comment').value.trim();
  if (!comment) return toast('请先填写法务意见');
  try {
    await api(`/api/review/tasks/${encodeURIComponent(state.selected)}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) });
    toast('法务意见已保存');
  } catch (error) { toast(error.message); }
});

$('#writeback-button').addEventListener('click', async () => {
  if (!state.selected) return;
  try {
    const comment = $('#legal-comment').value.trim();
    if (comment) await api(`/api/review/tasks/${encodeURIComponent(state.selected)}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) });
    const result = await api(`/api/review/tasks/${encodeURIComponent(state.selected)}/writeback`, { method: 'POST' });
    $('#writeback-state').textContent = result.status === 'success' ? '已回写到模拟审批系统' : '回写失败，可重试';
    await refreshTasks();
    toast('审查意见已回写');
  } catch (error) { toast(error.message); }
});

function showLogin() {
  state.token = null;
  state.user = null;
  localStorage.removeItem('contract-review-token');
  $('.app-shell').hidden = true;
  $('#login-screen').hidden = false;
}

async function start() {
  if (!state.token) return showLogin();
  try {
    state.user = await api('/api/auth/me');
    $('#user-label').textContent = state.user.display_name;
    $('#login-screen').hidden = true;
    $('.app-shell').hidden = false;
    await refreshTasks();
  } catch (error) {
    showLogin();
    $('#login-error').textContent = error.message;
  }
}

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#login-error').textContent = '';
  try {
    const result = await api('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: $('#login-user').value, password: $('#login-password').value }) });
    state.token = result.token;
    localStorage.setItem('contract-review-token', state.token);
    state.user = result.user;
    $('#user-label').textContent = state.user.display_name;
    $('#login-screen').hidden = true;
    $('.app-shell').hidden = false;
    await refreshTasks();
  } catch (error) { $('#login-error').textContent = error.message; }
});

$('#logout-button').addEventListener('click', async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch {}
  clearTask();
  showLogin();
});

start();
