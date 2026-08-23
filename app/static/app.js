const state = {
  profile: null,
  profileLoaded: false,
  jobs: [],
  jobsPaging: { page: 1, pageSize: 20, total: 0, pages: 1, sort: 'score_desc' },
  applications: [],
  blockers: [],
  skillsOverview: null,
  answerLibrary: [],
  answerLibrarySaved: [],
  answersDirty: false,
  sources: [],
  dashboard: null,
  autoApplyQueue: { current: null, waiting: [], waiting_count: 0, queued_count: 0, total_active_count: 0 },
  activeView: 'dashboard',
  applicationSection: 'queue',
  careerTracks: [],
  activeCareerTrack: 'computer_science',
};


const CAREER_TRACK_UI = Object.freeze({
  computer_science: {
    key: 'computer_science', symbol: 'CS', label: 'מדעי המחשב', shortLabel: 'מדמ״ח', themeClass: 'track-computer-science',
    description: 'פיתוח תוכנה, אלגוריתמים, תשתיות, AI ומחקר',
    eyebrow: 'סוכן חיפוש · מדעי המחשב', tagline: 'חיפוש משרות · מדעי המחשב',
    searchPlaceholder: 'חיפוש תפקיד, חברה או טכנולוגיה', skillsLegend: 'טכנולוגיות וכישורים',
    desiredTitles: [
      ['software engineer','Software Engineer'], ['backend','Backend'], ['frontend','Frontend'], ['full stack','Full Stack'],
      ['automation','Automation'], ['devops','DevOps'], ['data engineer','Data Engineer'], ['embedded','Embedded'], ['qa','QA'],
      ['product','Product'], ['r&d','R&D'], ['research engineer','Research Engineer'], ['research scientist','Research Scientist'],
      ['applied scientist','Applied Scientist'], ['algorithm','Algorithms'], ['ai engineer','AI Engineer'],
      ['machine learning engineer','Machine Learning Engineer'], ['ai research','AI Research']
    ],
    skills: [['Python','Python'],['JavaScript','JavaScript'],['TypeScript','TypeScript'],['React','React'],['Java','Java'],['C++','C++'],['C#','C#'],['SQL','SQL'],['Docker','Docker'],['Kubernetes','Kubernetes'],['AWS','AWS'],['Linux','Linux'],['Git','Git'],['REST API','REST API']],
    desiredPlaceholder: 'למשל: Developer Tools, Integration', skillsPlaceholder: 'מופרדים בפסיקים',
  },
  industrial_engineering: {
    key: 'industrial_engineering', symbol: 'IE', label: 'תעשייה וניהול', shortLabel: 'תעו״נ', themeClass: 'track-industrial-engineering',
    description: 'תפעול, שרשרת אספקה, אנליזה, BI, פרויקטים ותהליכים',
    eyebrow: 'סוכן חיפוש · תעשייה וניהול', tagline: 'חיפוש משרות · תעשייה וניהול',
    searchPlaceholder: 'חיפוש תפקיד, חברה או טכנולוגיה', skillsLegend: 'טכנולוגיות וכישורים',
    desiredTitles: [
      ['industrial engineer','Industrial Engineer'], ['business analyst','Business Analyst'], ['data analyst','Data Analyst'], ['bi analyst','BI Analyst'],
      ['operations analyst','Operations Analyst'], ['business operations','Business Operations'], ['supply chain','Supply Chain'],
      ['supply chain analyst','Supply Chain Analyst'], ['production planner','Production Planner'], ['material planner','Material Planner'],
      ['demand planner','Demand Planner'], ['procurement','Procurement / Buyer'], ['logistics','Logistics'], ['pmo','PMO'],
      ['project manager','Project Manager'], ['program manager','Program Manager'], ['process improvement','Process Improvement'],
      ['operational excellence','Operational Excellence'], ['manufacturing engineer','Manufacturing Engineer'], ['quality engineer','Quality Engineer'], ['npi','NPI']
    ],
    skills: [['Excel','Excel'],['SQL','SQL'],['Power BI','Power BI'],['Tableau','Tableau'],['Data Analysis','Data Analysis'],['ERP','ERP'],['SAP','SAP'],['Priority','Priority'],['Lean','Lean'],['Six Sigma','Six Sigma'],['Process Improvement','Process Improvement'],['Project Management','Project Management'],['Supply Chain','Supply Chain'],['Procurement','Procurement'],['Production Planning','Production Planning'],['Operations Research','Operations Research'],['Statistics','Statistics'],['Power Query','Power Query'],['VBA','VBA'],['Python','Python']],
    desiredPlaceholder: 'למשל: Developer Tools, Integration', skillsPlaceholder: 'מופרדים בפסיקים',
  },
  electrical_engineering: {
    key: 'electrical_engineering', symbol: 'EE', label: 'הנדסת חשמל', shortLabel: 'חשמל', themeClass: 'track-electrical-engineering',
    description: 'חומרה, שבבים, FPGA, Embedded, Verification, RF ומערכות',
    eyebrow: 'סוכן חיפוש · הנדסת חשמל', tagline: 'חיפוש משרות · הנדסת חשמל',
    searchPlaceholder: 'חיפוש חומרה, שבבים, FPGA, Embedded או חברה', skillsLegend: 'טכנולוגיות וכישורי חשמל וחומרה',
    desiredTitles: [
      ['electrical engineer','Electrical Engineer'],['hardware engineer','Hardware Engineer'],['fpga engineer','FPGA Engineer'],['asic','ASIC / VLSI'],
      ['verification engineer','Verification Engineer'],['embedded engineer','Embedded Engineer'],['firmware engineer','Firmware Engineer'],
      ['analog engineer','Analog Engineer'],['rf engineer','RF Engineer'],['board design','Board Design'],['silicon','Silicon Engineer'],['soc','SoC Engineer']
    ],
    skills: [['C','C'],['C++','C++'],['Python','Python'],['Verilog','Verilog'],['SystemVerilog','SystemVerilog'],['VHDL','VHDL'],['FPGA','FPGA'],['UVM','UVM'],['Embedded','Embedded'],['Linux','Linux'],['MATLAB','MATLAB'],['PCB','PCB'],['Analog Design','Analog Design'],['RF','RF'],['Git','Git']],
    desiredPlaceholder: 'למשל: RTL Design, Signal Integrity', skillsPlaceholder: 'מופרדים בפסיקים',
  },
});

window.jobPilotReloadAfterCareerSwitch = window.jobPilotReloadAfterCareerSwitch || refreshAfterCareerSwitch;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let scanPollActive = false;
let lastScanCompleted = 0;
let lastScanReport = null;

const authState = {
  config: null,
  session: null,
  user: null,
  capabilities: { application_agent: true },
  storageKey: 'jobpilot-cloud-session-v1',
};

const parseJwt = (token = '') => {
  try {
    const payload = token.split('.')[1];
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(atob(normalized).split('').map((char) => `%${(`00${char.charCodeAt(0).toString(16)}`).slice(-2)}`).join('')));
  } catch {
    return {};
  }
};

const authHeaders = () => authState.session?.access_token ? { Authorization: `Bearer ${authState.session.access_token}` } : {};
const applicationAgentAllowed = () => authState.config?.mode !== 'supabase' || authState.capabilities?.application_agent !== false;
const manualScanAllowed = () => authState.config?.mode !== 'supabase' || authState.capabilities?.manual_scan === true;
const sourceManagementAllowed = () => authState.config?.mode !== 'supabase' || authState.capabilities?.developer_tools === true;

const saveAuthSession = (session) => {
  authState.session = session?.access_token ? session : null;
  if (authState.session) localStorage.setItem(authState.storageKey, JSON.stringify(authState.session));
  else localStorage.removeItem(authState.storageKey);
};

const supabaseFetch = async (path, options = {}) => {
  const base = String(authState.config?.supabase_url || '').replace(/\/$/, '');
  const key = authState.config?.supabase_publishable_key || '';
  if (!base || !key) throw new Error('Supabase authentication is not configured');
  return fetch(`${base}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: key,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
};

async function refreshCloudSession() {
  const refreshToken = authState.session?.refresh_token;
  if (!refreshToken) return false;
  const response = await supabaseFetch('/token?grant_type=refresh_token', {
    method: 'POST', body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) { saveAuthSession(null); return false; }
  saveAuthSession(await response.json());
  return true;
}

async function ensureCloudAccessToken() {
  if (authState.config?.mode !== 'supabase') return '';
  if (!authState.session) return '';
  const claims = parseJwt(authState.session.access_token);
  const expires = Number(claims.exp || 0) * 1000;
  if (!expires || expires - Date.now() < 60_000) await refreshCloudSession();
  return authState.session?.access_token || '';
}

const api = async (path, options = {}) => {
  const method = String(options.method || 'GET').toUpperCase();
  const guestWriteAllowed = path === '/api/career-tracks/active' && method === 'PUT';
  if (authState.user?.is_guest && !['GET', 'HEAD', 'OPTIONS'].includes(method) && !guestWriteAllowed) {
    throw new Error('מצב אורח הוא לקריאה בלבד. התחבר לחשבון כדי לשמור, לסרוק או להגיש.');
  }
  if (authState.config?.mode === 'supabase') await ensureCloudAccessToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...authHeaders(),
      ...(adminPreviewActive() ? { 'X-JobPilot-Preview-Role': 'user' } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let message = await response.text();
    try { message = JSON.parse(message).detail || message; } catch { /* keep body */ }
    if (response.status === 401 && authState.config?.mode === 'supabase') {
      saveAuthSession(null);
      showAuthGate('פג תוקף ההתחברות. התחבר שוב.');
    }
    throw new Error(message || `שגיאת שרת ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
};

const esc = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[char]));

const safeUrl = (value = '') => {
  try {
    const raw = String(value);
    const absolute = /^[a-z][a-z0-9+.-]*:/i.test(raw);
    const url = absolute ? new URL(raw) : new URL(raw, window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? esc(url.href) : '#';
  } catch {
    return '#';
  }
};


function showAuthGate(message = '', tone = 'error') {
  const gate = $('#auth-gate');
  if (!gate) return;
  gate.hidden = false;
  $('#app-shell')?.setAttribute('aria-hidden', 'true');
  const note = $('#auth-message');
  if (note) { note.textContent = message; note.className = `auth-message ${message ? tone : ''}`; }
  requestAnimationFrame(initInteractiveLogos);
}

function hideAuthGate() {
  $('#auth-gate') && ($('#auth-gate').hidden = true);
  $('#app-shell')?.removeAttribute('aria-hidden');
}

function restoreStoredSession() {
  try { saveAuthSession(JSON.parse(localStorage.getItem(authState.storageKey) || 'null')); }
  catch { saveAuthSession(null); }
}

function cleanOAuthCallbackUrl() {
  const query = new URLSearchParams(location.search);
  ['error', 'error_code', 'error_description', 'code', 'state'].forEach((key) => query.delete(key));
  const suffix = query.toString();
  history.replaceState({}, document.title, `${location.pathname}${suffix ? `?${suffix}` : ''}`);
}

function captureOAuthSession() {
  const hashParams = new URLSearchParams(location.hash.replace(/^#/, ''));
  const queryParams = new URLSearchParams(location.search);
  const callbackError = hashParams.get('error_description') || queryParams.get('error_description')
    || hashParams.get('error') || queryParams.get('error') || '';
  if (callbackError) {
    cleanOAuthCallbackUrl();
    return { handled: true, error: callbackError };
  }

  const accessToken = hashParams.get('access_token');
  if (!accessToken) return { handled: false, error: '' };
  saveAuthSession({
    access_token: accessToken,
    refresh_token: hashParams.get('refresh_token') || '',
    token_type: hashParams.get('token_type') || 'bearer',
    expires_in: Number(hashParams.get('expires_in') || 3600),
  });
  cleanOAuthCallbackUrl();
  return { handled: true, error: '' };
}

function googleAuthFailureMessage(error, email = '') {
  const raw = String(error?.message || error || '').trim();
  const account = email ? ` (${email})` : '';
  if (/not invited/i.test(raw)) return `החשבון${account} אומת מול Google, אבל עדיין לא הוזמן ל-JobPilot.`;
  if (/reached its .*user limit|user limit/i.test(raw)) return 'ההתחברות עם Google הצליחה, אבל JobPilot הגיע למגבלת המשתמשים המורשים.';
  if (/session expired|invalid authenticated user|authentication required/i.test(raw)) return 'Google החזיר את החשבון, אבל ה-session לא אומת. נסה להתחבר שוב.';
  return raw ? `ההתחברות עם Google חזרה ל-JobPilot, אבל אימות החשבון נכשל: ${raw}` : 'ההתחברות עם Google לא הושלמה.';
}

async function verifyCloudSession({ throwOnError = false } = {}) {
  if (!authState.session) return false;
  try {
    await ensureCloudAccessToken();
    const result = await api('/api/auth/me');
    authState.user = result.user || null;
    authState.capabilities = result.capabilities || { application_agent: true };
    const scanButton = $('#scan-btn');
    if (scanButton) scanButton.hidden = !manualScanAllowed();
    const importButton = $('#import-job-btn');
    if (importButton) importButton.hidden = !manualScanAllowed();
    return Boolean(authState.user);
  } catch (error) {
    if (throwOnError) throw error;
    return false;
  }
}

function renderCloudAccount() {
  const button = $('#account-chip');
  const logout = $('#logout-action');
  const guestBanner = $('#guest-mode-banner');
  if (!button) return;
  if (authState.config?.mode !== 'supabase' || !authState.user) {
    button.hidden = true;
    if (logout) logout.hidden = true;
    if (guestBanner) guestBanner.hidden = true;
    document.body.classList.remove('guest-mode');
    return;
  }
  const guest = Boolean(authState.user.is_guest);
  button.hidden = false;
  if (logout) logout.hidden = false;
  if (guestBanner) guestBanner.hidden = !guest;
  document.body.classList.toggle('guest-mode', guest);
  const label = guest ? 'מצב אורח' : (authState.user.email || 'JobPilot');
  $('#account-email').textContent = label;
  $('#account-avatar').textContent = guest ? '◇' : (label.slice(0, 1).toUpperCase() || 'A');
  button.title = guest ? 'מצב אורח · צפייה בלבד' : `${label} · חשבון ענן`;
}

async function initAuthentication() {
  const response = await fetch('/api/auth/config', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('לא ניתן לטעון את הגדרות ההתחברות');
  authState.config = await response.json();
  if (authState.config.mode !== 'supabase') { hideAuthGate(); return true; }
  if (!authState.config.supabase_url || !authState.config.supabase_publishable_key) {
    showAuthGate('Cloud Mode פעיל אבל Supabase עדיין לא הוגדר בשרת.');
    return false;
  }
  const oauthCallback = captureOAuthSession();
  if (oauthCallback.error) {
    saveAuthSession(null);
    showAuthGate(`ההתחברות עם Google נכשלה: ${oauthCallback.error}`, 'error');
    return false;
  }
  if (!authState.session) restoreStoredSession();
  if (oauthCallback.handled && authState.session) {
    try {
      if (!await verifyCloudSession({ throwOnError: true })) throw new Error('JobPilot לא אישר את החשבון');
    } catch (error) {
      const email = String(parseJwt(authState.session?.access_token || '').email || '').trim();
      saveAuthSession(null);
      authState.user = null;
      showAuthGate(googleAuthFailureMessage(error, email), 'error');
      return false;
    }
  } else if (!await verifyCloudSession()) {
    showAuthGate('');
    return false;
  }
  hideAuthGate();
  renderCloudAccount();
  return true;
}

async function cloudEmailLogin(email, password) {
  const response = await supabaseFetch('/token?grant_type=password', {
    method: 'POST', body: JSON.stringify({ email, password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.msg || payload.error_description || payload.message || 'ההתחברות נכשלה');
  saveAuthSession(payload);
  if (!await verifyCloudSession()) throw new Error('החשבון אומת ב-Supabase אך JobPilot לא אישר גישה לחשבון הזה');
  hideAuthGate();
  renderCloudAccount();
  location.reload();
}

async function cloudSignup(email, password) {
  const response = await supabaseFetch('/signup', {
    method: 'POST', body: JSON.stringify({ email, password }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.msg || payload.message || 'יצירת החשבון נכשלה');
  if (payload.access_token) {
    saveAuthSession(payload);
    await verifyCloudSession();
    location.reload();
    return;
  }
  showAuthGate('החשבון נוצר. אם אימות אימייל פעיל ב-Supabase, אשר את ההודעה שנשלחה אליך ואז התחבר.', 'success');
}

async function cloudGuestLogin() {
  if (!authState.config?.guest_enabled) throw new Error('מצב אורח אינו פעיל כרגע');
  const response = await supabaseFetch('/signup', { method: 'POST', body: JSON.stringify({}) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.msg || payload.message || payload.error_description || '';
    if (/anonymous|disabled|signups/i.test(message)) {
      throw new Error('מצב אורח עדיין לא הופעל ב-Supabase. הפעל Allow anonymous sign-ins ונסה שוב.');
    }
    throw new Error(message || 'הכניסה כאורח נכשלה');
  }
  if (!payload.access_token) throw new Error('Supabase לא החזיר session למצב האורח');
  saveAuthSession(payload);
  if (!await verifyCloudSession({ throwOnError: true })) throw new Error('JobPilot לא הצליח לפתוח סביבת אורח');
  hideAuthGate();
  renderCloudAccount();
  location.reload();
}

function cloudGoogleLogin() {
  const base = String(authState.config?.supabase_url || '').replace(/\/$/, '');
  const key = authState.config?.supabase_publishable_key || '';
  if (!base || !key) return;
  const redirect = `${location.origin}${location.pathname}`;
  location.href = `${base}/auth/v1/authorize?provider=google&redirect_to=${encodeURIComponent(redirect)}`;
}

async function cloudSignOut() {
  const token = authState.session?.access_token;
  if (token) {
    try { await supabaseFetch('/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } }); } catch { /* local cleanup still wins */ }
  }
  saveAuthSession(null);
  authState.user = null;
  location.reload();
}

async function refreshAgentStatus() {
  if (authState.config?.mode !== 'supabase') return;
  if (authState.user?.is_guest) {
    const label = $('#agent-state');
    if (label) label.textContent = 'לא זמין במצב אורח';
    document.querySelector('.agent-dot')?.classList.add('restricted');
    return;
  }
  try {
    const status = await api('/api/agent/status');
    const label = $('#agent-state');
    if (label) label.textContent = status.available === false ? 'לא זמין בחשבון זה' : status.connected ? `מחובר · ${status.online}` : 'לא מחובר';
    document.querySelector('.agent-dot')?.classList.toggle('connected', Boolean(status.connected));
    document.querySelector('.agent-dot')?.classList.toggle('restricted', status.available === false);
  } catch { /* account may be signing out */ }
}

async function openCloudAccount() {
  if (authState.config?.mode !== 'supabase') return;
  const me = await api('/api/auth/me');
  if (me.user?.is_guest) {
    modal(`<span class="kicker">JobPilot Demo</span><h2>מצב אורח</h2>
      <p>זהו מצב צפייה בלבד. המשרות מגיעות מהקטלוג החי של החשבון הראשי, בלי לחשוף את סטטוסי ההגשה או המידע האישי שלו. אפשר לעבור בין מסלולים ולעיין במשרות, אך שינוי נתונים, סריקות והגשות חסומים.</p>
      <div class="modal-actions"><button class="btn danger-outline" type="button" onclick="cloudSignOut()">יציאה ממצב אורח</button></div>`);
    return;
  }
  const [devices, adminUsers] = await Promise.all([
    api('/api/agent-devices'),
    me.capabilities?.developer_tools === true ? api('/api/admin/users') : Promise.resolve(null),
  ]);
  const rows = (devices.devices || []).map((device) => `<div class="agent-device-row ${device.online ? 'online' : ''}">
    <i></i><span><strong>${esc(device.name)}</strong><small>${device.online ? 'מחובר עכשיו' : device.last_seen_at ? `נראה לאחרונה ${esc(new Date(device.last_seen_at).toLocaleString('he-IL'))}` : 'עדיין לא התחבר'} · ${esc(device.token_prefix)}…</small></span>
    ${device.enabled ? `<button class="btn danger-outline small" type="button" onclick="revokeAgentDevice(${device.id})">בטל</button>` : '<small>בוטל</small>'}
  </div>`).join('');
  const userRows = adminUsers ? (adminUsers.users || []).map((user) => `<div class="cloud-user-row">
    <span class="cloud-user-avatar">${esc((user.email || '?').slice(0, 1).toUpperCase())}</span>
    <span><strong>${esc(user.email || user.id)}</strong><small>${user.role === 'admin' ? 'Admin' : 'משתמש'} · ${user.last_seen_at ? `נראה לאחרונה ${esc(new Date(user.last_seen_at).toLocaleString('he-IL'))}` : 'טרם התחבר'}</small></span>
  </div>`).join('') : '';
  const adminSection = adminUsers ? `<div class="cloud-users-section">
    <div class="panel-head"><div><span class="kicker">גישה לקבוצה</span><h3>משתמשים ${adminUsers.count}/${adminUsers.max_users}</h3></div></div>
    <div class="cloud-user-list">${userRows}</div>
    <small class="cloud-users-note">הרשאות הצטרפות מנוהלות כרגע דרך JOBPILOT_ALLOWED_EMAILS בשרת.</small>
  </div>` : '';
  const agentSection = devices.available === false
    ? `<div class="agent-restricted-note"><strong>ה־worker מנוהל עבורך</strong><span>מנהל המערכת הגדיר את תשתית ההגשות המרכזית. אין בחשבון שלך token או הגדרת GitHub, ואפשר להגיש משרות נתמכות ישירות ברקע.</span></div>`
    : `<div class="panel-head"><div><span class="kicker">Application Agent</span><h3>מכשירי Agent</h3></div><button class="btn secondary small" type="button" onclick="createAgentDevice()">חבר Mac חדש</button></div><div class="agent-device-list">${rows || '<div class="empty-state"><strong>אין Agent מחובר</strong><span>צור token חד-פעמי וחבר את ה-Mac שלך.</span></div>'}</div>`;
  modal(`<span class="kicker">JobPilot Cloud</span><h2>החשבון והמכשירים שלך</h2>
    <p>${esc(me.user?.email || '')}</p>
    ${adminSection}
    ${agentSection}
    <div class="modal-actions"><button class="btn danger-outline" type="button" onclick="cloudSignOut()">התנתק מהחשבון</button></div>`);
}

async function createAgentDevice() {
  const name = prompt('שם למחשב / Agent', 'MacBook Pro') || 'Mac Agent';
  const result = await api('/api/agent-devices', { method: 'POST', body: JSON.stringify({ name }) });
  const token = result.token;
  const baseUrl = result.base_url || location.origin;
  modal(`<span class="kicker">Token חד-פעמי</span><h2>חיבור ${esc(name)}</h2>
    <p>העתק את ה-token עכשיו. מטעמי אבטחה JobPilot לא יציג אותו שוב.</p>
    <div class="agent-pair-token">${esc(token)}</div>
    <p>ב-Mac, בתוך תיקיית JobPilot, הפעל את פקודת החיבור ואז הדבק את ה-token כשהיא מבקשת אותו. ה-token לא יישמר ב-history של ה-Terminal:</p>
    <div class="agent-command">./configure-cloud-agent.sh ${esc(baseUrl)}</div>
    <p>לאחר ההגדרה הפעל <code>./start-agent.sh</code>.</p>
    <div class="modal-actions"><button class="btn secondary" type="button" onclick="navigator.clipboard.writeText('${esc(token)}'); toast('ה-token הועתק')">העתק token</button><button class="btn primary" type="button" onclick="openCloudAccount()">סיימתי</button></div>`);
}

async function revokeAgentDevice(id) {
  if (!confirm('לבטל את הגישה של ה-Agent הזה?')) return;
  await api(`/api/agent-devices/${id}`, { method: 'DELETE' });
  toast('גישה ל-Agent בוטלה');
  openCloudAccount();
}

function careerTrackUI(key = state.activeCareerTrack) {
  return CAREER_TRACK_UI[key] || CAREER_TRACK_UI.computer_science;
}

function applyCareerTrackTheme() {
  const config = careerTrackUI();
  document.body.classList.toggle('track-industrial-engineering', config.key === 'industrial_engineering');
  document.body.classList.toggle('track-computer-science', config.key === 'computer_science');
  document.body.classList.toggle('track-electrical-engineering', config.key === 'electrical_engineering');
  document.body.dataset.careerTrack = config.key;
  $('#career-track-symbol') && ($('#career-track-symbol').textContent = config.symbol);
  $('#career-track-label') && ($('#career-track-label').textContent = config.label);
  $('#career-eyebrow') && ($('#career-eyebrow').textContent = config.eyebrow);
  $('#brand-tagline') && ($('#brand-tagline').textContent = config.tagline);
  $('#job-search') && ($('#job-search').placeholder = config.searchPlaceholder);
  $('#skills-preference-legend') && ($('#skills-preference-legend').textContent = config.skillsLegend);
  $('#scan-btn') && ($('#scan-btn').textContent = `סרוק עכשיו · ${config.shortLabel}`);
  document.title = `JobPilot — ${config.label}`;
}

function preferenceOptionMarkup(field, values) {
  return values.map(([value, label]) => `<label><input type="checkbox" data-profile-option="${field}" value="${esc(value)}" /> ${esc(label)}</label>`).join('');
}

function renderCareerPreferenceOptions() {
  const config = careerTrackUI();
  const titles = $('#desired-title-options');
  const skills = $('#skill-options');
  if (titles) titles.innerHTML = preferenceOptionMarkup('desired_titles', config.desiredTitles);
  if (skills) skills.innerHTML = preferenceOptionMarkup('skills', config.skills);
  if ($('#desired-titles-custom')) $('#desired-titles-custom').placeholder = config.desiredPlaceholder;
  if ($('#skills-custom')) $('#skills-custom').placeholder = config.skillsPlaceholder;
  if (typeof bindPreferencePriorityDragging === 'function') bindPreferencePriorityDragging();
}

function renderCareerSwitcher() {
  const current = state.careerTracks.find((track) => track.key === state.activeCareerTrack);
  const config = careerTrackUI();
  const menu = $('#career-switcher-menu');
  if (!menu) return;
  $('#career-track-symbol').textContent = config.symbol;
  $('#career-track-label').textContent = current?.label || config.label;
  $('#career-switcher-trigger').title = `${current?.label || config.label} · סוכן חיפוש פעיל`;
  menu.innerHTML = state.careerTracks.map((track) => {
    const ui = CAREER_TRACK_UI[track.key] || { symbol: track.short_label || '•' };
    const active = track.key === state.activeCareerTrack;
    return `<button class="career-track-option ${active ? 'active' : ''}" type="button" role="menuitem" data-career-track="${esc(track.key)}" ${active ? 'aria-current="true"' : ''}>
      <span class="career-option-symbol">${esc(ui.symbol || track.short_label || '•')}</span>
      <span class="career-option-copy"><strong>${esc(track.label)}</strong><small>${esc(track.description || '')}</small><em>${active ? '● סוכן חיפוש פעיל' : '○ סוכן חיפוש כבוי'} · ${track.enabled_sources || 0} מקורות · ${track.jobs || 0} משרות</em></span>
      <i class="career-option-agent ${active ? 'on' : 'off'}" aria-hidden="true"></i>
    </button>`;
  }).join('') + `<div class="career-track-future"><span>＋</span><div><strong>מקצועות נוספים</strong><small>המבנה מוכן להוספת מסלולים נוספים בהמשך</small></div></div>`;
  $$('[data-career-track]', menu).forEach((button) => {
    button.onclick = () => switchCareerTrack(button.dataset.careerTrack);
  });
}

function setCareerMenu(open) {
  const menu = $('#career-switcher-menu');
  const trigger = $('#career-switcher-trigger');
  if (!menu || !trigger) return;
  menu.hidden = !open;
  trigger.setAttribute('aria-expanded', String(open));
  $('#career-switcher')?.classList.toggle('open', open);
}

async function loadCareerTracks() {
  const payload = await api('/api/career-tracks');
  state.careerTracks = payload.tracks || [];
  state.activeCareerTrack = payload.active_track || 'computer_science';
  applyCareerTrackTheme();
  renderCareerPreferenceOptions();
  renderCareerSwitcher();
  return payload;
}

async function switchCareerTrack(target) {
  if (!target || target === state.activeCareerTrack) { setCareerMenu(false); return; }
  const dirty = typeof getDirtyProfileFields === 'function' ? getDirtyProfileFields() : [];
  if (dirty.length || state.answersDirty) {
    const labels = dirty.map(profileFieldLabel).filter(Boolean);
    const details = [
      labels.length ? `לא נשמרו: ${labels.join(' · ')}` : '',
      state.answersDirty ? 'שאלות ההגשה כוללות שינויים שלא נשמרו' : '',
    ].filter(Boolean).join(' | ');
    toast(`אי אפשר להחליף מסלול עדיין. ${details}. שמור או בטל את השינויים ואז נסה שוב.`);
    return;
  }
  const targetTrack = state.careerTracks.find((track) => track.key === target);
  try {
    $('#career-switcher-trigger').disabled = true;
    const result = await api('/api/career-tracks/active', { method: 'PUT', body: JSON.stringify({ track: target }) });
    state.activeCareerTrack = result.active_track || target;
    state.careerTracks = result.tracks || state.careerTracks;
    state.profile = result.profile || null;
    applyCareerTrackTheme();
    renderCareerPreferenceOptions();
    renderCareerSwitcher();
    setCareerMenu(false);
    toast(`עברנו למסלול ${targetTrack?.label || careerTrackUI(target).label}. סוכן החיפוש הקודם כובה.`);
    window.setTimeout(() => window.jobPilotReloadAfterCareerSwitch(), 180);
  } catch (error) {
    toast(error.message);
  } finally {
    $('#career-switcher-trigger').disabled = false;
  }
}

async function refreshAfterCareerSwitch() {
  // A career-track toggle used to hard-reload the entire SPA. That repeated auth,
  // career-track, dashboard, profile and active-view requests at once and could
  // overwhelm a small cloud instance. Refresh only the data that actually changed.
  state.jobsPaging.page = 1;
  state.profileLoaded = false;
  await loadDashboard();
  if (state.activeView === 'dashboard') return;
  if (state.activeView === 'jobs') return loadJobs({ resetPage: true });
  if (state.activeView === 'applications') return state.applicationSection==='attention'?loadBlockers():loadApplications();
  if (state.activeView === 'skills') return loadSkills();
  if (state.activeView === 'sources') return loadSources();
  if (state.activeView === 'preferences' || state.activeView === 'profile') return loadProfile();
}

const JOB_DESCRIPTION_HEADINGS = [
  'about the role', 'about the position', 'about the team', 'about us', 'the role', 'the position',
  'what you’ll do', "what you'll do", 'what you will do', 'what you’ll bring', "what you'll bring",
  'responsibilities', 'your responsibilities', 'requirements', 'minimum requirements', 'qualifications',
  'minimum qualifications', 'preferred qualifications', 'what we’re looking for', "what we're looking for",
  'who you are', 'skills', 'experience', 'nice to have', 'preferred', 'benefits', 'why join us', 'why us',
  'day to day', 'day-to-day', 'job description', 'description', 'overview', 'key responsibilities'
];

function isJobDescriptionHeading(line = '') {
  const normalized = String(line).trim().replace(/[:：]+$/, '').toLowerCase();
  return JOB_DESCRIPTION_HEADINGS.includes(normalized);
}

function formatJobDescription(value = '') {
  const raw = String(value || '').replace(/\r\n?/g, '\n').trim();
  if (!raw) return '<div class="job-description-empty">אין תיאור</div>';

  // Add presentation-only line breaks around reliable structure markers. No words are removed.
  let text = raw
    .replace(/[ \t]*([•●▪◦])\s*/g, '\n$1 ')
    .replace(/([.!?])\s+(?=(?:Responsibilities|Requirements|Qualifications|Minimum Qualifications|Preferred Qualifications|About the Role|About the Team|What You(?:’|')ll Do|What We(?:’|')re Looking For|Benefits|Why Join Us)\s*:)/gi, '$1\n\n')
    .replace(/\s+(?=(?:Responsibilities|Requirements|Qualifications|Minimum Qualifications|Preferred Qualifications|Key Responsibilities)\s*:)/gi, '\n\n')
    .replace(/(Responsibilities|Requirements|Qualifications|Minimum Qualifications|Preferred Qualifications|Key Responsibilities|About the Role|About the Team|What You(?:’|')ll Do|What We(?:’|')re Looking For|Benefits|Why Join Us)\s*:\s*/gi, '\n\n$1:\n');

  const sourceLines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const lines = [];
  for (const line of sourceLines) {
    // ATS feeds sometimes flatten whole paragraphs into one line. Split only on sentence boundaries
    // and group them for readability while preserving every sentence and punctuation mark.
    if (line.length > 520 && !/^[•●▪◦*-]\s+/.test(line)) {
      const sentences = line.split(/(?<=[.!?])\s+(?=[A-Z0-9])/);
      if (sentences.length > 3) {
        for (let i = 0; i < sentences.length; i += 3) lines.push(sentences.slice(i, i + 3).join(' '));
        continue;
      }
    }
    lines.push(line);
  }

  let html = '';
  let listOpen = false;
  const closeList = () => { if (listOpen) { html += '</ul>'; listOpen = false; } };

  for (const line of lines) {
    const bullet = line.match(/^[•●▪◦*-]\s+(.+)$/);
    const numbered = line.match(/^(\d{1,2}[.)])\s+(.+)$/);
    if (bullet || numbered) {
      if (!listOpen) { html += '<ul class="job-description-list">'; listOpen = true; }
      html += `<li>${esc((bullet || numbered)[numbered ? 2 : 1])}</li>`;
      continue;
    }

    closeList();
    const colonHeading = line.match(/^(.{2,55})[:：]$/);
    if (isJobDescriptionHeading(line) || (colonHeading && colonHeading[1].split(/\s+/).length <= 7)) {
      html += `<h4>${esc(line)}</h4>`;
    } else {
      html += `<p>${esc(line)}</p>`;
    }
  }
  closeList();
  return `<div class="job-description-content" dir="auto">${html}</div>`;
}


const SOURCE_LOGO_DOMAINS = Object.freeze({
  'google': 'google.com',
  'valens semiconductor': 'valens.com',
  'valens': 'valens.com',
  'nextsilicon': 'nextsilicon.com',
  'retym': 'retym.com',
  'hailo': 'hailo.ai',
  'pliops': 'pliops.com',
  'chain reaction': 'chain-reaction.io',
  'scd - semiconductor devices': 'scd.co.il',
  'scd': 'scd.co.il',
  'cadence design systems': 'cadence.com',
  'cadence': 'cadence.com',
  'texas instruments': 'ti.com',
  'flex': 'flex.com',
  'siemens eda': 'siemens.com',
  'marvell': 'marvell.com',
  'broadcom': 'broadcom.com',
  'synopsys': 'synopsys.com',
  'arm': 'arm.com',
  'dustphotonics': 'dustphotonics.com',
  'wiliot': 'wiliot.com',
  'vayyar imaging': 'vayyar.com',
  'vayyar': 'vayyar.com',
  'arbe robotics': 'arberobotics.com',
  'arbe': 'arberobotics.com',
  'trieye': 'trieye.tech',
  'speedata': 'speedata.io',
  'proteantecs': 'proteantecs.com',
  'innoviz': 'innoviz.tech',
  'camtek': 'camtek.com',
  'nova measuring instruments': 'novami.com',
  'nova': 'novami.com',
  'neuroblade': 'neuroblade.com',
  'apple': 'apple.com',
  'amazon': 'amazon.com',
  'nvidia': 'nvidia.com',
  'intel': 'intel.com',
  'microsoft': 'microsoft.com',
  'mobileye': 'mobileye.com',
  'check point': 'checkpoint.com',
  'palo alto networks': 'paloaltonetworks.com',
  'wix': 'wix.com',
  'monday.com': 'monday.com',
  'monday': 'monday.com',
  'cisco': 'cisco.com',
  'ibm': 'ibm.com',
  'salesforce': 'salesforce.com',
  'meta': 'meta.com',
  'qualcomm': 'qualcomm.com',
  'samsung research israel': 'samsung.com',
  'samsung': 'samsung.com',
  'applied materials': 'appliedmaterials.com',
  'kla': 'kla.com',
  'medtronic': 'medtronic.com',
  'philips': 'philips.com',
  'elbit systems': 'elbitsystems.com',
  'elbit': 'elbitsystems.com',
  'rafael': 'rafael.co.il',
  'israel aerospace industries': 'iai.co.il',
  'iai': 'iai.co.il',
  'taboola': 'taboola.com',
  'appsflyer': 'appsflyer.com',
  'similarweb': 'similarweb.com',
  'outbrain': 'outbrain.com',
  'cyberark': 'cyberark.com',
  'cato networks': 'catonetworks.com',
  'cato': 'catonetworks.com',
  'wiz': 'wiz.io',
  'orca security': 'orca.security',
  'orca': 'orca.security',
  'sentinelone': 'sentinelone.com',
  'aqua security': 'aquasec.com',
  'aqua': 'aquasec.com',
  'figma': 'figma.com',
  'speechify': 'speechify.com',
  'pagaya': 'pagaya.com',
  'tenable': 'tenable.com',
  'redis': 'redis.io',
  'tavily': 'tavily.com',
  'nexxen': 'nexxen.com',
  'chainalysis': 'chainalysis.com',
  'reindeer ai': 'reindeer.ai',
  'reindeer': 'reindeer.ai',
  'traild': 'traildsoftware.com',
  'nice': 'nice.com',
  'riskified': 'riskified.com',
  'sunflower': 'sunfltd.com',
  'moon active': 'moonactive.com',
  'connecteam': 'connecteam.com',
  'via': 'ridewithvia.com',
  'apiiro': 'apiiro.com',
  'safebreach': 'safebreach.com',
  'guidde': 'guidde.com',
  'scaleops': 'scaleops.com',
  'sweet security': 'sweet.security',
  'accessibe': 'accessibe.com',
  'unframe': 'unframe.ai',
  'descope': 'descope.com',
  'guardz': 'guardz.com',
  'bluevine': 'bluevine.com',
  'pendo': 'pendo.io',
  'beamup': 'beamup.ai',
  'daylight security': 'daylight.ai',
  'aidoc': 'aidoc.com',
  'armis': 'armis.com',
  'forter': 'forter.com',
  'gong': 'gong.io',
  'torq': 'torq.io',
  'datarails': 'datarails.com',
  'cymulate': 'cymulate.com',
  'quanthealth': 'quanthealth.ai',
  'eleos health': 'eleos.health',
  'melio': 'melio.com',
  'neo security': 'neo.ai',
  'axon': 'axon.com',
  'wolt': 'wolt.com',
  'ashley digital': 'ashleyfurniture.com',
});

function normalizeSourceBrand(value = '') {
  return String(value).trim().toLowerCase().replace(/\s+/g, ' ');
}

function sourceLogoDomain(source) {
  const candidates = [source?.company_name, source?.identifier, source?.name]
    .map(normalizeSourceBrand)
    .filter(Boolean);
  for (const candidate of candidates) {
    if (SOURCE_LOGO_DOMAINS[candidate]) return SOURCE_LOGO_DOMAINS[candidate];
    for (const [brand, domain] of Object.entries(SOURCE_LOGO_DOMAINS)) {
      if (candidate === brand || candidate.startsWith(`${brand} `) || candidate.includes(` ${brand} `)) return domain;
    }
  }

  const identifier = String(source?.identifier || '').trim();
  if (/^https?:\/\//i.test(identifier)) {
    try { return new URL(identifier).hostname.replace(/^www\./i, ''); } catch { return ''; }
  }
  if (/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(identifier)) return identifier.replace(/^www\./i, '');
  return '';
}

function sourceLogoFallback(source) {
  const label = String(source?.company_name || source?.name || source?.identifier || '?').trim();
  return Array.from(label)[0]?.toUpperCase() || '?';
}

function sourceLogoMarkup(source, className = '') {
  const domain = sourceLogoDomain(source);
  const fallback = esc(sourceLogoFallback(source));
  const company = esc(source?.company_name || source?.name || 'חברה');
  if (!domain) {
    return `<div class="source-logo-tile ${className}" aria-label="${company}"><span class="source-logo-fallback">${fallback}</span></div>`;
  }
  const logoUrl = `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(`https://${domain}`)}&sz=128`;
  const fallbackUrl = `https://${domain}/favicon.ico`;
  return `<div class="source-logo-tile ${className}" title="${company}">
    <img class="source-company-logo" src="${esc(logoUrl)}" data-logo-fallback="${esc(fallbackUrl)}" alt="הלוגו של ${company}" loading="lazy" referrerpolicy="no-referrer" onerror="sourceLogoImageError(this)">
    <span class="source-logo-fallback" hidden>${fallback}</span>
  </div>`;
}

function sourceLogoImageError(image) {
  const fallbackUrl = String(image?.dataset?.logoFallback || '');
  if (fallbackUrl) {
    image.dataset.logoFallback = '';
    image.src = fallbackUrl;
    return;
  }
  image.hidden = true;
  if (image.nextElementSibling) image.nextElementSibling.hidden = false;
}

const dateFmt = (value) => value
  ? new Intl.DateTimeFormat('he-IL', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '—';

const statusLabel = (status) => ({
  new: 'חדש', saved: 'נשמרה', queued: 'בתור', applying: 'בטיפול', needs_input: 'מחכה לך',
  verification_pending: 'ממתין לאימות', submitted: 'הוגשה ואומתה', phone_screen: 'סינון טלפוני',
  test: 'מבחן', interview: 'ראיון', offer: 'הצעה', accepted: 'התקבלתי', rejected: 'נדחתה', failed: 'נכשל', skipped: 'דולג',
}[status] || status);

const blockerMeta = (kind) => ({
  captcha: { icon: '🧩', label: 'CAPTCHA', short: 'נדרש אימות אנושי', tone: 'danger' },
  review_before_submit: { icon: '✓', label: 'ממתין לאישור', short: 'הטופס מוכן לשליחה', tone: 'warning' },
  choice_required: { icon: '?', label: 'נדרשת בחירה', short: 'בחר אחת מהאפשרויות כדי להמשיך', tone: 'warning' },
  grade_sheet_required: { icon: '↑', label: 'נדרש גיליון ציונים', short: 'העלה גיליון ציונים בפרופיל כדי להמשיך', tone: 'warning' },
  file_required: { icon: '↑', label: 'נדרש מסמך', short: 'נדרש קובץ נוסף לפני השליחה', tone: 'warning' },
  unknown_field: { icon: '?', label: 'חסר פרט', short: 'נדרשת תשובה שלך', tone: 'warning' },
  missing_profile_detail: { icon: '◌', label: 'חסר בפרופיל', short: 'נדרש להשלים פרטים אישיים', tone: 'warning' },
  linkedin_manual: { icon: 'in', label: 'LinkedIn ידני', short: 'נדרשת השלמה ידנית', tone: 'warning' },
  submit_button_missing: { icon: '!', label: 'כפתור לא זוהה', short: 'נדרשת בדיקה ידנית', tone: 'danger' },
  confirmation_missing: { icon: '!', label: 'אין אישור שליחה', short: 'בקשת Submit נשלחה אך לא אומתה', tone: 'warning' },
  submit_not_sent: { icon: '!', label: 'לא נשלח', short: 'Lever עצר את השליחה לפני יציאת הבקשה', tone: 'danger' },
}[kind] || { icon: '!', label: 'דורש טיפול', short: 'הסוכן נעצר', tone: 'warning' });

function blockerTarget(blocker, application) {
  return blocker?.page_url || application?.job?.apply_url || '#';
}

function compactAgentFailure(value = '') {
  return String(value || '').replace(/^\[blocked:[^\]]+\]\s*/i, '').trim();
}

function renderApplicationStatus(application) {
  const blocker = application.blocker;
  const stageLabel = application.agent_stage || statusLabel(application.status);
  const waitingFor = application.agent_waiting_for || '—';
  const failureDetail = compactAgentFailure(application.agent_failure_detail || application.last_error || '');
  const queuePosition = application.queue_position ? `<span>מיקום בתור: ${application.queue_position}</span>` : '';
  const expectedStart = application.expected_start_at ? `<small>התחלה צפויה: ${esc(dateFmt(application.expected_start_at))}</small>` : '';

  const stageBadge = `<span class="status-pill">${esc(stageLabel)}</span>`;
  if (blocker) {
    const meta = blockerMeta(blocker.kind);
    return `${stageBadge}
      <div class="queue-blocker queue-blocker-${meta.tone}" title="${esc(blocker.explanation || meta.short)}">
        <span class="queue-blocker-icon">${esc(meta.icon)}</span>
        <span><strong>${esc(meta.label)}</strong><small>${esc(blocker.question || blocker.field_label || meta.short)}</small></span>
      </div>
      <div class="queue-progress-meta" title="${esc(failureDetail)}">
        <strong>שלב: ${esc(stageLabel)}</strong>
        <span>ממתין ל: ${esc(waitingFor)}</span>
        ${queuePosition ? queuePosition : ''}
        ${expectedStart}
        ${failureDetail ? `<small>${esc(failureDetail)}</small>` : ''}
      </div>`;
  }
  if (application.status === 'failed' && application.last_error) {
    return `${stageBadge}
      <div class="queue-error" title="${esc(application.last_error)}">${esc(application.last_error)}</div>`;
  }
  return `${stageBadge}
    <div class="queue-progress-meta">
      <strong>שלב: ${esc(stageLabel)}</strong>
      <span>ממתין ל: ${esc(waitingFor)}</span>
      ${queuePosition ? queuePosition : ''}
      ${expectedStart}
      ${failureDetail ? `<small>${esc(failureDetail)}</small>` : ''}
    </div>`;
}

function renderApplicationActions(application) {
  const blocker = application.blocker;
  if (blocker?.kind === 'review_before_submit') {
    return `<button class="btn primary small" type="button" onclick="event.stopPropagation();markApplicationSubmitted(${application.id})">סמן כהוגש</button>
      <a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(blockerTarget(blocker, application))}" onclick="event.stopPropagation()">פתח את הטופס</a>
      <button class="btn secondary small" type="button" onclick="event.stopPropagation();resolveBlockerAction(${blocker.id},'skip')">דלג</button>
      <button class="btn danger-outline small" type="button" onclick="event.stopPropagation();removeApplication(${application.id})">הסר מהתור</button>`;
  }
  if (blocker?.kind === 'grade_sheet_required') {
    const hasGradeSheet = Boolean(state.profile?.grade_sheet_uploaded);
    if (hasGradeSheet) return `<span class="blocker-auto-resolving"><span class="live-dot"></span> גיליון הציונים כבר שמור · ממשיך אוטומטית</span>`;
    return `<button class="btn primary small" type="button" onclick="event.stopPropagation();openGradeSheetProfile()">העלה גיליון ציונים</button>
      <a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(blockerTarget(blocker, application))}" onclick="event.stopPropagation()">פתח את הטופס</a>
      <button class="btn danger-outline small" type="button" onclick="event.stopPropagation();removeApplication(${application.id})">הסר מהתור</button>`;
  }
  if (blocker) {
    return `<a class="btn primary small" target="_blank" rel="noopener" href="${safeUrl(blockerTarget(blocker, application))}" onclick="event.stopPropagation()">פתח והמשך</a>
      ${['submit_not_sent','submit_button_missing','application_form_missing'].includes(blocker.kind)
        ? `<button class="btn secondary small" type="button" onclick="event.stopPropagation();retryApp(${application.id})">נסה שוב</button>`
        : blocker.kind === 'captcha' || blocker.kind === 'linkedin_manual' || blocker.kind === 'confirmation_missing'
          ? `<button class="btn secondary small" type="button" onclick="event.stopPropagation();markApplicationSubmitted(${application.id})">סמן כהוגש</button>`
          : `<button class="btn secondary small" type="button" onclick="event.stopPropagation();switchView('blockers')">ענה במערכת</button>`}
      <button class="btn danger-outline small" type="button" onclick="event.stopPropagation();removeApplication(${application.id})">הסר מהתור</button>`;
  }
  if (application.status === 'submitted' || application.status === 'verification_pending') {
    return `<button class="btn ${application.status === 'submitted' ? 'primary' : 'secondary'} small" type="button" onclick="event.stopPropagation();showApplicationTimeline(${application.id})">${application.status === 'submitted' ? 'קבלה ואימות' : 'בדוק אימות'}</button>`;
  }
  return `<button class="btn secondary small" type="button" onclick="event.stopPropagation();retryApp(${application.id})">נסה שוב</button>
    <button class="btn secondary small" type="button" onclick="event.stopPropagation();showApplicationTimeline(${application.id})">היסטוריה</button>
    <button class="btn danger-outline small" type="button" onclick="event.stopPropagation();removeApplication(${application.id})">הסר מהתור</button>`;
}

async function showApplicationTimeline(applicationId) {
  try {
    const data = await api(`/api/applications/${applicationId}/timeline`);
    const receipt = data.application?.latest_receipt;
    const evidence = receipt?.evidence || [];
    modal(`<span class="kicker">קבלה דיגיטלית וציר זמן</span><h2>${esc(data.application?.job?.company)} — ${esc(data.application?.job?.title)}</h2>
      <div class="application-receipt ${receipt?.verification_state === 'verified' ? 'verified' : 'pending'}">
        <div><strong>${receipt?.verification_state === 'verified' ? 'ההגשה אומתה' : 'עדיין אין אימות חד־משמעי'}</strong><span>${receipt ? `${esc(receipt.adapter)} · ניסיון ${receipt.attempt_number}` : 'לא נרשם עדיין ניסיון הגשה'}</span></div>
        ${receipt?.confirmation_text ? `<p>${esc(receipt.confirmation_text)}</p>` : ''}
        ${receipt?.external_application_id ? `<p><b>מספר מועמדות:</b> ${esc(receipt.external_application_id)}</p>` : ''}
        ${evidence.length ? `<ul>${evidence.map(item => `<li>${esc(item.type || 'ראיה')}: ${esc(item.value || item.url || '')}</li>`).join('')}</ul>` : ''}
        <div class="card-actions">${receipt?.confirmation_url ? `<a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(receipt.confirmation_url)}">פתח עמוד אישור</a>` : ''}${receipt?.screenshot_url ? `<a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(receipt.screenshot_url)}">צילום מסך</a>` : ''}</div>
      </div>
      <div class="application-timeline">${data.events.length ? data.events.map(event => `<article><i></i><span><strong>${esc(event.message || statusLabel(event.to_status) || event.event_type)}</strong><small>${dateFmt(event.created_at)} · ${esc(event.actor)}</small></span></article>`).join('') : '<p>אין עדיין אירועים.</p>'}</div>`);
  } catch (error) { toast(error.message); }
}
window.showApplicationTimeline = showApplicationTimeline;

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 3000);
}

function skeleton(count = 3, kind = 'cards') {
  return `<div class="skeleton-stack skeleton-${kind}" aria-label="טוען נתונים">${Array.from({ length: count }, () => '<div class="skeleton-item"><i></i><span></span><small></small></div>').join('')}</div>`;
}

function emptyState(icon, title, copy, action = '') {
  return `<div class="empty-state"><span class="empty-state-icon" aria-hidden="true">${icon}</span><strong>${title}</strong><p>${copy}</p>${action}</div>`;
}

const VIEW_CONTEXT = {
  dashboard: 'תמונת מצב עדכנית של החיפוש וההגשות', jobs: 'משרות שנאספו ודורגו לפי ההתאמה לפרופיל שלך',
  applications: 'מעקב אחר התור, ניסיונות ההגשה והסטטוס הנוכחי', blockers: 'פעולות שמחכות להחלטה או להשלמת מידע',
  skills: 'הכישורים שלך והפערים שעולים מהמשרות הפעילות', sources: 'אתרי הקריירה והלוחות ש־JobPilot סורק',
  preferences: 'הגדרות שמשפיעות על האיסוף, הסינון והדירוג', profile: 'המידע המאושר שמשמש למילוי טפסי מועמדות',
  settings: 'העדפות תצוגה ונגישות שנשמרות במכשיר הזה',
};

function setPageContext(view, count = null) {
  const suffix = count === null ? '' : ` · ${count} פריטים`;
  $('#page-context').textContent = `${VIEW_CONTEXT[view] || ''}${suffix}`;
}

function modal(html) {
  modal.previousFocus = document.activeElement;
  $('#modal-content').innerHTML = html;
  $('#modal').classList.add('open');
  $('#modal').setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => $('.modal-close').focus());
}

function closeModal() {
  $('#modal').classList.remove('open');
  $('#modal').setAttribute('aria-hidden', 'true');
  modal.previousFocus?.focus?.();
}

$('.modal-close').onclick = closeModal;
$('#modal').addEventListener('click', (event) => {
  if (event.target.id === 'modal') closeModal();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { closeModal(); setMobileTabMenu(false); }
  if (event.key === 'Tab' && $('#modal').classList.contains('open')) {
    const focusable = $$('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]', $('#modal'));
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

function switchView(view, options = {}) {
  persistCurrentProfileDraft();
  let applicationSection=options.applicationSection;
  if(view==='blockers'){view='applications';applicationSection='attention'}
  state.activeView = view;
  try { localStorage.setItem('jobpilot-active-view', view); } catch { /* Storage may be unavailable. */ }
  const contentView = view === 'preferences' ? 'profile' : view;
  $$('.view').forEach((element) => element.classList.remove('active'));
  $(`#view-${contentView}`).classList.add('active');
  $$('#nav button').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  $$('#nav button').forEach((button) => button.setAttribute('aria-current', button.dataset.view === view ? 'page' : 'false'));
  $$('[data-mobile-view]').forEach((button) => {
    const active = button.dataset.mobileView === view;
    button.classList.toggle('active', active);
    button.setAttribute('aria-current', active ? 'page' : 'false');
  });
  updateMobileTabDock(view);
  setMobileTabMenu(false);
  $('#page-title').textContent = ({
    dashboard: 'לוח בקרה', jobs: 'משרות', applications: 'הגשות', skills: 'סקילים',
    sources: 'מקורות', preferences: 'העדפות חיפוש', profile: 'הפרופיל שלי', settings:'הגדרות', developer: 'אפשרויות למפתחים',
  })[view];
  setPageContext(view);
  $('#view-profile').classList.toggle('showing-preferences', view === 'preferences');

  if (view === 'dashboard') loadDashboard();
  if (view === 'jobs') {
    if (options.minScore !== undefined) $('#score-filter').value = String(options.minScore);
    if (options.status !== undefined) $('#job-status-filter').value = options.status;
    loadJobs();
  }
  if (view === 'applications') {
    switchApplicationSection(applicationSection||'queue');
    if((applicationSection||'queue')==='attention')loadBlockers();else loadApplications();
  }
  if (view === 'skills') loadSkills();
  if (view === 'sources') loadSources();
  if (view === 'settings') {
    requestAnimationFrame(()=>positionThemeThumb(false));
    loadBackgroundWorkerSetup();
    loadGmailIntegration();
  }
  if (view === 'developer') loadDeveloperCenter();
  if (view === 'preferences') { switchProfileSection('preferences'); loadProfile(); }
  if (view === 'profile') {
    const savedSection = options.profileSection || localStorage.getItem('jobpilot-profile-section') || 'personal';
    switchProfileSection(['personal', 'automation'].includes(savedSection) ? savedSection : 'personal');
    loadProfile();
  }
}

function switchApplicationSection(section){
  const target=section==='attention'?'attention':'queue';
  state.applicationSection=target;
  $$('[data-application-section]').forEach(button=>button.classList.toggle('active',button.dataset.applicationSection===target));
  $$('[data-application-pane]').forEach(pane=>pane.classList.toggle('active',pane.dataset.applicationPane===target));
}

$$('[data-application-section]').forEach(button=>{button.onclick=()=>{
  switchApplicationSection(button.dataset.applicationSection);
  if(button.dataset.applicationSection==='attention')loadBlockers();else loadApplications();
}});

$$('[data-view]').forEach((button) => {
  button.onclick = () => switchView(button.dataset.view);
});

function updateMobileTabDock(view) {
  const active = document.querySelector(`[data-mobile-view="${view}"]`);
  if (!active || window.innerWidth > 760) return;
  // Keep the selected destination visible in the horizontally scrollable dock.
  requestAnimationFrame(() => active.scrollIntoView({behavior: 'smooth', block: 'nearest', inline: 'center'}));
}

// Kept as a harmless compatibility hook for callers that used to close the old floating menu.
function setMobileTabMenu() {}

$$('[data-mobile-view]').forEach((button) => {
  button.onclick = () => switchView(button.dataset.mobileView);
});

function switchProfileSection(section) {
  $$('[data-profile-section]').forEach((button) => button.classList.toggle('active', button.dataset.profileSection === section));
  $$('[data-profile-pane]').forEach((pane) => pane.classList.toggle('active', pane.dataset.profilePane === section));
  if (['personal', 'automation'].includes(section)) {
    try { localStorage.setItem('jobpilot-profile-section', section); } catch { /* Storage may be unavailable. */ }
  }
}

$$('[data-profile-section]').forEach((button) => {
  button.onclick = () => switchProfileSection(button.dataset.profileSection);
});

function initMacDockNav() {
  const nav = $('#nav');
  if (!nav || !window.matchMedia('(hover: hover) and (pointer: fine)').matches || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const buttons = [...nav.querySelectorAll('button')];
  let frame;
  let focusedButton = null;
  const exitTimers = new WeakMap();
  const keepSolidThroughExit = (button) => {
    if (!button) return;
    buttons.forEach((item) => {
      if (item === button) return;
      window.clearTimeout(exitTimers.get(item));
      item.classList.remove('is-dock-exit');
    });
    window.clearTimeout(exitTimers.get(button));
    button.classList.add('is-dock-exit');
    exitTimers.set(button, window.setTimeout(() => button.classList.remove('is-dock-exit'), 230));
  };
  const applyAt = (pointerY) => {
    const measurements = buttons.map((button) => {
      const rect = button.getBoundingClientRect();
      return { button, distance: Math.abs(pointerY - (rect.top + rect.height / 2)) };
    });
    const nearest = measurements.reduce((best, item) => item.distance < best.distance ? item : best, measurements[0]);
    const nextFocusedButton = nearest.distance < 95 ? nearest.button : null;
    if (focusedButton && focusedButton !== nextFocusedButton) keepSolidThroughExit(focusedButton);
    if (nextFocusedButton) {
      window.clearTimeout(exitTimers.get(nextFocusedButton));
      nextFocusedButton.classList.remove('is-dock-exit');
    }
    focusedButton = nextFocusedButton;
    measurements.forEach(({ button, distance }) => {
      const influence = Math.max(0, 1 - distance / 132);
      button.style.setProperty('--dock-scale', (1 + influence * .42).toFixed(3));
      button.style.setProperty('--dock-space', `${(influence * 10).toFixed(2)}px`);
      button.style.setProperty('--dock-x', `${(-influence * 11).toFixed(2)}px`);
      const labelProgress = button === nearest.button ? Math.max(0, Math.min(1, (influence - .28) / .72)) : 0;
      button.style.setProperty('--dock-label', labelProgress.toFixed(3));
      button.style.setProperty('--dock-glyph-scale', (1 + labelProgress * .55).toFixed(3));
      button.classList.toggle('is-dock-focus', button === nearest.button && influence > .28);
    });
  };
  const reset = () => {
    keepSolidThroughExit(focusedButton);
    focusedButton = null;
    buttons.forEach((button) => {
      button.style.setProperty('--dock-scale', '1');
      button.style.setProperty('--dock-glyph-scale', '1');
      button.style.setProperty('--dock-space', '0px');
      button.style.setProperty('--dock-x', '0px');
      button.style.setProperty('--dock-label', '0');
      button.classList.remove('is-dock-focus');
    });
  };
  nav.addEventListener('pointermove', (event) => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => applyAt(event.clientY));
  });
  nav.addEventListener('pointerleave', reset);
  buttons.forEach((button) => {
    button.addEventListener('focus', () => applyAt(button.getBoundingClientRect().top + button.offsetHeight / 2));
    button.addEventListener('blur', () => { if (!nav.contains(document.activeElement)) reset(); });
    button.addEventListener('click', () => {
      button.classList.remove('is-launching');
      void button.offsetWidth;
      button.classList.add('is-launching');
      button.addEventListener('animationend', () => button.classList.remove('is-launching'), { once: true });
    });
  });
}

initMacDockNav();
$$('[data-go]').forEach((button) => {
  button.onclick = () => switchView(button.dataset.go);
});

async function loadAnswerLibrary() {
  state.answerLibrary = await api('/api/answer-library');
  state.answerLibrarySaved = JSON.parse(JSON.stringify(state.answerLibrary));
  const root = $('#answer-library');
  root.innerHTML = state.answerLibrary.map((item) => {
    const control = item.choices.length
      ? `<select data-answer>${['', ...item.choices].map((choice) => `<option value="${esc(choice)}" ${choice === item.answer ? 'selected' : ''}>${esc(choice || 'בחר תשובה')}</option>`).join('')}</select>`
      : `<input data-answer type="text" value="${esc(item.answer)}" placeholder="כתוב תשובה מאושרת" />`;
    return `<div class="answer-card" data-answer-key="${esc(item.key)}">
      <div class="answer-card-copy"><strong>${esc(item.title)}</strong><small dir="ltr">${esc(item.example)}</small><small class="answer-compact-summary"></small></div>
      <div class="answer-card-actions">${control}
        <label class="answer-enabled"><input data-enabled type="checkbox" ${item.enabled ? 'checked' : ''} /> שימוש אוטומטי</label>
        <button class="btn primary small answer-save" type="button">שמור</button>
        <button class="section-collapse answer-collapse" type="button" aria-expanded="true" title="מזער"><span aria-hidden="true">⌃</span></button>
      </div></div>`;
  }).join('');
  $$('[data-answer], [data-enabled]', root).forEach((control) => control.addEventListener('input', updateAnswerDirtyState));
  $$('.answer-card', root).forEach((card) => {
    const key = card.dataset.answerKey;
    const collapse = $('.answer-collapse', card);
    const summary = $('.answer-compact-summary', card);
    const updateSummary = () => {
      const value = $('[data-answer]', card)?.value?.trim() || 'ללא תשובה';
      summary.textContent = `${value}${$('[data-enabled]', card)?.checked ? ' · שימוש אוטומטי' : ' · ידני בלבד'}`;
    };
    updateSummary();
    $$('[data-answer], [data-enabled]', card).forEach((control) => control.addEventListener('input', updateSummary));
    const collapsed = localStorage.getItem(`jobpilot-collapse-answer-${key}`) === '1';
    card.classList.toggle('is-answer-collapsed', collapsed);
    collapse.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    collapse.onclick = () => {
      const next = card.classList.toggle('is-answer-collapsed');
      collapse.setAttribute('aria-expanded', next ? 'false' : 'true');
      collapse.title = next ? 'פתח' : 'מזער';
      localStorage.setItem(`jobpilot-collapse-answer-${key}`, next ? '1' : '0');
    };
    $('.answer-save', card).onclick = () => saveAnswerCard(card);
  });
  updateAnswerDirtyState();
}

function currentAnswerLibraryPayload() {
  return Object.fromEntries($$('#answer-library [data-answer-key]').map((card) => [card.dataset.answerKey, {
    answer: $('[data-answer]', card).value,
    enabled: $('[data-enabled]', card).checked,
  }]));
}

function updateAnswerDirtyState() {
  const current = currentAnswerLibraryPayload();
  state.answersDirty = state.answerLibrarySaved.some((item) => {
    const value = current[item.key] || { answer: '', enabled: false };
    return value.answer !== item.answer || value.enabled !== item.enabled;
  });
  $('#profile-answer-panel')?.classList.toggle('has-unsaved', state.answersDirty);
  $('#answers-unsaved-note').textContent = state.answersDirty ? 'יש שינויים בתשובות שעדיין לא נשמרו' : '';
  syncProfileUnsavedUI();
}

async function saveAnswerCard(card) {
  const key = card?.dataset.answerKey;
  if (!key) return;
  const payload = {
    answer: $('[data-answer]', card)?.value || '',
    enabled: Boolean($('[data-enabled]', card)?.checked),
  };
  const button = $('.answer-save', card);
  const original = button?.textContent || 'שמור';
  if (button) { button.disabled = true; button.textContent = 'שומר…'; }
  try {
    await api(`/api/answer-library/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(payload) });
    const current = state.answerLibrary.find((item) => item.key === key);
    const saved = state.answerLibrarySaved.find((item) => item.key === key);
    if (current) Object.assign(current, payload);
    if (saved) Object.assign(saved, payload);
    updateAnswerDirtyState();
    if (button) button.textContent = 'נשמר ✓';
    toast('התשובה נשמרה');
  } catch (error) {
    toast(error.message);
  } finally {
    if (button) window.setTimeout(() => { button.disabled = false; button.textContent = original; }, 900);
  }
}

async function saveAllAnswers() {
  try {
    await api('/api/answer-library/save-all', { method: 'POST', body: JSON.stringify({ answers: currentAnswerLibraryPayload() }) });
    await loadAnswerLibrary();
    toast('כל התשובות נשמרו יחד');
  } catch (error) { toast(error.message); }
}

$('#save-all-answers').onclick = saveAllAnswers;
$('#save-answer-pane').onclick = saveAllAnswers;

let dashboardRankingRefreshTimer = null;

async function loadDashboard() {
  if (state.activeView === 'dashboard') {
    $('#metrics').innerHTML = skeleton(5, 'metrics');
    $('#recent-jobs').innerHTML = skeleton(3, 'rows');
  }
  state.dashboard = await api('/api/dashboard');
  const dashboard = state.dashboard;
  state.autoApplyQueue = dashboard.auto_apply_queue || state.autoApplyQueue;
  if (dashboard.career_track_info?.tracks) {
    state.careerTracks = dashboard.career_track_info.tracks;
    state.activeCareerTrack = dashboard.career_track || dashboard.career_track_info.active_track || state.activeCareerTrack;
    renderCareerSwitcher();
  }
  renderReadiness(dashboard.readiness || {});
  renderSourceErrorBadge(Number(dashboard.readiness?.sources_with_errors || 0));
  const metrics = authState.user?.is_guest ? [
    { label: 'משרות פעילות', value: dashboard.total_jobs, detail: 'מהקטלוג החי של האדמין', view: 'jobs', score: 0, status: '', tone: 'jobs' },
    { label: 'התאמות חזקות', value: dashboard.strong_matches, detail: 'ציון 80 ומעלה', view: 'jobs', score: 80, status: '', tone: 'strong' },
  ] : [
    { label: 'משרות פעילות', value: dashboard.total_jobs, detail: 'בכל המקורות', view: 'jobs', score: 0, status: '', tone: 'jobs' },
    { label: 'התאמות חזקות', value: dashboard.strong_matches, detail: 'ציון 80 ומעלה', view: 'jobs', score: 80, status: '', tone: 'strong' },
    { label: 'בתור להגשה', value: dashboard.queued, detail: 'ממתינות ל־Agent', view: 'applications', tone: 'queue' },
    { label: 'הוגשו', value: dashboard.submitted, detail: 'מועמדויות מתועדות', view: 'applications', tone: 'submitted' },
    { label: 'דורש טיפול', value: dashboard.open_blockers, detail: 'מחכה לתשובה שלך', view: 'blockers', tone: 'attention' },
  ];
  $('#metrics').innerHTML = metrics.map((metric) => `
    <button class="metric metric-link" type="button" data-metric-view="${metric.view}"
      data-min-score="${metric.score ?? ''}" data-status="${metric.status ?? ''}"
      data-metric-tone="${metric.tone}" data-has-value="${Number(metric.value) > 0}">
      <strong>${metric.value}</strong>
      <span class="metric-copy"><b>${metric.label}</b><small>${metric.detail}</small></span>
      <i aria-hidden="true">←</i>
    </button>
  `).join('');
  $$('#metrics [data-metric-view]').forEach((button) => {
    button.onclick = () => {
      if (button.dataset.metricTone === 'queue') return showAutoApplyQueue();
      switchView(button.dataset.metricView, {
        minScore: button.dataset.minScore === '' ? undefined : Number(button.dataset.minScore),
        status: button.dataset.status === '' ? undefined : button.dataset.status,
      });
    };
  });
  ['#blocker-count','#blocker-tab-count','#mobile-application-blocker-count'].forEach(selector=>{
    const badge=$(selector);if(!badge)return;badge.textContent=dashboard.open_blockers;badge.hidden=!Number(dashboard.open_blockers);
  });
  $('#daily-recommendations-title').textContent = 'המשרות עם ההתאמה הגבוהה ביותר';
  const rankingStatus = $('#recommendations-ranking-status');
  const rankingRefresh = dashboard.ranking_refresh || {};
  rankingStatus.hidden = !rankingRefresh.running;
  rankingStatus.innerHTML = rankingRefresh.running ? `
    <span class="recommendations-ranking-spinner" aria-hidden="true"></span>
    <span><strong>מתבצע דירוג מחדש של המשרות</strong><small>${esc(rankingRefresh.message || 'ההתאמות יתעדכנו אוטומטית עם השלמת התהליך.')}</small></span>
  ` : '';
  clearTimeout(dashboardRankingRefreshTimer);
  if (rankingRefresh.running) {
    dashboardRankingRefreshTimer = setTimeout(() => {
      if (state.activeView === 'dashboard') loadDashboard().catch((error) => toast(error.message));
    }, 8000);
  }
  renderRecent(dashboard.recent_jobs);
  renderScan(dashboard.scan);
}

function renderSourceErrorBadge(count) {
  const badge = $('#source-error-badge');
  if (!badge) return;
  const errors = Math.max(0, Number(count || 0));
  badge.hidden = errors === 0;
  badge.textContent = '!';
  badge.title = errors ? `${errors} מקורות עם שגיאה — לחץ לבדיקה` : '';
  const sourceButton = badge.closest('[data-view="sources"]');
  if (sourceButton) sourceButton.title = errors ? `${errors} מקורות עם שגיאה` : '';
}

function renderReadiness(readiness) {
  const root = $('#readiness');
  if (authState.user?.is_guest || readiness.guest_catalog) {
    root.hidden = true;
    root.className = 'readiness-panel';
    root.innerHTML = '';
    return;
  }
  const missingProfile = Array.isArray(readiness.missing_profile_fields) ? readiness.missing_profile_fields : [];
  const profileLabel = missingProfile.length ? `פרטי קשר — חסר ${missingProfile.join(', ')}` : 'פרטי קשר';
  const checks = [
    { ok: readiness.profile_complete, label: profileLabel, action: "switchView('profile')" },
    { ok: readiness.resume_uploaded, label: 'קורות חיים', action: "switchView('profile')" },
    { ok: readiness.sources_enabled > 0, label: 'מקורות פעילים', successLabel: `${readiness.sources_enabled || 0} מקורות פעילים`, action: "switchView('sources')" },
  ];
  const showAgentToken = Boolean(readiness.agent_required) && authState.capabilities?.developer_tools === true && applicationAgentAllowed();
  if (showAgentToken) checks.push({ ok: readiness.agent_token_secure, label: 'Token מאובטח ל־Agent', action: null });
  const missingChecks = checks.filter((check) => !check.ok);
  if (!missingChecks.length) {
    root.hidden = true;
    root.className = 'readiness-panel';
    root.innerHTML = '';
    return;
  }
  root.hidden = false;
  root.className = 'readiness-panel readiness-incomplete';
  const missingText = missingChecks.map((check) => check.label).join(' · ');
  root.innerHTML = `
    <div class="readiness-copy"><span class="readiness-icon">!</span>
      <div><strong>נשארו כמה צעדים לפני הגשה בטוחה</strong>
      <small>חסר: ${esc(missingText)}. אפשר עדיין לעיין ולסרוק משרות.</small></div>
    </div>
    <div class="readiness-checks">${checks.map((check) => {
      const label = check.ok && check.successLabel ? check.successLabel : check.label;
      return check.action
        ? `<button type="button" class="readiness-check ${check.ok ? 'ok' : 'missing'}" onclick="${check.action}">${check.ok ? '✓' : '○'} ${esc(label)}</button>`
        : `<span class="readiness-check ${check.ok ? 'ok' : 'missing'}">${check.ok ? '✓' : '○'} ${esc(label)}</span>`;
    }).join('')}</div>`;
}

function renderRecent(jobs) {
  const root = $('#recent-jobs');
  root.innerHTML = jobs.length ? jobs.map((job) => `
    <button class="job-row interactive-row" type="button" data-job-id="${job.id}" aria-label="פתח פרטי משרה ${esc(job.title)}">
      <div class="score-ring ${job.ranking_pending?'is-pending':''}" style="--score:${job.ranking_pending?0:job.score}"><b>${job.ranking_pending?'…':job.score}</b></div>
      <div class="job-info"><strong dir="auto">${esc(job.title)}</strong><span>${esc(job.company)} · ${esc(job.location || 'מיקום לא צוין')}</span></div>
      ${automaticSubmissionBadge(job)}
      <span class="status-pill">${statusLabel(job.status)}</span>
      <span class="row-arrow" aria-hidden="true">←</span>
    </button>
  `).join('') : emptyState('⌁', 'עוד אין משרות מדורגות', 'לאחר הסריקה יוצגו כאן המשרות בעלות ציון ההתאמה הגבוה ביותר מכל המאגר.', '<button class="btn secondary small" type="button" onclick="switchView(\'sources\')">בדוק מקורות</button>');
  $$('[data-job-id]', root).forEach((element) => {
    element.onclick = () => showJob(Number(element.dataset.jobId));
  });
}

function scanResultSummary(result) {
  if (!result) return '';
  if (result.status === 'no_sources') return 'אין מקורות פעילים';
  const found = Number(result.found || 0);
  const fresh = Number(result.new || 0);
  return `${found} משרות בישראל · ${fresh} חדשות`;
}

function scanNextLabel(nextScheduledAt) {
  if (!nextScheduledAt) return 'סריקה אוטומטית אינה פעילה';
  const date = new Date(nextScheduledAt);
  if (Number.isNaN(date.getTime())) return 'סריקה אוטומטית אינה פעילה';
  const minutes = Math.max(0, Math.ceil((date.getTime() - Date.now()) / 60000));
  if (minutes < 1) return 'הסריקה הבאה בעוד פחות מדקה';
  if (minutes < 60) return `הסריקה הבאה בעוד ${minutes} דקות`;
  if (minutes < 1440) return `הסריקה הבאה בעוד ${Math.floor(minutes / 60)} שעות ו־${minutes % 60} דקות`;
  const now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const day = date.toDateString() === now.toDateString() ? 'היום' : date.toDateString() === tomorrow.toDateString() ? 'מחר' : new Intl.DateTimeFormat('he-IL', { weekday: 'short', day: 'numeric', month: 'numeric' }).format(date);
  return `הסריקה הבאה ${day} ב־${new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' }).format(date)}`;
}

function renderScan(scan) {
  const element = $('#scan-status');
  const progress = $('#scan-progress');
  const button = $('#scan-btn');
  if (button) button.hidden = !manualScanAllowed();
  progress.hidden = true;
  progress.classList.remove('running');

  if (scan.running) {
    const current = scan.progress || {};
    const total = Math.max(0, Number(current.total || 0));
    const completed = Math.max(0, Number(current.completed || 0));
    const activeSources = Array.isArray(current.active_sources) ? current.active_sources.filter(Boolean) : [];
    const source = current.current_source || activeSources[0] || '';
    const phase = current.phase || 'starting';
    const percent = total ? Math.min(100, Math.max(0, Math.round((completed / total) * 100))) : 0;
    const counter = phase === 'queued' ? 'ממתין ל־worker' : (total ? `${Math.min(completed, total)} מתוך ${total}` : 'מכין מקורות');
    const parallel = activeSources.length > 1 ? ` · עוד ${activeSources.length - 1} במקביל` : '';
    const detail = phase === 'queued'
      ? 'הבקשה נשלחה ל־GitHub Actions. האתר נשאר פנוי בזמן שהסריקה מתחילה…'
      : phase === 'finalizing'
        ? 'מסיים שמירה ודירוג של המשרות…'
        : source ? `סורק עכשיו: ${source}${parallel}` : 'מכין את רשימת המקורות…';

    element.classList.add('is-running');
    element.style.setProperty('--scan-progress', `${percent}%`);
    element.dataset.nextScan = '';
    element.innerHTML = `
      <span><b>סריקה בתהליך · ${esc(counter)}</b><small>${esc(detail)}</small></span>
      <i class="scan-status-fill ${total ? '' : 'is-indeterminate'}" aria-hidden="true"></i>
    `;
    element.setAttribute('aria-label', `סריקה בתהליך. ${counter}. ${detail}`);
    element.title = 'הדוח המלא יהיה זמין כשהסריקה תסתיים';

    // The real scan action stays visually unchanged; it is only disabled to avoid duplicate scans.
    if (button) {
      button.disabled = true;
      button.classList.remove('scan-btn-running');
      button.textContent = 'סרוק עכשיו';
      button.setAttribute('aria-label', 'סריקה כבר מתבצעת');
    }
  } else {
    element.classList.remove('is-running');
    element.style.removeProperty('--scan-progress');
    if (button) {
      button.disabled = false;
      button.classList.remove('scan-btn-running');
      button.removeAttribute('aria-label');
      button.textContent = 'סרוק עכשיו';
    }

    if (scan.last_result) lastScanReport = scan.last_result;
    const summary = scanResultSummary(scan.last_result);
    element.dataset.nextScan = scan.next_scheduled_at || '';
    const nextScan = scanNextLabel(scan.next_scheduled_at);
    const finished = scan.last_finished_at ? `הסתיימה ${dateFmt(scan.last_finished_at)}` : '';
    const headline = scan.last_finished_at ? `סריקה אחרונה · ${summary || 'הושלמה'}` : 'טרם בוצעה סריקה';
    const detail = scan.last_finished_at
      ? `${finished} · ${nextScan} · לחץ לדוח המלא`
      : `${nextScan} · לאחר הסריקה אפשר ללחוץ כאן לדוח המלא`;
    element.innerHTML = `<span><b>${esc(headline)}</b><small>${esc(detail)}</small></span><i class="scan-status-fill" aria-hidden="true"></i>`;
    element.setAttribute('aria-label', `${headline}. ${detail}`);
    element.title = scan.last_result ? 'פתח דוח סריקה מלא' : 'עדיין אין דוח סריקה';
  }
}

function updateScanCountdown() {
  const element = $('#scan-status');
  if (!element || element.classList.contains('is-running')) return;
  const small = element.querySelector('small');
  if (!small || !element.dataset.nextScan) return;
  const finishedPart = small.textContent.split(' · ')[0];
  const nextScan = scanNextLabel(element.dataset.nextScan);
  small.textContent = `${finishedPart} · ${nextScan} · לחץ לדוח המלא`;
}
setInterval(updateScanCountdown, 30000);

function scanMetric(value, label, tone = '') {
  return `<div class="scan-report-metric ${tone}"><strong>${Number(value || 0)}</strong><span>${label}</span></div>`;
}

function showScanReport(result) {
  if (!result) return toast('עדיין אין דוח סריקה להצגה');
  if (result.status === 'no_sources') {
    modal(`
      <div class="scan-report-head"><span class="scan-report-icon warning" aria-hidden="true">!</span><div><span class="kicker">דוח סריקה</span><h2>לא נמצאו מקורות פעילים</h2><p>לא היה מה לסרוק. אפשר להפעיל מקורות קיימים או להוסיף מקורות חדשים.</p></div></div>
      <div class="card-actions modal-actions"><button class="btn primary" type="button" onclick="closeModal();switchView('sources')">עבור למקורות</button><button class="btn secondary" type="button" onclick="closeModal();installRecommendedSources()">הוסף מקורות מומלצים</button></div>
    `);
    return;
  }

  const perSource = Array.isArray(result.per_source) ? result.per_source : [];
  const failedItems = perSource.filter((item) => item.error);
  const successfulItems = perSource.filter((item) => !item.error);
  const fallbackErrors = Array.isArray(result.errors) ? result.errors : [];
  const errors = failedItems.length ? failedItems : fallbackErrors.map((item) => ({ source: item.source || 'מקור לא ידוע', error: item.error || String(item) }));
  const failed = Number(result.failed_sources || errors.length || 0);
  const successful = Number(result.successful_sources || Math.max(0, Number(result.sources || 0) - failed));
  const title = result.status === 'failed' ? 'הסריקה נכשלה' : failed ? 'הסריקה הסתיימה עם שגיאות' : 'הסריקה הושלמה בהצלחה';
  const subtitle = failed
    ? `${successful} מקורות נסרקו בהצלחה ו־${failed} נכשלו. המשרות ממקורות שהצליחו כבר נשמרו במערכת.`
    : `${successful || Number(result.sources || 0)} מקורות נסרקו בהצלחה והמשרות שלהם נשמרו ודורגו.`;

  const errorSection = errors.length ? `
    <section class="scan-report-section scan-report-errors">
      <div class="scan-report-section-title"><div><span class="kicker">דורש בדיקה</span><h3>${errors.length} מקורות עם שגיאה</h3></div><button class="btn secondary small" type="button" onclick="closeModal();switchView('sources')">פתח מקורות</button></div>
      <div class="scan-report-error-list">${errors.map((item) => `
        <div class="scan-report-error"><span aria-hidden="true">!</span><div><strong>${esc(item.source || 'מקור')}</strong><small>${esc(item.error || 'שגיאה לא ידועה')}</small></div></div>
      `).join('')}</div>
    </section>` : '';

  const sourceRows = perSource.map((item) => `
    <div class="scan-source-row ${item.error ? 'has-error' : ''}">
      <div class="scan-source-name"><i aria-hidden="true"></i><strong>${esc(item.source || 'מקור')}</strong></div>
      ${item.error
        ? `<span class="scan-source-error">${esc(item.error)}</span>`
        : item.deferred
          ? `<span class="scan-source-counts">הגישה נחסמה זמנית — המשרות מהסריקה התקינה האחרונה נשמרו</span>`
          : `<span class="scan-source-counts"><b>${Number(item.israel_found ?? item.found ?? 0)}</b> בישראל <b>${Number(item.found || 0)}</b> מתאימות <b>${Number(item.new || 0)}</b> חדשות <b>${Number(item.updated || 0)}</b> עודכנו${Number(item.filtered_foreign || 0) ? ` <b>${Number(item.filtered_foreign || 0)}</b> מחו״ל` : ''}${Number(item.filtered_mismatch || 0) ? ` <b>${Number(item.filtered_mismatch || 0)}</b> הוחרגו` : ''}</span>`}
    </div>
  `).join('');

  modal(`
    <div class="scan-report">
      <div class="scan-report-head"><span class="scan-report-icon ${failed ? 'warning' : 'success'}" aria-hidden="true">${failed ? '!' : '✓'}</span><div><span class="kicker">דוח סריקה</span><h2>${title}</h2><p>${esc(subtitle)}</p></div></div>
      <div class="scan-report-metrics">
        ${scanMetric(result.found, 'משרות בישראל', 'primary')}
        ${scanMetric(result.new, 'חדשות', 'success')}
        ${scanMetric(result.updated, 'עודכנו')}
        ${scanMetric(result.filtered_foreign, 'מחו״ל סוננו')}
        ${scanMetric(result.filtered_mismatch, 'לפי ההחרגות')}
        ${scanMetric(failed, 'שגיאות', failed ? 'danger' : '')}
      </div>
      ${errorSection}
      <details class="scan-report-details">
        <summary><span>פירוט לפי מקור</span><small>${perSource.length || Number(result.sources || 0)} מקורות</small></summary>
        <div class="scan-source-list">${sourceRows || '<div class="empty">אין פירוט מקורות זמין.</div>'}</div>
      </details>
      <div class="card-actions modal-actions"><button class="btn primary" type="button" onclick="closeModal();switchView('jobs')">צפה במשרות</button><button class="btn secondary" type="button" onclick="closeModal()">סגור</button></div>
    </div>
  `);
}

$('#scan-status').onclick = () => {
  if ($('#scan-status').classList.contains('is-running')) {
    toast('הסריקה עדיין פועלת — הדוח המלא יהיה זמין בסיום');
    return;
  }
  showScanReport(lastScanReport || state.dashboard?.scan?.last_result || null);
};

async function startSiteScan() {
  const started = await api('/api/scan', { method: 'POST' });
  lastScanCompleted = 0;
  const external = started?.worker === 'github_actions';
  toast(external ? 'בקשת הסריקה נשלחה ל־GitHub Actions' : 'הסריקה התחילה');
  renderScan({ running: true, progress: { phase: external ? 'queued' : 'starting', current: 0, completed: 0, total: 0, current_source: null } });
  pollScan();
  return started;
}

if ($('#scan-btn')) $('#scan-btn').onclick = async () => {
  try { await startSiteScan(); } catch (error) { toast(error.message); }
};

async function pollScan() {
  if (scanPollActive) return;
  scanPollActive = true;
  try {
    while (true) {
      // Multiple devices may watch the same durable scan. Poll gently so phones and
      // background tabs do not generate unnecessary traffic while GitHub Actions works.
      await new Promise((resolve) => setTimeout(resolve, document.hidden ? 6000 : 2000));
      const scan = await api('/api/scan/status');
      renderScan(scan);
      const completed = Math.max(0, Number(scan.progress?.completed || 0));
      if (scan.running && completed > lastScanCompleted) {
        lastScanCompleted = completed;
        // Each source is committed independently by the backend. Refresh only the
        // visible screen so newly collected jobs appear without waiting for the
        // remaining sources to finish.
        try {
          if (state.activeView === 'jobs') await loadJobs({ silent: true });
          else if (state.activeView === 'dashboard') await loadDashboard();
          else if (state.activeView === 'sources') await loadSources();
          else if (state.activeView === 'applications') await loadApplications();
        } catch (refreshError) {
          console.warn('Incremental scan refresh failed', refreshError);
        }
      }
      if (!scan.running) {
        lastScanCompleted = completed;
        const result = scan.last_result || {};
        if (scan.last_result) lastScanReport = scan.last_result;
        // Completion stays quiet: the persistent scan-status bar updates in place.
        // The full report opens only when the user explicitly clicks that bar.
        await Promise.all([loadDashboard(), state.activeView === 'sources' ? loadSources() : Promise.resolve()]);
        return;
      }
    }
  } catch (error) {
    toast(`לא הצלחתי לעדכן את מצב הסריקה: ${error.message}`);
  } finally {
    scanPollActive = false;
  }
}

async function loadJobs(options = {}) {
  if (options.resetPage) state.jobsPaging.page = 1;
  if (!options.silent) {
    $('#jobs-list').innerHTML = skeleton(4, 'cards');
    $('#jobs-pagination').innerHTML = '';
  }
  const query = encodeURIComponent($('#job-search').value || '');
  const score = $('#score-filter').value;
  const status = $('#job-status-filter').value;
  const sort = $('#job-sort').value || 'score_desc';
  const pageSize = Number($('#jobs-page-size').value || 20);
  state.jobsPaging.sort = sort;
  state.jobsPaging.pageSize = pageSize;
  const payload = await api(`/api/jobs?min_score=${score}&status=${status}&query=${query}&paginated=true&page=${state.jobsPaging.page}&page_size=${pageSize}&sort=${encodeURIComponent(sort)}`);
  if (Array.isArray(payload)) {
    state.jobs = payload;
    state.jobsPaging = { ...state.jobsPaging, page: 1, total: payload.length, pages: 1 };
  } else {
    state.jobs = payload.items || [];
    state.jobsPaging = {
      page: payload.page || 1,
      pageSize: payload.page_size || pageSize,
      total: payload.total || 0,
      pages: payload.pages || 1,
      sort: payload.sort || sort,
    };
  }
  renderJobs();
}

function jobCardActions(job) {
  if (authState.user?.is_guest) {
    return `<div class="card-actions guest-job-actions" data-no-card-click>
      <button class="btn primary small" type="button" onclick="event.stopPropagation();showJob(${job.id})">פרטי המשרה</button>
      <a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(job.apply_url)}" onclick="event.stopPropagation()">פתח באתר החברה</a>
    </div>`;
  }
  const appliedButton = job.status === 'submitted'
    ? '<button class="btn applied-job-button small" type="button" disabled>✓ הגשתי כבר למשרה זו</button>'
    : `<button class="btn secondary small" type="button" onclick="event.stopPropagation();markJobSubmitted(${job.id})">הגשתי כבר למשרה זו</button>`;
  const automaticSupported = job.application_adapter?.supports_automatic_submit === true;
  return `<div class="card-actions" data-no-card-click>
    ${appliedButton}
    <button class="btn secondary small" type="button" onclick="event.stopPropagation();saveJob(${job.id})">שמור</button>
    ${applicationAgentAllowed() && automaticSupported ? `<button class="btn primary small" type="button" onclick="event.stopPropagation();queueJob(${job.id},'auto')" ${job.status === 'submitted' ? 'disabled' : ''}>${job.application_id ? 'בדוק והחזר לתור' : 'הגש ברקע'}</button>` : `<a class="btn primary small" target="_blank" rel="noopener" href="${safeUrl(job.apply_url)}" onclick="event.stopPropagation()">הגש ידנית</a>`}
    <button class="btn secondary small" type="button" onclick="event.stopPropagation();showJob(${job.id})">פרטים ואפשרויות</button>
    <a class="btn secondary small" target="_blank" rel="noopener" href="${safeUrl(job.apply_url)}" onclick="event.stopPropagation()">פתח באתר</a>
    <button class="btn danger small" type="button" onclick="event.stopPropagation();skipJob(${job.id})">דלג</button>
    <button class="btn danger-outline small" type="button" onclick="event.stopPropagation();deleteJob(${job.id})">מחק</button>
  </div>`;
}

function automaticSubmissionBadge(job) {
  const adapter = job?.application_adapter || {};
  return adapter.supports_automatic_submit === true
    ? `<span class="auto-submit-badge supported" title="הגשה אוטומטית ברקע באמצעות ${esc(adapter.label || 'מערכת גיוס נתמכת')}"><b>✓</b> תומך בהגשה אוטומטית</span>`
    : `<span class="auto-submit-badge manual" title="מערכת הגיוס הזו עדיין אינה נתמכת להגשה אוטומטית">הגשה ידנית בלבד</span>`;
}

function renderJobs() {
  const root = $('#jobs-list');
  renderActiveFilters();
  setPageContext('jobs', state.jobsPaging.total);
  if (!state.jobs.length) {
    $('#jobs-pagination').innerHTML = '';
    const hasFilters = $('#job-search').value || $('#score-filter').value !== '0' || $('#job-status-filter').value;
    root.innerHTML = hasFilters
      ? emptyState('⌕', 'לא נמצאו התאמות לסינון הזה', 'אפשר להסיר מסנן אחד או לנקות את החיפוש ולנסות שוב.', '<button class="btn secondary small" type="button" onclick="clearJobFilters()">נקה את כל המסננים</button>')
      : emptyState('＋', 'עדיין אין משרות להצגה', 'הוסף מקורות משרות והפעל סריקה ראשונה.', '<button class="btn primary small" type="button" onclick="switchView(\'sources\')">הגדר מקורות</button>');
    return;
  }
  const first = ((state.jobsPaging.page - 1) * state.jobsPaging.pageSize) + 1;
  const last = Math.min(state.jobsPaging.total, first + state.jobs.length - 1);
  const sortLabel = $('#job-sort').selectedOptions[0]?.textContent || 'מיון';
  root.innerHTML = `<div class="results-summary">מציג ${first}–${last} מתוך ${state.jobsPaging.total} משרות · ${esc(sortLabel)}</div>` + state.jobs.map((job) => `
    <article class="job-card interactive-card ${job.status === 'submitted' ? 'is-applied' : ''}" role="button" tabindex="0" data-job-id="${job.id}" aria-label="פתח פרטי משרה ${esc(job.title)}">
      <div class="job-card-head"><div><h3 dir="auto">${esc(job.title)}</h3><div class="company">${esc(job.company)}</div></div><div class="score-badge">${job.ranking_pending?'…':job.score}</div></div>
      <div class="job-capabilities">${automaticSubmissionBadge(job)}</div>
      <div class="job-meta"><span>${esc(job.location || 'לא צוין')}</span><span>${esc(job.workplace)}</span><span>${statusLabel(job.status)}</span>${job.source ? `<span>${esc(job.source.kind)}</span>` : ''}</div>
      <div class="skills">${job.skills.slice(0, 6).map((skill) => `<span>${esc(skill)}</span>`).join('')}</div>
      ${job.skill_gaps?.length ? `<button class="skill-gap-alert" type="button" data-no-card-click onclick="event.stopPropagation();showSkillGaps(${job.id})">יש במשרה הזאת ${job.skill_gaps.length} סקילים שאין לך</button>` : ''}
      <div class="reason-list">${job.ranking_pending?'<div class="reason neutral">ממתין לדירוג</div>':job.score_reasons.slice(0, 3).map((reason) => `<div class="reason ${reason.type}">${esc(reason.label)}</div>`).join('')}</div>
      ${jobCardActions(job)}
    </article>
  `).join('');
  $$('.interactive-card', root).forEach((card) => {
    card.onclick = (event) => {
      if (event.target.closest('[data-no-card-click]')) return;
      showJob(Number(card.dataset.jobId));
    };
    card.onkeydown = (event) => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.target.closest('[data-no-card-click]')) {
        event.preventDefault();
        showJob(Number(card.dataset.jobId));
      }
    };
  });
  renderJobsPagination();
}

function renderJobsPagination() {
  const root = $('#jobs-pagination');
  const { page, pages, total } = state.jobsPaging;
  if (!total || pages <= 1) {
    root.innerHTML = '';
    return;
  }
  const visible = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2]);
  const pageNumbers = [...visible].filter((value) => value >= 1 && value <= pages).sort((a, b) => a - b);
  let buttons = '';
  let previous = 0;
  for (const value of pageNumbers) {
    if (previous && value - previous > 1) buttons += '<span class="pagination-ellipsis">…</span>';
    buttons += `<button type="button" class="pagination-page ${value === page ? 'active' : ''}" ${value === page ? 'aria-current="page"' : ''} onclick="goToJobsPage(${value})">${value}</button>`;
    previous = value;
  }
  root.innerHTML = `
    <button type="button" class="pagination-nav" onclick="goToJobsPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>הקודם</button>
    <div class="pagination-pages">${buttons}</div>
    <button type="button" class="pagination-nav" onclick="goToJobsPage(${page + 1})" ${page >= pages ? 'disabled' : ''}>הבא</button>`;
}

function goToJobsPage(page) {
  const nextPage = Math.max(1, Math.min(Number(page) || 1, state.jobsPaging.pages));
  if (nextPage === state.jobsPaging.page) return;
  state.jobsPaging.page = nextPage;
  loadJobs();
  document.querySelector('#view-jobs')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
window.goToJobsPage = goToJobsPage;

$('#job-search').addEventListener('input', debounce(() => loadJobs({ resetPage: true }), 300));
$('#score-filter').onchange = () => loadJobs({ resetPage: true });
$('#job-status-filter').onchange = () => loadJobs({ resetPage: true });
$('#job-sort').onchange = () => loadJobs({ resetPage: true });
$('#jobs-page-size').onchange = () => loadJobs({ resetPage: true });

function renderActiveFilters() {
  const root = $('#active-filters');
  const filters = [];
  const query = $('#job-search').value.trim();
  const score = $('#score-filter').value;
  const status = $('#job-status-filter').value;
  if (query) filters.push({ key: 'query', label: `חיפוש: ${query}` });
  if (score !== '0') filters.push({ key: 'score', label: `התאמה ${score}+` });
  if (status) filters.push({ key: 'status', label: `סטטוס: ${statusLabel(status)}` });
  root.innerHTML = filters.length ? `<span>מסננים פעילים</span>${filters.map((filter) => `<button type="button" data-clear-filter="${filter.key}">${esc(filter.label)} <b>×</b></button>`).join('')}<button type="button" class="clear-all-filters" data-clear-filter="all">נקה הכול</button>` : '';
  $$('[data-clear-filter]', root).forEach((button) => { button.onclick = () => clearJobFilters(button.dataset.clearFilter); });
}

function clearJobFilters(key = 'all') {
  if (key === 'all' || key === 'query') $('#job-search').value = '';
  if (key === 'all' || key === 'score') $('#score-filter').value = '0';
  if (key === 'all' || key === 'status') $('#job-status-filter').value = '';
  loadJobs({ resetPage: true });
}
window.clearJobFilters = clearJobFilters;

const densityButton = $('#density-toggle');
const applyDensity = (compact) => {
  document.body.classList.toggle('density-compact', compact);
  densityButton.setAttribute('aria-pressed', compact ? 'true' : 'false');
  densityButton.textContent = compact ? 'תצוגה מרווחת' : 'תצוגה קומפקטית';
  localStorage.setItem('jobpilot-density', compact ? 'compact' : 'comfortable');
};
densityButton.onclick = () => applyDensity(!document.body.classList.contains('density-compact'));
applyDensity(localStorage.getItem('jobpilot-density') === 'compact');

async function queueJob(id, mode = 'review', resumeId = null) {
  if (!applicationAgentAllowed()) {
    toast('סוכן ההגשות האוטומטי פעיל כרגע רק בחשבון הראשי. אפשר לפתוח את המשרה ולהגיש ידנית.');
    return;
  }
  try {
    const query = resumeId ? `?resume_id=${encodeURIComponent(resumeId)}` : '';
    const preview = await api(`/api/jobs/${id}/application-preview${query}`);
    const missing = preview.missing || [];
    const warnings = preview.warnings || [];
    const safeguards = preview.safeguards || [];
    const token = encodeURIComponent(preview.preview_token || '');
    const adapter = preview.adapter || {};
    modal(`<span class="kicker">בדיקה לפני הגשה</span>
      <h2>${esc(preview.job?.company)} — ${esc(preview.job?.title)}</h2>
      <div class="submission-preview-summary">
        <span><strong>מערכת הגיוס</strong><b>${esc(adapter.label || 'אתר קריירה')}</b></span>
        <span><strong>מסלול ביצוע</strong><b>${adapter.execution==='cloud_browser'?'Worker ענן · ברקע':'ידני בלבד כרגע'}</b></span>
        <span><strong>קורות חיים</strong><b>${esc(preview.resume?.filename || 'לא נבחרו')}</b></span>
      </div>
      ${missing.length ? `<div class="submission-preview-blocked"><strong>חסרים פרטים לפני שניתן לאשר שליחה אוטומטית:</strong><ul>${missing.map(item => `<li>${esc(item.label)}</li>`).join('')}</ul></div>` : '<div class="submission-preview-ready"><strong>הבדיקה הראשונית עברה.</strong> הפרטים הבסיסיים וקורות החיים מוכנים.</div>'}
      ${warnings.length ? `<div class="submission-preview-warnings"><strong>מה חשוב לדעת</strong><ul>${warnings.map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>` : ''}
      <details class="submission-preview-safeguards"><summary>בלמי הבטיחות שיופעלו</summary><ul>${safeguards.map(item => `<li>${esc(item)}</li>`).join('')}</ul></details>
      <div class="modal-actions">
        <button class="btn primary" type="button" ${preview.ready ? '' : 'disabled'} onclick="confirmApplicationPreview(${id},'auto',${resumeId || 'null'},decodeURIComponent('${token}'),true)">אשר הגשה אוטומטית חד־פעמית</button>
      </div>`);
  } catch (error) {
    toast(error.message);
  }
}

async function confirmApplicationPreview(id, mode, resumeId, previewToken, approveSubmit) {
  try {
    const application = await api(`/api/jobs/${id}/queue`, {
      method: 'POST',
      body: JSON.stringify({ mode, resume_id: resumeId, preview_token: previewToken, approve_submit: approveSubmit }),
    });
    closeModal();
    const queuePosition = Number(application.queue_position || 1);
    toast(approveSubmit
      ? (queuePosition > 1
        ? `ההגשה נשלחה לתור · מיקום ${queuePosition} · תופעל אוטומטית ברצף`
        : 'ההגשה נשלחה לתור ותופעל אוטומטית כשה־worker יתפנה')
      : 'המשרה נכנסה לתור לבדיקה');
    await Promise.all([loadDashboard(), state.activeView === 'jobs' ? loadJobs() : Promise.resolve()]);
    await syncPrimaryApplicationTracking(application.id, true);
  } catch (error) {
    toast(error.message);
  }
}
window.confirmApplicationPreview = confirmApplicationPreview;
async function saveJob(id){await api(`/api/jobs/${id}/save`,{method:'POST'});toast('המשרה נשמרה ב-Kanban');if(state.activeView==='jobs')await loadJobs();}

async function markJobSubmitted(id) {
  try {
    await api(`/api/jobs/${id}/mark-submitted`, { method: 'POST' });
    toast('המשרה סומנה כהוגשה והוסרה מהדאשבורד');
    closeModal();
    await Promise.all([
      loadDashboard(),
      state.activeView === 'jobs' ? loadJobs({ silent: true }) : Promise.resolve(),
      state.activeView === 'applications' && state.applicationSection==='queue' ? loadApplications() : Promise.resolve(),
      state.activeView === 'applications' && state.applicationSection==='attention' ? loadBlockers() : Promise.resolve(),
    ]);
  } catch (error) {
    toast(error.message);
  }
}

async function skipJob(id) {
  try {
    await api(`/api/jobs/${id}/skip`, { method: 'POST' });
    toast('המשרה סומנה כלא רלוונטית');
    closeModal();
    await Promise.all([loadDashboard(), state.activeView === 'jobs' ? loadJobs() : Promise.resolve()]);
  } catch (error) {
    toast(error.message);
  }
}

async function deleteJob(id) {
  if (!confirm('למחוק את המשרה לצמיתות? גם הגשה או חסימה ששייכות אליה יימחקו.')) return;
  try {
    await api(`/api/jobs/${id}`, { method: 'DELETE' });
    closeModal();
    state.jobs = state.jobs.filter((job) => job.id !== id);
    toast('המשרה נמחקה לצמיתות');
    await Promise.all([
      loadDashboard(),
      state.activeView === 'jobs' ? loadJobs() : Promise.resolve(),
      state.activeView === 'applications' && state.applicationSection==='queue' ? loadApplications() : Promise.resolve(),
      state.activeView === 'applications' && state.applicationSection==='attention' ? loadBlockers() : Promise.resolve(),
    ]);
  } catch (error) {
    toast(error.message);
  }
}

function rankingTierLabel(value) {
  return ({top_match:'התאמה מצוינת',strong_match:'התאמה חזקה',good_match:'התאמה טובה',low_match:'התאמה נמוכה',stretch:'מתיחה',excluded:'נפסלה'})[value] || 'ללא סיווג';
}

function rankingConfidenceLabel(value) {
  return ({high:'גבוהה',medium:'בינונית',low:'נמוכה'})[value] || 'לא ידועה';
}

function rankingStatusMeta(status) {
  const map={
    match:['תואם','pass'],fresh:['עדכנית','pass'],realistic:['ריאלי','pass'],
    stretch:['גבולי','warn'],preference_mismatch:['מחוץ להעדפה','warn'],
    mismatch:['לא תואם','fail'],old:['ישנה מדי','fail'],excluded:['נפסלה','fail'],alternative:['חלופת ניסיון','warn'],
    not_configured:['לא הוגדרה העדפה','neutral'],unknown:['לא ידוע','neutral'],
  };
  return map[status] || [String(status||'לא ידוע'),'neutral'];
}

function rankingYears(value) {
  if (value===null || value===undefined || value==='') return null;
  const n=Number(value);
  if (!Number.isFinite(n)) return null;
  return Number.isInteger(n) ? String(n) : String(Math.round(n*10)/10);
}

function v2ExperienceDetail(e) {
  const min=rankingYears(e.required_experience_min),max=rankingYears(e.required_experience_max),profile=rankingYears(e.profile_experience);
  const required=min===null?'לא זוהתה דרישת ניסיון':max!==null&&max!==min?`${min}–${max} שנות ניסיון`:max===min?`${min} שנות ניסיון`:`${min}+ שנות ניסיון`;
  const selected=Array.isArray(e.profile_experience_options)?e.profile_experience_options.filter(Boolean):[];
  if (selected.length) return `${required} · מסנן בפרופיל: ${selected.join(' · ')}`;
  return profile===null?required:`${required} · ניסיון בפרופיל: ${profile}`;
}


function degreeLevelLabel(value) {
  return ({bachelor:'תואר ראשון (B.A. / B.Sc.)',master:'תואר שני (M.A. / M.Sc.)',phd:'דוקטורט (Ph.D.)'})[value] || 'לא זוהתה דרישת תואר';
}

function v2DegreeDetail(e) {
  const level=degreeLevelLabel(e.required_degree);
  const required=e.degree_experience_alternative?`${level} או ניסיון מקביל`:e.degree_required?`${level} ומעלה`:level;
  const profile=e.profile_degree_level?degreeLevelLabel(e.profile_degree_level):'לא הוגדר תואר בפרופיל';
  return `${required} · בפרופיל: ${profile}`;
}

function v2RoleDetail(part) {
  const reason=String(part?.reasons?.[0]||'');
  if (reason.startsWith('Desired role matched:')) return `תפקיד רצוי נמצא בכותרת: ${reason.split(':').slice(1).join(':').trim()}`;
  if (reason.startsWith('Related role family:')) return `משפחת תפקידים תואמת: ${reason.split(':').slice(1).join(':').trim()}`;
  if (reason.startsWith('Track role family:')) return `משפחת תפקיד במסלול: ${reason.split(':').slice(1).join(':').trim()}`;
  if (reason.includes('not a desired family')) return 'המשרה במסלול הנכון, אבל לא במשפחת תפקיד שבחרת';
  if (reason.includes('No reliable role-family match')) return 'לא זוהתה התאמת תפקיד אמינה';
  return reason || 'אין פירוט נוסף';
}

function v2SkillsDetail(part) {
  const chunks=[];
  if (part?.matched_required?.length) chunks.push(`חובה שנמצאו: ${part.matched_required.join(', ')}`);
  if (part?.missing_required?.length) chunks.push(`חובה שחסרים: ${part.missing_required.join(', ')}`);
  if (part?.matched_preferred?.length) chunks.push(`תומכים שנמצאו: ${part.matched_preferred.join(', ')}`);
  if (!chunks.length && (part?.required?.length || part?.preferred?.length || part?.supporting?.length)) chunks.push('לא נמצאה חפיפה בין הטכנולוגיות שזוהו לפרופיל');
  if (!chunks.length) chunks.push('לא זוהו מספיק טכנולוגיות במודעה');
  return chunks.join(' · ');
}

function v2RequirementsDetail(part) {
  const degree=part?.required_degree?(part.degree_experience_alternative?`${degreeLevelLabel(part.required_degree)} או ניסיון מקביל`:part.degree_required?`${degreeLevelLabel(part.required_degree)} ומעלה`:degreeLevelLabel(part.required_degree)):'לא זוהתה דרישת תואר ברורה';
  const chunks=[part?.required_degree?`דרישת תואר: ${degree}`:degree];
  if (part?.mandatory_prerequisites?.length) chunks.push(`דרישות חובה לבדיקה: ${part.mandatory_prerequisites.join(', ')}`);
  return chunks.join(' · ');
}

function v2PreferencesDetail(job,part) {
  const e=job.eligibility||{},chunks=[];
  const loc=rankingStatusMeta(e.location_status)[0],mode=rankingStatusMeta(e.work_mode_status)[0];
  chunks.push(`מיקום: ${loc}`);
  chunks.push(`מודל עבודה: ${mode}`);
  if (part?.keyword_hits?.length) chunks.push(`מילות העדפה: ${part.keyword_hits.join(', ')}`);
  return chunks.join(' · ');
}

function v2WarningHebrew(value) {
  const text=String(value||'');
  let match=text.match(/^Experience gap of ([0-9.]+) years$/i); if(match) return `פער ניסיון של ${match[1]} שנים`;
  match=text.match(/^Role seniority is (.+)$/i); if(match) return `רמת התפקיד שזוהתה: ${match[1]}`;
  if(text==='Location is outside preferred locations') return 'המיקום מחוץ להעדפות שלך';
  if(text==='Work mode is outside preferences') return 'מודל העבודה מחוץ להעדפות שלך';
  if(text==='Employment type is outside preferences') return 'סוג ההעסקה מחוץ להעדפות שלך';
  if(text==='Job description is incomplete; recommendation is capped') return 'תיאור המשרה חלקי ולכן הציון הוגבל';
  return text;
}

function renderV2RankingExplanation(job) {
  if (job.ranking_pending || !job.eligibility) return `<section class="ranking-v2-explanation"><div class="empty-state">הדירוג מתעדכן… המשרה נשארת זמינה בזמן החישוב.</div></section>`;
  const e=job.eligibility||{},b=job.match_breakdown||{};
  const state=rankingStatusMeta(e.state||'unknown');
  const filterRows=[
    ['מסלול מקצועי',e.career_track_status,e.career_track_status==='match'?'המשרה שייכת למסלול הפעיל':'המשרה אינה שייכת למסלול הפעיל'],
    ['ניסיון',e.experience_status,v2ExperienceDetail(e)],
    ['תואר',e.degree_status,v2DegreeDetail(e)],
    ['עדכניות',e.recency_status,e.age_days===null||e.age_days===undefined?'תאריך הפרסום לא ידוע':`פורסמה לפני ${e.age_days} ימים`],
    ['מיקום',e.location_status,e.job_location||job.location||'לא צוין'],
    ['מודל עבודה',e.work_mode_status,job.workplace&&job.workplace!=='unknown'?job.workplace:'לא צוין'],
    ['סוג העסקה',e.employment_type_status,e.employment_type||'לא זוהה'],
  ];
  const filters=filterRows.map(([label,status,detail])=>{const [statusLabel,tone]=rankingStatusMeta(status);return `<article class="ranking-filter ${tone}"><span>${esc(label)}</span><strong>${esc(statusLabel)}</strong><small>${esc(detail)}</small></article>`}).join('');
  const cards=[
    ['התאמת תפקיד','role',v2RoleDetail(b.role)],
    ['כישורים וטכנולוגיות','skills',v2SkillsDetail(b.skills)],
    ['דרישות מקצועיות','requirements',v2RequirementsDetail(b.requirements)],
    ['העדפות','preferences',v2PreferencesDetail(job,b.preferences)],
  ].map(([label,key,detail])=>{const part=b[key]||{},score=Number(part.score)||0,max=Number(part.max)||0,pct=max?Math.max(0,Math.min(100,Math.round(score/max*100))):0;return `<article class="ranking-score-card"><header><span>${esc(label)}</span><strong>${score}/${max}</strong></header><i><b style="width:${pct}%"></b></i><small>${esc(detail)}</small></article>`}).join('');
  const adjustments=[];
  if (Number(b.skills?.penalty)>0) adjustments.push(`חסרים סקילי חובה: הופחתו ${Number(b.skills.penalty)} נקודות והציון הוגבל לכל היותר ל־69`);
  for (const warning of (job.ranking_warnings||[])) { const label=v2WarningHebrew(warning); if(label&&!adjustments.includes(label)) adjustments.push(label); }
  const unknown=(e.unknown_fields||[]).map(value=>({experience:'ניסיון נדרש',degree:'דרישת תואר',profile_degree:'תואר בפרופיל',seniority:'רמת תפקיד',location:'מיקום',publication_date:'תאריך פרסום',work_mode:'מודל עבודה',employment_type:'סוג העסקה'})[value]||value);
  return `<section class="ranking-v2-explanation">
    <header class="ranking-v2-header"><span><strong>${rankingTierLabel(job.ranking_tier)}</strong><small>ודאות ${rankingConfidenceLabel(job.ranking_confidence)} · הסינון הראשוני נפרד מהניקוד</small></span><b>${Number(job.score)||0}<small>/100</small></b></header>
    <div class="ranking-filter-summary ${state[1]}"><strong>סינון ראשוני: ${esc(state[0])}</strong><span>${e.state==='excluded'?'לפחות תנאי סף אחד פסל את המשרה':e.state==='stretch'?'המשרה עברה עם הסתייגות שחשוב לבדוק':'המשרה עברה את תנאי הסף שניתן היה לבדוק'}</span></div>
    <div class="ranking-eligibility-grid">${filters}</div>
    ${unknown.length?`<p class="ranking-unknown"><strong>מידע שלא ניתן היה לקבוע:</strong> ${unknown.map(esc).join(', ')}</p>`:''}
    <div class="ranking-section-title"><strong>ניקוד התאמה</strong><small>רק ארבעת המרכיבים האלה נכנסים לציון</small></div>
    <div class="ranking-score-grid">${cards}</div>
    ${adjustments.length?`<div class="ranking-adjustments"><strong>התאמות לציון הסופי</strong>${adjustments.map(item=>`<span>${esc(item)}</span>`).join('')}</div>`:''}
  </section>`;
}

async function showJob(id) {
  try {
    const [job, resumes] = await Promise.all([api(`/api/jobs/${id}`), api(`/api/resumes?job_id=${id}`)]);
    const alreadySubmitted = job.status === 'submitted';
    const automaticSupported = job.application_adapter?.supports_automatic_submit === true;
    const breakdownEntries=job.ranking_engine==='v2'
      ? Object.entries({role:'התאמת תפקיד',skills:'כישורים וטכנולוגיות',requirements:'דרישות מקצועיות',preferences:'העדפות'}).map(([key,label])=>{const part=job.match_breakdown?.[key]||{},maximum=Number(part.max)||1,points=Number(part.score)||0;return `<div><span>${label}</span><i><b style="width:${Math.max(0,Math.min(100,Math.round(points/maximum*100)))}%"></b></i><strong>${points}/${maximum}</strong></div>`})
      : Object.entries({title:'כותרת',skills:'סקילים',experience:'ניסיון',location:'מיקום',freshness:'עדכניות'}).map(([key,label]) => `<div><span>${label}</span><i><b style="width:${job.match_breakdown?.[key] ?? 50}%"></b></i><strong>${job.match_breakdown?.[key] ?? 50}</strong></div>`);
    modal(`
      <span class="kicker">${esc(job.company)}</span>
      <h2 dir="auto">${esc(job.title)}</h2>
      <div class="job-meta"><span>${esc(job.location || 'לא צוין')}</span><span>${job.ranking_pending?'ממתין לדירוג':`ציון ${job.score}`}</span><span>${statusLabel(job.status)}</span>${job.degree_requirement?`<span>${esc(job.degree_requirement_label||degreeLevelLabel(job.degree_requirement))}</span>`:''}</div>
      <h3>למה היא מתאימה</h3>
      ${job.ranking_engine==='v2'
        ? renderV2RankingExplanation(job)
        : `<div class="score-breakdown">${breakdownEntries.join('')}</div><div class="reason-list">${job.score_reasons.map((reason) => `<div class="reason ${reason.type}">${esc(reason.label)} (${reason.points > 0 ? '+' : ''}${reason.points})</div>`).join('')}</div>`}
      ${job.skill_gaps?.length ? `<h3>סקילים שזוהו ואינם בפרופיל שלך</h3><div class="skill-gap-list">${job.skill_gaps.map((skill) => `<button type="button" onclick="addSkill(decodeURIComponent('${encodeURIComponent(skill)}'), ${job.id})">+ ${esc(skill)}</button>`).join('')}</div><p class="skill-honesty-note">הוסף רק סקיל שיש לך בפועל; המערכת לא מניחה ניסיון שלא אישרת.</p>` : ''}
      <section class="job-description-section">
        <div class="job-description-heading"><span class="kicker">פרטי התפקיד</span><h3>תיאור המשרה</h3></div>
        ${formatJobDescription(job.description)}
      </section>
      <h3>אפשרויות הגשה</h3>
      <div class="job-capabilities job-capabilities-modal">${automaticSubmissionBadge(job)}${job.application_adapter?.label ? `<span class="ats-label">${esc(job.application_adapter.label)}</span>` : ''}</div>
      ${resumes.length ? `<div class="resume-choice-head"><h3>איזה קובץ יישלח?</h3><p>JobPilot ממליץ על הגרסה עם חפיפת הסקילים הגבוהה ביותר. אפשר לשנות ידנית לפני הכנסה לתור.</p></div><label class="resume-selector">גרסת קורות חיים<select id="job-resume-select" onchange="updateResumeFit(this)">${resumes.sort((a,b)=>(b.fit?.score||0)-(a.fit?.score||0)).map((resume) => `<option value="${resume.id}" data-fit='${esc(JSON.stringify(resume.fit||{}))}' ${resume.fit?.recommended ? 'selected' : ''}>${resume.fit?.recommended?'מומלץ · ':''}${esc(resume.label)} · ${resume.fit?.score ?? 0}% התאמה</option>`).join('')}</select></label><div class="resume-fit" id="resume-fit"></div>` : '<div class="warning">לא הוגדרה גרסת קורות חיים. העלה גרסאות באזור המסמכים בפרופיל.</div>'}
      ${applicationAgentAllowed() && automaticSupported ? `<div class="application-options">
        <button class="application-option application-option-auto" type="button" onclick="queueJob(${job.id},'auto',Number(document.querySelector('#job-resume-select')?.value)||null);closeModal()" ${alreadySubmitted ? 'disabled' : ''}>
          <i class="application-option-icon">↗</i><span class="application-option-copy"><small>ברקע בלבד</small><strong>בדיקה והגשה אוטומטית</strong><span>ירוץ ב־worker ענן נסתר. לא ייפתח אצלך אתר או חלון דפדפן.</span></span><b>←</b>
        </button>
      </div>` : automaticSupported ? `<div class="agent-restricted-note"><strong>הסוכן האוטומטי סגור בשלב הבטא</strong><span>בחשבון הזה אפשר עדיין לפתוח את אתר החברה ולהגיש ידנית.</span></div>` : `<div class="agent-restricted-note manual-only-note"><strong>הגשה אוטומטית אינה נתמכת במשרה הזו</strong><span>מערכת ${esc(job.application_adapter?.label || 'הגיוס')} מסומנת כרגע להגשה ידנית בלבד. JobPilot לא יפתח עבורך חלון נסתר ולא יציג כאילו המשרה נשלחה.</span></div>`}
      <div class="card-actions modal-actions">
        ${alreadySubmitted
          ? '<button class="btn applied-job-button" type="button" disabled>✓ הגשתי כבר למשרה זו</button>'
          : `<button class="btn secondary" type="button" onclick="markJobSubmitted(${job.id})">הגשתי כבר למשרה זו</button>`}
        <a class="btn secondary" target="_blank" rel="noopener" href="${safeUrl(job.apply_url)}">פתח באתר החברה</a>
        ${job.application_links?.slice(1).map((link) => `<a class="btn secondary" target="_blank" rel="noopener" href="${safeUrl(link.apply_url)}">הגש דרך ${esc(link.source || 'מקור נוסף')}</a>`).join('') || ''}
        <button class="btn secondary" type="button" onclick="openDraftComposer(${job.id})">טיוטת תשובה פתוחה</button>
        ${job.official_careers_url && job.official_careers_url !== job.apply_url ? `<a class="btn secondary" target="_blank" rel="noopener" href="${safeUrl(job.official_careers_url)}">עמוד הקריירה הרשמי</a>` : ''}
        <button class="btn danger" type="button" onclick="skipJob(${job.id})">לא רלוונטי</button>
        <button class="btn danger-outline" type="button" onclick="deleteJob(${job.id})">מחק משרה לצמיתות</button>
      </div>
    `);
    const resumeSelect=$('#job-resume-select'); if(resumeSelect) updateResumeFit(resumeSelect);
  } catch (error) {
    toast(error.message);
  }
}

function updateResumeFit(select){let fit={};try{fit=JSON.parse(select.selectedOptions[0]?.dataset.fit||'{}')}catch{}const missing=fit.missing_skills||[];const matched=fit.matched_skills||[];$('#resume-fit').innerHTML=`<div class="resume-fit-score"><strong>${fit.score ?? 0}% התאמת קורות חיים</strong><span>${matched.length} סקילים תואמים</span></div>${missing.length?`<p><strong>${missing.length} סקילים מרכזיים אינם מופיעים בגרסה:</strong> ${missing.map(esc).join(', ')}</p>`:'<p><strong>לא זוהו פערי סקילים מול הגרסה שנבחרה.</strong></p>'}`;}

let applicationsView = localStorage.getItem('jobpilot-applications-view') || 'kanban';
if (!['kanban', 'table'].includes(applicationsView)) applicationsView = 'kanban';

function syncApplicationsViewButtons() {
  [['kanban-view', 'kanban'], ['table-view', 'table']].forEach(([id, view]) => {
    const button = $(`#${id}`);
    if (!button) return;
    const active = applicationsView === view;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

async function loadApplications() {
  syncApplicationsViewButtons();
  loadApplicationCampaign().catch((error) => console.warn('Campaign load failed', error));
  $('#applications-list').innerHTML = skeleton(4, 'rows');
  state.applications = await api('/api/applications');
  const root = $('#applications-list');
  root.classList.toggle('kanban-wrap', applicationsView === 'kanban');
  setPageContext('applications', state.applications.length);
  if (applicationsView === 'kanban') { renderApplicationsKanban(root); return; }
  root.innerHTML = state.applications.length ? `
    <table><thead><tr><th>פעולה</th><th>משרה</th><th>חברה</th><th>סטטוס</th><th>מצב</th><th>ניסיונות</th><th>עודכן</th></tr></thead>
    <tbody>${state.applications.map((application) => `
      <tr class="interactive-table-row" data-job-id="${application.job_id}" tabindex="0">
        <td class="application-row-actions">${renderApplicationActions(application)}</td>
        <td>${esc(application.job?.title)}</td><td>${esc(application.job?.company)}</td>
        <td class="application-status-cell">${renderApplicationStatus(application)}</td><td>${esc(application.mode)}</td>
        <td>${application.attempt_count}</td><td>${dateFmt(application.updated_at)}</td>
      </tr>`).join('')}</tbody></table>
  ` : emptyState('↗', 'עדיין אין הגשות', 'משרות שתוסיף לתור יופיעו כאן עם סטטוס וניסיונות ההגשה.', '<button class="btn primary small" type="button" onclick="switchView(\'jobs\')">מצא משרה להגשה</button>');
  $$('.interactive-table-row', root).forEach((row) => {
    const open = () => showJob(Number(row.dataset.jobId));
    row.onclick = (event) => { if (!event.target.closest('button,a,input,select,textarea')) open(); };
    row.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
  });
}

let applicationCampaign = null;
async function loadApplicationCampaign() {
  if (!applicationAgentAllowed() || !$('#campaign-controls')) return;
  applicationCampaign = await api('/api/application-campaign');
  $('#campaign-mode').value = applicationCampaign.mode || 'simple';
  $('#campaign-daily-cap').value = applicationCampaign.daily_cap || 5;
  $('#campaign-budget-cap').value = applicationCampaign.budget_cap || '';
  $('#campaign-blocked-companies').value = (applicationCampaign.blocked_companies || []).join('\n');
  const runs = await api('/api/application-campaign/runs');
  $('#campaign-history').innerHTML = runs.length ? `<details><summary>היסטוריית בדיקות והרצות (${runs.length})</summary><div>${runs.slice(0,8).map(run => `<span><b>${run.status === 'activated' ? 'הופעל' : 'בדיקה'}</b><small>${dateFmt(run.created_at)} · ${run.queued_count || run.selected_count} בתור · ${run.skipped_count} דולגו</small></span>`).join('')}</div></details>` : '';
}

function campaignPayload() {
  return {
    mode: $('#campaign-mode').value,
    min_score: Number($('#threshold').value || 82),
    daily_cap: Number($('#campaign-daily-cap').value || 5),
    budget_cap: $('#campaign-budget-cap').value ? Number($('#campaign-budget-cap').value) : null,
    blocked_companies: $('#campaign-blocked-companies').value.split(/\n|,/).map(value => value.trim()).filter(Boolean),
  };
}

async function saveApplicationCampaign(showToast = true) {
  applicationCampaign = await api('/api/application-campaign', {method:'PATCH', body:JSON.stringify(campaignPayload())});
  if (showToast) toast('הקמפיין נשמר');
  return applicationCampaign;
}

async function previewApplicationCampaign() {
  try {
    await saveApplicationCampaign(false);
    const preview = await api('/api/application-campaign/dry-run', {method:'POST'});
    const token = encodeURIComponent(preview.preview_token || '');
    modal(`<span class="kicker">הרצה יבשה — דבר עדיין לא נשלח</span><h2>${preview.will_queue_count} משרות מוכנות לקמפיין</h2>
      <div class="campaign-preview-list">${preview.selected.length ? preview.selected.map(item => `<article><span><strong>${esc(item.title)}</strong><small>${esc(item.company)} · ${item.score}% · ${esc(item.adapter)}</small></span><b>מוכן</b></article>`).join('') : '<p>לא נמצאו משרות שעוברות את כל התנאים.</p>'}</div>
      <p class="muted">${preview.skipped.length} משרות דולגו בגלל חוסרים, חסימת חברה, כפילות או מגבלות הקמפיין.</p>
      <div class="modal-actions"><button class="btn secondary" type="button" onclick="closeModal()">חזרה להגדרות</button><button class="btn primary" type="button" ${preview.will_queue_count ? '' : 'disabled'} onclick="activateApplicationCampaign(${preview.run_id},decodeURIComponent('${token}'))">אשר והכנס לתור האוטומטי</button></div>`);
  } catch (error) { toast(error.message); }
}

async function activateApplicationCampaign(runId, previewToken) {
  try {
    const result = await api(`/api/application-campaign/runs/${runId}/activate`, {method:'POST',body:JSON.stringify({preview_token:previewToken})});
    closeModal();
    toast(`${result.queued_count} משרות נכנסו לתור האוטומטי`);
    await Promise.all([loadApplications(), loadDashboard()]);
  } catch (error) { toast(error.message); }
}
window.activateApplicationCampaign = activateApplicationCampaign;
$('#campaign-save').onclick = () => saveApplicationCampaign();
$('#campaign-preview').onclick = previewApplicationCampaign;

$('#kanban-view').onclick=()=>{applicationsView='kanban';localStorage.setItem('jobpilot-applications-view',applicationsView);syncApplicationsViewButtons();loadApplications();};
$('#table-view').onclick=()=>{applicationsView='table';localStorage.setItem('jobpilot-applications-view',applicationsView);syncApplicationsViewButtons();loadApplications();};
syncApplicationsViewButtons();

async function openDraftComposer(jobId) {
  modal(`<span class="kicker">טיוטה באישור שלך</span><h2>תשובה לשאלה פתוחה</h2><label>השאלה<textarea id="draft-question" placeholder="Why do you want to work here?"></textarea></label><label>טיוטה אופציונלית<textarea id="draft-text" rows="7" placeholder="השאר ריק כדי ש-JobPilot יכין נקודת פתיחה מותאמת"></textarea></label><label class="remember-label"><input id="draft-approved" type="checkbox" /> מאשר להשתמש בתשובה לאחר שאבדוק אותה</label><button class="btn primary" type="button" onclick="saveDraft(${jobId})">צור ושמור</button>`);
}
async function saveDraft(jobId){const result=await api(`/api/jobs/${jobId}/answer-drafts`,{method:'POST',body:JSON.stringify({question:$('#draft-question').value,draft:$('#draft-text').value||null,approved:$('#draft-approved').checked})});$('#draft-text').value=result.draft;toast(result.approved?'הטיוטה נשמרה ואושרה':'הטיוטה נשמרה ומחכה לאישור');}

function applicationBoardStatus(application){return application.status==='queued'&&application.auto_queue_eligible!==true?'saved':application.status}
function renderApplicationsKanban(root) {
  const columns = [['saved','נשמרה / ידנית'],['queued','בתור אוטומטי'],['applying','בטיפול'],['verification_pending','אימות'],['submitted','הוגשה'],['interview','ראיון'],['offer','הצעה'],['rejected','נדחתה']];
  root.classList.add('kanban-wrap');
  root.innerHTML = state.applications.length ? `<div class="kanban-board">${columns.map(([status,label]) => `<section class="kanban-column" data-status="${status}"><header><strong>${label}</strong><span>${state.applications.filter(a=>applicationBoardStatus(a)===status).length}</span></header><div>${state.applications.filter(a=>applicationBoardStatus(a)===status).map(a=>`<article class="kanban-card" draggable="true" data-application-id="${a.id}" onclick="showJob(${a.job_id})"><strong>${esc(a.job?.title)}</strong><span>${esc(a.job?.company)}</span>${a.status==='queued'&&a.auto_queue_eligible!==true?'<small>לא ממתינה ל־Auto Apply</small>':''}${a.reminder_at ? `<small>תזכורת: ${dateFmt(a.reminder_at)}</small>`:''}<button type="button" onclick="event.stopPropagation();editApplication(${a.id})">ניהול</button></article>`).join('')}</div></section>`).join('')}</div>` : emptyState('↗','עדיין אין הגשות','משרות שתשמור או תוסיף לתור יופיעו כאן.');
  $$('.kanban-card', root).forEach(card => card.ondragstart = e => e.dataTransfer.setData('text/plain', card.dataset.applicationId));
  $$('.kanban-column', root).forEach(column => { column.ondragover=e=>e.preventDefault(); column.ondrop=async e=>{ e.preventDefault(); await updateApplication(Number(e.dataTransfer.getData('text/plain')), {status:column.dataset.status}); }; });
}

async function updateApplication(id, payload) { await api(`/api/applications/${id}`, {method:'PATCH',body:JSON.stringify(payload)}); await loadApplications(); }

async function editApplication(id) {
  const item=state.applications.find(a=>a.id===id); if(!item)return;
  modal(`<span class="kicker">מעקב הגשה</span><h2>${esc(item.job?.title)}</h2><label>שלב<select id="application-stage">${['saved','queued','applying','needs_input','verification_pending','submitted','phone_screen','test','interview','offer','accepted','rejected'].map(s=>`<option value="${s}" ${s===item.status?'selected':''}>${statusLabel(s)}</option>`).join('')}</select></label><label>הערות<textarea id="application-notes">${esc(item.notes||'')}</textarea></label><label>מועד תזכורת<input id="application-reminder" type="datetime-local" /></label><label>מה להזכיר<input id="application-reminder-note" value="${esc(item.reminder_note||'')}" placeholder="מעקב מול המגייסת" /></label><button class="btn primary" type="button" onclick="saveApplicationEdit(${id})">שמור</button>`);
}
async function saveApplicationEdit(id){await updateApplication(id,{status:$('#application-stage').value,notes:$('#application-notes').value,reminder_at:$('#application-reminder').value||null,reminder_note:$('#application-reminder-note').value});closeModal();}

function renderOwnedSkills(skills = []) {
  const root = $('#my-skills');
  if (!root) return;
  root.innerHTML = skills.length
    ? skills.map((skill) => `<span>${esc(skill)} <button type="button" title="הסר" onclick="removeSkill(decodeURIComponent('${encodeURIComponent(skill)}'))">×</button></span>`).join('')
    : emptyState('＋', 'רשימת הסקילים עדיין ריקה', 'הוסף סקילים מתוך הצעות המערכת או דרך העדפות החיפוש.', '<button class="btn secondary small" type="button" onclick="switchView(\'preferences\')">להעדפות החיפוש</button>');
}

function syncSkillsEverywhere(skills = [], changedSkill = '') {
  const normalized = [...new Set((skills || []).map((value) => String(value).trim()).filter(Boolean))];
  if (state.profile) state.profile = { ...state.profile, skills: normalized };
  if (state.profileLoaded && profileForm()?.elements?.skills) {
    applyArrayFieldToControls('skills', normalized);
    updateProfileDirtyState();
    updateProfileSectionSummaries();
  }
  if (state.skillsOverview) state.skillsOverview.profile_skills = normalized;
  renderOwnedSkills(normalized);

  // Resume suggestions live in another surface. Remove an accepted skill from all
  // visible CV suggestion cards immediately instead of waiting for a full re-fetch.
  if (changedSkill) {
    $$('[data-resume-suggestion][data-field="skills"]').forEach((button) => {
      const value = decodeURIComponent(button.dataset.value || '');
      if (value.trim().toLowerCase() === changedSkill.trim().toLowerCase()) button.remove();
    });
  }
}

async function loadSkills() {
  $('#my-skills').innerHTML = skeleton(2, 'rows');
  $('#skill-suggestions').innerHTML = skeleton(3, 'rows');
  state.skillsOverview = await api('/api/skills/overview');
  setPageContext('skills', state.skillsOverview.profile_skills.length);
  renderOwnedSkills(state.skillsOverview.profile_skills);
  $('#skill-suggestions').innerHTML = state.skillsOverview.suggestions.length
    ? state.skillsOverview.suggestions.map((item) => `<article class="skill-suggestion"><div><strong>${esc(item.skill)}</strong><span>מופיע ב־${item.job_count} משרות</span><small>${item.jobs.map((job) => `${esc(job.company)} — ${esc(job.title)}`).join('<br>')}</small></div><button class="btn secondary small" type="button" onclick="addSkill(decodeURIComponent('${encodeURIComponent(item.skill)}'))">הוסף לסקילים שלי</button></article>`).join('')
    : emptyState('✓', 'אין כרגע פערי סקילים חדשים', 'כל הסקילים שזוהו במשרות הפעילות כבר מופיעים בפרופיל שלך.');
}

async function addSkill(skill, reopenJobId = null) {
  try {
    const result = await api('/api/profile/skills', { method: 'POST', body: JSON.stringify({ skill }) });
    syncSkillsEverywhere(result.skills || [], skill);
    toast(`${skill} נוסף מיד · ציוני המשרות מתעדכנים ברקע`);
    if (state.activeView === 'skills') loadSkills().catch((error) => console.warn('Skill overview refresh failed', error));
    if (state.activeView === 'jobs') loadJobs({ silent:true }).catch((error) => console.warn('Jobs refresh failed', error));
    if (reopenJobId) await showJob(reopenJobId);
  } catch (error) {
    toast(error.message);
  }
}

async function removeSkill(skill) {
  if (!confirm(`להסיר את ${skill} מרשימת הסקילים שלך?`)) return;
  try {
    const result = await api(`/api/profile/skills?skill=${encodeURIComponent(skill)}`, { method: 'DELETE' });
    syncSkillsEverywhere(result.skills || []);
    toast(`${skill} הוסר · ציוני המשרות מתעדכנים ברקע`);
    loadSkills().catch((error) => console.warn('Skill overview refresh failed', error));
  } catch (error) {
    toast(error.message);
  }
}

async function showSkillGaps(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    modal(`<span class="kicker">פערי סקילים</span><h2>${esc(job.company)} — ${esc(job.title)}</h2><p>במשרה זוהו ${job.skill_gaps.length} סקילים שאינם כרגע בפרופיל שלך:</p><div class="skill-gap-list">${job.skill_gaps.map((skill) => `<button type="button" onclick="addSkill(decodeURIComponent('${encodeURIComponent(skill)}'), ${job.id})">+ ${esc(skill)}</button>`).join('')}</div><p class="skill-honesty-note">לחץ להוספה רק אם זה סקיל שכבר יש לך.</p>`);
  } catch (error) {
    toast(error.message);
  }
}

async function retryApp(id) {
  try {
    await api(`/api/applications/${id}/retry`, { method: 'POST' });
    toast('ההגשה הוחזרה לתור');
    await Promise.all([loadApplications(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

async function removeApplication(id) {
  if (!confirm('להסיר את המשרה מתור ההגשות? המשרה עצמה תישאר ברשימת המשרות.')) return;
  try {
    await api(`/api/applications/${id}`, { method: 'DELETE' });
    toast('המשרה הוסרה מהתור ונשארה ברשימת המשרות');
    await Promise.all([loadApplications(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

function renderBlockerCard(blocker) {
  const meta = blockerMeta(blocker.kind);
  const target = blocker.page_url || blocker.job?.apply_url || '#';
  let interaction = '';
  if (blocker.kind === 'review_before_submit') {
    interaction = `<div class="blocker-decision">
      <button class="btn primary" type="button" onclick="markApplicationSubmitted(${blocker.application_id})">סמן כהוגש לאחר שליחה ידנית</button>
      <button class="btn secondary" type="button" onclick="resolveBlockerAction(${blocker.id},'skip')">דלג על המשרה</button>
    </div>`;
  } else if (blocker.kind === 'grade_sheet_required') {
    const hasGradeSheet = Boolean(state.profile?.grade_sheet_uploaded);
    interaction = hasGradeSheet
      ? `<div class="blocker-manual-note blocker-auto-resolving"><span class="live-dot"></span> גיליון הציונים כבר שמור בפרופיל. JobPilot משחרר את ההגשה ומפעיל ניסיון חוזר אוטומטית — אין צורך לאשר שוב.</div>`
      : `<div class="blocker-manual-note">גיליון הציונים נשמר בפרופיל ומשמש אוטומטית בכל הגשה שתבקש אותו.</div><div class="blocker-decision"><button class="btn primary" type="button" onclick="openGradeSheetProfile()">העלה גיליון ציונים בפרופיל</button></div>`;
  } else if (blocker.kind === 'file_required') {
    interaction = `<div class="blocker-manual-note">הטופס דורש מסמך נוסף שאינו קורות חיים או גיליון ציונים. כרגע יש להשלים את המסמך הזה ידנית.</div>`;
  } else if (blocker.kind === 'submit_not_sent') {
    interaction = `<div class="blocker-manual-note">לא זוהתה בקשת הגשה שיצאה מהדפדפן. אפשר לפתוח את הטופס כדי לראות את החסימה, או לנסות שוב אחרי תיקון הפרט שמוצג.</div><div class="blocker-decision"><button class="btn secondary" type="button" onclick="retryApp(${blocker.application_id})">נסה שוב</button></div>`;
  } else if (blocker.kind === 'captcha' || blocker.kind === 'linkedin_manual' || blocker.kind === 'confirmation_missing') {
    interaction = `<div class="blocker-manual-note">הטופס זמין בקישור הישיר. לאחר שסיימת בו ידנית, אפשר לסמן את ההגשה כהושלמה.</div>`;
  } else if (blocker.kind === 'choice_required' && Array.isArray(blocker.options) && blocker.options.length) {
    interaction = `<div class="blocker-choice-options" aria-label="אפשרויות תשובה">${blocker.options.map((option) => `<button class="btn secondary small" type="button" data-choice-blocker="${blocker.id}" data-choice-application="${blocker.application_id}" data-choice-answer="${esc(option)}">${esc(option)}</button>`).join('')}</div>
      <div class="blocker-memory-note">התשובה תיזכר אוטומטית למשרות הבאות ב־${esc(blocker.job?.company || 'אותה חברה')}.</div>`;
  } else {
    interaction = `<div class="blocker-answer"><input id="answer-${blocker.id}" placeholder="כתוב תשובה מאושרת" />
      <div class="blocker-memory-note">התשובה תיזכר אוטומטית למשרות הבאות ב־${esc(blocker.job?.company || 'אותה חברה')}.</div>
      <label class="remember-label"><input id="remember-${blocker.id}" type="checkbox" /> השתמש בתשובה גם בחברות אחרות כשהשאלה זהה</label>
      <button class="btn primary" type="button" onclick="resolveBlocker(${blocker.id})">שמור והמשך</button></div>`;
  }
  return `<article class="blocker-card blocker-${meta.tone}">
    <div><div class="blocker-title-line"><span class="blocker-kind-badge"><b>${esc(meta.icon)}</b>${esc(meta.label)}</span><h3>${esc(blocker.job?.company)} — ${esc(blocker.job?.title)}</h3></div>
      <p><strong>${esc(blocker.question || blocker.field_label || meta.short)}</strong></p><p>${esc(blocker.explanation)}</p>
      ${blocker.options.length && !['review_before_submit','grade_sheet_required','file_required'].includes(blocker.kind) ? `<div class="skills">${blocker.options.map((option) => `<span>${esc(option)}</span>`).join('')}</div>` : ''}
      ${interaction}
    </div>
    <div class="blocker-actions"><button class="btn secondary small" type="button" onclick="showJob(${blocker.job?.id})">פרטי משרה</button>
      <a class="btn primary small" target="_blank" rel="noopener" href="${safeUrl(target)}">פתח והמשך מהנקודה</a>
      ${(blocker.kind === 'captcha' || blocker.kind === 'linkedin_manual' || blocker.kind === 'confirmation_missing') ? `<button class="btn secondary small" type="button" onclick="markApplicationSubmitted(${blocker.application_id})">סמן כהוגש ידנית</button>` : ''}
      ${blocker.screenshot_url ? `<a class="btn secondary small" target="_blank" href="${esc(blocker.screenshot_url)}">צילום מסך</a>` : ''}</div>
  </article>`;
}

function openGradeSheetProfile() {
  switchView('profile', { profileSection: 'personal' });
  window.setTimeout(() => {
    const card = document.querySelector('[data-profile-document="grade-sheet"]');
    card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card?.classList.add('document-attention');
    window.setTimeout(() => card?.classList.remove('document-attention'), 1800);
  }, 80);
}

async function loadBlockers() {
  $('#blockers-list').innerHTML = skeleton(3, 'rows');
  state.blockers = await api('/api/blockers');
  ['#blocker-count','#blocker-tab-count','#mobile-application-blocker-count'].forEach(selector=>{
    const badge=$(selector);if(!badge)return;badge.textContent=state.blockers.length;badge.hidden=!state.blockers.length;
  });
  const root = $('#blockers-list');
  setPageContext('blockers', state.blockers.length);
  root.innerHTML = state.blockers.length ? state.blockers.map(renderBlockerCard).join('') : emptyState('✓', 'הכול מטופל', 'אין כרגע שאלות, אימותים או פעולות שמחכים לך.');
  bindChoiceBlockerButtons(root);
}

async function resolveBlocker(id) {
  const answerInput = $(`#answer-${id}`);
  const answer = answerInput?.value.trim() || '';
  if (!answer) return toast('צריך להזין תשובה');
  try {
    await api(`/api/blockers/${id}/resolve`, {
      method: 'POST', body: JSON.stringify({ answer, remember: $(`#remember-${id}`)?.checked || false }),
    });
    toast('התשובה נשמרה לחברה הזו וההגשה חזרה לתור');
    await Promise.all([loadBlockers(), loadApplications(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

async function resolveChoiceBlocker(blockerId, applicationId, answer, button = null) {
  if (!answer) return;
  const originalText = button?.textContent || '';
  if (button) { button.disabled = true; button.textContent = 'ממשיך…'; }
  try {
    await api(`/api/blockers/${blockerId}/resolve`, {
      method: 'POST', body: JSON.stringify({ answer, remember: false }),
    });
    toast('התשובה נשמרה לחברה הזו — ההגשה ממשיכה אוטומטית');
    await Promise.all([loadBlockers(), loadApplications(), loadDashboard()]);
    if (Number(applicationId) === Number(trackedApplicationId)) startApplicationTracking(applicationId, false);
  } catch (error) {
    if (button) { button.disabled = false; button.textContent = originalText; }
    toast(error.message);
  }
}

function bindChoiceBlockerButtons(root) {
  $$('[data-choice-blocker]', root).forEach((button) => {
    button.onclick = () => resolveChoiceBlocker(
      Number(button.dataset.choiceBlocker),
      Number(button.dataset.choiceApplication),
      button.dataset.choiceAnswer || '',
      button,
    );
  });
}

async function resolveBlockerAction(id, action, applicationId = null) {
  try {
    await api(`/api/blockers/${id}/resolve`, {
      method: 'POST', body: JSON.stringify({ action }),
    });
    if (action === 'approve_submit') toast('אישור חד־פעמי נשמר — ה־Agent ישלח בניסיון הבא');
    else if (action === 'use_profile_grade_sheet') toast('גיליון הציונים השמור צורף · ההגשה חזרה לתור');
    else toast('ההגשה דולגה');
    if (action === 'use_profile_grade_sheet' && applicationId) startApplicationTracking(applicationId, true);
    await Promise.all([loadBlockers(), loadApplications(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

async function markApplicationSubmitted(id) {
  if (!confirm('לסמן שהמועמדות הוגשה ידנית?')) return;
  try {
    await api(`/api/applications/${id}/mark-submitted`, { method: 'POST' });
    toast('המועמדות סומנה כהוגשה');
    await Promise.all([loadBlockers(), loadApplications(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

async function loadSources() {
  $('#sources-list').innerHTML = skeleton(4, 'rows');
  state.sources = await api('/api/sources');
  renderSourceErrorBadge(state.sources.filter((source) => source.enabled && source.last_error).length);
  const root = $('#sources-list');
  setPageContext('sources', state.sources.length);
  const canManageSources = sourceManagementAllowed();
  const installButton = $('#install-recommended-sources');
  const sourceForm = $('#source-form');
  if (installButton) installButton.hidden = !canManageSources;
  if (sourceForm) sourceForm.closest('.sticky-card').hidden = !canManageSources;
  root.innerHTML = state.sources.length ? state.sources.map((source) => `
    <div class="source-item interactive-row ${source.enabled ? '' : 'source-disabled'}" role="button" tabindex="0" data-source-id="${source.id}">
      ${sourceLogoMarkup(source)}
      <div class="source-main"><strong>${esc(source.name)}</strong><span>${esc(source.kind)} · ${esc(source.identifier)}${source.last_scanned_at ? ` · נסרק ${dateFmt(source.last_scanned_at)}` : ''}${source.disabled_until ? ` · בהשהיה עד ${dateFmt(source.disabled_until)}` : ''}</span><div class="source-health"><i><b style="width:${source.health_score}%"></b></i><strong>${source.health_score}% בריאות מקור</strong></div></div>
      <div class="source-item-controls" data-no-source-click>${canManageSources ? `<div class="source-actions">
        <label class="source-toggle" title="${source.enabled ? 'המקור נסרק במסלול הזה' : 'המקור לא ייכלל בסריקות'}" onclick="event.stopPropagation()">
          <input type="checkbox" ${source.enabled ? 'checked' : ''} aria-label="${source.enabled ? 'כבה' : 'הפעל'} את ${esc(source.name)}" onchange="event.stopPropagation();toggleSource(${source.id},this.checked,this)" />
          <span class="source-toggle-track" aria-hidden="true"><i></i></span>
          <span class="source-toggle-copy"><strong>${source.enabled ? 'פעיל' : 'כבוי'}</strong><small>${source.enabled ? 'ייכלל בסריקה' : 'לא ייסרק'}</small></span>
        </label>
        <button class="btn danger small" type="button" onclick="event.stopPropagation();deleteSource(${source.id})">מחק</button>
      </div>` : '<span class="source-readonly-note">מנוהל אוטומטית</span>'}</div>
    </div>
  `).join('') : emptyState('⌁', 'לא הוגדרו מקורות משרות', canManageSources ? 'אפשר להוסיף מקור ידנית או להתקין את רשימת המקורות המומלצים.' : 'המקורות מנוהלים על ידי מנהל המערכת.', canManageSources ? '<button class="btn primary small" type="button" onclick="installRecommendedSources()">הוסף מקורות מומלצים</button>' : '');
  $$('.source-item', root).forEach((item) => {
    const open = () => showSource(Number(item.dataset.sourceId));
    item.onclick = (event) => { if (!event.target.closest('button,input,label,[role="switch"]')) open(); };
    item.onkeydown = (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
  });
}

function showSource(id) {
  const source = state.sources.find((item) => item.id === id);
  if (!source) return;
  modal(`
    <div class="source-modal-heading">${sourceLogoMarkup(source, 'source-logo-modal')}<div><span class="kicker">מקור משרות</span><h2>${esc(source.name)}</h2></div></div>
    <div class="source-detail-grid"><span>מערכת</span><strong>${esc(source.kind)}</strong><span>מזהה</span><strong>${esc(source.identifier)}</strong><span>חברה</span><strong>${esc(source.company_name || 'לא הוגדרה')}</strong><span>מצב</span><strong>${source.disabled_until ? 'מושהה זמנית' : source.enabled ? 'פעיל' : 'כבוי'}</strong><span>בריאות מקור</span><strong>${source.health_score}% · ${source.consecutive_failures} כשלים רצופים</strong><span>סריקה אחרונה</span><strong>${dateFmt(source.last_scanned_at)}</strong></div>
    ${source.last_error ? `<div class="warning">${esc(source.last_error)}</div>` : ''}
    ${sourceManagementAllowed() ? `<div class="card-actions modal-actions"><label class="source-toggle source-toggle-modal"><input type="checkbox" ${source.enabled ? 'checked' : ''} onchange="toggleSource(${source.id},this.checked,this);closeModal()" /><span class="source-toggle-track" aria-hidden="true"><i></i></span><span class="source-toggle-copy"><strong>${source.enabled ? 'פעיל' : 'כבוי'}</strong><small>${source.enabled ? 'ייכלל בסריקה הבאה' : 'לא ייסרק'}</small></span></label><button class="btn danger" type="button" onclick="deleteSource(${source.id});closeModal()">מחק מקור</button></div>` : '<div class="automation-note">המקורות מנוהלים על ידי מנהל המערכת והסריקה מתבצעת אוטומטית בכל שעה עגולה.</div>'}
  `);
}

async function installRecommendedSources() {
  const button = $('#install-recommended-sources');
  if (button) button.disabled = true;
  try {
    const result = await api('/api/sources/recommended/install', { method: 'POST' });
    toast(result.installed ? `נוספו ${result.installed} מקורות מומלצים` : 'כל המקורות המומלצים כבר מותקנים');
    await loadSources();
  } catch (error) {
    toast(error.message);
  } finally {
    if (button) button.disabled = false;
  }
}

$('#install-recommended-sources').onclick = installRecommendedSources;

$('#source-form').onsubmit = async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target).entries());
  try {
    await api('/api/sources', { method: 'POST', body: JSON.stringify(body) });
    event.target.reset();
    toast('המקור נוסף');
    await loadSources();
  } catch (error) {
    toast(error.message);
  }
};

async function toggleSource(id, enabled, input = null) {
  try {
    if (input) input.disabled = true;
    await api(`/api/sources/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) });
    toast(enabled ? 'המקור הופעל' : 'המקור כובה');
    await loadSources();
  } catch (error) {
    if (input) { input.checked = !enabled; input.disabled = false; }
    toast(error.message);
  }
}

async function deleteSource(id) {
  if (!confirm('למחוק את המקור וכל המשרות שנאספו ממנו?')) return;
  try {
    await api(`/api/sources/${id}`, { method: 'DELETE' });
    toast('המקור נמחק');
    await Promise.all([loadSources(), loadDashboard()]);
  } catch (error) {
    toast(error.message);
  }
}

// ---------------- Profile draft and unsaved state ----------------

const LEGACY_PROFILE_DRAFT_KEY = 'jobpilot.profileDraft.v1';
const profileDraftKey = () => `jobpilot.profileDraft.v3.${state.activeCareerTrack || 'computer_science'}`;
const PROFILE_TEXT_FIELDS = [
  'full_name', 'email', 'phone', 'location', 'linkedin_url', 'github_url', 'portfolio_url',
  'application_password', 'years_experience_options', 'degree_level', 'skills', 'desired_titles', 'preferred_locations',
  'preferred_work_modes', 'keywords', 'excluded_keywords', 'auto_apply_threshold',
];
const APPLICATION_PROFILE_FIELDS = [
  'preferred_name', 'pronouns', 'country', 'city', 'address_line1', 'address_line2', 'state', 'postal_code',
  'phone_country_code', 'website_url', 'work_experiences',
  'education_school', 'education_field', 'education_grade', 'education_start_date',
  'education_end_date', 'languages', 'certifications', 'notice_period', 'available_start_date',
];
const EXTRA_PROFILE_FIELDS = APPLICATION_PROFILE_FIELDS.map((name) => `extra_${name}`);
const PROFILE_CHECK_FIELDS = ['work_authorization', 'needs_sponsorship', 'auto_submit_enabled'];
const PROFILE_ARRAY_FIELDS = new Set(['years_experience_options', 'skills', 'desired_titles', 'preferred_locations', 'preferred_work_modes', 'keywords', 'excluded_keywords']);
const PRIORITY_PROFILE_ARRAY_FIELDS = new Set(['skills', 'desired_titles', 'preferred_locations', 'preferred_work_modes', 'keywords', 'excluded_keywords']);
const SEARCH_PREFERENCE_FIELDS = new Set(['skills', 'desired_titles', 'preferred_locations', 'preferred_work_modes', 'keywords', 'excluded_keywords']);
const PROFILE_NUMBER_FIELDS = new Set(['auto_apply_threshold']);
const PROFILE_FIELDS = [...PROFILE_TEXT_FIELDS, ...PROFILE_CHECK_FIELDS, ...EXTRA_PROFILE_FIELDS];

function profileForm() {
  return $('#profile-form');
}

function savedProfileFormValue(name) {
  if (name === 'extra_languages') return JSON.stringify(normalizeLanguages(state.profile?.application_profile?.languages));
  if (name === 'extra_work_experiences') return JSON.stringify(normalizeWorkExperiences(state.profile?.application_profile));
  if (name.startsWith('extra_')) return String(state.profile?.application_profile?.[name.slice(6)] ?? '');
  if (name === 'application_password') return '';
  if (PROFILE_CHECK_FIELDS.includes(name)) return !!state.profile?.[name];
  if (PROFILE_ARRAY_FIELDS.has(name)) return (state.profile?.[name] || []).join(', ');
  return String(state.profile?.[name] ?? '');
}

function currentProfileFormValue(name) {
  const control = profileForm()?.elements[name];
  if (!control) return '';
  if (name === 'extra_languages') return JSON.stringify(collectLanguages());
  if (name === 'extra_work_experiences') return JSON.stringify(collectWorkExperiences());
  if (PROFILE_ARRAY_FIELDS.has(name)) {
    const selected = $$(`[data-profile-option="${name}"]:checked`, profileForm()).map((item) => item.value);
    const custom = String(control.value || '').split(',').map((item) => item.trim()).filter(Boolean);
    return [...new Set([...selected, ...custom])].join(', ');
  }
  return control.type === 'checkbox' ? control.checked : control.value;
}

function normalizedProfileValue(name, value) {
  if (PROFILE_CHECK_FIELDS.includes(name)) return !!value;
  if (PROFILE_ARRAY_FIELDS.has(name)) {
    const values = String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
    return PRIORITY_PROFILE_ARRAY_FIELDS.has(name) ? values : values.sort((a, b) => a.localeCompare(b, undefined, { numeric:true }));
  }
  if (PROFILE_NUMBER_FIELDS.has(name)) return Number(value || 0);
  if (name === 'extra_languages') return normalizeLanguages(value)
    .sort((a, b) => a.name.localeCompare(b.name));
  if (name === 'extra_work_experiences') return normalizeWorkExperiences(value);
  return String(value ?? '');
}

function setFieldUnsaved(name, isUnsaved) {
  const control = profileForm()?.elements[name];
  if (!control) return;
  const label = control.closest('label');
  if (!label) return;
  let note = label.querySelector(`.unsaved-note[data-field="${name}"]`);
  if (isUnsaved && !note) {
    note = document.createElement('small');
    note.className = 'unsaved-note';
    note.dataset.field = name;
    note.textContent = 'הנתון לא נשמר עדיין';
    label.appendChild(note);
  }
  if (!isUnsaved && note) note.remove();
  label.classList.toggle('has-unsaved', isUnsaved);
  control.closest('.preference-group')?.classList.toggle('has-unsaved', isUnsaved);
  control.setAttribute('aria-invalid', isUnsaved ? 'true' : 'false');
}

function syncProfileOptionVisual(control) {
  if (!control?.dataset?.profileOption) return;
  const label = control.closest('label');
  label?.classList.toggle('is-option-checked', control.checked);
  label?.setAttribute('aria-checked', String(control.checked));
}

function applyArrayFieldToControls(name, values) {
  const normalized = (values || []).map((value) => String(value).trim()).filter(Boolean);
  const options = $$(`[data-profile-option="${name}"]`, profileForm());
  const known = new Set(options.map((option) => option.value.toLowerCase()));
  options.forEach((option) => {
    option.checked = normalized.some((value) => value.toLowerCase() === option.value.toLowerCase());
    syncProfileOptionVisual(option);
  });
  const custom = normalized.filter((value) => !known.has(value.toLowerCase()));
  profileForm().elements[name].value = custom.join(', ');
  if (PRIORITY_PROFILE_ARRAY_FIELDS.has(name)) syncPreferenceOptionOrder(name, normalized, false);
}

function animateOptionReorder(grid, mutate) {
  const labels = $$(':scope > label', grid);
  const before = new Map(labels.map((label) => [label, label.getBoundingClientRect()]));
  mutate();
  labels.forEach((label) => {
    const first = before.get(label); const last = label.getBoundingClientRect();
    const dx = first.left - last.left; const dy = first.top - last.top;
    if (dx || dy) label.animate([{ transform:`translate(${dx}px,${dy}px)` },{ transform:'translate(0,0)' }], { duration:440, easing:'cubic-bezier(.32,.72,0,1)' });
  });
}
function refreshPreferencePriorities(grid) {
  $$(':scope > label', grid).forEach((label) => { delete label.dataset.priority; });
  $$(':scope > label:has(input:checked)', grid).forEach((label,index) => { label.dataset.priority = String(index + 1); });
}
function syncPreferenceOptionOrder(name, preferredValues = null, animate = true) {
  const group = $(`.preference-group[data-field="${name}"]`, profileForm());
  const grid = $('.option-grid', group);
  if (!grid) return;
  const labels = $$(':scope > label', grid);
  labels.forEach((label,index) => { if (!label.dataset.originalOrder) label.dataset.originalOrder = String(index); });
  const order = new Map((preferredValues || labels.filter((label) => $('input',label).checked).map((label) => $('input',label).value))
    .map((value,index) => [String(value).toLowerCase(),index]));
  const mutate = () => labels.sort((a,b) => {
    const ai = $('input',a); const bi = $('input',b);
    if (ai.checked !== bi.checked) return ai.checked ? -1 : 1;
    if (ai.checked) return (order.get(ai.value.toLowerCase()) ?? 999) - (order.get(bi.value.toLowerCase()) ?? 999);
    return Number(a.dataset.originalOrder) - Number(b.dataset.originalOrder);
  }).forEach((label) => grid.appendChild(label));
  if (animate) animateOptionReorder(grid, mutate); else mutate();
  refreshPreferencePriorities(grid);
}

const LANGUAGE_LEVELS = ['Native / Bilingual', 'Fluent', 'Advanced', 'Intermediate', 'Beginner'];

function normalizeLanguages(value) {
  if (Array.isArray(value)) return value.map((item) => typeof item === 'string'
    ? { name: item.trim(), proficiency: '' }
    : { name: String(item.name || '').trim(), proficiency: String(item.proficiency || '') }).filter((item) => item.name);
  if (!value) return [];
  try { return normalizeLanguages(JSON.parse(value)); } catch { /* Legacy comma-separated value. */ }
  return String(value).split(',').map((name) => ({ name: name.trim(), proficiency: '' })).filter((item) => item.name);
}

function languageRow(item = {}, removable = true) {
  const options = ['', ...LANGUAGE_LEVELS].map((level) => `<option value="${esc(level)}" ${level === item.proficiency ? 'selected' : ''}>${esc(level || 'בחר רמת שליטה')}</option>`).join('');
  return `<div class="language-row" data-language-row>
    <input data-language-name value="${esc(item.name || '')}" placeholder="שם השפה" aria-label="שם השפה" />
    <select data-language-level aria-label="רמת שליטה">${options}</select>
    ${removable ? '<button class="btn danger-outline small" type="button" data-remove-language>הסר</button>' : '<span></span>'}
  </div>`;
}

function renderLanguages(value) {
  const saved = normalizeLanguages(value);
  const byName = new Map(saved.map((item) => [item.name.toLowerCase(), item]));
  const defaults = [byName.get('hebrew') || { name: 'Hebrew', proficiency: '' }, byName.get('english') || { name: 'English', proficiency: '' }];
  const additional = saved.filter((item) => !['hebrew', 'english'].includes(item.name.toLowerCase()));
  $('#language-rows').innerHTML = [...defaults.map((item) => languageRow(item, false)), ...additional.map((item) => languageRow(item, true))].join('');
  bindLanguageRows();
}

function collectLanguages() {
  return $$('[data-language-row]', $('#language-rows')).map((row) => ({
    name: $('[data-language-name]', row).value.trim(), proficiency: $('[data-language-level]', row).value,
  })).filter((item) => item.name && item.proficiency);
}

function bindLanguageRows() {
  $$('[data-remove-language]', $('#language-rows')).forEach((button) => {
    button.onclick = () => { button.closest('[data-language-row]').remove(); updateProfileDirtyState(); };
  });
}

function normalizeWorkExperiences(value) {
  let source = value;
  if (typeof source === 'string') {
    try { source = JSON.parse(source); } catch { source = []; }
  }
  if (source && !Array.isArray(source) && typeof source === 'object') {
    if (Array.isArray(source.work_experiences)) source = source.work_experiences;
    else {
      const legacy = {
        job_title: source.current_job_title || '', company: source.current_company || '',
        location: source.employment_location || '', employment_type: source.employment_type || '',
        start_date: source.employment_start_date || '', end_date: source.employment_end_date || '',
        description: source.employment_description || '',
      };
      source = Object.values(legacy).some(Boolean) ? [legacy] : [];
    }
  }
  return (Array.isArray(source) ? source : []).map((item) => ({
    job_title: String(item?.job_title || item?.title || '').trim(),
    company: String(item?.company || '').trim(),
    location: String(item?.location || '').trim(),
    employment_type: String(item?.employment_type || item?.type || '').trim(),
    start_date: String(item?.start_date || '').trim(),
    end_date: String(item?.end_date || '').trim(),
    description: String(item?.description || '').trim(),
  })).filter((item) => Object.values(item).some(Boolean));
}

function employmentEntry(item = {}, index = 0) {
  const typeOptions = ['', 'Full-time', 'Part-time', 'Contract', 'Internship', 'Self-employed']
    .map((value) => `<option value="${esc(value)}" ${value === item.employment_type ? 'selected' : ''}>${esc(value || 'לא נבחר')}</option>`).join('');
  return `<article class="employment-entry" data-employment-entry>
    <div class="employment-entry-head"><strong>ניסיון ${index + 1}</strong><button class="btn danger-outline small" type="button" data-remove-employment>הסר</button></div>
    <div class="form-grid">
      <label>תפקיד<input data-work-field="job_title" value="${esc(item.job_title || '')}" /></label>
      <label>חברה<input data-work-field="company" value="${esc(item.company || '')}" /></label>
      <label>מיקום העבודה<input data-work-field="location" value="${esc(item.location || '')}" /></label>
      <label>סוג העסקה<select data-work-field="employment_type">${typeOptions}</select></label>
      <label>תאריך התחלה<input data-work-field="start_date" type="month" value="${esc(item.start_date || '')}" /></label>
      <label>תאריך סיום<input data-work-field="end_date" type="month" value="${esc(item.end_date || '')}" /><small>השאר ריק אם זו העבודה הנוכחית.</small></label>
      <label class="wide-field">תיאור תפקיד והישגים<textarea data-work-field="description" rows="3">${esc(item.description || '')}</textarea></label>
    </div>
  </article>`;
}

function collectWorkExperiences() {
  return $$('[data-employment-entry]', $('#employment-entries')).map((entry) => {
    const value = (field) => $(`[data-work-field="${field}"]`, entry)?.value?.trim() || '';
    return {
      job_title: value('job_title'), company: value('company'), location: value('location'),
      employment_type: value('employment_type'), start_date: value('start_date'), end_date: value('end_date'),
      description: value('description'),
    };
  }).filter((item) => Object.values(item).some(Boolean));
}

function syncEmploymentHidden() {
  const hidden = profileForm()?.elements?.extra_work_experiences;
  if (hidden) hidden.value = JSON.stringify(collectWorkExperiences());
}

function bindEmploymentEntries() {
  $$('[data-remove-employment]', $('#employment-entries')).forEach((button) => {
    button.onclick = () => {
      button.closest('[data-employment-entry]')?.remove();
      if (!$('#employment-entries').children.length) renderWorkExperiences([]);
      else {
        $$('[data-employment-entry] .employment-entry-head strong', $('#employment-entries')).forEach((title,index) => { title.textContent = `ניסיון ${index + 1}`; });
        syncEmploymentHidden(); updateProfileDirtyState(); updateProfileSectionSummaries();
      }
    };
  });
  $$('[data-work-field]', $('#employment-entries')).forEach((control) => {
    control.addEventListener('input', () => { syncEmploymentHidden(); updateProfileDirtyState(); updateProfileSectionSummaries(); });
    control.addEventListener('change', () => { syncEmploymentHidden(); updateProfileDirtyState(); updateProfileSectionSummaries(); });
  });
}

function renderWorkExperiences(applicationProfile = {}) {
  const items = normalizeWorkExperiences(applicationProfile);
  const visible = items.length ? items : [{}];
  $('#employment-entries').innerHTML = visible.map((item,index) => employmentEntry(item,index)).join('');
  bindEmploymentEntries();
  syncEmploymentHidden();
}

function captureProfileDraft() {
  const values = {};
  PROFILE_FIELDS.filter((name) => name !== 'application_password')
    .forEach((name) => { values[name] = currentProfileFormValue(name); });
  return values;
}

function profileFieldValuesEqual(name, current, saved) {
  // Skill order is presentation-only. Custom skills live in a free-text control and
  // are rendered after the preset checkboxes, so the same saved skill set can
  // legitimately come back in a different UI order. Do not manufacture a dirty
  // state from that representation detail.
  if (name === 'skills') {
    const canonical = (values) => [...values].map((value) => String(value).trim().toLowerCase()).filter(Boolean).sort();
    return JSON.stringify(canonical(current)) === JSON.stringify(canonical(saved));
  }
  return JSON.stringify(current) === JSON.stringify(saved);
}

function getDirtyProfileFields() {
  if (!state.profileLoaded) return [];
  return PROFILE_FIELDS.filter((name) => {
    const current = normalizedProfileValue(name, currentProfileFormValue(name));
    const saved = normalizedProfileValue(name, savedProfileFormValue(name));
    return !profileFieldValuesEqual(name, current, saved);
  });
}

function persistProfileDraft(dirtyFields = getDirtyProfileFields()) {
  try {
    if (!dirtyFields.length) {
      localStorage.removeItem(profileDraftKey());
      if (state.activeCareerTrack === 'computer_science') localStorage.removeItem(LEGACY_PROFILE_DRAFT_KEY);
      return;
    }
    localStorage.setItem(profileDraftKey(), JSON.stringify({
      savedProfileUpdatedAt: state.profile?.updated_at || '',
      savedAt: new Date().toISOString(),
      values: captureProfileDraft(),
    }));
  } catch {
    // localStorage may be unavailable in private or restricted browser modes.
  }
}

function persistCurrentProfileDraft() {
  if (!state.profileLoaded || !profileForm()) return;
  updateProfileDirtyState();
}

function updateProfileDirtyState() {
  if (!state.profileLoaded || !profileForm()) return;
  const dirtyFields = getDirtyProfileFields();
  PROFILE_FIELDS.forEach((name) => setFieldUnsaved(name, dirtyFields.includes(name)));
  profileForm().classList.toggle('has-unsaved', dirtyFields.length > 0);
  syncProfileUnsavedUI(dirtyFields);
  persistProfileDraft(dirtyFields);
  updateProfileCompletion();
}

function profileFieldLabel(name) {
  const explicit = {
    full_name:'שם מלא', email:'אימייל', phone:'טלפון', location:'מיקום נוכחי', linkedin_url:'LinkedIn',
    github_url:'GitHub', portfolio_url:'Portfolio', application_password:'סיסמה לאתרי הגשה',
    years_experience_options:'שנות ניסיון', degree_level:'סוג תואר', work_authorization:'אישור עבודה בישראל', needs_sponsorship:'Sponsorship',
    skills:'סקילים', desired_titles:'סוגי תפקידים', preferred_locations:'מיקומים', preferred_work_modes:'אופי עבודה',
    keywords:'רמות ניסיון רצויות', excluded_keywords:'רמות ניסיון שלא לחפש', auto_apply_threshold:'סף התאמה',
    auto_submit_enabled:'תור אוטומטי', extra_work_experiences:'ניסיון תעסוקתי', extra_languages:'שפות',
  };
  if (explicit[name]) return explicit[name];
  const control = profileForm()?.elements?.[name];
  const label = control?.closest('label');
  if (label) return [...label.childNodes].filter((node)=>node.nodeType===Node.TEXT_NODE).map((node)=>node.textContent.trim()).filter(Boolean).join(' ') || name;
  return String(name).replace(/^extra_/,'').replaceAll('_',' ');
}

function syncProfileUnsavedUI(dirtyFields = getDirtyProfileFields()) {
  const total = dirtyFields.length + (state.answersDirty ? 1 : 0);
  const preferenceDirty = dirtyFields.filter((field) => SEARCH_PREFERENCE_FIELDS.has(field));
  const personalDirty = dirtyFields.filter((field) => !SEARCH_PREFERENCE_FIELDS.has(field));
  // Preferences and My Profile share the same underlying form/view, but their
  // validation summaries must never bleed into each other. Only describe the
  // fields owned by the tab the user is currently looking at.
  const visibleDirty = state.activeView === 'preferences' ? preferenceDirty : personalDirty;
  const parts = [];
  if (visibleDirty.length) {
    const labels = visibleDirty.map(profileFieldLabel).filter(Boolean);
    parts.push(`לא נשמרו: ${labels.slice(0,4).join(' · ')}${labels.length > 4 ? ` · ועוד ${labels.length - 4}` : ''}`);
  }
  if (state.activeView !== 'preferences' && state.answersDirty) parts.push('שינויים בשאלות ההגשה לא נשמרו');
  $('#profile-unsaved-count').textContent = parts.join(' · ');
  $('#preferences-nav-unsaved').hidden = preferenceDirty.length === 0;
  $('#profile-nav-unsaved').hidden = personalDirty.length === 0 && !state.answersDirty;
  allProfileSaveButtons().forEach((button) => {
    const owned = profileSaveFieldsForButton(button);
    const hasOwnedDirty = owned.some((field) => dirtyFields.includes(field));
    button.disabled = authState.user?.is_guest || !hasOwnedDirty;
    button.classList.toggle('save-ready', hasOwnedDirty && !authState.user?.is_guest);
    button.title = authState.user?.is_guest ? 'מצב אורח הוא לקריאה בלבד' : '';
  });
}

const PROFILE_COMPLETION_FIELDS = [
  ['full_name','שם מלא'], ['email','אימייל'], ['phone','טלפון'], ['location','מיקום'],
  ['linkedin_url','LinkedIn'], ['extra_city','עיר'], ['extra_education_school','מוסד לימודים'],
  ['degree_level','השכלה'], ['extra_languages','שפות'],
];
function updateProfileCompletion() {
  const form = profileForm();
  if (!form || !$('#profile-completion')) return;
  const missing = [];
  PROFILE_COMPLETION_FIELDS.forEach(([name,label]) => {
    const control = form.elements[name];
    const value = name === 'extra_languages' ? collectLanguages() : control?.value?.trim();
    const complete = Array.isArray(value) ? value.length > 0 : Boolean(value);
    if (!complete) missing.push(label);
    const fieldLabel = control?.closest('label');
    fieldLabel?.classList.toggle('is-recommended-missing', !complete);
    if (fieldLabel) fieldLabel.title = complete ? '' : `${label} הוא פרט נפוץ בטפסי מועמדות ומומלץ להשלים אותו`;
  });
  const work = collectWorkExperiences();
  const workComplete = work.some((item) => item.job_title && item.company);
  if (!workComplete) missing.push('ניסיון תעסוקתי');
  const resumeComplete = Boolean(state.profile?.cv_filename || $('#resume-name')?.textContent !== 'לא הועלה קובץ');
  if (!resumeComplete) missing.push('קורות חיים');
  const total = PROFILE_COMPLETION_FIELDS.length + 2;
  const percent = Math.round((total - missing.length) / total * 100);
  const completion = $('#profile-completion');
  $('#profile-completion-value').textContent = `${percent}%`;
  $('#profile-completion-bar').style.width = `${percent}%`;
  $('#profile-completion-copy').textContent = missing.length ? `מומלץ להשלים: ${missing.slice(0,3).join(' · ')}${missing.length > 3 ? ` ועוד ${missing.length - 3}` : ''}` : 'הפרופיל מלא ומוכן למילוי טפסים';
  completion.hidden = percent >= 100;
  renderNotificationCenter();
}

function clearProfileDirtyState() {
  PROFILE_FIELDS.forEach((name) => setFieldUnsaved(name, false));
  $$('.unsaved-note', profileForm()).forEach((note) => note.remove());
  $$('.has-unsaved', profileForm()).forEach((element) => element.classList.remove('has-unsaved'));
  $$('[aria-invalid="true"]', profileForm()).forEach((control) => control.setAttribute('aria-invalid', 'false'));
  profileForm().classList.remove('has-unsaved');
  $('#profile-unsaved-count').textContent = '';
  $('#profile-answer-panel')?.classList.toggle('has-unsaved', state.answersDirty);
  syncProfileUnsavedUI([]);
  try {
    localStorage.removeItem(profileDraftKey());
    localStorage.removeItem(LEGACY_PROFILE_DRAFT_KEY);
  } catch {
    // Ignore storage errors.
  }
}

function applyProfileToForm(profile) {
  const form = profileForm();
  PROFILE_TEXT_FIELDS.forEach((name) => {
    if (PROFILE_ARRAY_FIELDS.has(name)) {
      const fallback = name === 'years_experience_options' ? [String(Math.min(5, Number(profile.years_experience || 0))) + (Number(profile.years_experience || 0) >= 5 ? '+' : '')] : [];
      applyArrayFieldToControls(name, profile[name]?.length ? profile[name] : fallback);
    }
    else form.elements[name].value = name === 'auto_apply_threshold' ? (profile[name] ?? 82) : savedProfileFormValue(name);
  });
  form.elements.application_password.placeholder = profile.application_password_configured
    ? 'נשמרה סיסמה · הזן חדשה רק כדי להחליף'
    : 'הזן סיסמה לשימוש בטפסי הגשה';
  const restorePassword=$('#profile-password-restore');
  if(restorePassword)restorePassword.hidden=!profile.application_password_configured;
  PROFILE_CHECK_FIELDS.forEach((name) => { form.elements[name].checked = !!profile[name]; });
  if (!applicationAgentAllowed() && form.elements.auto_submit_enabled) {
    form.elements.auto_submit_enabled.checked = false;
    form.elements.auto_submit_enabled.disabled = true;
    const card = form.elements.auto_submit_enabled.closest('.automation-toggle-card');
    if (card) {
      card.classList.add('is-restricted');
      const small = card.querySelector('small');
      if (small) small.textContent = 'זמין כרגע רק לחשבון הראשי';
    }
  }
  APPLICATION_PROFILE_FIELDS.forEach((name) => {
    if (name === 'work_experiences') return;
    if (form.elements[`extra_${name}`]) form.elements[`extra_${name}`].value = profile.application_profile?.[name] ?? '';
  });
  renderWorkExperiences(profile.application_profile || {});
  renderLanguages(profile.application_profile?.languages);
  $('#threshold-value').textContent = profile.auto_apply_threshold ?? 82;
  $('#resume-name').textContent = profile.cv_filename || 'לא הועלה קובץ';
  const gradeSheetName = $('#grade-sheet-name');
  if (gradeSheetName) gradeSheetName.textContent = profile.grade_sheet_filename || 'לא הועלה קובץ';
  const gradeSheetCard = document.querySelector('[data-profile-document="grade-sheet"]');
  if (gradeSheetCard) gradeSheetCard.classList.toggle('resume-uploaded', !!profile.grade_sheet_uploaded);
  if (typeof updateProfileSectionSummaries === 'function') updateProfileSectionSummaries();
  updateProfileCompletion();
}

function readStoredProfileDraft() {
  try {
    const raw = localStorage.getItem(profileDraftKey()) || (state.activeCareerTrack === 'computer_science' ? localStorage.getItem(LEGACY_PROFILE_DRAFT_KEY) : null);
    return JSON.parse(raw || 'null');
  } catch {
    return null;
  }
}

function restoreProfileDraft() {
  const draft = readStoredProfileDraft();
  if (!draft?.values) return false;
  const form = profileForm();
  PROFILE_FIELDS.forEach((name) => {
    if (!(name in draft.values)) return;
    const control = form.elements[name];
    if (name === 'extra_languages') {
      renderLanguages(draft.values[name]);
    } else if (name === 'extra_work_experiences') {
      renderWorkExperiences(draft.values[name]);
    } else if (PROFILE_ARRAY_FIELDS.has(name)) {
      applyArrayFieldToControls(name, normalizedProfileValue(name, draft.values[name]));
    } else if (control.type === 'checkbox') control.checked = !!draft.values[name];
    else control.value = draft.values[name];
  });
  $('#threshold-value').textContent = form.elements.auto_apply_threshold.value;
  return true;
}

async function loadProfile() {
  if (state.profileLoaded) {
    updateProfileDirtyState();
    if (!state.answerLibrary.length) await loadAnswerLibrary();
    await loadResumeInsights();
    return;
  }
  [state.profile] = await Promise.all([api('/api/profile'), loadAnswerLibrary()]);
  state.profileLoaded = true;
  applyProfileToForm(state.profile);
  restoreProfileDraft();
  updateProfileDirtyState();
  await loadResumeInsights();
}

async function loadResumeInsights(){
  const root=$('#resume-insights'); if(!root)return;
  const resumes=await api('/api/resumes');
  const allSuggestions=resumes.flatMap(resume=>(resume.analysis?.suggestions||[]).map(item=>({...item,resume_id:resume.id,resume_label:resume.label})));
  const suggestions=[...new Map(allSuggestions.map(item=>[`${item.field}:${String(item.value).toLowerCase()}`,item])).values()];
  if(!resumes.length){root.innerHTML='';return;}
  root.innerHTML=`<div class="resume-insights-head"><strong>${resumes.length} גרסאות קורות חיים</strong><button class="text-btn" type="button" data-resume-manager>ניהול גרסאות</button></div>${suggestions.length?`<div class="resume-suggestions"><span>סקילים ופרטים שסותרים מידע קיים מחכים לאישור שלך</span>${suggestions.map(item=>`<button type="button" data-resume-suggestion data-resume-id="${item.resume_id}" data-field="${esc(item.field)}" data-value="${encodeURIComponent(String(item.value))}"><b>＋</b>${esc(item.label)}<small>${esc(item.resume_label)}</small></button>`).join('')}</div>`:`<p class="resume-analysis-ok">הקבצים נותחו. פרטי קשר חסרים מולאו אוטומטית ואין כרגע הצעות שממתינות לאישור.</p>`}`;
  $('[data-resume-manager]',root)?.addEventListener('click',()=>$('#privacy-center').click());
  $$('[data-resume-suggestion]',root).forEach((button)=>{button.onclick=()=>applyResumeSuggestion(Number(button.dataset.resumeId),button.dataset.field,decodeURIComponent(button.dataset.value||''));});
}
async function applyResumeSuggestion(resumeId,field,value){
  const button = $(`[data-resume-suggestion][data-resume-id="${resumeId}"][data-field="${CSS.escape(field)}"]`);
  if (button) { button.disabled = true; button.classList.add('is-saving'); }
  try {
    const result=await api(`/api/resumes/${resumeId}/suggestions/apply`,{method:'POST',body:JSON.stringify({field,value})});
    state.profile=result.profile; state.profileLoaded=true;
    if(field==='skills') syncSkillsEverywhere(state.profile.skills||[], value);
    else if(PROFILE_FIELDS.includes(field) && profileForm().elements[field]) profileForm().elements[field].value=state.profile[field]||'';
    updateProfileDirtyState(); updateProfileSectionSummaries(); updateProfileCompletion();
    if (button?.isConnected) button.remove();
    toast(field==='skills'?'הסקיל נוסף מיד · ציוני המשרות מתעדכנים ברקע':'הפרט נוסף לפרופיל');
    loadResumeInsights().catch((error) => console.warn('Resume insights refresh failed', error));
  } catch (error) {
    toast(`לא ניתן להוסיף את ההצעה: ${error.message}`);
  } finally {
    if (button?.isConnected) { button.disabled = false; button.classList.remove('is-saving'); }
  }
}

function allProfileSaveButtons() {
  return [...new Set([
    ...$$('button[type="submit"]', profileForm()),
    ...$$('button[type="submit"][form="profile-form"]'),
  ])];
}

function profileFieldsInContainer(container) {
  if (!container) return [];
  const fields = new Set();
  if (container.matches?.('.preference-group[data-field]')) fields.add(container.dataset.field);
  $$('[name]', container).forEach((control) => {
    if (PROFILE_FIELDS.includes(control.name)) fields.add(control.name);
  });
  $$('[data-profile-option]', container).forEach((control) => {
    if (PROFILE_FIELDS.includes(control.dataset.profileOption)) fields.add(control.dataset.profileOption);
  });
  return [...fields];
}

function profileSaveFieldsForButton(button) {
  const explicit = String(button?.dataset?.saveFields || '').split(',').map((item) => item.trim()).filter(Boolean);
  if (explicit.length) return explicit.filter((field) => PROFILE_FIELDS.includes(field));
  const preference = button?.closest?.('.preference-group[data-field]');
  if (preference) return profileFieldsInContainer(preference);
  const section = button?.closest?.('.profile-detail-section');
  if (section) return profileFieldsInContainer(section);
  const pane = button?.closest?.('.profile-pane');
  if (pane) return profileFieldsInContainer(pane);
  return getDirtyProfileFields();
}

function buildProfilePayload(fields = PROFILE_FIELDS) {
  const form = profileForm();
  const wanted = new Set(fields);
  const payload = {};
  const array = (name) => {
    const values = normalizedProfileValue(name, currentProfileFormValue(name));
    return name === 'years_experience_options' && !values.length ? ['0'] : values;
  };
  const scalar = [
    'full_name', 'email', 'phone', 'location', 'linkedin_url', 'github_url', 'portfolio_url', 'degree_level',
    'auto_apply_threshold', 'work_authorization', 'needs_sponsorship', 'auto_submit_enabled',
  ];
  scalar.forEach((name) => {
    if (!wanted.has(name)) return;
    const control = form.elements[name];
    if (!control) return;
    if (PROFILE_CHECK_FIELDS.includes(name)) payload[name] = control.checked;
    else if (PROFILE_NUMBER_FIELDS.has(name)) payload[name] = Number(control.value || 0);
    else payload[name] = control.value;
  });
  if (wanted.has('application_password') && form.elements.application_password.value) {
    payload.application_password = form.elements.application_password.value;
  }
  PROFILE_ARRAY_FIELDS.forEach((name) => {
    if (wanted.has(name)) payload[name] = array(name);
  });
  if (wanted.has('years_experience_options')) {
    payload.years_experience_options = array('years_experience_options');
  }
  const applicationFields = [...wanted].filter((name) => name.startsWith('extra_'));
  if (applicationFields.length) {
    payload.application_profile = Object.fromEntries(applicationFields.map((field) => {
      const name = field.slice(6);
      if (name === 'languages') return [name, collectLanguages()];
      if (name === 'work_experiences') return [name, collectWorkExperiences()];
      return [name, form.elements[field]?.value || ''];
    }));
  }
  return payload;
}

const profileElement = profileForm();
function updateProfileSectionSummaries() {
  $$('.profile-detail-section', profileElement).forEach((section) => {
    const summary = $('.profile-section-summary', section);
    if (!summary) return;
    const values = [];
    $$('input:not([type="hidden"]), select, textarea', section).forEach((control) => {
      if (control.type === 'checkbox' && control.checked) values.push(control.closest('label')?.textContent?.trim());
      else if (control.type !== 'checkbox' && control.value?.trim()) values.push(control.tagName === 'SELECT' ? control.selectedOptions?.[0]?.textContent?.trim() : control.value.trim());
    });
    const unique = [...new Set(values.filter(Boolean))];
    summary.textContent = unique.length ? `${unique.slice(0, 3).join(' · ')}${unique.length > 3 ? ` · +${unique.length - 3}` : ''}` : 'טרם הושלמו פרטים';
  });
}
$$('.profile-detail-section', profileElement).forEach((section) => {
  const head = $('.profile-detail-head', section);
  if (!head) return;
  const summary = document.createElement('small');
  summary.className = 'profile-section-summary';
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'section-collapse';
  toggle.setAttribute('aria-expanded', 'true');
  toggle.setAttribute('aria-label', 'צמצם את הרובריקה');
  toggle.title = 'צמצם';
  toggle.innerHTML = '<span aria-hidden="true">⌃</span>';
  const sectionKey = `profile-${$('.profile-section-index', section)?.textContent || $$('.profile-detail-section', profileElement).indexOf(section)}`;
  const rememberedCollapsed = localStorage.getItem(`jobpilot-collapse-${sectionKey}`) === '1';
  section.classList.toggle('is-collapsed', rememberedCollapsed);
  toggle.setAttribute('aria-expanded', rememberedCollapsed ? 'false' : 'true');
  toggle.querySelector('span').style.transform = rememberedCollapsed ? 'rotate(180deg)' : '';
  toggle.onclick = () => {
    const collapsed = section.classList.toggle('is-collapsed');
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle.setAttribute('aria-label', collapsed ? 'פתח את הרובריקה' : 'צמצם את הרובריקה');
    toggle.title = collapsed ? 'פתח' : 'צמצם';
    localStorage.setItem(`jobpilot-collapse-${sectionKey}`, collapsed ? '1' : '0');
    // Natural grid rows handle the collapsed height; forcing a masonry span here
    // can overlap the card below while the collapse animation is still settling.
    section.style.gridRowEnd = '';
  };
  const actions = document.createElement('div');
  actions.className = 'card-head-actions';
  const saveButton = head.querySelector(':scope > .btn');
  if (saveButton) actions.appendChild(saveButton);
  actions.appendChild(toggle);
  head.append(summary, actions);
  const navigation = document.createElement('div');
  navigation.className = 'profile-card-navigation';
  navigation.innerHTML = '<button type="button" data-card-step="-1">→ הכרטיס הקודם</button><button type="button" data-card-step="1">הכרטיס הבא ←</button>';
  navigation.onclick = (event) => {
    const step = Number(event.target.closest('[data-card-step]')?.dataset.cardStep || 0);
    if (!step) return;
    const sections = $$('.profile-detail-section', profileElement);
    const target = sections[sections.indexOf(section) + step];
    if (!target) return;
    target.classList.remove('is-collapsed');
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    highlightSelectedCard(target);
  };
  section.appendChild(navigation);
});

// Every preference box has its own Save + Minimize controls and a useful compact summary.
$$('.preference-group', profileElement).forEach((group, index) => {
  if (group.querySelector(':scope > .preference-group-toolbar')) return;
  const field = group.dataset.field || `group-${index}`;
  const toolbar = document.createElement('div');
  toolbar.className = 'preference-group-toolbar';
  toolbar.innerHTML = `<small class="preference-group-summary"></small><span class="card-head-actions"><button class="btn primary small" type="submit">שמור</button><button class="section-collapse preference-collapse" type="button" aria-expanded="true" title="מזער"><span aria-hidden="true">⌃</span></button></span>`;
  const legend = group.querySelector(':scope > legend');
  legend?.insertAdjacentElement('afterend', toolbar);
  const updateSummary = () => {
    const selected = $$('[data-profile-option]:checked', group).map((control) => control.closest('label')?.textContent?.replace(/#\d+/g, '')?.trim()).filter(Boolean);
    const custom = $$('textarea,input:not([type="checkbox"]):not([type="hidden"])', group).map((control) => control.value?.trim()).filter(Boolean);
    const values = [...selected, ...custom];
    $('.preference-group-summary', group).textContent = values.length ? `${values.length} בחירות · ${values.slice(0, 3).join(' · ')}${values.length > 3 ? '…' : ''}` : 'אין בחירות';
  };
  updateSummary();
  group.addEventListener('input', updateSummary);
  group.addEventListener('change', updateSummary);
  const toggle = $('.preference-collapse', group);
  const storageKey = `jobpilot-collapse-preference-${state.activeCareerTrack}-${field}`;
  const collapsed = localStorage.getItem(storageKey) === '1';
  group.classList.toggle('is-preference-collapsed', collapsed);
  toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  toggle.onclick = () => {
    const next = group.classList.toggle('is-preference-collapsed');
    toggle.setAttribute('aria-expanded', next ? 'false' : 'true');
    toggle.title = next ? 'פתח' : 'מזער';
    localStorage.setItem(storageKey, next ? '1' : '0');
  };
});

// Keep every titled content card consistent: its existing action and the
// collapse control live together in the upper-left corner.
$$('.panel').forEach((panel, panelIndex) => {
  const head = panel.querySelector(':scope > .panel-head');
  if (!head || panel.classList.contains('jobs-toolbar') || panel.classList.contains('settings-card')) return;
  let actions = head.querySelector(':scope > .card-head-actions');
  if (!actions) {
    actions = document.createElement('div');
    actions.className = 'card-head-actions';
    $$(':scope > button, :scope > a', head).forEach((action) => actions.appendChild(action));
    head.appendChild(actions);
  }
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'section-collapse panel-collapse';
  toggle.setAttribute('aria-expanded', 'true');
  toggle.setAttribute('aria-label', 'צמצם כרטיס');
  toggle.title = 'צמצם';
  toggle.innerHTML = '<span aria-hidden="true">⌃</span>';
  const panelKey = `panel-${panel.dataset.profilePane || panel.closest('.view')?.id || 'global'}-${panelIndex}`;
  const rememberedCollapsed = localStorage.getItem(`jobpilot-collapse-${panelKey}`) === '1';
  const panelSummary = document.createElement('small');
  panelSummary.className = 'panel-collapse-summary';
  const refreshPanelSummary = () => {
    const items = panel.querySelectorAll('.job-card,.source-item,.blocker-card,.answer-card,.skill-suggestion,.resume-profile-card').length;
    const selected = panel.querySelectorAll('input:checked').length;
    if (panel.classList.contains('application-automation-panel')) {
      const threshold = $('#threshold')?.value || $('#threshold-value')?.textContent || '—';
      const enabled = profileForm()?.elements?.auto_submit_enabled?.checked;
      panelSummary.textContent = `סף ${threshold} · תור אוטומטי ${enabled ? 'פעיל' : 'כבוי'}`;
      return;
    }
    const filled = $$('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]),select,textarea', panel)
      .map((control) => control.tagName === 'SELECT' ? control.selectedOptions?.[0]?.textContent?.trim() : control.value?.trim())
      .filter(Boolean);
    panelSummary.textContent = items ? `${items} פריטים` : selected ? `${selected} אפשרויות נבחרו` : filled.length ? filled.slice(0, 2).join(' · ') : 'אין מידע נוסף';
  };
  refreshPanelSummary();
  head.querySelector(':scope > div')?.appendChild(panelSummary);
  panel.classList.toggle('is-panel-collapsed', rememberedCollapsed);
  toggle.setAttribute('aria-expanded', rememberedCollapsed ? 'false' : 'true');
  toggle.onclick = () => {
    const collapsed = panel.classList.toggle('is-panel-collapsed');
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle.setAttribute('aria-label', collapsed ? 'פתח כרטיס' : 'צמצם כרטיס');
    toggle.title = collapsed ? 'פתח' : 'צמצם';
    localStorage.setItem(`jobpilot-collapse-${panelKey}`, collapsed ? '1' : '0');
    refreshPanelSummary();
  };
  actions.appendChild(toggle);
});
const personalProfileLayout = $('.personal-profile-layout', profileElement);
// Keep the DOM, keyboard order and visual order aligned with the numbered,
// user-priority flow even when sections are maintained independently in HTML.
if(personalProfileLayout){
  [...personalProfileLayout.querySelectorAll(':scope > .profile-detail-section')]
    .sort((a,b)=>Number($('.profile-section-index',a)?.textContent||99)-Number($('.profile-section-index',b)?.textContent||99))
    .forEach(section=>personalProfileLayout.appendChild(section));
}
// Natural CSS Grid rows are intentionally used here. The old JavaScript masonry
// span calculation could race with collapse animations and make cards overlap.
$$('.profile-detail-section', personalProfileLayout).forEach((section) => { section.style.gridRowEnd = ''; });
updateProfileSectionSummaries();

// A single, calm selection state helps the eye keep its place in dense forms.
// Clicking a field highlights its nearest card; clicking the page clears it.
const selectableCardSelector = '.profile-detail-section, .preference-group, .answer-card, .job-card, .source-item, .blocker-card, .panel';
function highlightSelectedCard(target) {
  if (target?.closest?.('input, button, select, textarea, a, label, [role="button"]')) {
    $$('.is-card-selected').forEach((card) => card.classList.remove('is-card-selected'));
    return;
  }
  const selected = target?.closest?.(selectableCardSelector);
  $$('.is-card-selected').forEach((card) => {
    if (card !== selected) card.classList.remove('is-card-selected');
  });
  selected?.classList.add('is-card-selected');
}
document.addEventListener('pointerdown', (event) => highlightSelectedCard(event.target));
document.addEventListener('focusin', (event) => highlightSelectedCard(event.target));
$('#add-language').onclick = () => {
  $('#language-rows').insertAdjacentHTML('beforeend', languageRow({}, true));
  bindLanguageRows();
  $('#language-rows [data-language-row]:last-child [data-language-name]').focus();
  updateProfileDirtyState();
};
$('#available-now').onclick = () => {
  const now = new Date();
  const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
  profileElement.elements.extra_available_start_date.value = localDate;
  profileElement.elements.extra_available_start_date.dispatchEvent(new Event('input', { bubbles: true }));
};
$('#add-employment').onclick = () => {
  const entries = $('#employment-entries');
  entries.insertAdjacentHTML('beforeend', employmentEntry({}, entries.children.length));
  bindEmploymentEntries(); syncEmploymentHidden(); updateProfileDirtyState(); updateProfileSectionSummaries();
  entries.lastElementChild?.scrollIntoView({ behavior:'smooth', block:'nearest' });
};
profileElement.addEventListener('input', (event) => {
  $('#toast').classList.remove('show');
  $('#toast').textContent = '';
  if (event.target.dataset?.profileOption) syncProfileOptionVisual(event.target);
  if (event.target.name === 'auto_apply_threshold') $('#threshold-value').textContent = event.target.value;
  updateProfileDirtyState();
  updateProfileSectionSummaries();
});
profileElement.addEventListener('change', (event) => {
  const field = event.target.dataset.profileOption;
  if (field) syncProfileOptionVisual(event.target);
  if (field && PRIORITY_PROFILE_ARRAY_FIELDS.has(field)) {
    const selectedOrder = $$(`[data-profile-option="${field}"]:checked`, profileElement).map((item) => item.value);
    syncPreferenceOptionOrder(field, selectedOrder, true);
  }
  updateProfileDirtyState();
});
$$('[form="profile-form"]').forEach((control) => {
  control.addEventListener('input', () => {
    if (control.name === 'auto_apply_threshold') $('#threshold-value').textContent = control.value;
    updateProfileDirtyState();
  });
  control.addEventListener('change', updateProfileDirtyState);
});
$$('[data-profile-option]', profileElement).forEach(syncProfileOptionVisual);

$$('[data-profile-option="keywords"], [data-profile-option="excluded_keywords"]', profileElement).forEach((control) => {
  control.addEventListener('change', () => {
    if (!control.checked) return;
    const opposite = control.dataset.profileOption === 'keywords' ? 'excluded_keywords' : 'keywords';
    const conflicting = $$(`[data-profile-option="${opposite}"]`, profileElement)
      .find((item) => item.value.toLowerCase() === control.value.toLowerCase());
    if (conflicting?.checked) {
      conflicting.checked = false;
      toast(`הבחירה ${control.value} הוסרה מהרשימה ההפוכה`);
      updateProfileDirtyState();
    }
  });
});

function bindPreferencePriorityDragging() {
  $$('.preference-group .option-grid', profileElement).forEach((grid) => {
    const field = $('input[data-profile-option]', grid)?.dataset.profileOption;
    if (!PRIORITY_PROFILE_ARRAY_FIELDS.has(field) || grid.dataset.dragBound === 'true') return;
    grid.dataset.dragBound = 'true';
    let pressedLabel = null; let holdTimer = null; let pointerId = null; let dragging = false; let suppressClick = false;
    grid.addEventListener('pointerdown', (event) => {
      const label = event.target.closest('label');
      if (!label || label.parentElement !== grid || event.button !== 0) return;
      pressedLabel = label; pointerId = event.pointerId; dragging = false;
      holdTimer = window.setTimeout(() => {
        if (!pressedLabel) return;
        dragging = true; suppressClick = true;
        pressedLabel.classList.add('is-priority-dragging');
        grid.classList.add('is-priority-sorting');
        pressedLabel.setPointerCapture?.(pointerId);
        navigator.vibrate?.(18);
      }, 420);
    });
    grid.addEventListener('pointermove', (event) => {
      if (!dragging || event.pointerId !== pointerId) return;
      const target = document.elementFromPoint(event.clientX,event.clientY)?.closest('.option-grid > label');
      if (!target || target === pressedLabel || target.parentElement !== grid) return;
      const sourceChecked = $('input',pressedLabel).checked; const targetChecked = $('input',target).checked;
      if (sourceChecked !== targetChecked) return;
      const targetRect = target.getBoundingClientRect();
      animateOptionReorder(grid, () => grid.insertBefore(pressedLabel, event.clientY < targetRect.top + targetRect.height / 2 ? target : target.nextSibling));
      refreshPreferencePriorities(grid);
    });
    const finish = () => {
      clearTimeout(holdTimer);
      if (dragging) {
        pressedLabel?.classList.remove('is-priority-dragging');
        grid.classList.remove('is-priority-sorting');
        refreshPreferencePriorities(grid);
        updateProfileDirtyState();
        window.setTimeout(() => { suppressClick = false; }, 0);
      }
      pressedLabel = null; pointerId = null; dragging = false;
    };
    grid.addEventListener('pointerup', finish); grid.addEventListener('pointercancel', finish);
    grid.addEventListener('click', (event) => { if (suppressClick) { event.preventDefault(); event.stopPropagation(); } }, true);
  });
}
bindPreferencePriorityDragging();
profileElement.onsubmit = async (event) => {
  event.preventDefault();
  const submitter = event.submitter;
  if (!submitter) return;
  if (authState.user?.is_guest) { toast('מצב אורח הוא לקריאה בלבד'); return; }
  $('#toast').classList.remove('show');
  $('#toast').textContent = '';
  const dirty = new Set(getDirtyProfileFields());
  const ownedFields = profileSaveFieldsForButton(submitter);
  const fields = ownedFields.filter((field) => dirty.has(field));
  if (!fields.length) { toast('אין שינויים בכרטיס הזה'); updateProfileDirtyState(); return; }
  const originalText = submitter.textContent;
  submitter.disabled = true;
  submitter.textContent = 'שומר…';
  try {
    const payload = buildProfilePayload(fields);
    const saved = await api('/api/profile', { method: 'PATCH', body: JSON.stringify(payload) });
    state.profile = saved;
    state.profileLoaded = true;
    if (fields.includes('application_password')) profileElement.elements.application_password.value = '';
    updateProfileDirtyState();
    updateProfileSectionSummaries();
    submitter.textContent = 'נשמר ✓';
    toast(fields.length === 1 ? 'ההגדרה נשמרה' : 'הכרטיס נשמר');
  } catch (error) {
    toast(`השמירה נכשלה: ${error.message}`);
    updateProfileDirtyState();
  } finally {
    window.setTimeout(() => {
      submitter.textContent = originalText || 'שמור';
      updateProfileDirtyState();
    }, 1100);
  }
};

window.addEventListener('beforeunload', persistCurrentProfileDraft);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') persistCurrentProfileDraft();
});

const NOTIFICATION_VIEWS = {
  blockers: { icon: '!', title: 'פעולות שמחכות לך', copy: 'שאלות או אישורים דורשים טיפול' },
  jobs: { icon: '⌁', title: 'משרות חדשות לבדיקה', copy: 'התאמות חדשות זמינות עבורך' },
  profile: { icon: '○', title: 'הפרופיל עדיין לא מלא', copy: 'השלמת הפרטים תשפר את מילוי הטפסים' },
  sources: { icon: '↯', title: 'מקורות דורשים בדיקה', copy: 'מקור אחד או יותר דיווח על שגיאה' },
};
let trackedApplicationId=Number(localStorage.getItem('jobpilot-tracked-application')||0)||null;
let applicationTrackingTimer=null,applicationTrackingData=null,applicationTrackingAdvanceTimer=null;
function normalizeAutoApplyQueue(snapshot={}){return {current:snapshot?.current||null,waiting:Array.isArray(snapshot?.waiting)?snapshot.waiting:[],waiting_count:Number(snapshot?.waiting_count||0),queued_count:Number(snapshot?.queued_count||0),total_active_count:Number(snapshot?.total_active_count||0)}}
function setAutoApplyQueue(snapshot={}){state.autoApplyQueue=normalizeAutoApplyQueue(snapshot);return state.autoApplyQueue}
function otherAutoQueueItems(snapshot=state.autoApplyQueue,applicationId=trackedApplicationId){const queue=normalizeAutoApplyQueue(snapshot),items=[];if(queue.current&&Number(queue.current.id)!==Number(applicationId))items.push(queue.current);queue.waiting.forEach(item=>{if(Number(item.id)!==Number(applicationId))items.push(item)});return items}
function autoQueueWaitingCount(snapshot=state.autoApplyQueue,applicationId=trackedApplicationId){const queue=normalizeAutoApplyQueue(snapshot),currentId=Number(queue.current?.id||0),trackedId=Number(applicationId||0);if(trackedId&&currentId===trackedId)return queue.waiting.length;return queue.queued_count}
async function refreshAutoApplyQueue(){try{return setAutoApplyQueue(await api('/api/applications/auto-queue'))}catch{return setAutoApplyQueue(state.autoApplyQueue)}}
function autoQueueCountLabel(count){return count===1?'משרה אחת ממתינה בתור להגשה':`${count} משרות ממתינות בתור להגשה`}
function autoQueueRowActions(item,{isCurrent=false}={}){const running=item.status==='applying',alreadyNext=isCurrent&&!running;return `<div class="auto-queue-row-actions"><button class="btn secondary small" type="button" onclick="openAutoQueueApplication(${item.id})">פתח</button><button class="btn secondary small" type="button" onclick="prioritizeAutoQueueApplication(${item.id})" ${running||alreadyNext?'disabled':''}>${alreadyNext?'הבא בתור':'הגש הבא בתור'}</button><button class="btn danger-outline small" type="button" onclick="cancelAutoQueueApplication(${item.id})" ${running?'disabled title="לא ניתן לבטל worker שכבר רץ"':''}>ביטול</button></div>`}
async function showAutoApplyQueue(){const queue=await refreshAutoApplyQueue(),current=queue.current,waiting=queue.waiting||[];if(!current&&!waiting.length){closeModal();toast('אין כרגע משרות בתור להגשה אוטומטית');return}const currentMarkup=current?`<article class="auto-queue-current ${current.status==='applying'?'is-running':'is-next'}"><b>${current.status==='applying'?'▶':Number(current.queue_position||1)}</b><span><strong>${esc(current.job?.title||'משרה')}</strong><small>${esc(current.job?.company||'')} · ${current.status==='applying'?'רץ עכשיו':'הבאה בתור'}</small></span><em>${current.status==='applying'?'רץ עכשיו':'הבאה'}</em>${autoQueueRowActions(current,{isCurrent:true})}</article>`:'';const waitingMarkup=waiting.map((item,index)=>`<article class="auto-queue-waiting"><b>${Number(item.queue_position||index+1)}</b><span><strong>${esc(item.job?.title||'משרה')}</strong><small>${esc(item.job?.company||'')} · ממתינה בתור</small></span><em>ממתינה</em>${autoQueueRowActions(item)}</article>`).join('');modal(`<span class="kicker">תור הגשה אוטומטית</span><h2>${waiting.length?esc(autoQueueCountLabel(waiting.length)):'אין משרות נוספות שממתינות'}</h2><p class="muted">המשרה שמסומנת "רץ עכשיו" נשארת פעילה. אפשר לפתוח כל הגשה, לבטל משרה שעדיין ממתינה או לקדם אותה להיות ההגשה הבאה בתור.</p><div class="auto-apply-queue-list">${currentMarkup}${waitingMarkup}</div><div class="modal-actions"><button class="btn secondary" type="button" onclick="closeModal()">סגור</button></div>`)}
function openAutoQueueApplication(id){closeModal();startApplicationTracking(Number(id),true)}
async function prioritizeAutoQueueApplication(id){try{const result=await api(`/api/applications/${id}/prioritize`,{method:'POST'});if(result.auto_apply_queue)setAutoApplyQueue(result.auto_apply_queue);toast('המשרה קודמה להגשה הבאה בתור');await Promise.all([loadDashboard(),showAutoApplyQueue()])}catch(error){toast(error.message)}}
async function cancelAutoQueueApplication(id){if(!confirm('לבטל את ההגשה האוטומטית הזו? המשרה עצמה תישאר ברשימת המשרות.'))return;try{await api(`/api/applications/${id}`,{method:'DELETE'});if(Number(trackedApplicationId)===Number(id)){trackedApplicationId=null;applicationTrackingData=null;localStorage.removeItem('jobpilot-tracked-application')}toast('ההגשה בוטלה והמשרה נשארה ברשימת המשרות');await Promise.all([loadDashboard(),state.activeView==='applications'?loadApplications():Promise.resolve()]);await showAutoApplyQueue()}catch(error){toast(error.message)}}
window.showAutoApplyQueue=showAutoApplyQueue;
window.openAutoQueueApplication=openAutoQueueApplication;
window.prioritizeAutoQueueApplication=prioritizeAutoQueueApplication;
window.cancelAutoQueueApplication=cancelAutoQueueApplication;
const APPLICATION_PROGRESS_STEPS=[['queued','נכנסה לתור','המשימה נשמרה בבטחה'],['worker_dispatched','ה־worker הופעל','GitHub Actions מכין סביבת עבודה זמנית'],['attempt_started','סביבת הרקע מוכנה','המשימה נלקחה לעבודה בלעדית'],['page_opened','עמוד ההגשה נפתח','נפתח ב־Chromium נסתר בענן'],['form_detected','הטופס זוהה','נמצא טופס מועמדות תקין'],['details_filled','הפרטים והמסמכים מולאו','הפרופיל, קורות החיים וגיליון הציונים (אם נדרש) הוזנו'],['submit_clicked','נלחץ Submit','כפתור ה־Submit הסופי נלחץ; עדיין לא נחשב כהגשה'],['submission_verified','ההגשה אומתה','האתר אישר שהמועמדות נקלטה']];
function openNotifications(){setMobileTabMenu(false);renderNotificationCenter();$('#notification-center').classList.add('open');$('#notification-center').setAttribute('aria-hidden','false');$('#notification-trigger').setAttribute('aria-expanded','true')}
function applicationProgressMarkup(){
  if(!applicationTrackingData)return '';
  const data=applicationTrackingData,events=data.events||[],latestAttemptId=Number(data.attempts?.[0]?.id||0),attemptEvents=latestAttemptId?events.filter(event=>['queued','worker_dispatched','grade_sheet_auto_requeued'].includes(event.event_type)||Number(event.details?.attempt_id||0)===latestAttemptId):events,types=new Set(attemptEvents.map(event=>event.event_type)),status=data.application?.status||'',blocker=data.application?.blocker||null;types.add('queued');
  const queuePosition=Number(data.application?.queue_position||0),queuedWaiting=status==='queued';
  const choiceOptions=blocker?.kind==='choice_required'&&Array.isArray(blocker.options)?blocker.options.filter(Boolean):[],choiceWaiting=status==='needs_input'&&choiceOptions.length>=2&&choiceOptions.length<=6;
  const gradeSheetWaiting=status==='needs_input'&&blocker?.kind==='grade_sheet_required',hasGradeSheet=Boolean(state.profile?.grade_sheet_uploaded),gradeSheetNeedsUpload=gradeSheetWaiting&&!hasGradeSheet,attentionWaiting=choiceWaiting||gradeSheetNeedsUpload;
  const verificationPending=status==='verification_pending',isRunning=status==='applying',failed=['failed','needs_input'].includes(status)&&!attentionWaiting,verified=status==='submitted'&&types.has('submission_verified');let firstPending=true;
  const rows=APPLICATION_PROGRESS_STEPS.map(([key,title,copy],index)=>{const event=attemptEvents.find(item=>item.event_type===key),done=queuedWaiting?(key==='queued'||(key==='worker_dispatched'&&types.has(key))):(types.has(key)||(key==='submission_verified'&&verified)),current=!done&&firstPending;if(current)firstPending=false;const stateClass=done?'done':current?(attentionWaiting?'choice-waiting':verificationPending&&key==='submission_verified'?'verification-waiting':failed?'failed':'active'):'pending';const marker=done?'✓':current&&choiceWaiting?'?':current&&gradeSheetNeedsUpload?'↑':current&&verificationPending&&key==='submission_verified'?'…':current&&failed?'!':index+1;const rowCopy=current&&queuedWaiting&&key==='attempt_started'?(queuePosition>1?`מיקום ${queuePosition} בתור · תופעל אוטומטית ברצף אחרי ההגשות שלפניה`:'ממתינה ל־worker · תתחיל אוטומטית כשהוא יתפנה'):current&&gradeSheetWaiting?(hasGradeSheet?'הצירוף האוטומטי של גיליון הציונים נכשל':'חסר גיליון ציונים בפרופיל'):current&&verificationPending&&key==='submission_verified'?'נצפתה בקשת Submit; ממתינים לראיית אישור חד־משמעית מהאתר או ממייל':done?(event?.message||copy):copy;return `<li class="${stateClass}"><i>${marker}</i><span><strong>${esc(title)}</strong><small>${esc(rowCopy)}</small></span></li>`}).join('');
  const choicePanel=choiceWaiting?`<div class="application-live-choice"><strong>${esc(blocker.question||'נדרשת בחירה כדי להמשיך')}</strong><div>${choiceOptions.map((option)=>`<button type="button" data-choice-blocker="${blocker.id}" data-choice-application="${data.application.id}" data-choice-answer="${esc(option)}">${esc(option)}</button>`).join('')}</div><small>בחר תשובה וה־Agent יחזור אוטומטית להגשה עם הבחירה הזו.</small></div>`:'';
  const gradeSheetPanel=gradeSheetWaiting?(hasGradeSheet
    ? `<div class="application-live-warning"><strong>גיליון הציונים קיים בפרופיל, אבל לא צורף לטופס</strong><small>${esc(blocker.explanation||'הניסיון האוטומטי לצרף את הקובץ נכשל. ההגשה נעצרה כדי לא ליצור לולאה.')}</small></div>`
    : `<div class="application-live-choice application-live-document"><strong>${esc(blocker.question||'נדרש גיליון ציונים')}</strong><div><button type="button" onclick="openGradeSheetProfile()">העלה גיליון ציונים בפרופיל</button></div><small>הקובץ יישמר בפרטים האישיים וישמש אוטומטית בכל הגשה שתבקש אותו.</small></div>`):'';
  const gradeSheetRetryIndex=events.findIndex(event=>event.event_type==='grade_sheet_auto_requeued');
  const gradeSheetRetryActive=gradeSheetRetryIndex>=0&&!events.slice(0,gradeSheetRetryIndex).some(event=>event.event_type==='attempt_started');
  const queuePanel=queuedWaiting?`<div class="application-live-queue"><span class="live-dot"></span><strong>${gradeSheetRetryActive?'גיליון הציונים צורף · ממתינה לניסיון חוזר':'ממתינה בתור להגשה אוטומטית'}</strong><small>${gradeSheetRetryActive?'ה־worker הקודם כבר הסתיים, לכן JobPilot פותח את הטופס מחדש אוטומטית וממלא אותו שוב עם גיליון הציונים השמור. לא נדרשת ממך פעולה.':queuePosition>1?`מיקום ${queuePosition} בתור. ההגשות מופעלות ברצף, והמשרה הזו תתחיל אוטומטית כשיגיע תורה.`:'המשימה שמורה בתור ותתחיל אוטומטית כשה־worker יתפנה.'}</small></div>`:'';
  const extraQueueCount=autoQueueWaitingCount(data.auto_apply_queue||state.autoApplyQueue,data.application?.id);
  const extraQueuePanel=extraQueueCount?`<button class="application-live-queue-summary" type="button" onclick="showAutoApplyQueue()"><span><strong>${esc(autoQueueCountLabel(extraQueueCount))}</strong><small>לחץ כדי לראות את התור. הגשה חדשה תקודם לראש ההמתנה בלי להחליף את המשרה שרצה עכשיו.</small></span><b>←</b></button>`:'';
  return `<section class="application-live-tracker ${verified?'verified':attentionWaiting?'has-choice':queuedWaiting?'has-queue':isRunning?'has-running':verificationPending?'has-verification-wait':failed?'has-failure':''}"><div class="application-live-head"><span><b>${verified?'ההגשה הושלמה ואומתה':choiceWaiting?'מחכה לבחירה שלך':gradeSheetWaiting?(hasGradeSheet?'ההגשה נעצרה':'נדרש גיליון ציונים'):queuedWaiting?'ממתינה בתור להגשה אוטומטית':isRunning?'רץ עכשיו':verificationPending?'נשלחה בקשת Submit — ממתין לאימות':failed?'ההגשה נעצרה':'מעקב הגשה חי'}</b><small>${esc(data.application?.job?.company||'')} · ${esc(data.application?.job?.title||'')}</small></span>${isRunning?'<span class="application-running-badge"><i></i> רץ עכשיו</span>':''}<button type="button" onclick="showApplicationTimeline(${data.application.id})">היסטוריה</button></div><ol>${rows}</ol>${verified?'<div class="application-live-success">✓ התקבל אישור שהמועמדות נקלטה.</div>':choiceWaiting?choicePanel:gradeSheetWaiting?gradeSheetPanel:queuedWaiting?queuePanel:verificationPending?'<div class="application-live-verification">נשלחה בקשת Submit, אבל עדיין אין ראיה חד־משמעית ש־Lever קלט את המועמדות. המשרה לא מסומנת כהוגשה עד שמתקבל אישור.</div>':failed?`<div class="application-live-warning">לא סומן כהוגש. ${esc(data.application?.agent_failure_detail||'נדרשת בדיקה שלך.')}</div>`:'<div class="application-live-note"><span class="live-dot"></span> עובד ברקע ומתעדכן אוטומטית. רק כל השלבים בירוק משמעם שהוגש.</div>'}${extraQueuePanel}</section>`;
}
async function refreshApplicationTracking(){if(!trackedApplicationId)return;try{applicationTrackingData=await api(`/api/applications/${trackedApplicationId}/timeline`);if(applicationTrackingData.auto_apply_queue)setAutoApplyQueue(applicationTrackingData.auto_apply_queue);const status=applicationTrackingData.application?.status,nextActiveId=Number(applicationTrackingData.auto_apply_queue?.current?.id||0);if(['verification_pending','failed','needs_input'].includes(status)&&nextActiveId&&nextActiveId!==Number(trackedApplicationId)){startApplicationTracking(nextActiveId,false);return}renderNotificationCenter();if(status==='submitted'){if(applicationTrackingTimer){clearInterval(applicationTrackingTimer);applicationTrackingTimer=null}clearTimeout(applicationTrackingAdvanceTimer);applicationTrackingAdvanceTimer=setTimeout(advanceTrackingToNextAutoQueue,2200)}else if(['verification_pending','failed','needs_input'].includes(status)&&applicationTrackingTimer){clearInterval(applicationTrackingTimer);applicationTrackingTimer=null}}catch{if(applicationTrackingTimer){clearInterval(applicationTrackingTimer);applicationTrackingTimer=null}}}
function startApplicationTracking(id,autoOpen=false){trackedApplicationId=Number(id);localStorage.setItem('jobpilot-tracked-application',String(id));applicationTrackingData=null;clearTimeout(applicationTrackingAdvanceTimer);refreshApplicationTracking();if(applicationTrackingTimer)clearInterval(applicationTrackingTimer);applicationTrackingTimer=setInterval(refreshApplicationTracking,2000);if(autoOpen)openNotifications()}
async function syncPrimaryApplicationTracking(newApplicationId,autoOpen=false){const queue=await refreshAutoApplyQueue();let trackedStatus=applicationTrackingData?.application?.status||'';if(trackedApplicationId&&!applicationTrackingData){try{applicationTrackingData=await api(`/api/applications/${trackedApplicationId}/timeline`);if(applicationTrackingData.auto_apply_queue)setAutoApplyQueue(applicationTrackingData.auto_apply_queue);trackedStatus=applicationTrackingData.application?.status||''}catch{trackedStatus=''}}const preserveCurrent=Boolean(trackedApplicationId&&trackedStatus==='applying');if(!preserveCurrent){const primaryId=Number(queue.current?.id||newApplicationId||0);if(primaryId)startApplicationTracking(primaryId,false)}else{renderNotificationCenter()}if(autoOpen)openNotifications()}
async function advanceTrackingToNextAutoQueue(){const queue=await refreshAutoApplyQueue(),nextId=Number(queue.current?.id||0);if(nextId&&nextId!==Number(trackedApplicationId))startApplicationTracking(nextId,false);else renderNotificationCenter()}
function notificationItems() {
  const dashboard = state.dashboard || {};
  const items = [];
  if (Number(dashboard.open_blockers)) items.push({ view:'blockers', count:Number(dashboard.open_blockers) });
  const autoQueue=normalizeAutoApplyQueue(state.autoApplyQueue||dashboard.auto_apply_queue||{});
  const autoQueueCount=autoQueue.queued_count;
  if (autoQueueCount) items.push({ view:'applications', count:autoQueueCount, queue:true });
  if (Number(dashboard.due_reminders)) items.push({ view:'applications', count:Number(dashboard.due_reminders), reminder:true });
  const fresh = Number(dashboard.scan?.last_result?.new || 0);
  if (fresh) items.push({ view:'jobs', count:fresh });
  const completion = Number($('#profile-completion-value')?.textContent?.replace('%','') || 100);
  if (completion < 100) items.push({ view:'profile', count:`${completion}%` });
  return items;
}
function renderNotificationCenter() {
  const root = $('#notification-list');
  if (!root) return;
  const items = notificationItems();
  $('#notification-count').hidden = !items.length;
  $('#notification-count').textContent = items.length;
  const tracker=applicationProgressMarkup();
  const notices=items.length ? items.map((item) => {
    const meta = item.queue ? {icon:'↻',title:'ממתינות להגשה אוטומטית',copy:'המשימות שמורות בתור ויופעלו ברצף'} : item.reminder ? {icon:'◷',title:'תזכורות שהגיע זמנן',copy:'מעקב אחרי הגשה, ראיון או מגייס'} : NOTIFICATION_VIEWS[item.view];
    return `<button class="notification-item" type="button" ${item.queue?'data-auto-queue-list="true"':`data-notification-view="${item.view}"`}><i>${meta.icon}</i><span><strong>${meta.title}</strong><small>${meta.copy}</small></span><b>${item.count}</b></button>`;
  }).join('') : (!tracker?emptyState('✓','הכול מעודכן','אין כרגע פעולות שמחכות לך.'):'');
  root.innerHTML=tracker+notices;
  bindChoiceBlockerButtons(root);
  $$('[data-auto-queue-list]',root).forEach(button=>{button.onclick=()=>showAutoApplyQueue()});
  $$('[data-notification-view]', root).forEach((button) => { button.onclick = () => { closeNotifications(); switchView(button.dataset.notificationView); }; });
}
function closeNotifications() {
  $('#notification-center').classList.remove('open');
  $('#notification-center').setAttribute('aria-hidden','true');
  $('#notification-trigger').setAttribute('aria-expanded','false');
}
$('#notification-trigger').onclick = () => {
  setMobileTabMenu(false);
  renderNotificationCenter();
  const open = $('#notification-center').classList.toggle('open');
  $('#notification-center').setAttribute('aria-hidden', String(!open));
  $('#notification-trigger').setAttribute('aria-expanded', String(open));
};
$('#notification-close').onclick = closeNotifications;
document.addEventListener('pointerdown', (event) => {
  const center = $('#notification-center');
  if (!center?.classList.contains('open')) return;
  if (event.target.closest('#notification-center, #notification-trigger')) return;
  closeNotifications();
});

const COMMAND_VIEWS = [
  ['dashboard','לוח בקרה','תמונת מצב'], ['jobs','משרות','חיפוש והתאמות'], ['preferences','העדפות חיפוש','תפקידים ומיקום'],
  ['applications','הגשות','תור והיסטוריה'], ['blockers','דורש טיפול','פעולות שממתינות'], ['skills','סקילים','כישורים ופערים'],
  ['sources','מקורות','אתרי קריירה'], ['profile','הפרופיל שלי','פרטים אישיים'], ['settings','הגדרות','תצוגה ונגישות'],
];
let commandSelection = 0;
function commandEntries(query = '') {
  const term = query.trim().toLowerCase();
  const views = COMMAND_VIEWS.map(([view,title,copy]) => ({ type:'view', view, title, copy }));
  const jobs = state.jobs.map((job) => ({ type:'job', id:job.id, title:job.title, copy:`${job.company} · ${job.location || ''}` }));
  return [...views,...jobs].filter((item) => !term || `${item.title} ${item.copy}`.toLowerCase().includes(term)).slice(0,9);
}
function renderCommandResults() {
  const entries = commandEntries($('#command-input').value);
  commandSelection = Math.min(commandSelection, Math.max(0, entries.length - 1));
  $('#command-results').innerHTML = entries.length ? entries.map((item,index) => `<button type="button" class="command-result ${index === commandSelection ? 'active' : ''}" data-command-index="${index}"><span>${esc(item.title)}</span><small>${esc(item.copy)}</small></button>`).join('') : emptyState('⌕','לא נמצאו תוצאות','נסה שם חברה, תפקיד או שם עמוד.');
  $$('[data-command-index]', $('#command-results')).forEach((button) => { button.onclick = () => runCommand(entries[Number(button.dataset.commandIndex)]); });
}
function runCommand(item) {
  if (!item) return;
  closeCommandPalette();
  if (item.type === 'view') switchView(item.view);
  else { switchView('jobs'); window.setTimeout(() => showJob(item.id), 80); }
}
function openCommandPalette() {
  closeNotifications();
  commandSelection = 0;
  $('#command-palette').classList.add('open');
  $('#command-palette').setAttribute('aria-hidden','false');
  document.body.classList.add('overlay-open');
  $('#command-input').value = '';
  renderCommandResults();
  requestAnimationFrame(() => $('#command-input').focus());
}
function closeCommandPalette() {
  $('#command-palette').classList.remove('open');
  $('#command-palette').setAttribute('aria-hidden','true');
  document.body.classList.remove('overlay-open');
}
$('#quick-search-trigger')?.addEventListener('click', openCommandPalette);
$('#command-input').oninput = () => { commandSelection = 0; renderCommandResults(); };
$('#command-input').onkeydown = (event) => {
  const entries = commandEntries(event.currentTarget.value);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    commandSelection = (commandSelection + (event.key === 'ArrowDown' ? 1 : -1) + entries.length) % Math.max(1,entries.length);
    renderCommandResults();
  } else if (event.key === 'Enter') { event.preventDefault(); runCommand(entries[commandSelection]); }
};
$('#command-palette').onclick = (event) => { if (event.target.id === 'command-palette') closeCommandPalette(); };

function applyTheme(theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.body.classList.toggle('theme-dark', dark);
  document.body.dataset.themePreference = theme;
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  $$('#theme-switch [data-theme]').forEach((button) => {
    const selected = button.dataset.theme === theme;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  positionThemeThumb();
}
function positionThemeThumb(animate = true) {
  const switcher = $('#theme-switch');
  const thumb = $('.theme-switch-thumb', switcher);
  const active = $('[data-theme].active', switcher);
  if (!switcher || !thumb || !active) return;
  if (!animate) thumb.style.transition = 'none';
  thumb.style.left = `${active.offsetLeft}px`;
  thumb.style.width = `${active.offsetWidth}px`;
  if (!animate) requestAnimationFrame(() => { thumb.style.transition = ''; });
}
const storedThemePreference = localStorage.getItem('jobpilot-theme');
let preferredTheme = ['light','system','dark'].includes(storedThemePreference) ? storedThemePreference : 'system';
if (storedThemePreference && !['light','system','dark'].includes(storedThemePreference)) localStorage.removeItem('jobpilot-theme');
applyTheme(preferredTheme);
const TEXT_SIZE_CLASSES=['text-size-large','text-size-xlarge'];
function applyTextSize(size,announce=false){
  const normalized=['default','large','xlarge'].includes(size)?size:'default';
  document.body.classList.remove(...TEXT_SIZE_CLASSES);
  if(normalized!=='default')document.body.classList.add(`text-size-${normalized}`);
  document.body.dataset.userTextSize=normalized;
  $$('#view-settings [data-text-size]').forEach(button=>{
    const selected=button.dataset.textSize===normalized;
    button.classList.toggle('active',selected);button.setAttribute('aria-checked',String(selected));
  });
  try{localStorage.setItem('jobpilot-text-size',normalized)}catch{}
  requestAnimationFrame(()=>positionThemeThumb(false));
  if(announce)toast(normalized==='default'?'גודל הטקסט הרגיל הופעל':normalized==='large'?'גודל טקסט גדול הופעל':'גודל טקסט גדול מאוד הופעל');
}
applyTextSize(localStorage.getItem('jobpilot-text-size')||'default');
$$('#view-settings [data-text-size]').forEach(button=>{button.onclick=()=>applyTextSize(button.dataset.textSize,true)});
let suppressThemeClick = false;
function selectTheme(theme, compactMessage = false, silent = false) {
  preferredTheme = theme;
  localStorage.setItem('jobpilot-theme', preferredTheme);
  applyTheme(preferredTheme);
  if (!silent) toast(preferredTheme === 'system' ? (compactMessage ? 'מצב אוטומטי לפי ה־Mac' : 'ערכת הצבעים תותאם אוטומטית ל־Mac') : preferredTheme === 'dark' ? 'מצב לילה הופעל' : 'מצב יום הופעל');
}
$$('#theme-switch [data-theme]').forEach((button) => { button.onclick = () => {
  if (suppressThemeClick) return;
  selectTheme(button.dataset.theme);
}; });
{
  const switcher = $('#theme-switch');
  const thumb = $('.theme-switch-thumb', switcher);
  let pointerId = null;
  let startX = 0;
  let dragged = false;
  const buttons = () => $$('#theme-switch [data-theme]');
  const closestThemeButton = (clientX) => buttons().reduce((closest, button) => {
    const rect = button.getBoundingClientRect();
    const distance = Math.abs(clientX - (rect.left + rect.width / 2));
    return !closest || distance < closest.distance ? { button, distance } : closest;
  }, null)?.button;
  switcher.addEventListener('pointerdown', (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    dragged = false;
    switcher.setPointerCapture(pointerId);
  });
  switcher.addEventListener('pointermove', (event) => {
    if (pointerId !== event.pointerId) return;
    if (!dragged && Math.abs(event.clientX - startX) < 4) return;
    dragged = true;
    suppressThemeClick = true;
    switcher.classList.add('is-dragging');
    const rect = switcher.getBoundingClientRect();
    const half = thumb.offsetWidth / 2;
    const left = Math.max(3, Math.min(rect.width - thumb.offsetWidth - 3, event.clientX - rect.left - half));
    thumb.style.left = `${left}px`;
    const hovered = closestThemeButton(event.clientX);
    if (hovered && hovered.dataset.theme !== preferredTheme) selectTheme(hovered.dataset.theme, true, true);
  });
  const finishThemeDrag = (event) => {
    if (pointerId !== event.pointerId) return;
    const target = closestThemeButton(event.clientX);
    suppressThemeClick = true;
    if (target) selectTheme(target.dataset.theme, dragged);
    window.setTimeout(() => { suppressThemeClick = false; }, 0);
    switcher.classList.remove('is-dragging');
    pointerId = null;
  };
  switcher.addEventListener('pointerup', finishThemeDrag);
  switcher.addEventListener('pointercancel', (event) => { finishThemeDrag(event); positionThemeThumb(); });
  window.addEventListener('resize', () => positionThemeThumb(false));
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (preferredTheme === 'system') applyTheme('system'); });

document.addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommandPalette(); }
  if (event.key === 'Escape') { closeCommandPalette(); closeNotifications(); }
});
document.addEventListener('click', (event) => {
  const actionable = event.target.closest('.btn, .icon-action, .section-collapse, .notification-item');
  if (!actionable) return;
  actionable.classList.remove('micro-confirm');
  requestAnimationFrame(() => actionable.classList.add('micro-confirm'));
  window.setTimeout(() => actionable.classList.remove('micro-confirm'), 380);
});

$('#upload-resume').onclick = () => $('#resume-file').click();
$('#upload-grade-sheet').onclick = () => $('#grade-sheet-file').click();
$('#manage-resumes').onclick = () => $('#privacy-center').click();
const RESUME_AUTOFILL_LABELS = Object.freeze({
  full_name:'שם מלא', email:'אימייל', phone:'טלפון', location:'מיקום',
  linkedin_url:'LinkedIn', github_url:'GitHub', portfolio_url:'אתר אישי'
});
function resumeAutofillSummary(fields=[]){
  return fields.map(field=>RESUME_AUTOFILL_LABELS[field]||field).join(' · ');
}
$('#resume-file').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const result = await api('/api/profile/resume', { method: 'POST', body: formData });
    $('#resume-name').textContent = `✓ ${result.filename}`;
    document.querySelector('.resume-profile-card')?.classList.add('resume-uploaded');
    if (state.profile) state.profile.cv_filename = result.filename;
    state.profile=result.profile||state.profile; state.profileLoaded=false;
    await loadProfile();
    const count=result.analysis?.suggestions?.length||0;
    const filled=(result.autofilled_fields||[]).length;
    const parts=['קורות החיים הועלו ונותחו'];
    if(filled) parts.push(`מולאו אוטומטית: ${resumeAutofillSummary(result.autofilled_fields)}`);
    if(count) parts.push(`${count} הצעות מחכות לאישור`);
    toast(parts.join(' · '));
  } catch (error) {
    toast(error.message);
  }
};

$('#grade-sheet-file').onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    event.target.value = '';
    return toast('גיליון הציונים גדול מ־10MB');
  }
  const formData = new FormData();
  formData.append('file', file);
  try {
    const result = await api('/api/profile/grade-sheet', { method: 'POST', body: formData });
    state.profile = result.profile || state.profile;
    if (state.profile) {
      state.profile.grade_sheet_filename = result.filename;
      state.profile.grade_sheet_uploaded = true;
    }
    $('#grade-sheet-name').textContent = `✓ ${result.filename}`;
    document.querySelector('[data-profile-document="grade-sheet"]')?.classList.add('resume-uploaded');
    const resumed = Array.isArray(result.resumed_application_ids) ? result.resumed_application_ids.length : 0;
    toast(resumed
      ? `גיליון הציונים נשמר בפרופיל · ${resumed} הגשות חזרו אוטומטית לתור`
      : 'גיליון הציונים נשמר בפרופיל וישמש אוטומטית בהגשות');
    await Promise.all([loadProfile(), loadApplications(), loadBlockers(), loadDashboard()]);
    if (trackedApplicationId && result.resumed_application_ids?.includes(Number(trackedApplicationId))) {
      startApplicationTracking(trackedApplicationId, false);
    }
  } catch (error) {
    toast(error.message);
  } finally {
    event.target.value = '';
  }
};

if ($('#import-job-btn')) $('#import-job-btn').onclick = () => {
  modal(`
    <span class="kicker">הוספה ידנית</span><h2>הוסף משרה מקישור</h2>
    <form id="import-form" class="form-stack">
      <label>כותרת<input name="title" required /></label><label>חברה<input name="company" required /></label>
      <label>מיקום<input name="location" /></label><label>קישור להגשה<input name="apply_url" type="url" required /></label>
      <label>תיאור<textarea name="description" rows="6"></textarea></label><button class="btn primary" type="submit">נתח והוסף</button>
    </form>
  `);
  $('#import-form').onsubmit = async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.target).entries());
    try {
      await api('/api/jobs/import', { method: 'POST', body: JSON.stringify(body) });
      closeModal();
      toast('המשרה נוספה ודורגה');
      await loadJobs();
    } catch (error) {
      toast(error.message);
    }
  };
};

function debounce(fn, wait) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), wait);
  };
}

window.queueJob = queueJob;
window.skipJob = skipJob;
window.deleteJob = deleteJob;
window.showJob = showJob;
window.retryApp = retryApp;
window.removeApplication = removeApplication;
window.addSkill = addSkill;
window.removeSkill = removeSkill;
window.showSkillGaps = showSkillGaps;
window.resolveBlocker = resolveBlocker;
window.resolveBlockerAction = resolveBlockerAction;
window.markApplicationSubmitted = markApplicationSubmitted;
window.switchView = switchView;
window.toggleSource = toggleSource;
window.deleteSource = deleteSource;
window.closeModal = closeModal;
window.cloudSignOut = cloudSignOut;
window.createAgentDevice = createAgentDevice;
window.revokeAgentDevice = revokeAgentDevice;
window.openCloudAccount = openCloudAccount;

function initInteractiveLogo(brand) {
  if (!brand || brand.dataset.logoReady === 'true') return;
  // Onboarding keeps the animated JP mark, but its orb is optically anchored to the mark itself.
  // The full flight-to-wordmark interaction is reserved for the in-app brand where there is more room.
  if (brand.classList.contains('onboarding-brand')) {
    brand.dataset.logoReady = 'true';
    brand.classList.add('onboarding-logo-ready');
    return;
  }
  const mark = brand.querySelector('.brand-mark');
  const dot = brand.querySelector('.brand-flight-dot');
  const target = brand.querySelector('.brand-i-dot');
  if (!mark || !dot || !target || !brand.getClientRects().length) return;
  brand.dataset.logoReady = 'true';
  let parked = false;
  let moving = false;
  let autoReturnTimer = null;
  let route = { x: 0, y: 0 };
  let pathDeltas = [];

  const scheduleAutoReturn = () => {
    clearTimeout(autoReturnTimer);
    if (moving || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    autoReturnTimer = window.setTimeout(() => {
      if (!moving && document.visibilityState === 'visible') toggleDot();
    }, 9000);
  };

  const positionDot = () => {
    const brandRect = brand.getBoundingClientRect();
    const path = mark.querySelector('.logo-route');
    const targetRect = target.getBoundingClientRect();
    const matrix = path.getScreenCTM();
    const length = path.getTotalLength();
    const screenPoint = (distance) => {
      const point = path.getPointAtLength(distance);
      return new DOMPoint(point.x, point.y).matrixTransform(matrix);
    };
    const localStart = path.getPointAtLength(0);
    const source = new DOMPoint(localStart.x, localStart.y - 10).matrixTransform(matrix);
    const dotRadius = dot.offsetWidth / 2;
    const sourceX = source.x - brandRect.left - dotRadius;
    const sourceY = source.y - brandRect.top - dotRadius;
    dot.style.left = `${sourceX}px`;
    dot.style.top = `${sourceY}px`;
    const targetVisible = targetRect.width > 0 && targetRect.height > 0;
    route = targetVisible ? {
      x: targetRect.left + targetRect.width / 2 - source.x,
      y: targetRect.top + targetRect.height / 2 - source.y,
    } : { x: 0, y: 0 };
    pathDeltas = Array.from({ length: 49 }, (_, index) => {
      const point = screenPoint(length * index / 48);
      return { x: point.x - source.x, y: point.y - source.y };
    });
    dot.style.transform = parked ? `translate(${route.x}px, ${route.y}px)` : 'translate(0, 0)';
  };

  const toggleDot = () => {
    if (moving) return;
    clearTimeout(autoReturnTimer);
    moving = true;
    brand.classList.add('is-moving');
    positionDot();
    const pathEnd = pathDeltas[pathDeltas.length - 1];
    const apex = { x: (pathEnd.x + route.x) / 2, y: Math.min(pathEnd.y, route.y) - 17 };
    const alongPath = pathDeltas.map((point, index) => ({
      transform: `translate3d(${point.x}px, ${point.y}px, 0) scale(1)`, offset: .03 + index / 48 * .79,
    }));
    const outbound = [
      { transform: 'translate(0, 0) scale(1)', offset: 0 }, ...alongPath,
      { transform: `translate(${pathEnd.x}px, ${pathEnd.y}px) scale(1)`, offset: .83 },
      { transform: `translate(${apex.x}px, ${apex.y}px) scale(1.08)`, offset: .91 },
      { transform: `translate(${route.x}px, ${route.y}px) scale(1)`, offset: 1 },
    ];
    const inbound = [
      { transform: `translate(${route.x}px, ${route.y}px) scale(1)`, offset: 0 },
      { transform: `translate(${route.x / 2}px, ${Math.min(route.y, 0) - 20}px) scale(1.3)`, offset: .5 },
      { transform: 'translate(0, 0) scale(.9)', offset: .9 },
      { transform: 'translate(0, 0) scale(1)', offset: 1 },
    ];
    const animation = dot.animate(parked ? inbound : outbound, {
      duration: parked ? 1050 : 2350,
      easing: parked ? 'cubic-bezier(.32,.72,0,1)' : 'cubic-bezier(.25,.1,.25,1)', fill: 'forwards',
    });
    animation.onfinish = () => {
      parked = !parked;
      brand.classList.toggle('is-parked', parked);
      brand.setAttribute('aria-label', parked ? 'לחץ להחזרת נקודת ה-Pilot אל תחילת המסלול' : 'הפעל את מסלול JobPilot');
      dot.style.transform = parked ? `translate(${route.x}px, ${route.y}px)` : 'translate(0, 0)';
      animation.cancel();
      moving = false;
      brand.classList.remove('is-moving');
      scheduleAutoReturn();
    };
  };
  brand.addEventListener('click', toggleDot);
  brand.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleDot(); }
  });
  window.addEventListener('resize', positionDot);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') scheduleAutoReturn(); });
  requestAnimationFrame(() => { positionDot(); scheduleAutoReturn(); });
}

function initInteractiveLogos() {
  document.querySelectorAll('.brand').forEach((brand) => initInteractiveLogo(brand));
}

initInteractiveLogos();

$('#restore-backup').onclick=()=>$('#restore-backup-file').click();
$('#restore-backup-file').onchange=async(event)=>{const file=event.target.files[0];if(!file)return;if(!confirm('לשחזר את הפרופיל, ההעדפות והתשובות מהגיבוי?'))return;const body=new FormData();body.append('file',file);await api('/api/backup/restore',{method:'POST',body});toast('הגיבוי שוחזר');state.profileLoaded=false;await loadProfile();};
$('#privacy-center').onclick=async()=>{
  const [privacy,resumes,security]=await Promise.all([api('/api/privacy'),api('/api/resumes'),api('/api/security/status')]);
  modal(`<span class="kicker">הנתונים נשארים בשליטתך</span><h2>מרכז פרטיות וקורות חיים</h2><div class="privacy-grid"><article><strong>סיסמת טפסים</strong><span>${privacy.password_stored?'שמורה מקומית':'לא שמורה'}</span><button class="btn danger-outline small" onclick="deletePrivateData('password')">מחיקה</button></article><article><strong>צילומי Agent</strong><span>${privacy.screenshots} קבצים</span><button class="btn danger-outline small" onclick="deletePrivateData('screenshots')">מחיקה</button></article><article><strong>פרופיל דפדפן</strong><span>${privacy.browser_profile?'קיים':'לא קיים'}</span><button class="btn danger-outline small" onclick="deletePrivateData('browser')">מחיקה</button></article></div><h3>גרסאות קורות חיים</h3><p class="resume-version-help">העלה גרסה נפרדת לכל כיוון מקצועי, למשל Backend, AI או Research. המערכת קוראת את הקובץ וממליצה על הגרסה עם חפיפת הסקילים הגבוהה ביותר לכל משרה; תמיד אפשר לבחור אחרת ידנית.</p><div class="resume-manager">${resumes.map(r=>`<div><strong>${esc(r.label)}</strong><span>${esc(r.filename)}${r.is_default?' · ברירת מחדל':''}</span><small>${r.skills.length?`סקילים: ${esc(r.skills.join(', '))}`:'לא הוגדרו סקילים לגרסה'}</small><button class="btn danger-outline small" onclick="deleteResume(${r.id})">מחק</button></div>`).join('')||'<p>אין עדיין גרסאות.</p>'}</div><form id="resume-version-form"><label>שם הגרסה<input name="label" required placeholder="Backend / AI / Research" /></label><label>סקילים נוספים לגרסה — אופציונלי<input name="skills" placeholder="המערכת מחלצת סקילים אוטומטית; אפשר להוסיף ידנית" /></label><label><input name="is_default" type="checkbox" value="true" /> ברירת מחדל</label><input name="file" type="file" required accept=".pdf,.doc,.docx,.txt,.rtf" /><button class="btn primary" type="submit">הוסף גרסה</button></form><h3>נעילת האתר</h3>${security.configured?'<button class="btn danger-outline" onclick="disableSiteLock()">בטל נעילת PIN</button>':'<div class="inline-form"><input id="new-site-pin" type="password" minlength="4" placeholder="PIN מקומי חדש" /><button class="btn secondary" onclick="setupSiteLock()">הפעל נעילה</button></div>'}`);
  $('#resume-version-form').onsubmit=async e=>{e.preventDefault();const body=new FormData(e.target);if(!body.get('is_default'))body.set('is_default','false');await api('/api/resumes',{method:'POST',body});toast('גרסת קורות החיים נוספה');closeModal();$('#privacy-center').click();};
};
async function deletePrivateData(resource){if(!confirm('למחוק את הנתונים האלה לצמיתות מהמחשב המקומי?'))return;await api(`/api/privacy/${resource}`,{method:'DELETE'});toast('הנתונים נמחקו');closeModal();}
async function deleteResume(id){if(!confirm('למחוק את גרסת קורות החיים?'))return;await api(`/api/resumes/${id}`,{method:'DELETE'});closeModal();$('#privacy-center').click();}
async function setupSiteLock(){await api('/api/security/setup',{method:'POST',body:JSON.stringify({pin:$('#new-site-pin').value})});toast('נעילת האתר הופעלה');closeModal();}
async function disableSiteLock(){await api('/api/security/lock',{method:'DELETE'});toast('נעילת האתר בוטלה');closeModal();}

async function ensureUnlocked(){const status=await api('/api/security/status');if(!status.locked)return true;modal(`<span class="kicker">JobPilot נעול</span><h2>הזן PIN מקומי</h2><input id="unlock-pin" type="password" autofocus /><button class="btn primary" onclick="unlockSite()">פתח</button>`);return false;}
async function unlockSite(){try{await api('/api/security/unlock',{method:'POST',body:JSON.stringify({pin:$('#unlock-pin').value})});location.reload();}catch(error){toast(error.message);}}

$('#auth-password-toggle').onclick = () => {
  const input = $('#auth-password');
  const button = $('#auth-password-toggle');
  if (!input || !button) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.setAttribute('aria-label', reveal ? 'הסתר סיסמה' : 'הצג סיסמה');
  button.title = reveal ? 'הסתר סיסמה' : 'הצג סיסמה';
  button.classList.toggle('is-revealed', reveal);
  input.focus({ preventScroll: true });
};

$('#profile-password-toggle').onclick=()=>{
  const input=profileForm().elements.application_password,button=$('#profile-password-toggle');
  const reveal=input.type==='password';
  input.type=reveal?'text':'password';
  button.setAttribute('aria-label',reveal?'הסתר סיסמה':'הצג סיסמה');
  button.title=reveal?'הסתר סיסמה':'הצג סיסמה';
  button.classList.toggle('is-revealed',reveal);
  input.focus({preventScroll:true});
};

$('#profile-password-restore').onclick=async()=>{
  const button=$('#profile-password-restore'),input=profileForm().elements.application_password;
  button.disabled=true;
  try{
    const result=await api('/api/profile/application-password/reveal',{method:'POST'});
    input.value=result.password||'';input.type='text';
    const toggle=$('#profile-password-toggle');
    toggle.setAttribute('aria-label','הסתר סיסמה');toggle.title='הסתר סיסמה';toggle.classList.add('is-revealed');
    input.focus();toast('הסיסמה השמורה נטענה לשדה');
  }catch(error){toast(error.message)}finally{button.disabled=false}
};

$('#auth-form').onsubmit = async (event) => {
  event.preventDefault();
  const email = $('#auth-email').value.trim();
  const password = $('#auth-password').value;
  try {
    showAuthGate('מתחבר…', 'success');
    await cloudEmailLogin(email, password);
  } catch (error) { showAuthGate(error.message, 'error'); }
};
$('#auth-signup').onclick = async () => {
  const email = $('#auth-email').value.trim();
  const password = $('#auth-password').value;
  if (!email || password.length < 6) { showAuthGate('הזן אימייל וסיסמה של לפחות 6 תווים.', 'error'); return; }
  try { showAuthGate('יוצר חשבון…', 'success'); await cloudSignup(email, password); }
  catch (error) { showAuthGate(error.message, 'error'); }
};
$('#auth-google').onclick = () => cloudGoogleLogin();
$('#auth-guest').onclick = async () => {
  try { showAuthGate('פותח סביבת אורח…', 'success'); await cloudGuestLogin(); }
  catch (error) { showAuthGate(error.message, 'error'); }
};
$('#account-chip').onclick = () => openCloudAccount().catch((error) => toast(error.message));
$('#logout-action').onclick = () => cloudSignOut();

$('#career-switcher-trigger').onclick = (event) => { event.stopPropagation(); setCareerMenu($('#career-switcher-menu').hidden); };
document.addEventListener('click', (event) => { if (!event.target.closest('#career-switcher')) setCareerMenu(false); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setCareerMenu(false); });


const ONBOARDING_VERSION = 2;
const onboardingState = { step: 0, preview: false, resume: null, selectedSkills: new Set(), draft: {}, scanTimer: null, scanStartedAt: 0, scanObservedRunning: false, saveTimer: null, saveChain: Promise.resolve() };

function onboardingSyncSavedProfile(profile){
  if(!profile)return;
  state.profile=profile; state.profileLoaded=true;
  // The onboarding is only another editor for the real profile. Keep the hidden/main
  // site controls in sync immediately so entering the site never reveals stale values.
  renderCareerPreferenceOptions();
  applyProfileToForm(profile);
  updateProfileDirtyState();
}
function onboardingPersistProfile(patch){
  onboardingState.saveChain=onboardingState.saveChain.then(async()=>{
    const saved=await api('/api/profile',{method:'PATCH',body:JSON.stringify(patch)});
    onboardingSyncSavedProfile(saved);
    return saved;
  }).catch(error=>{toast(`השמירה מהפתיחה נכשלה: ${error.message}`);throw error});
  return onboardingState.saveChain;
}
function onboardingSchedulePreferences(delay=0){
  if(onboardingState.saveTimer)clearTimeout(onboardingState.saveTimer);
  const run=()=>{onboardingState.saveTimer=null;const draft=onboardingCollectPreferences();onboardingPersistProfile(draft).then(saved=>{
    onboardingState.draft={desired_titles:[...(saved.desired_titles||[])],preferred_locations:[...(saved.preferred_locations||[])],years_experience_options:[...(saved.years_experience_options||[])],degree_level:saved.degree_level||'',preferred_work_modes:[...(saved.preferred_work_modes||[])],keywords:[...(saved.keywords||[])],excluded_keywords:[...(saved.excluded_keywords||[])]};
  }).catch(()=>{});};
  if(delay)onboardingState.saveTimer=setTimeout(run,delay);else run();
}
async function onboardingFlushSave(){
  if(onboardingState.saveTimer){clearTimeout(onboardingState.saveTimer);onboardingState.saveTimer=null;await onboardingPersistProfile(onboardingCollectPreferences());}
  await onboardingState.saveChain;
}
const onboardingSteps = ['track','resume','skills','preferences','review','ranking'];

function onboardingSplit(value=''){ return String(value).split(',').map(v=>v.trim()).filter(Boolean); }
function onboardingTrackConfig(key=state.activeCareerTrack){ return CAREER_TRACK_UI[key] || CAREER_TRACK_UI.computer_science; }
function onboardingPresetSkills(){ return (onboardingTrackConfig().skills||[]).map(([value])=>value); }
function onboardingSkillValues(){ return [...new Set([...onboardingPresetSkills(), ...onboardingState.selectedSkills])]; }
function onboardingChoiceValues(items=[]){return (items||[]).map(item=>Array.isArray(item)?item:[item,item]).filter(([v])=>v)}
function onboardingChoiceBox(kind,value,label,selected){
  const negative=kind==='excluded';
  return `<button type="button" class="onboarding-choice ${negative?'onboarding-choice-negative ':''}${selected?'selected':''}" data-ob-choice="${kind}" data-value="${encodeURIComponent(value)}"><span class="onboarding-choice-check" aria-hidden="true">${negative?'×':'✓'}</span><strong>${esc(label)}</strong></button>`;
}
function onboardingToggleChoice(button){
  button.classList.toggle('selected');
}

function onboardingApplyTrackTheme(key){ state.activeCareerTrack=key; applyCareerTrackTheme(); document.querySelector('.onboarding-shell')?.setAttribute('data-track',key); }
async function onboardingChooseTrack(key){
  if(!key || key===state.activeCareerTrack){ onboardingApplyTrackTheme(key||state.activeCareerTrack); onboardingSetStep(1); return; }
  const result=await api('/api/career-tracks/active',{method:'PUT',body:JSON.stringify({track:key})});
  state.activeCareerTrack=result.active_track||key; state.careerTracks=result.tracks||state.careerTracks; state.profile=result.profile||state.profile;
  onboardingApplyTrackTheme(state.activeCareerTrack); renderCareerPreferenceOptions(); renderCareerSwitcher(); onboardingState.selectedSkills=new Set(); onboardingSetStep(1);
}
function onboardingSetStep(index){
  onboardingState.step=Math.max(0,Math.min(onboardingSteps.length-1,index));
  const step=onboardingSteps[onboardingState.step], profile=state.profile||{}, track=onboardingTrackConfig();
  $('#onboarding-progress-label').textContent=`${onboardingState.step+1} מתוך ${onboardingSteps.length}`;
  $('#onboarding-progress-bar').style.width=`${((onboardingState.step+1)/onboardingSteps.length)*100}%`;
  $('#onboarding-back').hidden=onboardingState.step===0 || step==='ranking';
  $('#onboarding-skip').hidden=onboardingState.preview || step==='ranking';
  $('#onboarding-next').hidden=step==='track' || step==='ranking';
  const content=$('#onboarding-content');
  content.className=`onboarding-content onboarding-step onboarding-step-${step}`;
  if(step==='track'){
    const tracks=(state.careerTracks||[]).filter(t=>CAREER_TRACK_UI[t.key]);
    content.innerHTML=`<div class="onboarding-hero compact"><span class="kicker">מתחילים מהכיוון שלך</span><h1 id="onboarding-title">באיזה תחום מחפשים את התפקיד הבא?</h1><p>הבחירה מתאימה מיד את הצבעים, הסקילים, המקורות והעדפות החיפוש. המבנה מוכן למסלולים נוספים בהמשך.</p><div class="onboarding-track-grid">${tracks.map(t=>{const ui=onboardingTrackConfig(t.key);return `<button class="onboarding-track-card ${t.key===state.activeCareerTrack?'active':''}" type="button" data-ob-track="${esc(t.key)}"><span class="onboarding-track-symbol">${esc(ui.symbol)}</span><span><strong>${esc(t.label||ui.label)}</strong><small>${esc(t.description||ui.description)}</small></span><i>בחירה</i></button>`}).join('')}</div></div>`;
    $$('[data-ob-track]',content).forEach(b=>b.onclick=()=>onboardingChooseTrack(b.dataset.obTrack));
  }else if(step==='resume'){
    const uploaded=onboardingState.resume || (profile.cv_filename ? {filename:profile.cv_filename, persisted:true} : null);
    content.innerHTML=`<span class="kicker">קורות חיים</span><h1 id="onboarding-title">נכיר את הניסיון שלך</h1><p>העלה PDF או DOCX. JobPilot יקרא את הקובץ ויציע סקילים — שום סקיל לא מתווסף בלי בחירה שלך.</p><label class="onboarding-upload ${uploaded?'uploaded':''}"><input id="onboarding-resume-file" type="file" accept=".pdf,.docx,.doc,.txt,.rtf"><span class="onboarding-upload-icon">${uploaded?'✓':'↑'}</span><strong>${uploaded?esc(uploaded.filename||uploaded.cv_filename||'קורות החיים הועלו'):'בחר קובץ או גרור לכאן'}</strong><small>${uploaded?'הקובץ נשמר ונקרא בהצלחה · לחץ כדי להחליף':'PDF או DOCX מומלצים · עד 10MB'}</small>${uploaded?'<span class="onboarding-upload-success"><b>✓</b> קורות החיים מוכנים</span>':''}</label>`;
    $('#onboarding-resume-file').onchange=onboardingResume;
  }else if(step==='skills'){
    const values=onboardingSkillValues();
    content.innerHTML=`<span class="kicker">סקילים · ${esc(track.label)}</span><h1 id="onboarding-title">מה באמת מייצג אותך?</h1><p>סימנו הצעות שנמצאו בקורות החיים. הוסף או הסר בלחיצה — הרשימה מותאמת למסלול שבחרת.</p><div class="onboarding-skill-checks">${values.map(v=>`<label class="onboarding-skill-check ${onboardingState.selectedSkills.has(v)?'selected':''}"><input type="checkbox" data-ob-skill="${encodeURIComponent(v)}" ${onboardingState.selectedSkills.has(v)?'checked':''}><span class="checkmark">✓</span><strong>${esc(v)}</strong></label>`).join('')}</div>`;
    $$('[data-ob-skill]',content).forEach(input=>input.onchange=()=>{const skill=decodeURIComponent(input.dataset.obSkill||'');input.closest('.onboarding-skill-check').classList.toggle('selected',input.checked);input.checked?onboardingState.selectedSkills.add(skill):onboardingState.selectedSkills.delete(skill);onboardingPersistProfile({skills:[...onboardingState.selectedSkills]}).catch(()=>{})});
  }else if(step==='preferences'){
    const draft=onboardingState.draft||{};
    const modes=new Set(draft.preferred_work_modes||profile.preferred_work_modes||['hybrid','remote','onsite']);
    const titles=new Set(draft.desired_titles||profile.desired_titles||[]);
    const keywords=new Set(draft.keywords||profile.keywords||[]);
    const excluded=new Set(draft.excluded_keywords||profile.excluded_keywords||[]);
    const locations=new Set(draft.preferred_locations||profile.preferred_locations||[]);
    const locationChoices=[['Israel','ישראל'],['Haifa','חיפה'],['Tel Aviv','תל אביב'],['Jerusalem','ירושלים']];
    const titleChoices=onboardingChoiceValues(track.desiredTitles||[]);
    const experienceChoices=[['student','Student / Intern'],['entry level','Entry Level / Graduate'],['junior','Junior'],['mid level','Mid Level'],['senior','Senior'],['lead','Lead'],['staff','Staff / Principal'],['manager','Manager']];
    content.innerHTML=`<span class="kicker">העדפות · ${esc(track.label)}</span><h1 id="onboarding-title">נחדד את החיפוש</h1><p>בחר בכמה לחיצות את מה שמתאים לך. אפשר לדייק הכול גם אחר כך בהעדפות החיפוש.</p><div class="onboarding-form polished choice-form">
      <fieldset class="onboarding-choice-field full"><legend>תפקידים רצויים</legend><div class="onboarding-choice-grid">${titleChoices.map(([v,l])=>onboardingChoiceBox('title',v,l,titles.has(v))).join('')}</div><label class="onboarding-other"><span>משהו נוסף?</span><input id="ob-titles-extra" value="${esc((profile.desired_titles||[]).filter(v=>!titleChoices.some(([x])=>x===v)).join(', '))}" placeholder="אפשר להוסיף תפקיד שלא מופיע ברשימה"></label></fieldset>
      <fieldset class="onboarding-choice-field full onboarding-location-field"><legend>אזורי חיפוש</legend><div class="onboarding-choice-grid locations">${locationChoices.map(([v,l])=>onboardingChoiceBox('location',v,l,locations.has(v)||locations.has(l)||(v==='Israel'&&!locations.size))).join('')}</div></fieldset>
      <label><span>רמת ניסיון</span><select id="ob-experience">${['0','1','2','3','4','5+'].map(v=>`<option ${(profile.years_experience_options||['0']).includes(v)?'selected':''}>${v}</option>`).join('')}</select></label>
      <label><span>סוג תואר</span><select id="ob-degree" required><option value="" disabled ${!(draft.degree_level||profile.degree_level)?'selected':''}>בחר סוג תואר</option><option value="bachelor" ${(draft.degree_level||profile.degree_level)==='bachelor'?'selected':''}>תואר ראשון (B.A. / B.Sc.)</option><option value="master" ${(draft.degree_level||profile.degree_level)==='master'?'selected':''}>תואר שני (M.A. / M.Sc.)</option><option value="phd" ${(draft.degree_level||profile.degree_level)==='phd'?'selected':''}>דוקטורט (Ph.D.)</option></select></label>
      <fieldset class="full"><legend>אופן עבודה</legend><div class="onboarding-chips">${[['hybrid','היברידי'],['remote','מרחוק'],['onsite','מהמשרד']].map(([v,l])=>`<button type="button" class="onboarding-chip ${modes.has(v)?'selected':''}" data-ob-mode="${v}">${l}</button>`).join('')}</div></fieldset>
      <fieldset class="onboarding-choice-field full"><legend>רמות ניסיון שתרצה לראות</legend><div class="onboarding-choice-grid compact">${experienceChoices.map(([v,l])=>onboardingChoiceBox('keyword',v,l,keywords.has(v))).join('')}</div><label class="onboarding-other"><span>מילות מפתח חיוביות נוספות</span><input id="ob-keywords-extra" value="${esc((draft.keywords||profile.keywords||[]).filter(v=>!experienceChoices.some(([x])=>x===v)).join(', '))}" placeholder="למשל: infrastructure, developer tools"></label></fieldset>
      <fieldset class="onboarding-choice-field full onboarding-exclude-field"><legend>רמות ניסיון ש<span class="negative-word">לא</span> לחפש עבורך</legend><div class="onboarding-choice-grid compact">${experienceChoices.map(([v,l])=>onboardingChoiceBox('excluded',v,l,excluded.has(v))).join('')}</div><label class="onboarding-other"><span>תחומים לא רצויים בכותרת המשרה בלבד</span><input id="ob-excluded-extra" value="${esc((draft.excluded_keywords||profile.excluded_keywords||[]).filter(v=>!experienceChoices.some(([x])=>x===v)).join(', '))}" placeholder="למשל: sales, manual QA"></label></fieldset>
    </div>`;
    $$('[data-ob-mode]',content).forEach(b=>b.onclick=()=>{b.classList.toggle('selected');onboardingSchedulePreferences()});
    $$('[data-ob-choice]',content).forEach(b=>b.onclick=()=>{onboardingToggleChoice(b);onboardingSchedulePreferences()});
    $('#ob-experience').onchange=()=>onboardingSchedulePreferences();
    $('#ob-degree').onchange=()=>onboardingSchedulePreferences();
    ['#ob-titles-extra','#ob-keywords-extra','#ob-excluded-extra'].forEach(selector=>{const input=$(selector);if(input)input.oninput=()=>onboardingSchedulePreferences(450)});
  }else if(step==='review'){
    const d=onboardingState.draft;
    const modeLabels=(d.preferred_work_modes||[]).map(v=>({hybrid:'היברידי',remote:'מרחוק',onsite:'מהמשרד'}[v]||v));
    const topTitles=(d.desired_titles||[]).slice(0,3);
    content.innerHTML=`<div class="onboarding-ready onboarding-launchpad"><div class="ready-eyebrow"><span class="ready-check">✓</span><span><b>הפרופיל הראשוני הושלם</b><small>${esc(track.label)}</small></span></div><h1 id="onboarding-title">הכול מוכן להתאמות האישיות שלך</h1><p class="ready-lead">JobPilot כבר יודע מה חשוב לך. מאגר המשרות משותף ומתעדכן אוטומטית בכל שעה; עכשיו נשאר רק לדרג אותו עבורך.</p>
      <div class="ready-spotlight"><div class="ready-spotlight-main"><span class="onboarding-track-symbol">${esc(track.symbol)}</span><div><small>מחפשים עבורך</small><strong>${esc(topTitles.join(' · ')||'משרות שמתאימות לפרופיל שלך')}</strong><p>${esc((d.preferred_locations||[]).join(' · ')||'ישראל')} · ${esc(modeLabels.join(' · ')||'כל צורות העבודה')}</p></div></div><div class="ready-pulse"><i></i><span>מוכן</span></div></div>
      <div class="ready-facts"><article><span>01</span><div><small>תחום</small><strong>${esc(track.label)}</strong></div></article><article><span>02</span><div><small>סקילים שנבחרו</small><strong>${onboardingState.selectedSkills.size}</strong></div></article><article><span>03</span><div><small>אזורי חיפוש</small><strong>${(d.preferred_locations||[]).length||1}</strong></div></article><article><span>04</span><div><small>רמת ניסיון</small><strong>${esc((d.years_experience_options||[]).join(' · ')||'0')} שנים</strong></div></article><article><span>05</span><div><small>תואר</small><strong>${esc(({bachelor:'תואר ראשון',master:'תואר שני',phd:'דוקטורט'}[d.degree_level]||'לא נבחר'))}</strong></div></article></div>
      <div class="ready-next"><span class="ready-next-icon">↗</span><div><strong>בשלב הבא</strong><p>נדרג עבורך את המשרות שכבר נמצאות במאגר המשותף ונציג קודם את ההתאמות החזקות ביותר. אין צורך להפעיל סריקה.</p></div></div><p class="onboarding-ready-note">כל הבחירות נשמרות בהעדפות החיפוש וניתנות לשינוי בכל רגע.</p></div>`;
  }else{
    content.innerHTML=`<div class="onboarding-scan-stage scanning"><span class="kicker">ההתאמות שלך</span><h1 id="onboarding-title">מדרגים את מאגר המשרות עבורך</h1><p>אין כאן סריקה חדשה — המאגר כבר משותף לכולם ומתעדכן אוטומטית בכל שעה. אנחנו מחשבים עכשיו את ההתאמה האישית שלך.</p><div id="onboarding-ranking-status" class="scan-status onboarding-scan-status is-running" aria-live="polite"><span><b>מחשב התאמות…</b><small>טוען את המשרות הקיימות ומדרג לפי הפרופיל שלך</small></span><i class="scan-status-fill is-indeterminate" aria-hidden="true"></i></div><div class="onboarding-ranking-actions"><button class="btn primary onboarding-scan" id="onboarding-enter-ranked" type="button" disabled>מכין את המשרות שלך…</button><button class="btn secondary onboarding-enter-now" id="onboarding-enter-now" type="button">המשך לאתר עכשיו</button></div></div>`;
    $('#onboarding-enter-now').onclick=async()=>{await onboardingFinish();switchView('jobs');await loadJobs()};
    onboardingStartRanking();
  }
}
async function onboardingResume(event){
  const file=event.target.files?.[0]; if(!file)return;
  const allowed=['.pdf','.docx','.doc','.txt','.rtf'], suffix='.'+(file.name.split('.').pop()||'').toLowerCase();
  if(!allowed.includes(suffix)){toast('אפשר להעלות PDF, DOCX, DOC, TXT או RTF');event.target.value='';return}
  const label=event.target.closest('.onboarding-upload'); label?.classList.add('uploading');
  const body=new FormData(); body.append('file',file);
  try{
    const result=await api('/api/profile/resume',{method:'POST',body}); onboardingState.resume={...result,filename:result.filename||result.profile?.cv_filename||file.name}; state.profile=result.profile||state.profile;
    const suggestions=result.analysis?.suggestions||[];
    const found=[...(result.analysis?.detected_skills||result.analysis?.skills||[]),...suggestions.filter(x=>x.field==='skills').map(x=>x.value)].flat().map(v=>String(v||'').trim()).filter(Boolean);
    onboardingState.selectedSkills=new Set([...(state.profile?.skills||[]), ...found]); onboardingSetStep(onboardingState.step);
    const filled=resumeAutofillSummary(result.autofilled_fields||[]);
    toast(filled?`קורות החיים נותחו · מולאו: ${filled}`:'קורות החיים הועלו ונותחו');
  }catch(error){label?.classList.remove('uploading');toast(error.message)}
}
async function onboardingSaveSkills(){
  const skills=[...onboardingState.selectedSkills].map(v=>String(v||'').trim()).filter(Boolean);
  state.profile=await onboardingPersistProfile({skills});
  onboardingState.selectedSkills=new Set(state.profile.skills||skills);
}
async function saveOnboardingPreferences(){
  const draft=onboardingCollectPreferences();
  if(!draft.degree_level) throw new Error('בחר סוג תואר כדי שנוכל לסנן משרות לפי דרישת ההשכלה');
  const saved=await onboardingPersistProfile(draft);
  state.profile=saved;
  onboardingState.draft={
    desired_titles:[...(state.profile.desired_titles||[])],
    preferred_locations:[...(state.profile.preferred_locations||[])],
    years_experience_options:[...(state.profile.years_experience_options||[])],
    degree_level:state.profile.degree_level||'',
    preferred_work_modes:[...(state.profile.preferred_work_modes||[])],
    keywords:[...(state.profile.keywords||[])],
    excluded_keywords:[...(state.profile.excluded_keywords||[])],
  };
  return saved;
}
function onboardingCollectPreferences(){
  const selected=(kind)=>$$(`[data-ob-choice="${kind}"].selected`).map(b=>decodeURIComponent(b.dataset.value||''));
  onboardingState.draft={desired_titles:[...new Set([...selected('title'),...onboardingSplit($('#ob-titles-extra')?.value||'')])],preferred_locations:selected('location'),years_experience_options:[$('#ob-experience')?.value||'0'],degree_level:$('#ob-degree')?.value||'',preferred_work_modes:$$('[data-ob-mode].selected').map(b=>b.dataset.obMode),keywords:[...new Set([...selected('keyword'),...onboardingSplit($('#ob-keywords-extra')?.value||'')])],excluded_keywords:[...new Set([...selected('excluded'),...onboardingSplit($('#ob-excluded-extra')?.value||'')])]};return onboardingState.draft;
}
async function onboardingFinish(skipped=false){
  await onboardingFlushSave();
  if(onboardingState.scanTimer){clearTimeout(onboardingState.scanTimer);onboardingState.scanTimer=null}
  if(!onboardingState.preview)await api('/api/onboarding',{method:'PUT',body:JSON.stringify({completed:!skipped,skipped,step:'done'})});
  $('#onboarding-gate').hidden=true;$('#onboarding-gate').setAttribute('aria-hidden','true');document.body.classList.remove('onboarding-open');onboardingState.preview=false;
}
function renderOnboardingRankingStatus(status){
  const target=$('#onboarding-ranking-status'); if(!target)return;
  const total=Math.max(0,Number(status.total||0)), ranked=Math.max(0,Number(status.ranked||0));
  const percent=total?Math.min(100,Math.round((ranked/total)*100)):100;
  const ready=Boolean(status.ready);
  target.classList.toggle('is-running',!ready);
  target.style.setProperty('--scan-progress',`${percent}%`);
  const waiting=!ready && (!total || status.phase==='queued');
  target.innerHTML=ready
    ? `<span><b>ההתאמות מוכנות</b><small>${total?`${ranked} משרות דורגו עבורך`:'הפרופיל מוכן; משרות חדשות ידורגו אוטומטית כשהמאגר יתעדכן'}</small></span><i class="scan-status-fill" aria-hidden="true"></i>`
    : waiting
      ? `<span><b>מכין את הדירוג האישי…</b><small>הדירוג נכנס לתור ויתחיל מיד כשהשרת פנוי. אפשר להמשיך לאתר כבר עכשיו.</small></span><i class="scan-status-fill is-indeterminate" aria-hidden="true"></i>`
      : `<span><b>מחשב התאמות · ${ranked} מתוך ${total}</b><small>המאגר המשותף נשאר זמין בזמן שהדירוג האישי מתעדכן</small></span><i class="scan-status-fill" aria-hidden="true"></i>`;
}
async function onboardingWatchRanking(){
  try{
    const status=await api('/api/ranking/status');
    renderOnboardingRankingStatus(status);
    if(!status.ready){onboardingState.scanTimer=setTimeout(onboardingWatchRanking,700);return}
    $('.onboarding-scan-stage')?.classList.add('complete');
    const button=$('#onboarding-enter-ranked');
    if(button){button.disabled=false;button.textContent='למשרות שנבחרו עבורך';button.onclick=async()=>{await onboardingFinish();switchView('jobs');await loadJobs()}}
  }catch(error){
    const target=$('#onboarding-ranking-status');
    if(target)target.innerHTML=`<span><b>לא הצלחנו לקרוא את מצב הדירוג</b><small>${esc(error.message||'נסה שוב')}</small></span><i class="scan-status-fill is-indeterminate" aria-hidden="true"></i>`;
    onboardingState.scanTimer=setTimeout(onboardingWatchRanking,1500);
  }
}
async function onboardingStartRanking(){
  if(onboardingState.scanTimer){clearTimeout(onboardingState.scanTimer);onboardingState.scanTimer=null}
  try{await onboardingFlushSave();await api('/api/ranking/refresh',{method:'POST'});}catch(error){toast(error.message)}
  onboardingWatchRanking();
}

async function openOnboarding(preview=false){
  if(authState.user?.is_guest)return;
  // Always hydrate onboarding from the server so reopening it reflects what was actually saved.
  state.profile=await api('/api/profile');state.profileLoaded=true;
  onboardingState.preview=preview;onboardingState.step=0;onboardingState.resume=null;onboardingState.selectedSkills=new Set(state.profile?.skills||[]);onboardingState.draft={};onboardingApplyTrackTheme(state.activeCareerTrack);
  $('#onboarding-gate').hidden=false;$('#onboarding-gate').setAttribute('aria-hidden','false');document.body.classList.add('onboarding-open');onboardingSetStep(0);
}
async function maybeOpenOnboarding(){if(authState.user?.is_guest)return;const status=await api('/api/onboarding');if(Number(status.current_version||0)!==ONBOARDING_VERSION)console.warn('Onboarding asset/API version mismatch',status);if(!status.completed)await openOnboarding(false)}
$('#onboarding-back').onclick=()=>onboardingSetStep(onboardingState.step-1);
$('#onboarding-skip').onclick=()=>onboardingFinish(true);
$('#onboarding-next').onclick=async()=>{try{const step=onboardingSteps[onboardingState.step];if(step==='skills')await onboardingSaveSkills();if(step==='preferences'){await onboardingFlushSave();await saveOnboardingPreferences()}onboardingSetStep(onboardingState.step+1)}catch(e){toast(e.message)}};
let developerUsersCache=[];
const developerDate=value=>value?new Date(value).toLocaleString('he-IL'):'—';
const developerTrackLabel=key=>CAREER_TRACK_UI[key]?.label||key||'—';
function developerMetric(label,value,detail='',tone='') { return `<article class="developer-health ${tone}"><small>${esc(label)}</small><strong>${esc(value)}</strong><span>${esc(detail)}</span></article>`; }
async function loadDeveloperOverview(){
  const grid=$('#developer-health-grid'),details=$('#developer-system-details'); if(!grid||!details)return;
  try{
    const o=await api('/api/admin/developer/overview');
    const scan=o.scan||{},sources=o.sources||{},agent=o.agent||{},queue=o.derived_refresh||{};
    grid.innerHTML=[developerMetric('API','Online',`v${o.app.version}`,'ok'),developerMetric('מקורות',`${sources.enabled}/${sources.total}`,`${sources.errors} שגיאות · Health ${sources.average_health}%`,sources.errors?'warn':'ok'),developerMetric('סריקה',scan.running?'Running':'Idle',developerTrackLabel(o.track),scan.running?'live':''),developerMetric('Agent',`${agent.online}/${agent.enabled}`,agent.last_seen_at?`נראה ${developerDate(agent.last_seen_at)}`:'אין heartbeat',agent.online?'ok':''),developerMetric('משרות',String(o.jobs.active),`${o.jobs.strong} התאמות 80+`),developerMetric('Re-rank queue',String(queue.count||0),queue.count?'עבודה נגזרת ברקע':'התור נקי',queue.count?'live':'ok')].join('');
    details.innerHTML=Object.entries({Auth:o.app.auth_mode,Storage:o.app.storage_mode,'Scan worker':o.app.scan_execution_mode,Scheduler:o.app.scheduler_enabled?`פעיל · ${o.app.scan_time}`:'כבוי',Timezone:o.app.timezone,'Concurrent scans':o.app.max_concurrent_user_scans,'Cloud storage':o.flags.cloud_storage?'כן':'לא','Application Agent':o.flags.application_agent?'מורשה':'לא מורשה'}).map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
    const badge=$('#developer-health-badge');if(badge){badge.textContent=sources.errors?'דורש בדיקה':'תקין';badge.classList.toggle('warn',!!sources.errors)}
  }catch(e){grid.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}
}
async function loadDeveloperUsers(){
  const root=$('#developer-users-list'),count=$('#developer-users-count');if(!root)return;root.innerHTML='<div class="empty-state">טוען משתמשים…</div>';
  try{const payload=await api('/api/admin/users');developerUsersCache=payload.users||[];count.textContent=`${payload.count||0}/${payload.max_users||'—'}`;renderDeveloperUsers()}catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}
}
function renderDeveloperUsers(){
  const root=$('#developer-users-list'),q=String($('#developer-user-search')?.value||'').trim().toLowerCase();if(!root)return;
  const users=developerUsersCache.filter(u=>!q||String(u.email||u.id).toLowerCase().includes(q));
  root.innerHTML=users.map(u=>`<button type="button" class="developer-user-row" data-developer-user="${esc(u.id)}"><span class="cloud-user-avatar">${esc((u.email||'?').slice(0,1).toUpperCase())}</span><span><strong>${esc(u.email||u.id)}</strong><small>${u.role==='admin'?'Admin':'משתמש'} · כניסה אחרונה ${esc(developerDate(u.last_login_at||u.claimed_at))} · פעילות ${esc(developerDate(u.last_seen_at))}</small></span><b>›</b></button>`).join('')||'<div class="empty-state">אין משתמשים להצגה</div>';
  $$('[data-developer-user]',root).forEach(b=>b.onclick=()=>inspectDeveloperUser(b.dataset.developerUser));
}
let developerInspectedUserId='';
async function inspectDeveloperUser(id){
  const root=$('#developer-user-inspector');developerInspectedUserId=id;root.innerHTML='<div class="empty-state">טוען…</div>';
  try{
    const d=await api(`/api/admin/developer/users/${encodeURIComponent(id)}`);
    const card=(section,label,value)=>`<button type="button" class="developer-kv-action" data-developer-section="${section}"><span>${label}</span><strong>${value}</strong><b>›</b></button>`;
    root.innerHTML=`<div class="developer-inspector-head"><strong>${esc(d.user.email||d.user.id)}</strong><span>${esc(d.user.role)}</span></div><div class="developer-kv developer-kv-interactive">${card('track','מסלול',esc(developerTrackLabel(d.profile.track)))}${card('onboarding','Onboarding',`v${d.profile.onboarding_version}`)}${card('skills','Skills',d.profile.skills)}${card('desired_titles','Desired titles',d.profile.desired_titles)}${card('jobs','Jobs',d.counts.jobs)}${card('sources','Sources',d.counts.sources)}${card('applications','Applications',d.counts.applications)}${card('resumes','Resumes',d.counts.resumes)}</div><div id="developer-user-section" class="developer-user-section"><div class="empty-state">לחץ על אחד הכרטיסים כדי לראות פרטים</div></div><div class="developer-user-admin-actions"><button type="button" class="btn secondary" data-user-onboarding-reset>הפעל Onboarding מחדש</button><button type="button" class="btn secondary developer-reset-profile" data-user-profile-reset>אפס פרופיל</button></div>`;
    $$('[data-developer-section]',root).forEach(b=>b.onclick=()=>openDeveloperUserSection(id,b.dataset.developerSection));
    $('[data-user-onboarding-reset]',root).onclick=()=>resetDeveloperUserOnboarding(id,d.user.email||id);
    $('[data-user-profile-reset]',root).onclick=()=>resetDeveloperUserProfile(id,d.user.email||id);
  }catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}
}
async function openDeveloperUserSection(id,section){
  const root=$('#developer-user-section');if(!root)return;
  if(section==='onboarding'){
    root.innerHTML='<div class="developer-section-head"><strong>Onboarding</strong><small>איפוס יגרום למסכי הפתיחה להופיע שוב בכניסה הבאה של המשתמש, בלי למחוק את הפרופיל הקיים.</small></div>';
    return;
  }
  root.innerHTML='<div class="empty-state">טוען פרטים…</div>';
  try{
    const d=await api(`/api/admin/developer/users/${encodeURIComponent(id)}/section/${encodeURIComponent(section)}`);
    root.innerHTML=`<div class="developer-section-head"><strong>${esc(d.title||section)}</strong><small>${(d.items||[]).length} פריטים</small></div><div class="developer-inspector-list">${(d.items||[]).map(item=>item.resume_id?`<a class="developer-inspector-item" target="_blank" rel="noopener" href="/api/admin/developer/users/${encodeURIComponent(id)}/resumes/${item.resume_id}/file"><span><strong>${esc(item.primary||'קורות חיים')}</strong><small>${esc(item.secondary||'')}</small></span><b>פתח קובץ ↗</b></a>`:`<article class="developer-inspector-item"><span><strong>${esc(item.primary||'—')}</strong><small>${esc(item.secondary||'')}</small></span></article>`).join('')||'<div class="empty-state">אין פריטים להצגה</div>'}</div>`;
  }catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}
}
async function resetDeveloperUserOnboarding(id,email){
  if(!confirm(`להפעיל מחדש את ה-Onboarding עבור ${email}? הוא יוצג שוב בכניסה הבאה והנתונים הקיימים יישמרו.`))return;
  try{await api(`/api/admin/developer/users/${encodeURIComponent(id)}/onboarding/reset`,{method:'POST'});toast('ה-Onboarding יופעל מחדש בכניסה הבאה');await inspectDeveloperUser(id)}catch(e){toast(e.message)}
}
async function resetDeveloperUserProfile(id,email){
  if(!confirm(`לאפס את הפרופיל של ${email}?\n\nהפעולה תאפס פרטים אישיים והעדפות חיפוש ותפעיל מחדש את ה-Onboarding. משרות, מקורות, הגשות וקבצי קורות חיים לא יימחקו.`))return;
  const typed=prompt(`פעולה רגישה: הקלד RESET כדי לאשר איפוס פרופיל של ${email}`);if(typed!=='RESET')return;
  try{await api(`/api/admin/developer/users/${encodeURIComponent(id)}/profile/reset`,{method:'POST'});toast('הפרופיל אופס וה-Onboarding יופעל מחדש');await inspectDeveloperUser(id)}catch(e){toast(e.message)}
}
async function loadDeveloperSources(){const root=$('#developer-sources-list');if(!root)return;try{const rows=await api('/api/sources');root.innerHTML=rows.map(s=>`<article class="developer-source-row"><span><strong>${esc(s.name)}</strong><small>${esc(s.kind)} · health ${s.health_score}%${s.last_error?` · ${esc(s.last_error.slice(0,110))}`:''}</small></span><button class="btn secondary" type="button" data-test-source="${s.id}">בדוק מקור</button></article>`).join('')||'<div class="empty-state">אין מקורות במסלול הפעיל</div>';$$('[data-test-source]',root).forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await api(`/api/admin/developer/sources/${b.dataset.testSource}/test`,{method:'POST'});toast(r.status==='started'?'בדיקת המקור התחילה':'כבר מתבצעת סריקה');setTimeout(loadDeveloperOverview,900)}catch(e){toast(e.message)}finally{b.disabled=false}})}catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}}
async function loadDeveloperAudit(){const root=$('#developer-audit-list');if(!root)return;try{const rows=await api('/api/admin/developer/audit?limit=30');root.innerHTML=rows.map(r=>`<article><span><strong>${esc(r.event_type)}</strong><small>${esc(r.entity_type||'system')} ${r.entity_id?`#${esc(r.entity_id)}`:''}</small></span><time>${esc(developerDate(r.created_at))}</time>${r.message?`<p>${esc(r.message.slice(0,180))}</p>`:''}</article>`).join('')||'<div class="empty-state">אין אירועים</div>'}catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}}
let rankingLabState={settings:null,userId:'',comparison:null};
const RANKING_CONFIG_FIELDS=[['role_weight','Role Match'],['skills_weight','Skills / Technologies'],['requirements_weight','Professional Requirements'],['preferences_weight','Soft Preferences'],['maximum_job_age_days','Maximum job age'],['realistic_experience_gap','Realistic experience gap'],['stretch_experience_gap','Stretch experience gap'],['exclude_experience_gap','Exclude experience gap'],['top_match_threshold','Top Match threshold'],['strong_match_threshold','Strong Match threshold'],['good_match_threshold','Good Match threshold'],['low_match_threshold','Low Match threshold']];
function rankingConfigValues(){const value={...rankingLabState.settings?.config};RANKING_CONFIG_FIELDS.forEach(([key])=>{const input=$(`[data-ranking-config="${key}"]`);if(input)value[key]=Number(input.value)});return value}
function renderRankingConfig(config){const root=$('#ranking-config-fields');if(!root)return;root.innerHTML=RANKING_CONFIG_FIELDS.map(([key,label])=>`<label><span>${esc(label)}</span><input type="number" data-ranking-config="${key}" value="${Number(config?.[key]??0)}"></label>`).join('')}
function rankingRow(item,compact=false){const stateLabel=item.state==='ready'?'stored':item.state==='computed'?'live':item.state||'ready';return `<button type="button" class="developer-source-row ranking-row ${item.eligibility==='excluded'?'is-excluded':''}" data-ranking-job="${item.job_id}"><span><strong>${esc(item.job)}</strong><small>${esc(item.company)} · ${esc(item.tier||'—')} · ${esc(item.eligibility||'unknown')}${compact?'':` · ${esc(stateLabel)}`}</small></span><span class="ranking-row-metrics"><b class="ranking-score primary">${item.score??'—'}</b></span></button>`}
function bindRankingRows(){$$('[data-ranking-job]').forEach(button=>button.onclick=()=>inspectRankingJob(Number(button.dataset.rankingJob)))}
async function loadRankingLab(){const user=$('#ranking-lab-user');if(!user)return;if(!rankingLabState.userId)rankingLabState.userId=developerUsersCache[0]?.id||authState.user?.id||'';user.innerHTML=developerUsersCache.map(item=>`<option value="${esc(item.id)}" ${item.id===rankingLabState.userId?'selected':''}>${esc(item.email||item.id)}</option>`).join('');if(!rankingLabState.userId)return;try{const data=await api(`/api/admin/developer/ranking?user_id=${encodeURIComponent(rankingLabState.userId)}`);rankingLabState.settings=data.settings;const s=data.status||{},settings=data.settings||{};$('#ranking-lab-status').innerHTML=[developerMetric('Engine','V2',`config v${settings.config_version}`),developerMetric('Evaluated',`${s.evaluated}/${s.total}`,`${s.waiting} waiting`),developerMetric('Stale / errors',`${s.stale} / ${s.failed}`,s.last_evaluation?developerDate(s.last_evaluation):'Never'),developerMetric('Average evaluation',`${s.average_evaluation_ms||0} ms`,s.queue?.count?'Queued / running':'Idle')].join('');$('#ranking-lab-engine-badge').textContent='V2';$('#ranking-inspected-user').textContent=developerUsersCache.find(item=>item.id===rankingLabState.userId)?.email||rankingLabState.userId;renderRankingConfig(settings.config);await loadRankingComparison()}catch(e){$('#ranking-lab-status').innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}}
async function loadRankingComparison(){if(!rankingLabState.userId)return;const root=$('#ranking-comparison-list');root.innerHTML='<div class="empty-state">טוען דירוגים…</div>';try{const sort=$('#ranking-comparison-sort').value;const data=await api(`/api/admin/developer/ranking/jobs?user_id=${encodeURIComponent(rankingLabState.userId)}&sort=${encodeURIComponent(sort)}`);rankingLabState.comparison=data;$('#ranking-v2-top').innerHTML=(data.top||[]).map(item=>rankingRow(item,true)).join('')||'<div class="empty-state">אין תוצאות דירוג</div>';root.innerHTML=(data.items||[]).slice(0,100).map(item=>rankingRow(item)).join('')||'<div class="empty-state">אין תוצאות דירוג</div>';bindRankingRows()}catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}}
async function inspectRankingJob(jobId){const root=$('#ranking-job-inspector');root.hidden=false;root.innerHTML='<div class="empty-state">טוען Inspector…</div>';try{const data=await api(`/api/admin/developer/ranking/users/${encodeURIComponent(rankingLabState.userId)}/jobs/${jobId}`),v=data.ranking||{},e=v.eligibility||{},b=v.breakdown||{};const part=(label,key)=>`<article><span>${label}</span><strong>${b[key]?.score??0} / ${b[key]?.max??0}</strong><small>${esc((b[key]?.reasons||[]).join(' · '))}</small></article>`;root.innerHTML=`<button type="button" class="ranking-inspector-close">×</button><h3>${esc(data.job.title)}</h3><p>${esc(data.job.company)}</p><div class="ranking-inspector-score"><strong>${v.score}%</strong><span>${esc(v.tier)} · ${esc(v.confidence)} confidence</span></div><section><h4>Eligibility · ${esc(e.state)}</h4><p>${esc([...(e.reasons||[]),...(e.warnings||[])].join(' · '))}</p><small>Unknown: ${esc((e.unknown_fields||[]).join(', ')||'none')}</small></section><div class="ranking-breakdown">${part('Role','role')}${part('Skills','skills')}${part('Requirements','requirements')}${part('Preferences','preferences')}</div>`;$('.ranking-inspector-close',root).onclick=()=>{root.hidden=true}}catch(e){root.innerHTML=`<div class="empty-state">${esc(e.message)}</div>`}}
async function previewRankingConfig(){try{const data=await api('/api/admin/developer/ranking/preview',{method:'POST',body:JSON.stringify({user_id:rankingLabState.userId,config:rankingConfigValues(),sample_size:100})}),s=data.statistics||{},root=$('#ranking-preview-stats');root.hidden=false;root.innerHTML=`<strong>Preview בלבד — לא נשמר</strong><span>Promoted ${s.jobs_promoted} · Demoted ${s.jobs_demoted} · Average Δ ${s.average_score_delta}</span>`;$('#ranking-v2-top').innerHTML=(data.preview_top||[]).map(item=>rankingRow(item,true)).join('');bindRankingRows()}catch(e){toast(e.message)}}
async function applyRankingConfig(){if(!confirm('להחיל את הגדרת הדירוג? הגרסה תעלה וייכנס rerank אסינכרוני לתור.'))return;try{await api('/api/admin/developer/ranking/config',{method:'PUT',body:JSON.stringify({config:rankingConfigValues()})});toast('Ranking config applied');await loadRankingLab()}catch(e){toast(e.message)}}
async function resetRankingConfig(){if(!confirm('לשחזר את ברירות המחדל של הדירוג?'))return;try{await api('/api/admin/developer/ranking/config/reset',{method:'POST'});toast('Ranking defaults restored');await loadRankingLab()}catch(e){toast(e.message)}}
function renderDeveloperThemeLab(){const root=$('#developer-theme-lab');if(!root)return;root.innerHTML=Object.values(CAREER_TRACK_UI).map(t=>`<div><strong>${esc(t.label)}</strong><button type="button" data-theme-preview="${t.key}:light">יום</button><button type="button" data-theme-preview="${t.key}:dark">לילה</button></div>`).join('');$$('[data-theme-preview]',root).forEach(b=>b.onclick=()=>{const [track,mode]=b.dataset.themePreview.split(':');Object.values(CAREER_TRACK_UI).forEach(t=>document.body.classList.remove(t.themeClass));document.body.classList.add(CAREER_TRACK_UI[track].themeClass);document.body.classList.toggle('theme-dark',mode==='dark');document.body.classList.toggle('theme-light',mode==='light');auditDeveloperColors();toast(`תצוגת QA: ${developerTrackLabel(track)} · ${mode==='dark'?'לילה':'יום'}`)})}
function auditDeveloperColors(){const root=$('#developer-color-audit');if(!root)return;const track=document.body.classList.contains('track-electrical-engineering')?'electrical_engineering':document.body.classList.contains('track-industrial-engineering')?'industrial_engineering':'computer_science';const suspicious=[];if(track!=='computer_science'){const blue=/rgb\((?:0|1?\d?\d|2[0-4]\d|25[0-5]),\s*(?:8\d|9\d|1[0-9]\d),\s*(?:1[4-9]\d|2[0-5]\d)\)/;$$('button,input,select,textarea,.panel,.metric,.option-grid label,.check-row label').slice(0,500).forEach(el=>{const c=getComputedStyle(el);if(blue.test(c.borderColor)||blue.test(c.backgroundColor)||blue.test(c.color))suspicious.push(el)})}root.textContent=track==='computer_science'?'Color audit: כחול הוא צבע המסלול ולכן אינו נחשב זליגה.':suspicious.length?`Color audit: נמצאו ${suspicious.length} אלמנטים חשודים לבדיקה.`:'Color audit: לא נמצאה זליגה כחולה במדגם האינטראקטיבי.';root.classList.toggle('warn',suspicious.length>0)}
async function loadDeveloperCenter(){await Promise.all([loadDeveloperOverview(),loadDeveloperUsers(),loadDeveloperSources(),loadDeveloperAudit()]);await loadRankingLab();renderDeveloperThemeLab();auditDeveloperColors()}
$('#developer-preview-onboarding').onclick=async()=>{try{await api('/api/admin/onboarding/preview',{method:'POST'});await openOnboarding(true)}catch(e){toast(e.message)}};
$('#developer-preview-non-admin').onclick=enterNonAdminPreview;$('#admin-preview-exit').onclick=exitNonAdminPreview;
$('#developer-user-search').oninput=renderDeveloperUsers;
$('#developer-refresh-all').onclick=loadDeveloperCenter;
$('#developer-rerank').onclick=async()=>{try{await api('/api/admin/developer/rerank',{method:'POST'});toast('Re-rank נכנס לתור');loadDeveloperOverview()}catch(e){toast(e.message)}};
$('#ranking-lab-user').onchange=event=>{rankingLabState.userId=event.target.value;loadRankingLab()};
$('#ranking-comparison-sort').onchange=loadRankingComparison;
$('#ranking-rerank-v2').onclick=async()=>{try{await api(`/api/admin/developer/ranking/rerank?user_id=${encodeURIComponent(rankingLabState.userId)}`,{method:'POST'});toast('V2 rerank queued');await loadRankingLab()}catch(e){toast(e.message)}};
$('#ranking-preview-config').onclick=previewRankingConfig;$('#ranking-apply-config').onclick=applyRankingConfig;$('#ranking-reset-config').onclick=resetRankingConfig;
$('#developer-reset-scan-runtime').onclick=async()=>{if(!confirm('לאפס את מצב הסריקה המקומי?'))return;try{await api('/api/admin/developer/scan-runtime/reset',{method:'POST'});toast('מצב הסריקה אופס');loadDeveloperOverview()}catch(e){toast(e.message)}};
$('#developer-reset-onboarding').onclick=async()=>{if(!confirm('לאפס את ה-Onboarding שלך כדי שיופיע מחדש?'))return;try{await api('/api/admin/developer/onboarding/reset',{method:'POST'});toast('ה-Onboarding אופס')}catch(e){toast(e.message)}};
$('#developer-hard-refresh').onclick=()=>{if(!confirm('לנקות cache מקומי של תצוגה ולרענן? נתוני השרת לא יימחקו.'))return;['jobpilot-active-view','jobpilot-profile-section'].forEach(k=>localStorage.removeItem(k));location.reload()};
const ADMIN_PREVIEW_KEY='jobpilot-preview-non-admin';
function adminPreviewActive(){try{return sessionStorage.getItem(ADMIN_PREVIEW_KEY)==='1'}catch{return false}}
function applyAdminPreviewMode(){const exit=$('#admin-preview-exit');if(exit)exit.hidden=!adminPreviewActive()}
async function refreshPreviewIdentity(){
  if(authState.config?.mode==='supabase'&&authState.session){await verifyCloudSession({throwOnError:true});renderCloudAccount()}
  configureDeveloperTools();
  await Promise.allSettled([refreshAgentStatus(),loadDashboard()]);
}
async function enterNonAdminPreview(){try{sessionStorage.setItem(ADMIN_PREVIEW_KEY,'1')}catch{}configureDeveloperTools();try{await refreshPreviewIdentity();switchView('dashboard');toast('תצוגת משתמש רגיל פעילה — השרת וה־UI משתמשים כעת בדיוק בהרשאות משתמש רגיל.')}catch(error){try{sessionStorage.removeItem(ADMIN_PREVIEW_KEY)}catch{}configureDeveloperTools();toast(error.message)}}
async function exitNonAdminPreview(){try{sessionStorage.removeItem(ADMIN_PREVIEW_KEY)}catch{}configureDeveloperTools();try{await refreshPreviewIdentity();toast('חזרת לתצוגת Admin')}catch(error){toast(error.message)}}

function configureDeveloperTools(){
  const allowed=!adminPreviewActive()&&(authState.config?.mode!=='supabase'||authState.capabilities?.developer_tools === true);$$('.admin-only-nav').forEach(el=>el.hidden=!allowed);
  const importButton=$('#import-job-btn'); if(importButton) importButton.hidden=!allowed;
  const workerSetting=$('#admin-worker-setting');if(workerSetting)workerSetting.hidden=!allowed;
  applyAdminPreviewMode();const status=$('#developer-runtime-status');if(status)status.textContent=allowed?`מחובר כ־${authState.user?.email||'local'} · role: ${authState.user?.role||'admin'} · onboarding v${ONBOARDING_VERSION}`:'';if(allowed)loadDeveloperCenter();
}

let backgroundWorkerDevice=null;
const GITHUB_ACTIONS_SECRETS_URL='https://github.com/almogkarif/JobPilot/settings/secrets/actions';
async function loadBackgroundWorkerSetup(){
  const status=$('#background-worker-status'),create=$('#background-worker-create'),test=$('#background-worker-test'),revoke=$('#background-worker-revoke');if(!status)return;
  if($('#admin-worker-setting')?.hidden)return;
  try{
    const data=await api('/api/agent-devices');
    backgroundWorkerDevice=(data.devices||[]).find(item=>item.enabled&&String(item.name||'').startsWith('GitHub Actions Worker'))||null;
    create.hidden=!!backgroundWorkerDevice;test.hidden=!backgroundWorkerDevice;revoke.hidden=!backgroundWorkerDevice;
    if(!backgroundWorkerDevice)status.innerHTML='<strong>עדיין לא חובר worker</strong><span>צור token חד־פעמי, שמור אותו ב־GitHub Secret והרץ בדיקת חיבור.</span>';
    else if(backgroundWorkerDevice.last_seen_at)status.innerHTML=`<strong>Worker חובר בהצלחה</strong><span>GitHub Actions התחבר לאחרונה ${esc(developerDate(backgroundWorkerDevice.last_seen_at))}. כל ההגשות הנתמכות ירוצו ברקע.</span>`;
    else status.innerHTML='<strong>ה־token נוצר וממתין לחיבור ראשון</strong><span>השלם את שני ה־Secrets ב־GitHub. החיבור יאומת אוטומטית בהרצה הראשונה.</span>';
  }catch(error){status.innerHTML=`<strong>לא ניתן לבדוק את ה־worker</strong><span>${esc(error.message)}</span>`}
}
function backgroundWorkerGuide(token='',baseUrl=location.origin){
  const tokenSection=token?`<div class="worker-secret-block"><label>Secret ראשון · JOBPILOT_AGENT_TOKEN</label><code id="worker-token-value">${esc(token)}</code><button class="btn secondary small" type="button" onclick="navigator.clipboard.writeText(document.querySelector('#worker-token-value').textContent);toast('ה־token הועתק')">העתק token</button></div>`:'<div class="submission-preview-warnings"><strong>אין token זמין להצגה.</strong> מטעמי אבטחה token מוצג רק בזמן יצירתו. אם איבדת אותו, בטל את החיבור וצור חדש.</div>';
  modal(`<span class="kicker">חיבור חד־פעמי · ללא תשלום</span><h2>GitHub Actions Worker</h2><ol class="worker-setup-steps"><li><b>1</b><span>פתח את GitHub Secrets בקישור למטה.</span></li><li><b>2</b><span>צור secret בשם <code>JOBPILOT_AGENT_TOKEN</code> והדבק את ה־token.</span></li><li><b>3</b><span>צור secret בשם <code>JOBPILOT_BASE_URL</code> עם הערך <code>${esc(baseUrl)}</code>.</span></li><li><b>4</b><span>חזור לכאן. ההגשה הראשונה תפעיל את ה־worker אוטומטית.</span></li></ol>${tokenSection}<div class="worker-secret-block"><label>Secret שני · JOBPILOT_BASE_URL</label><code id="worker-base-url">${esc(baseUrl)}</code><button class="btn secondary small" type="button" onclick="navigator.clipboard.writeText(document.querySelector('#worker-base-url').textContent);toast('הכתובת הועתקה')">העתק כתובת</button></div><div class="modal-actions"><a class="btn primary" target="_blank" rel="noopener" href="${GITHUB_ACTIONS_SECRETS_URL}">פתח GitHub Secrets</a><button class="btn secondary" type="button" onclick="closeModal();loadBackgroundWorkerSetup()">סיימתי</button></div>`);
}
async function createBackgroundWorker(){
  try{const result=await api('/api/agent-devices',{method:'POST',body:JSON.stringify({name:'GitHub Actions Worker'})});backgroundWorkerDevice=result.device;backgroundWorkerGuide(result.token,result.base_url||location.origin);await loadBackgroundWorkerSetup()}catch(error){toast(error.message)}
}
async function revokeBackgroundWorker(){
  if(!backgroundWorkerDevice||!confirm('לבטל את חיבור GitHub Actions Worker? הגשות חדשות יישארו בתור.'))return;
  try{await api(`/api/agent-devices/${backgroundWorkerDevice.id}`,{method:'DELETE'});backgroundWorkerDevice=null;toast('חיבור ה־worker בוטל');await loadBackgroundWorkerSetup()}catch(error){toast(error.message)}
}
async function testBackgroundWorker(){
  const button=$('#background-worker-test');button.disabled=true;
  try{await api('/api/background-worker/test',{method:'POST'});toast('בדיקת החיבור הופעלה; GitHub מכין Chromium ברקע');[15000,45000,90000].forEach(delay=>setTimeout(loadBackgroundWorkerSetup,delay))}catch(error){toast(error.message)}finally{setTimeout(()=>{button.disabled=false},2000)}
}
$('#background-worker-create').onclick=createBackgroundWorker;
$('#background-worker-test').onclick=testBackgroundWorker;
$('#background-worker-guide').onclick=()=>backgroundWorkerGuide('',authState.config?.base_url||location.origin);
$('#background-worker-revoke').onclick=revokeBackgroundWorker;

async function loadGmailIntegration(){
  const status=$('#gmail-integration-status'),connect=$('#gmail-connect'),verify=$('#gmail-verify'),disconnect=$('#gmail-disconnect');
  if(!status)return;
  try{
    const data=await api('/api/integrations/gmail');
    connect.hidden=!!data.connected||!data.available;
    verify.hidden=!data.connected;disconnect.hidden=!data.connected;
    if(data.connected){
      status.innerHTML=`<strong>Gmail מחובר</strong><span>${esc(data.email||'חשבון Google')} · בדיקה אחרונה ${esc(developerDate(data.last_checked_at))}</span>`;
    }else if(!data.available){
      status.innerHTML='<strong>החיבור עדיין לא הוגדר בשרת</strong><span>נדרשים פרטי OAuth של Google. הנתונים נשמרים מוצפנים והמערכת קוראת רק כותרות של הודעות אישור.</span>';
    }else{
      status.innerHTML='<strong>Gmail לא מחובר</strong><span>חיבור אופציונלי מאפשר לאמת שההגשה התקבלה בפועל.</span>';
    }
  }catch(error){status.innerHTML=`<strong>לא ניתן לבדוק את החיבור</strong><span>${esc(error.message)}</span>`}
}

async function connectGmail(){
  try{const data=await api('/api/integrations/gmail/connect');window.location.assign(data.authorization_url)}catch(error){toast(error.message)}
}
async function verifyGmailApplications(){
  const button=$('#gmail-verify');button.disabled=true;
  try{const data=await api('/api/integrations/gmail/verify-applications',{method:'POST'});toast(`הבדיקה הסתיימה: ${data.verified_count||0} הגשות אומתו`);await Promise.all([loadGmailIntegration(),loadApplications()])}catch(error){toast(error.message)}finally{button.disabled=false}
}
async function disconnectGmail(){
  if(!confirm('לנתק את Gmail? הגשות שכבר אומתו יישארו שמורות.'))return;
  try{await api('/api/integrations/gmail',{method:'DELETE'});toast('Gmail נותק');await loadGmailIntegration()}catch(error){toast(error.message)}
}
$('#gmail-connect').onclick=connectGmail;
$('#gmail-verify').onclick=verifyGmailApplications;
$('#gmail-disconnect').onclick=disconnectGmail;

(async () => {
  try {
    if (!await initAuthentication()) return;
    if (!await ensureUnlocked()) return;
    await loadCareerTracks();
    await Promise.all([loadDashboard(), loadProfile()]);
    configureDeveloperTools();
    await maybeOpenOnboarding();
    if (state.dashboard?.scan?.running) pollScan();
    renderNotificationCenter();
    updateScanCountdown();
    await refreshAgentStatus();
    if(trackedApplicationId)startApplicationTracking(trackedApplicationId,false);
    if (authState.config?.mode === 'supabase') window.setInterval(refreshAgentStatus, 30_000);
    const savedView = localStorage.getItem('jobpilot-active-view');
    const validViews = new Set(['dashboard','jobs','preferences','applications','blockers','skills','sources','profile','settings','developer']);
    if (validViews.has(savedView) && savedView !== 'dashboard') switchView(savedView);
    const gmailResult=new URLSearchParams(location.search).get('gmail');
    if(gmailResult){
      toast(gmailResult==='connected'?'Gmail חובר בהצלחה':'חיבור Gmail לא הושלם');
      history.replaceState({},'',location.pathname+location.hash);
      switchView('settings');
    }
  } catch (error) {
    if (authState.config?.mode === 'supabase' && !authState.user) showAuthGate(`שגיאת התחברות: ${error.message}`);
    else toast(`שגיאת חיבור: ${error.message}`);
  }
})();
