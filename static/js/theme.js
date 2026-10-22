// Dark/light mode: localStorage is the fast, always-available source of
// truth for THIS browser (applied inline in <head> before first paint —
// see base.html). We also mirror the choice to the user's account (if
// logged in) so it follows them to a different browser/device too.
(function () {
    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        var meta = document.querySelector('#theme-toggle');
        if (meta) meta.setAttribute('aria-pressed', theme === 'dark');
    }

    function getCookie(name) {
        var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? match[2] : '';
    }

    document.addEventListener('DOMContentLoaded', function () {
        var saved = localStorage.getItem('lms-theme');
        var body = document.body;
        var serverPref = body ? body.dataset.userTheme : '';

        if (!saved && serverPref) {
            saved = serverPref.toLowerCase();
            localStorage.setItem('lms-theme', saved);
        }
        if (!saved) {
            saved = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        applyTheme(saved);

        var toggle = document.getElementById('theme-toggle');
        if (!toggle) return;
        toggle.addEventListener('click', function () {
            var current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
            var next = current === 'dark' ? 'light' : 'dark';
            applyTheme(next);
            localStorage.setItem('lms-theme', next);

            // Best-effort sync to the account; failure here doesn't affect
            // the (already-applied) local preference.
            if (body && body.dataset.userTheme !== undefined && body.dataset.userTheme !== '') {
                fetch('/theme/set/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                    body: JSON.stringify({ theme: next }),
                }).catch(function () { /* local preference still applied */ });
            }
        });
    });
})();
