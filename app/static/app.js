"use strict";

/* Presentation only: each fixed event source is resolved and authorized again by
   the server. The UI never sends an object/operation or trusts hidden buttons. */
const S = { user: null, permissions: new Set(), csrf: "", page: "dashboard", data: {}, filters: {}, roleId: null, rbacTab: "matrix", auditTab: "audit", requestId: 0 };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const h = value => String(value ?? "").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const can = permission => S.permissions.has(permission);
const pages = {
  dashboard: { name: "工作台概览", icon: "◫", kicker: "OVERVIEW", description: "从设备到预约，掌握实验室的每一步进展。" },
  equipment: { name: "实验设备", icon: "▣", kicker: "EQUIPMENT", description: "浏览实验设备、查看可用状态，安排下一次实验。" },
  reservations: { name: "预约管理", icon: "▦", kicker: "RESERVATIONS", description: "让每一份实验计划，经过清晰有序的申请与审批。" },
  loans: { name: "借用与归还", icon: "⇄", kicker: "CIRCULATION", description: "关联已审批预约，记录设备领用、归还与检查情况。" },
  rbac: { name: "角色与权限", icon: "◇", kicker: "ACCESS CONTROL", description: "以操作 × 控制对象配置细粒度权限，支持多角色合并。" },
  audit: { name: "审计与事件", icon: "≋", kicker: "AUDIT & EVENTS", description: "追踪固定事件源、授权判定与业务操作的完整路径。" }
};
const statusNames = { available: "可预约", maintenance: "维护中", pending: "待审批", approved: "已批准", rejected: "已拒绝", cancelled: "已取消", borrowed: "借用中", returned: "已归还", accepted: "已执行", success: "已执行", denied: "已拒绝", invalid: "校验失败" };
const operationNames = { view: "查看", create: "申请", update: "维护", approve: "批准", reject: "拒绝", cancel: "取消", manage: "管理", export: "导出", checkout: "领用", return: "归还" };
const deviceIcons = ["⌕", "◈", "▥", "⊞", "⌁", "◉"];
const eventTitles = { "equipment.save": "保存设备", "reservation.submit": "预约实验设备", "reservation.approve": "批准预约", "reservation.reject": "拒绝预约", "reservation.cancel": "取消预约", "loan.checkout": "办理设备领用", "loan.return": "办理设备归还", "rbac.save_permissions": "保存角色权限", "rbac.assign_roles": "分配用户角色" };
const supportedEvents = new Set(Object.keys(eventTitles));
let dialogReturnFocus = null;

class ApiError extends Error {
  constructor(message, code, status) { super(message); this.code = code; this.status = status; }
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const method = options.method || "GET";
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && S.csrf) headers["X-CSRF-Token"] = S.csrf;
  let response;
  try { response = await fetch(path, { ...options, headers, credentials: "same-origin", body: options.body === undefined ? undefined : JSON.stringify(options.body) }); }
  catch (_) { throw new ApiError("无法连接本地服务，请确认服务已启动后重试。", "NETWORK", 0); }
  let result;
  try { result = await response.json(); }
  catch (_) { throw new ApiError("服务器返回了无法识别的响应，请刷新后重试。", "RESPONSE", response.status); }
  if (!response.ok || !result.ok) {
    if (response.status === 401 && path !== "/api/login") showLogin();
    throw new ApiError(result.error?.message || "操作失败，请稍后重试。", result.error?.code || "ERROR", response.status);
  }
  return result.data;
}

function applySession(data) {
  S.user = data.user;
  S.csrf = data.csrf_token;
  S.permissions = new Set(data.permissions || []);
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#user-name").textContent = S.user.display_name;
  $("#user-avatar").textContent = S.user.display_name.slice(-2, -1) || S.user.display_name.slice(0, 1);
  $("#user-roles").textContent = S.user.roles.map(role => role.name).join(" · ");
  renderNavigation();
}

function showLogin() {
  S.user = null; S.csrf = ""; S.permissions = new Set(); S.data = {};
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
  if ($("#action-dialog").open) $("#action-dialog").close();
  document.title = "登录 · LabReserve";
}

function renderNavigation() {
  $("#main-nav").innerHTML = Object.entries(pages).filter(([key]) => can(`menu.${key}:view`)).map(([key, page]) => `${key === "rbac" ? '<div class="nav-separator"></div>' : ""}<button type="button" class="nav-item ${S.page === key ? "active" : ""}" data-nav="${key}" ${S.page === key ? 'aria-current="page"' : ""}><span class="nav-icon" aria-hidden="true">${page.icon}</span>${page.name}</button>`).join("") || '<p class="muted" style="padding:12px;font-size:11px">当前角色尚未获得菜单权限。</p>';
}

function heading(actions = "") {
  const page = pages[S.page];
  return `<div class="page-heading"><div><div class="page-kicker">${page.kicker}</div><h1>${page.name}</h1><p>${page.description}</p></div><div class="page-actions">${actions}</div></div>`;
}

function statusTag(status) { const code = Object.hasOwn(statusNames, status) ? status : "cancelled"; return `<span class="status ${code}">${h(statusNames[status] || status)}</span>`; }
function dateTime(value) { if (!value) return "—"; return h(String(value).replace("T", " ").slice(0, 16)); }
function interval(row) { return `${dateTime(row.start_at)}<small>至 ${dateTime(row.end_at)}</small>`; }
function isOwn(row) { return Number(row.user_id) === Number(S.user.id); }
function eventButton(source, text, id, extra = "") { return `<button type="button" class="button small ${extra}" data-source-id="${source}" data-id="${Number(id)}" title="固定事件源：${source}">${text}</button>`; }
function empty(title, description, action = "") { return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">◫</span><h3>${h(title)}</h3><p>${h(description)}</p>${action}</div>`; }
function notice(text, warning = false) { return `<div class="notice ${warning ? "warning" : ""}"><span class="notice-icon" aria-hidden="true">${warning ? "△" : "◇"}</span><div>${text}</div></div>`; }
function readScope() { return can("reservation:approve") || can("reservation:reject") || can("loan:checkout") || can("loan:return") || can("audit:view") || can("reservation:manage") ? "当前角色可查看实验室记录；审批仍受本人申请不可自审等业务规则约束。" : "仅展示本人预约及关联借用记录，数据归属由服务端校验。"; }
function permissionStrip() { return `<div class="permission-strip"><span aria-hidden="true">◇</span><strong>当前权限来源</strong><span>${h(S.user.roles.map(role => role.name).join(" + "))}，取所有角色授权的并集</span><span class="permission-count">${S.permissions.size} 项有效权限</span></div>`; }
function table(headers, body, className = "") { return `<div class="table-wrap"><table class="${className}"><thead><tr>${headers.map(item => `<th scope="col">${item}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`; }

async function go(page, changeHash = true) {
  if (!S.user) return;
  if (!Object.hasOwn(pages, page)) page = "dashboard";
  S.page = page;
  if (changeHash && location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  renderNavigation();
  $("#current-page-name").textContent = pages[page].name;
  document.title = `${pages[page].name} · LabReserve`;
  $("#sidebar").classList.remove("open");
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  const main = $("#main-content");
  const requestId = ++S.requestId;
  if (!can(`page.${page}:view`)) {
    main.innerHTML = heading() + `<div class="panel">${empty("此页面尚未授权", `当前角色缺少 page.${page}:view。可由系统管理员在权限矩阵中配置页面权限。`)}</div>` + permissionStrip();
    return;
  }
  const business = { equipment: "equipment:view", reservations: "reservation:view", loans: "loan:view", rbac: "rbac:view", audit: "audit:view" }[page];
  if (business && !can(business)) {
    main.innerHTML = heading() + `<div class="panel">${empty("页面可访问，业务读取未授权", `当前角色缺少 ${business}。页面、菜单与业务权限独立配置。`)}</div>` + permissionStrip();
    return;
  }
  main.innerHTML = '<div class="loading-state" role="status"><div class="spinner"></div>正在读取实验室数据…</div>';
  try {
    let data;
    if (page === "dashboard") {
      const result = await Promise.all([api("/api/dashboard"), can("equipment:view") && can("page.equipment:view") ? api("/api/equipment") : Promise.resolve([]), can("reservation:view") && can("page.reservations:view") ? api("/api/reservations") : Promise.resolve([])]);
      data = { dashboard: result[0], equipment: result[1], reservations: result[2] };
    } else if (page === "loans") {
      const result = await Promise.all([api("/api/loans"), can("reservation:view") && can("page.reservations:view") ? api("/api/reservations") : Promise.resolve([])]);
      data = { loans: result[0], reservations: result[1] };
    } else if (page === "audit") {
      const result = await Promise.all([api("/api/audit"), api("/api/events")]);
      data = { audit: result[0], events: result[1] };
    } else data = { [page]: await api(`/api/${page === "rbac" ? "rbac" : page}`) };
    if (requestId !== S.requestId || !S.user) return;
    S.data = { ...S.data, ...data };
    renderPage();
  } catch (error) {
    if (requestId !== S.requestId || !S.user) return;
    main.innerHTML = heading() + `<div class="panel">${empty("暂时无法读取数据", error.message, '<button class="button" data-action="refresh">重新加载</button>')}</div>`;
  }
}

function renderPage() {
  const renderers = { dashboard: renderDashboard, equipment: renderEquipment, reservations: renderReservations, loans: renderLoans, rbac: renderRbac, audit: renderAudit };
  $("#main-content").innerHTML = renderers[S.page]();
}

function renderDashboard() {
  const d = S.data.dashboard;
  const localDate = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date());
  const actions = `<span class="date-label"><span aria-hidden="true">▦</span>${h(localDate)}</span>`;
  const reserveAction = can("reservation:create") ? '<button class="button primary" data-action="open-reservation">预约实验设备 <span>↗</span></button>' : '<span class="field-hint">当前角色具有只读权限</span>';
  const items = [
    { label: "实验设备", value: d.equipment_count, unit: "台设备已登记入库", icon: "▣" },
    { label: "待审批预约", value: d.pending_count, unit: "份申请等待教师处理", icon: "◷" },
    { label: "已批准预约", value: d.approved_count, unit: "份预约可办理设备领用", icon: "✓" },
    { label: "正在借用", value: d.borrowed_count, unit: "台设备处于借用状态", icon: "⇄" }
  ];
  const recent = S.data.reservations.slice(0, 5);
  const reservationRows = recent.map(row => `<tr><td><strong>${h(row.equipment_name)}</strong><small>${h(row.equipment_code)} · #${Number(row.id)}</small></td><td>${h(row.applicant_name)}</td><td>${dateTime(row.start_at)}<small>${h(row.purpose).slice(0, 24)}</small></td><td>${statusTag(row.status)}</td></tr>`).join("");
  const deviceRows = S.data.equipment.slice(0, 4).map((row, index) => `<div class="equipment-mini"><span class="device-icon" aria-hidden="true">${deviceIcons[index % deviceIcons.length]}</span><span class="equipment-mini-info"><strong>${h(row.name)}</strong><small>${h(row.location)} · ${h(row.code)}</small></span>${statusTag(row.status)}</div>`).join("");
  return heading(actions) + `<section class="hero"><div class="hero-copy"><span class="eyebrow">A WELL-ORGANIZED LAB STARTS HERE</span><h2>${h(S.user.display_name)}，欢迎回到实验室。</h2><p>提前规划实验，让设备有序流转。<br>你的每一次预约与操作，都将在权限与规则的保护下完成。</p>${reserveAction}</div><div class="hero-art" aria-hidden="true"><div class="art-circle"></div><div class="equipment-art">⌕</div><span class="art-plus">＋</span><span class="art-label">READY FOR YOUR NEXT DISCOVERY</span></div></section>` +
    `<section class="stats-grid" aria-label="实验室统计">${items.map(item => `<article class="stat-card"><div class="stat-top">${item.label}<span class="stat-icon" aria-hidden="true">${item.icon}</span></div><div class="stat-value">${Number(item.value) || 0}</div><p class="stat-bottom"><b>●</b> ${item.unit}</p></article>`).join("")}</section>` +
    `<div class="dashboard-grid"><section class="panel"><div class="panel-head"><h2>最近预约 <small>RECENT RESERVATIONS</small></h2>${can("page.reservations:view") ? '<button class="button text" data-nav="reservations">查看全部 →</button>' : ""}</div>${reservationRows ? table(["预约设备", "申请人", "实验安排", "状态"], reservationRows) : empty("暂无可见预约", "创建第一份设备预约，让实验计划有序开始。") }<div class="panel-footer"><span aria-hidden="true">◇</span>${h(readScope())}</div></section><div><section class="panel"><div class="panel-head"><h2>设备速览 <small>EQUIPMENT</small></h2>${can("page.equipment:view") ? '<button class="button text" data-nav="equipment">全部 →</button>' : ""}</div><div class="panel-body">${deviceRows || '<p class="muted" style="font-size:11px">当前没有可见设备。</p>'}</div></section><section class="panel" style="margin-top:18px"><div class="panel-head"><h2>实验设备流转 <small>WORKFLOW</small></h2></div><div class="panel-body"><div class="workflow"><div class="workflow-step"><i>01</i><b>提交预约</b><small>学生 / 申请人</small></div><span class="workflow-arrow">→</span><div class="workflow-step"><i>02</i><b>教师审批</b><small>不可审批本人</small></div><span class="workflow-arrow">→</span><div class="workflow-step"><i>03</i><b>领用归还</b><small>设备管理员</small></div></div></div></section></div></div>` + permissionStrip();
}

function filterToolbar(placeholder, statuses, page) {
  const f = S.filters[page] || {};
  return `<div class="toolbar"><div class="search-field"><span aria-hidden="true">⌕</span><input data-filter="search" data-page="${page}" aria-label="${placeholder}" placeholder="${placeholder}" value="${h(f.search || "")}"></div>${statuses ? `<select data-filter="status" data-page="${page}" aria-label="按状态筛选"><option value="">全部状态</option>${statuses.map(status => `<option value="${status}" ${f.status === status ? "selected" : ""}>${statusNames[status]}</option>`).join("")}</select>` : ""}<span id="result-count" class="result-count"></span></div>`;
}

function filterRows(rows, page, text) {
  const f = S.filters[page] || {};
  const search = String(f.search || "").toLocaleLowerCase().trim();
  return rows.filter(row => (!f.status || row.status === f.status) && (!search || text(row).toLocaleLowerCase().includes(search)));
}

function renderEquipment() {
  return heading(`${can("equipment:update") ? '<button class="button" data-action="open-equipment">＋ 登记设备</button>' : ""}${can("reservation:create") ? '<button class="button primary" data-action="open-reservation">＋ 新建预约</button>' : ""}`) + `<section class="panel filters-panel">${filterToolbar("搜索设备名称、编号或位置", ["available", "maintenance"], "equipment")}</section><div id="filter-results">${equipmentResults()}</div>` + permissionStrip();
}

function equipmentResults() {
  const rows = filterRows(S.data.equipment, "equipment", row => `${row.name} ${row.code} ${row.location} ${row.category}`);
  queueMicrotask(() => { if ($("#result-count")) $("#result-count").textContent = `共 ${rows.length} 台设备`; });
  if (!rows.length) return `<div class="panel">${empty("没有找到设备", "尝试调整搜索条件，或由设备管理员登记实验设备。")}</div>`;
  return `<div class="equipment-grid">${rows.map((row, index) => `<article class="equipment-card"><div class="equipment-card-head"><span class="device-icon" aria-hidden="true">${deviceIcons[index % deviceIcons.length]}</span>${statusTag(row.status)}</div><h2>${h(row.name)}</h2><div class="equipment-code">${h(row.code)}</div><p class="equipment-description">${h(row.description || "实验室登记设备，可查看状态后提交预约。")}</p><div class="equipment-meta"><span>▣ ${h(row.category)}</span><span>⌖ ${h(row.location)}</span></div><div class="equipment-card-bottom">${can("reservation:create") ? `<button class="button primary small" data-action="open-reservation" data-equipment-id="${Number(row.id)}" ${row.status !== "available" ? "disabled title=维护中的设备无法预约" : ""}>${row.status === "available" ? "预约设备 ↗" : "设备维护中"}</button>` : '<span class="muted" style="font-size:10px">仅查看设备信息</span>'}${can("equipment:update") ? `<button class="button small" data-action="open-equipment" data-id="${Number(row.id)}">维护</button>` : ""}</div></article>`).join("")}</div>`;
}

function renderReservations() {
  const actions = `${can("reservation:export") ? '<button class="button" data-action="export">↓ 导出 CSV</button>' : ""}${can("reservation:create") ? '<button class="button primary" data-action="open-reservation">＋ 新建预约</button>' : ""}`;
  return heading(actions) + notice(h(readScope()) + " <strong>同一设备的待审批、已批准及借用中预约不可时间重叠。</strong>") + `<section class="panel">${filterToolbar("搜索设备、申请人或实验用途", ["pending", "approved", "borrowed", "returned", "rejected", "cancelled"], "reservations")}<div id="filter-results">${reservationResults()}</div></section>` + permissionStrip();
}

function reservationActions(row) {
  let actions = "";
  if (row.status === "pending") {
    if (isOwn(row) && (can("reservation:approve") || can("reservation:reject"))) actions += '<span class="muted" style="font-size:9px" title="业务规则：本人预约不可自审">本人申请不可自审</span>';
    else {
      if (can("reservation:approve")) actions += eventButton("reservation.approve", "批准", row.id, "primary");
      if (can("reservation:reject")) actions += eventButton("reservation.reject", "拒绝", row.id);
    }
  }
  if (["pending", "approved"].includes(row.status) && can("reservation:cancel") && (isOwn(row) || can("reservation:manage"))) actions += eventButton("reservation.cancel", "取消", row.id);
  if (row.status === "approved" && can("loan:checkout")) actions += eventButton("loan.checkout", "办理领用", row.id, "primary");
  return actions || '<span class="muted" style="font-size:10px">—</span>';
}

function reservationResults() {
  const rows = filterRows(S.data.reservations, "reservations", row => `${row.equipment_name} ${row.equipment_code} ${row.applicant_name} ${row.purpose}`);
  queueMicrotask(() => { if ($("#result-count")) $("#result-count").textContent = `共 ${rows.length} 条预约`; });
  if (!rows.length) return empty("暂无预约记录", "提交设备预约后，可以在这里查看进度与审批结果。");
  return table(["设备 / 预约编号", "申请人", "实验时间", "实验用途", "状态", "审批信息", "操作"], rows.map(row => `<tr><td><strong>${h(row.equipment_name)}</strong><small>${h(row.equipment_code)} · #${Number(row.id)}</small></td><td>${h(row.applicant_name)}${isOwn(row) ? '<small>本人申请</small>' : ""}</td><td>${interval(row)}</td><td style="min-width:130px;max-width:220px;word-break:break-word">${h(row.purpose)}</td><td>${statusTag(row.status)}</td><td>${h(row.reviewer_name || "—")}<small>${h(row.review_note || "")}</small></td><td><div class="table-actions">${reservationActions(row)}</div></td></tr>`).join(""));
}

function renderLoans() {
  const approved = S.data.reservations.filter(row => row.status === "approved");
  return heading() + notice("<strong>领用前需完成预约审批，设备同时只能存在一笔未归还借用。</strong> " + h(readScope())) + (can("loan:checkout") ? `<section class="panel" style="margin-bottom:20px"><div class="panel-head"><h2>待领用预约 <small>READY FOR CHECKOUT</small></h2><span class="result-count">${approved.length} 条</span></div>${approved.length ? table(["预约设备", "申请人", "预约时间", "操作"], approved.map(row => `<tr><td><strong>${h(row.equipment_name)}</strong><small>预约 #${Number(row.id)}</small></td><td>${h(row.applicant_name)}</td><td>${interval(row)}</td><td>${eventButton("loan.checkout", "办理领用 →", row.id, "primary")}</td></tr>`).join("")) : empty("没有待领用预约", "教师批准预约后，设备管理员可在此办理领用。")}</section>` : "") + `<section class="panel"><div class="panel-head"><h2>借用记录 <small>CIRCULATION RECORDS</small></h2></div>${filterToolbar("搜索设备或借用人", ["borrowed", "returned"], "loans")}<div id="filter-results">${loanResults()}</div></section>` + permissionStrip();
}

function loanResults() {
  const rows = filterRows(S.data.loans, "loans", row => `${row.equipment_name} ${row.applicant_name}`);
  queueMicrotask(() => { if ($("#result-count")) $("#result-count").textContent = `共 ${rows.length} 条记录`; });
  if (!rows.length) return empty("暂无借用记录", "已领用的实验设备将在这里记录借用与归还情况。");
  return table(["借用设备", "借用人", "领用时间", "归还时间", "状态", "检查备注", "操作"], rows.map(row => `<tr><td><strong>${h(row.equipment_name)}</strong><small>借用 #${Number(row.id)} · 预约 #${Number(row.reservation_id)}</small></td><td>${h(row.applicant_name)}</td><td>${dateTime(row.checkout_at)}</td><td>${dateTime(row.returned_at)}</td><td>${statusTag(row.status)}</td><td style="max-width:230px;word-break:break-word">${h(row.condition_note || "—")}</td><td>${row.status === "borrowed" && can("loan:return") ? eventButton("loan.return", "办理归还", row.id, "primary") : '<span class="muted">—</span>'}</td></tr>`).join(""));
}

function renderRbac() {
  const data = S.data.rbac;
  if (!data.roles.some(role => Number(role.id) === Number(S.roleId))) S.roleId = data.roles[0]?.id;
  const objectCounts = { page: 0, menu: 0, business: 0 };
  S.permissions.forEach(permission => { const code = permission.split(":")[0]; if (code.startsWith("page.")) objectCounts.page++; else if (code.startsWith("menu.")) objectCounts.menu++; else objectCounts.business++; });
  const overview = `<div class="permission-overview"><div class="permission-card"><strong>${objectCounts.page}</strong><b>页面权限</b>控制共享页面是否可进入 · page.*:view</div><div class="permission-card"><strong>${objectCounts.menu}</strong><b>菜单权限</b>控制导航入口是否展示 · menu.*:view</div><div class="permission-card"><strong>${objectCounts.business}</strong><b>业务权限</b>监听器触发后独立校验 · 对象:操作</div></div>`;
  return heading() + overview + notice("<strong>权限来源为用户所有角色授权的并集。</strong> 控制对象与操作分表存储，矩阵仅展示后端支持的组合。系统管理员关键管理权限受保护。") + `<div class="tabs" role="tablist" aria-label="权限管理"><button class="tab ${S.rbacTab === "matrix" ? "active" : ""}" data-action="rbac-tab" data-tab="matrix" role="tab" aria-selected="${S.rbacTab === "matrix"}">角色权限矩阵</button><button class="tab ${S.rbacTab === "users" ? "active" : ""}" data-action="rbac-tab" data-tab="users" role="tab" aria-selected="${S.rbacTab === "users"}">用户角色分配</button></div>` + (S.rbacTab === "matrix" ? matrixPanel() : usersPanel()) + permissionStrip();
}

function matrixPanel() {
  const data = S.data.rbac;
  const assigned = new Set(data.role_permissions[String(S.roleId)] || []);
  const supported = new Set(data.permissions.map(permission => `${permission.object_code}:${permission.operation_code}`));
  const ops = data.operations;
  const kindNames = { page: "01 · 页面控制对象 PAGE", menu: "02 · 菜单控制对象 MENU", business: "03 · 业务控制对象 BUSINESS" };
  let body = "";
  ["page", "menu", "business"].forEach(kind => {
    body += `<tr class="kind-row"><td colspan="${ops.length + 1}">${kindNames[kind]}</td></tr>`;
    data.objects.filter(object => object.kind === kind).forEach(object => {
      body += `<tr><td><strong>${h(object.name)}</strong><small class="event-code">${h(object.code)}</small></td>${ops.map(operation => { const key = `${object.code}:${operation.code}`; return `<td>${supported.has(key) ? `<input class="matrix-check" type="checkbox" name="permissions" value="${h(key)}" aria-label="${h(object.name)}：${h(operation.name)}" ${assigned.has(key) ? "checked" : ""} ${!can("rbac:manage") ? "disabled" : ""}>` : '<span class="unsupported" aria-label="不支持此组合">—</span>'}</td>`; }).join("")}</tr>`;
    });
  });
  return `<form id="permission-form" data-source-id="rbac.save_permissions" class="panel"><div class="rbac-header"><div><label for="role-selector" style="font-size:10px;color:var(--muted)">选择配置角色</label><select id="role-selector">${data.roles.map(role => `<option value="${Number(role.id)}" ${Number(role.id) === Number(S.roleId) ? "selected" : ""}>${h(role.name)} · ${h(role.code)}</option>`).join("")}</select></div><span class="rbac-summary">已勾选 <strong id="matrix-count">${assigned.size}</strong> 项权限 · ${can("rbac:manage") ? "可编辑" : "只读"}</span></div>${table(["控制对象 / 操作", ...ops.map(operation => h(operation.name))], body, "matrix-table")}<div class="rbac-footer"><p>保存后立即生效。管理权限变更以事务提交，防止失去系统管理入口。</p>${can("rbac:manage") ? '<button class="button primary" type="submit" data-source-id="rbac.save_permissions">保存角色权限</button>' : '<span class="role-tag">缺少 rbac:manage · 仅可查看</span>'}</div><p class="form-error" style="padding:0 22px" role="alert"></p></form>`;
}

function usersPanel() {
  const data = S.data.rbac;
  return `<section class="panel"><div class="panel-head"><h2>用户与多角色分配 <small>USER ROLES</small></h2><span class="result-count">${data.users.length} 个用户</span></div>${table(["用户", "登录名", "角色（权限取并集）", "操作"], data.users.map(user => `<tr><td><strong>${h(user.display_name)}</strong>${Number(user.id) === Number(S.user.id) ? '<small>当前用户</small>' : ""}</td><td class="event-code">${h(user.username)}</td><td><div class="role-options">${data.roles.filter(role => user.role_ids.includes(role.id)).map(role => `<span class="role-tag">${h(role.name)}</span>`).join("")}</div></td><td>${can("rbac:manage") ? eventButton("rbac.assign_roles", "分配角色", user.id) : '<span class="muted">只读</span>'}</td></tr>`).join(""))}<div class="panel-footer">◇ 用户至少保留一个角色；系统始终保留至少一名管理员。</div></section>`;
}

function renderAudit() {
  const events = S.data.events;
  const tabs = `<div class="tabs" role="tablist" aria-label="审计视图"><button class="tab ${S.auditTab === "audit" ? "active" : ""}" data-action="audit-tab" data-tab="audit" role="tab" aria-selected="${S.auditTab === "audit"}">操作审计记录</button><button class="tab ${S.auditTab === "events" ? "active" : ""}" data-action="audit-tab" data-tab="events" role="tab" aria-selected="${S.auditTab === "events"}">事件监听与绑定</button></div>`;
  const bindingRows = (events.bindings || []).map(binding => `<tr><td><strong class="event-code">${h(binding.source_id)}</strong></td><td>${h(binding.event_type)}</td><td><span class="event-code">${h(binding.object_code)}:${h(binding.operation_code)}</span></td><td class="event-code">${h(binding.handler)}</td></tr>`).join("");
  const bindings = `<section class="panel bindings-panel"><div class="panel-head"><h2>固定事件注册表 <small>EVENT REGISTRY</small></h2><span class="result-count">${(events.bindings || []).length} 个绑定</span></div>${table(["事件源 source_id", "事件类型", "控制对象 × 操作", "业务处理器"], bindingRows)}<div class="panel-footer"><div class="binding-flow"><code>DOM 事件</code>→<code>EventListener</code>→<code>dispatch(source_id)</code>→<code>RBAC 校验</code>→<code>业务处理器</code>→<code>审计</code></div></div></section>`;
  return heading('<button class="button" data-action="refresh">↻ 刷新记录</button>') + notice("<strong>事件源与控制对象的对应关系在服务端固定注册。</strong> 接口忽略调用方自称的权限；授权拒绝及输入错误同样写入审计记录，审计不记录密码与会话秘密。") + tabs + (S.auditTab === "events" ? bindings + auditTable(events.recent || [], "最近事件响应") : auditTable(S.data.audit, "操作审计记录")) + permissionStrip();
}

function auditTable(rows, title) {
  return `<section class="panel"><div class="panel-head"><h2>${title} <small>LAST 200 EVENTS</small></h2><span class="result-count">${rows.length} 条</span></div>${rows.length ? table(["发生时间 / 操作人", "固定事件源", "授权目标", "对象记录", "结果", "详情"], rows.map(row => `<tr><td>${dateTime(row.created_at)}<small>${h(row.actor_name || "匿名")}</small></td><td><strong class="event-code">${h(row.source_id)}</strong><small>${h(row.event_type)}</small></td><td class="event-code">${h(row.object_code)}:${h(row.operation_code)}</td><td>${row.target_id === null || row.target_id === undefined ? "—" : h(row.target_id)}</td><td>${statusTag(row.outcome)}</td><td class="audit-detail">${h(typeof row.detail === "object" ? JSON.stringify(row.detail) : row.detail)}</td></tr>`).join("")) : empty("暂无审计记录", "提交预约、审批、借还或权限变更后可在此查看事件执行情况。")}</section>`;
}

function openDialog(title, subtitle, content, source, submitText, options = {}) {
  dialogReturnFocus = document.activeElement;
  const dialog = $("#action-dialog");
  $("#dialog-content").innerHTML = `<form id="action-form" data-source-id="${source}"><div class="dialog-header"><div><h2 id="dialog-title">${h(title)}</h2><p>${h(subtitle)}</p></div><button class="icon-button" type="button" data-action="close-dialog" aria-label="关闭对话框">×</button></div><div class="dialog-body">${content}<p class="form-error dialog-error" role="alert"></p></div><div class="dialog-footer"><span class="event-caption">${h(source)}</span><div class="dialog-footer-actions"><button class="button" type="button" data-action="close-dialog">取消</button><button class="button ${options.danger ? "danger" : "primary"}" type="submit" data-source-id="${source}">${h(submitText)}</button></div></div></form>`;
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => { $("input:not([type=hidden]), select, textarea", dialog)?.focus(); });
}

function field(id, title, input, full = false, hint = "") { return `<div class="form-field ${full ? "full" : ""}"><label for="${id}">${title}</label>${input}${hint ? `<p class="field-hint">${hint}</p>` : ""}</div>`; }
function hidden(name, value) { return `<input type="hidden" name="${name}" value="${h(value)}">`; }
function localDateTime(date) { const value = new Date(date); return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }

async function openReservation(equipmentId) {
  if (!can("reservation:create")) return toast("当前身份没有预约申请权限。", true);
  try {
    if (!can("equipment:view") || !can("page.equipment:view")) return toast("预约需要读取设备，请管理员同时授予设备页面与查看权限。", true);
    S.data.equipment = await api("/api/equipment");
    const available = S.data.equipment.filter(row => row.status === "available");
    if (!available.length) return toast("当前没有可预约设备，请联系设备管理员。", true);
    const start = new Date(Date.now() + 24 * 60 * 60 * 1000); start.setMinutes(0, 0, 0);
    const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);
    const content = `<div class="form-grid">${field("reserve-equipment", "选择实验设备", `<select id="reserve-equipment" name="equipment_id" required>${available.map(row => `<option value="${Number(row.id)}" ${Number(row.id) === Number(equipmentId) ? "selected" : ""}>${h(row.name)} · ${h(row.code)} · ${h(row.location)}</option>`).join("")}</select>`, true)}${field("reserve-start", "实验开始时间", `<input id="reserve-start" name="start_at" type="datetime-local" required value="${localDateTime(start)}" min="${localDateTime(new Date())}">`)}${field("reserve-end", "实验结束时间", `<input id="reserve-end" name="end_at" type="datetime-local" required value="${localDateTime(end)}" min="${localDateTime(new Date())}">`)}${field("reserve-purpose", "实验用途", '<textarea id="reserve-purpose" name="purpose" required maxlength="500" placeholder="请填写实验内容、课程或项目名称（2—500 字）"></textarea>', true, "预约按实际设备区分；时间区间前闭后开，结束时刻可衔接下一份预约。")}</div>` + notice("提交后进入待审批状态；同一设备的有效预约不可时间重叠。本人申请不可由本人审批。");
    openDialog("预约实验设备", "填写实验安排，由指导教师审批后办理领用。", content, "reservation.submit", "提交预约");
  } catch (error) { toast(error.message, true); }
}

function openEquipment(id) {
  if (!can("equipment:update")) return toast("当前身份没有设备维护权限。", true);
  const row = S.data.equipment?.find(item => Number(item.id) === Number(id)) || {};
  const content = hidden("id", row.id || "") + `<div class="form-grid">${field("device-code", "设备编号", `<input id="device-code" name="code" value="${h(row.code || "")}" required maxlength="40" placeholder="如 LAB-007">`)}${field("device-name", "设备名称", `<input id="device-name" name="name" value="${h(row.name || "")}" required maxlength="100" placeholder="如 数字示波器">`)}${field("device-category", "设备分类", `<input id="device-category" name="category" value="${h(row.category || "")}" required maxlength="60" placeholder="如 电子测量">`)}${field("device-location", "存放位置", `<input id="device-location" name="location" value="${h(row.location || "")}" required maxlength="100" placeholder="如 实验楼 A302">`)}${field("device-status", "设备状态", `<select id="device-status" name="status"><option value="available" ${row.status !== "maintenance" ? "selected" : ""}>可预约</option><option value="maintenance" ${row.status === "maintenance" ? "selected" : ""}>维护中</option></select>`, true, "维护中的设备暂停新预约；存在有效预约或未归还借用时不能切换为维护中。")}${field("device-description", "设备说明", `<textarea id="device-description" name="description" maxlength="1000" placeholder="规格、适用实验及使用注意事项">${h(row.description || "")}</textarea>`, true)}</div>`;
  openDialog(row.id ? "维护实验设备" : "登记实验设备", "每条设备记录对应一台实物，以便独立检查预约冲突。", content, "equipment.save", "保存设备");
}

function reservationSummary(row) { return `<div class="reservation-summary"><b>${h(row.equipment_name)}</b> · 预约 #${Number(row.id)}<br>申请人：${h(row.applicant_name)}<br>实验安排：${dateTime(row.start_at)} 至 ${dateTime(row.end_at)}<br>用途：${h(row.purpose)}</div>`; }

function openEvent(source, id) {
  if (!supportedEvents.has(source)) return;
  const operation = { "equipment.save": "equipment:update", "reservation.submit": "reservation:create", "reservation.approve": "reservation:approve", "reservation.reject": "reservation:reject", "reservation.cancel": "reservation:cancel", "loan.checkout": "loan:checkout", "loan.return": "loan:return", "rbac.assign_roles": "rbac:manage" }[source];
  if (operation && !can(operation)) return toast(`缺少业务权限 ${operation}。`, true);
  if (source === "equipment.save") return openEquipment(id);
  if (source === "reservation.submit") return openReservation(id);
  if (source === "rbac.assign_roles") {
    const user = S.data.rbac.users.find(item => Number(item.id) === Number(id));
    if (!user) return;
    const content = hidden("user_id", user.id) + `<p style="font-size:12px;margin-bottom:18px">为 <strong>${h(user.display_name)}</strong>（${h(user.username)}）选择一个或多个角色。</p><div class="role-checkboxes">${S.data.rbac.roles.map(role => `<label><input type="checkbox" name="role_ids" value="${Number(role.id)}" ${user.role_ids.includes(role.id) ? "checked" : ""}><span>${h(role.name)}<small class="muted" style="display:block">${h(role.code)}</small></span></label>`).join("")}</div><p class="field-hint" style="margin-top:17px">角色权限取并集。至少保留一个角色，系统不可移除最后一名管理员。</p>`;
    return openDialog("分配用户角色", "角色变更立即影响对应用户的服务端授权。", content, source, "保存角色分配");
  }
  if (source === "loan.return") {
    const row = S.data.loans.find(item => Number(item.id) === Number(id));
    if (!row) return;
    return openDialog("办理设备归还", "请核对设备实物并记录归还检查情况。", hidden("id", row.id) + `<div class="reservation-summary"><b>${h(row.equipment_name)}</b> · 借用 #${Number(row.id)}<br>借用人：${h(row.applicant_name)}<br>领用时间：${dateTime(row.checkout_at)}</div>` + field("return-condition", "归还检查记录", '<textarea id="return-condition" name="condition_note" required maxlength="1000" placeholder="如：设备、配件齐全，外观正常，功能检查通过。"></textarea>', false, "归还检查记录必填，将连同操作人写入借用记录。"), source, "确认归还");
  }
  const row = S.data.reservations.find(item => Number(item.id) === Number(id));
  if (!row) return;
  let content = hidden(source === "loan.checkout" ? "reservation_id" : "id", row.id) + reservationSummary(row);
  if (source === "reservation.approve") content += field("review-note", "审批备注（可选）", '<textarea id="review-note" name="note" maxlength="500" placeholder="可填写使用指导或实验要求"></textarea>');
  if (source === "reservation.reject") content += field("reject-note", "拒绝原因", '<textarea id="reject-note" name="note" required maxlength="500" placeholder="请说明拒绝原因，便于申请人调整实验安排"></textarea>');
  if (source === "reservation.cancel") content += notice("确认取消此预约？取消后将释放对应设备的预约时段。", true);
  if (source === "loan.checkout") content += field("checkout-condition", "领用检查记录（可选）", '<textarea id="checkout-condition" name="condition_note" maxlength="1000" placeholder="如：设备功能正常、配件齐全。"></textarea>', false, "只可领用已批准且未结束的预约；设备不能存在另一笔未归还借用。");
  const subtitles = { "reservation.approve": "核对实验用途与设备安排，批准后可办理领用。", "reservation.reject": "拒绝后记录审批人和原因，释放预约时段。", "reservation.cancel": "仅限本人预约或具备额外管理权限的用户。", "loan.checkout": "核对预约与实物后，登记设备领用。" };
  openDialog(eventTitles[source], subtitles[source], content, source, source === "reservation.cancel" ? "确认取消预约" : source === "loan.checkout" ? "确认领用" : "确认" + (source.endsWith("approve") ? "批准" : "拒绝"), { danger: source.endsWith("reject") || source.endsWith("cancel") });
}

function formPayload(source, form) {
  const values = new FormData(form);
  if (source === "rbac.save_permissions") return { role_id: Number(S.roleId), permissions: values.getAll("permissions") };
  if (source === "rbac.assign_roles") return { user_id: Number(values.get("user_id")), role_ids: values.getAll("role_ids").map(Number) };
  const data = Object.fromEntries(values.entries());
  ["id", "equipment_id", "reservation_id"].forEach(key => { if (data[key] !== undefined) { if (data[key] === "") delete data[key]; else data[key] = Number(data[key]); } });
  Object.keys(data).forEach(key => { if (typeof data[key] === "string") data[key] = data[key].trim(); });
  return data;
}

async function dispatch(source, payload, form) {
  if (!supportedEvents.has(source)) return toast("未知事件源，已停止操作。", true);
  const submit = $("button[type=submit]", form);
  const error = $(".form-error", form);
  if (error) error.textContent = "";
  const previousText = submit.textContent;
  submit.disabled = true; submit.textContent = "正在保存…";
  try {
    await api("/api/events", { method: "POST", body: { source_id: source, payload } });
    if ($("#action-dialog").open) $("#action-dialog").close();
    if (source.startsWith("rbac.")) applySession(await api("/api/me"));
    toast(`${eventTitles[source]}成功。`);
    await go(S.page);
  } catch (exception) {
    if (error && document.contains(error)) error.textContent = exception.message;
    else toast(exception.message, true);
  } finally {
    if (document.contains(submit)) { submit.disabled = false; submit.textContent = previousText; }
  }
}

function toast(message, error = false) {
  const region = $("#toast-region");
  const element = document.createElement("div");
  element.className = `toast ${error ? "error" : ""}`;
  const symbol = document.createElement("span"); symbol.className = "toast-icon"; symbol.textContent = error ? "△" : "✓";
  const content = document.createElement("span"); content.textContent = message;
  const close = document.createElement("button"); close.type = "button"; close.setAttribute("aria-label", "关闭消息"); close.textContent = "×"; close.addEventListener("click", () => element.remove());
  element.append(symbol, content, close); region.append(element);
  while (region.children.length > 3) region.firstElementChild.remove();
  setTimeout(() => element.remove(), error ? 9000 : 4500);
}

async function exportReservations(button) {
  button.disabled = true;
  try {
    const response = await fetch("/api/export/reservations", { credentials: "same-origin" });
    if (!response.ok) { const data = await response.json(); throw new Error(data.error?.message || "导出失败。"); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = "LabReserve_预约记录.csv"; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("预约记录已导出为 CSV。");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

document.addEventListener("click", async event => {
  const button = event.target.closest("button, a[data-nav]");
  if (!button || button.disabled) return;
  if (button.dataset.demo) { $("#username").value = button.dataset.demo; $("#password").value = "Lab@2026!"; $("#login-error").textContent = ""; $("#login-form button[type=submit]").focus(); return; }
  if (button.dataset.nav) return go(button.dataset.nav);
  if (button.dataset.sourceId && button.type !== "submit") return openEvent(button.dataset.sourceId, Number(button.dataset.id));
  const action = button.dataset.action;
  if (action === "close-dialog") $("#action-dialog").close();
  if (action === "open-reservation") await openReservation(Number(button.dataset.equipmentId));
  if (action === "open-equipment") openEquipment(Number(button.dataset.id));
  if (action === "refresh") await go(S.page);
  if (action === "export") await exportReservations(button);
  if (action === "rbac-tab") { S.rbacTab = button.dataset.tab; renderPage(); }
  if (action === "audit-tab") { S.auditTab = button.dataset.tab; renderPage(); }
});

document.addEventListener("submit", async event => {
  const form = event.target;
  if (form.id === "login-form") {
    event.preventDefault();
    const button = $("button[type=submit]", form); button.disabled = true; button.textContent = "正在登录…"; $("#login-error").textContent = "";
    try { applySession(await api("/api/login", { method: "POST", body: { username: $("#username").value.trim(), password: $("#password").value } })); const preferred = location.hash.slice(1); await go(Object.hasOwn(pages, preferred) ? preferred : "dashboard"); }
    catch (error) { $("#login-error").textContent = error.message; }
    finally { button.disabled = false; button.innerHTML = '登录工作台 <span>→</span>'; }
    return;
  }
  if (form.dataset.sourceId) {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const source = form.dataset.sourceId;
    const payload = formPayload(source, form);
    const error = $(".form-error", form);
    if (source === "reservation.submit" && payload.end_at <= payload.start_at) { error.textContent = "实验结束时间必须晚于开始时间。"; return; }
    if (source === "rbac.assign_roles" && !payload.role_ids.length) { error.textContent = "请至少选择一个角色。"; return; }
    await dispatch(source, payload, form);
  }
});

document.addEventListener("input", event => {
  if (event.target.dataset.filter === "search") updateFilter(event.target);
  if (event.target.classList.contains("matrix-check")) { const count = $("#matrix-count"); if (count) count.textContent = $$('.matrix-check:checked').length; }
});
document.addEventListener("change", event => {
  if (event.target.dataset.filter) updateFilter(event.target);
  if (event.target.id === "role-selector") { S.roleId = Number(event.target.value); renderPage(); }
});

function updateFilter(input) {
  const page = input.dataset.page;
  S.filters[page] = { ...(S.filters[page] || {}), [input.dataset.filter]: input.value };
  const renderers = { equipment: equipmentResults, reservations: reservationResults, loans: loanResults };
  if ($("#filter-results") && renderers[page]) $("#filter-results").innerHTML = renderers[page]();
}

$("#menu-toggle").addEventListener("click", () => { const open = $("#sidebar").classList.toggle("open"); $("#menu-toggle").setAttribute("aria-expanded", String(open)); });
document.addEventListener("click", event => { if (window.innerWidth <= 700 && !event.target.closest("#sidebar, #menu-toggle")) { $("#sidebar").classList.remove("open"); $("#menu-toggle").setAttribute("aria-expanded", "false"); } });
$("#logout-button").addEventListener("click", async () => { try { await api("/api/logout", { method: "POST", body: {} }); showLogin(); toast("已退出登录。"); } catch (error) { toast(error.message, true); } });
$("#action-dialog").addEventListener("close", () => { if (dialogReturnFocus?.isConnected) dialogReturnFocus.focus(); });
$("#action-dialog").addEventListener("click", event => { if (event.target === $("#action-dialog")) { const bounds = event.target.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.target.close(); } });
window.addEventListener("hashchange", () => { if (S.user) go(location.hash.slice(1), false); });
document.addEventListener("keydown", event => { if (event.key === "Escape") { $("#sidebar").classList.remove("open"); $("#menu-toggle").setAttribute("aria-expanded", "false"); } });

(async () => {
  try { applySession(await api("/api/me")); const preferred = location.hash.slice(1); await go(Object.hasOwn(pages, preferred) ? preferred : "dashboard"); }
  catch (_) { showLogin(); }
})();
