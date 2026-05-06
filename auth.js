/**
 * Kronautomation — Auth Layer (compartido)
 *
 * Uso en cada dashboard:
 *   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
 *   <script src="auth.js"></script>
 *   <script>requireAuth('bareno');</script>
 *
 * El segundo argumento es el PROJECT_ID que debe coincidir con
 * el campo `project` del usuario en la tabla `app_users` de Supabase.
 */

// ════════════════════════════════════════════════════
// CONFIG — Kronautomation Supabase
// ════════════════════════════════════════════════════
const SUPABASE_URL      = 'https://xfblbceaewcyeegjrylf.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_KZxKiCjJE_H1vTTRDIx5YQ_Y8p1X4sg';

// ════════════════════════════════════════════════════
// Cliente Supabase
// ════════════════════════════════════════════════════
const _sb = window.supabase?.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storage: window.localStorage,
  },
});

if (!_sb) {
  console.error('[auth] Supabase SDK not loaded. Did you include the CDN script?');
}

// ════════════════════════════════════════════════════
// API Pública
// ════════════════════════════════════════════════════

/**
 * Gating: llama esto al inicio del dashboard.
 * Si no hay sesión válida, redirige a /login.html
 * Si la sesión existe pero el usuario no pertenece al proyecto, también redirige.
 */
async function requireAuth(projectId) {
  if (!_sb) return;
  document.documentElement.style.visibility = 'hidden';

  try {
    const { data: { session } } = await _sb.auth.getSession();
    if (!session) {
      _redirectToLogin(projectId);
      return;
    }

    // Validar que el usuario pertenece al proyecto correcto
    const { data: row, error } = await _sb
      .from('app_users')
      .select('project, role')
      .eq('email', session.user.email)
      .eq('project', projectId)
      .maybeSingle();

    if (error || !row) {
      console.warn('[auth] usuario sin acceso al proyecto', projectId);
      await _sb.auth.signOut();
      _redirectToLogin(projectId, 'no_access');
      return;
    }

    // OK
    window.__KRON_USER__ = { ...session.user, project: row.project, role: row.role };
    document.documentElement.style.visibility = 'visible';
  } catch (e) {
    console.error('[auth] error', e);
    _redirectToLogin(projectId);
  }
}

/**
 * Login desde la pantalla de login.html
 */
async function signIn(email, password) {
  if (!_sb) throw new Error('Supabase no inicializado');
  const { data, error } = await _sb.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

/**
 * Logout — limpia sesión y manda al login
 */
async function signOut() {
  if (!_sb) return;
  await _sb.auth.signOut();
  const projectId = _detectProjectFromHost();
  _redirectToLogin(projectId);
}

/**
 * Helper para mostrar un botón de logout flotante en el dashboard.
 * Llamar después de requireAuth() si quieres que aparezca.
 */
function mountLogoutButton() {
  if (document.getElementById('kron-logout-btn')) return;
  const btn = document.createElement('button');
  btn.id = 'kron-logout-btn';
  btn.title = 'Cerrar sesión';
  btn.innerHTML = '⏻';
  btn.style.cssText = `
    position:fixed; bottom:calc(20px + env(safe-area-inset-bottom,0px)); right:20px;
    width:44px; height:44px; border-radius:14px; border:none; cursor:pointer;
    background:rgba(190,18,60,.14); color:#fb7185;
    font-size:18px; font-weight:700;
    border:1px solid rgba(190,18,60,.3);
    backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
    box-shadow:0 6px 20px rgba(0,0,0,.4);
    z-index:9999; transition:transform .15s;
  `;
  btn.onmouseenter = () => btn.style.transform = 'scale(1.06)';
  btn.onmouseleave = () => btn.style.transform = 'scale(1)';
  btn.onclick = signOut;
  document.body.appendChild(btn);
}

// ════════════════════════════════════════════════════
// Internos
// ════════════════════════════════════════════════════

function _redirectToLogin(projectId, reason) {
  const params = new URLSearchParams();
  if (projectId) params.set('p', projectId);
  if (reason)    params.set('e', reason);
  const qs = params.toString();
  window.location.replace('/login' + (qs ? '?' + qs : ''));
}

function _detectProjectFromHost() {
  // ej. bareno.kronautomation.co → "bareno"
  const host = window.location.hostname.split('.');
  if (host.length >= 3 && host[host.length-2] === 'kronautomation') {
    return host[0];
  }
  return null;
}

// expose
window.kronAuth = { requireAuth, signIn, signOut, mountLogoutButton };
window.requireAuth = requireAuth;
window.signIn = signIn;
window.signOut = signOut;
window.mountLogoutButton = mountLogoutButton;
