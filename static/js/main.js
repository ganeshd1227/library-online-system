// Small shared behaviours used on every page.
document.addEventListener('DOMContentLoaded', function () {
    var hamburger = document.getElementById('hamburger');
    var sidebar = document.getElementById('sidebar');
    if (hamburger && sidebar) {
        hamburger.addEventListener('click', function () { sidebar.classList.toggle('open'); });
    }

    // Highlight the current page's nav link.
    document.querySelectorAll('.nav-link').forEach(function (link) {
        if (link.getAttribute('href') && location.pathname.startsWith(link.getAttribute('href')) && link.getAttribute('href') !== '/') {
            link.classList.add('active');
        }
    });

});

function getCsrfToken() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
}

// Browser (OS-level) notifications, with an in-app toast as the ALWAYS
// -shown fallback (so the feature degrades gracefully if permission is
// denied or the browser doesn't support the API at all).
function requestNotificationPermissionOnce() {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function notifyUser(title, body, toastType) {
    if (window.showToast) window.showToast(body, toastType || 'info');
    if ('Notification' in window && Notification.permission === 'granted') {
        try { new Notification(title, { body: body }); } catch (e) { /* ignore */ }
    }
}

// Notification delete: fade the row out, then submit (falls back to normal POST).
document.addEventListener('submit', function (e) {
    var form = e.target.closest('.notif-delete');
    if (!form) return;
    e.preventDefault();
    var row = form.closest('.notif-row');
    fetch(form.action, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) {
            if (!r.ok) throw new Error();
            if (row) { row.style.transition = 'opacity .25s'; row.style.opacity = '0'; setTimeout(function () { row.remove(); }, 250); }
            if (window.showToast) showToast('Notification deleted.', 'success');
        })
        .catch(function () { if (window.showToast) showToast('Could not delete notification.', 'error'); });
});


// ---------- Confirm dialog (replaces window.confirm; accessible <dialog> with focus trap) ----------
(function () {
    var dialog = null;
    function build() {
        dialog = document.createElement('dialog');
        dialog.className = 'confirm-dialog';
        dialog.setAttribute('aria-labelledby', 'confirm-title');
        dialog.innerHTML = '<form method="dialog"><h2 id="confirm-title">Please confirm</h2><p id="confirm-msg"></p>' +
            '<div class="confirm-actions"><button value="cancel" class="btn btn-ghost">Cancel</button>' +
            '<button value="ok" class="btn btn-danger" id="confirm-ok">Confirm</button></div></form>';
        document.body.appendChild(dialog);
    }
    function proceed(el) {
        el.dataset.confirmed = '1';
        if (el.tagName === 'FORM') el.submit();
        else if (el.tagName === 'A') window.location.href = el.href;
        else if (el.form && el.form.requestSubmit) el.form.requestSubmit(el);
        else el.click();
    }
    document.addEventListener('click', function (e) {
        var el = e.target.closest('[data-confirm]');
        if (!el) return;
        if (el.dataset.confirmed === '1') { delete el.dataset.confirmed; return; }
        e.preventDefault();
        var message = el.getAttribute('data-confirm');
        if (typeof HTMLDialogElement !== 'function') { if (window.confirm(message)) proceed(el); return; }
        if (!dialog) build();
        dialog.querySelector('#confirm-msg').textContent = message;
        dialog.returnValue = '';
        dialog.onclose = function () { if (dialog.returnValue === 'ok') proceed(el); };
        dialog.showModal();
        dialog.querySelector('#confirm-ok').focus();
    });
})();

// ---------- Notification dropdown (loads on open only; no polling) ----------
(function () {
    var toggle = document.getElementById('notif-toggle');
    var panel = document.getElementById('notif-panel');
    if (!toggle || !panel) return;
    var list = document.getElementById('notif-list');
    var loading = false, loadedAt = 0;
    function close() { panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); }
    function render(items) {
        list.textContent = '';
        if (!items.length) {
            var empty = document.createElement('li'); empty.className = 'notif-empty'; empty.textContent = "You're all caught up.";
            list.appendChild(empty); return;
        }
        items.forEach(function (n) {
            var li = document.createElement('li'); li.textContent = n.message; list.appendChild(li);
        });
    }
    function load() {
        if (loading || Date.now() - loadedAt < 15000) return;     // never duplicate/hammer the API
        loading = true;
        list.textContent = 'Loading…';
        fetch(toggle.dataset.feedUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function (d) { render(d.notifications || []); loadedAt = Date.now(); })
            .catch(function () { list.textContent = 'Could not load notifications.'; })
            .finally(function () { loading = false; });
    }
    toggle.addEventListener('click', function (e) {
        e.stopPropagation();
        if (panel.hidden) { panel.hidden = false; toggle.setAttribute('aria-expanded', 'true'); load(); } else close();
    });
    document.addEventListener('click', function (e) { if (!panel.hidden && !panel.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !panel.hidden) { close(); toggle.focus(); } });
})();

// ---------- Password show/hide + submit loading state (prevents double-submits) ----------
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-toggle-password]');
    if (!btn) return;
    var input = btn.parentElement.querySelector('input');
    var show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    btn.title = btn.getAttribute('aria-label');
    btn.querySelector('use').setAttribute('href', show ? '#i-eye-off' : '#i-eye');
});
document.addEventListener('submit', function (e) {
    var btn = e.target.querySelector && e.target.querySelector('[type=submit][data-loading]');
    if (!btn || e.defaultPrevented) return;
    var label = btn.getAttribute('data-loading');
    setTimeout(function () { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> ' + label; }, 0);
});
