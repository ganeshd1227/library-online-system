// Toast notifications (fixed-position, never shift page layout).
// Django flash messages are rendered as hidden spans and shown as toasts.
window.showToast = function (message, type) {
    type = type === 'warning' ? 'info' : (type === 'danger' ? 'error' : (type || 'info'));
    var container = document.getElementById('toast-container');
    if (!container) return;
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.textContent = message;
    container.appendChild(toast);
    function dismiss() {
        toast.classList.add('toast-fade-out');
        setTimeout(function () { toast.remove(); }, 200);
    }
    toast.addEventListener('click', dismiss);
    setTimeout(dismiss, type === 'error' ? 6000 : 4000);
};
document.addEventListener('DOMContentLoaded', function () {
    var box = document.getElementById('django-messages');
    if (!box) return;
    box.querySelectorAll('span').forEach(function (el) {
        var tag = (el.dataset.type || 'info').split(' ').pop();
        window.showToast(el.textContent, tag);
    });
    box.remove();
});
