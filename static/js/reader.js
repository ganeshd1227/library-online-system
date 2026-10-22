/**
 * Online reader behaviour, shared setup for both reading modes:
 *   - TEXT mode (#reader-content present): sanitized HTML + highlighting.
 *   - PDF mode (#pdf-canvas present): PDF.js page-by-page viewer.
 *
 * Reading timer — the server is the source of truth. This script only
 * displays a live-updating clock; the actual duration is calculated on
 * the backend from started_at/heartbeat/ended_at timestamps.
 *
 * Stop Reading always: ends the session on the server, then redirects
 * back to the Books page (never leaves the user on a dead reader page).
 */
(function () {
    var root = document.getElementById('reader-root');
    if (!root) return;

    var bookId = root.dataset.bookId;
    var booksUrl = root.dataset.booksUrl;
    var isPdf = root.dataset.isPdf === 'true';
    var resumePosition = parseInt(root.dataset.resumePosition || '0', 10);

    var timerEl = document.getElementById('reader-timer');
    var stopBtn = document.getElementById('stop-reading-btn');
    var csrfToken = getCsrfToken();

    var trackTime = root.dataset.trackTime === 'true';
    var pendingPosition = null;
    var sessionId = null;
    var elapsedSeconds = 0;
    var tickHandle = null;
    var heartbeatHandle = null;
    var stopped = false;

    requestNotificationPermissionOnce();

    // ---------------- Timer ----------------
    function formatTime(totalSeconds) {
        var h = Math.floor(totalSeconds / 3600);
        var m = Math.floor((totalSeconds % 3600) / 60);
        var s = Math.floor(totalSeconds % 60);
        return [h, m, s].map(function (n) { return String(n).padStart(2, '0'); }).join(':');
    }
    function updateDisplay() { if (timerEl) timerEl.textContent = formatTime(elapsedSeconds); }
    function startClock() { tickHandle = setInterval(function () { if (document.hidden) return; elapsedSeconds += 1; updateDisplay(); }, 1000); }
    function startHeartbeat() {
        heartbeatHandle = setInterval(function () {
            if (!sessionId || document.hidden) return;
            fetch('/reading/session/' + sessionId + '/heartbeat/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
                .catch(function () { /* next heartbeat retries */ });
        }, 20000);
    }

    function beginSession() {
        if (!trackTime) return;
        fetch('/reading/session/start/' + bookId + '/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                sessionId = data.session_id;
                if (!sessionId) return;
                elapsedSeconds = data.elapsed_seconds || 0;
                updateDisplay();
                startClock();
                startHeartbeat();
                notifyUser('Reading started', 'Your reading timer is running.', 'success');
                if (pendingPosition !== null) { savePosition(pendingPosition); pendingPosition = null; }
            })
            .catch(function () { showToast('Could not start the reading timer — your progress may not be saved.', 'error'); });
    }

    function savePosition(position) {
        if (!trackTime) return;
        if (!sessionId) { pendingPosition = position; return; }
        fetch('/reading/session/' + sessionId + '/position/', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ position: position }),
        }).catch(function () {});
    }

    function endSession(redirect) {
        if (stopped) return;
        stopped = true;
        clearInterval(tickHandle);
        clearInterval(heartbeatHandle);

        if (!sessionId) {
            if (redirect) window.location.href = booksUrl;
            return;
        }
        var url = '/reading/session/' + sessionId + '/end/';

        if (redirect) {
            // User explicitly clicked Stop Reading — wait for the server
            // to confirm, then navigate back to Books (never sendBeacon
            // here, since we need the response before redirecting).
            fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    var secs = data.duration_seconds || elapsedSeconds;
                    notifyUser('Reading stopped', 'Session saved: ' + formatTime(secs) + '.', 'info');
                })
                .catch(function () {})
                .finally(function () { window.location.href = booksUrl; });
        } else {
            // Page is unloading — use sendBeacon (fire-and-forget).
            var fd = new FormData();
            fd.append('csrfmiddlewaretoken', csrfToken);
            fd.append('auto', '1');
            if (navigator.sendBeacon) {
                navigator.sendBeacon(url, fd);
            } else {
                fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, keepalive: true });
            }
        }
    }

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden && sessionId && !stopped) {
            fetch('/reading/session/' + sessionId + '/heartbeat/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } }).catch(function () {});
        }
    });
    window.addEventListener('pagehide', function () { endSession(false); });
    window.addEventListener('beforeunload', function () { endSession(false); });
    if (stopBtn) {
        stopBtn.addEventListener('click', function () {
            stopBtn.disabled = true;
            stopBtn.innerHTML = stopBtn.dataset.compact ? '<span class="spinner"></span>' : '<span class="spinner"></span> Saving session…';
            endSession(true);
        });
    }

    beginSession();

    // ===================================================================
    // PDF MODE — PDF.js viewer: range-loaded, DPI-aware, fit/zoom modes
    // ===================================================================
    if (isPdf) initPdfReader();

    function initPdfReader() {
        var $ = function (id) { return document.getElementById(id); };
        var stage = $('pdf-stage'), canvas = $('pdf-canvas'), ctx = canvas.getContext('2d');
        var pageInput = $('pdf-page-num'), pageCountEl = $('pdf-page-count');
        var zoomLabel = $('pdf-zoom-label'), loadingEl = $('pdf-loading'), loadingText = $('pdf-loading-text');
        var errorEl = $('pdf-error'), errorMsg = $('pdf-error-msg');
        var toolbar = $('pdf-toolbar'), fab = $('pdf-show-controls'), viewer = $('pdf-viewer');

        var CSS_UNITS = 96 / 72;            // PDF.js "100%" = 96dpi CSS pixels
        var MIN_SCALE = 0.25, MAX_SCALE = 4, MAX_PIXELS = 16 * 1024 * 1024;
        var FITS = ['width', 'height', 'page', 'actual'];

        var prefs = loadPrefs();
        var fit = FITS.indexOf(prefs.fit) >= 0 ? prefs.fit : 'width';   // null while zoomed manually
        var controlsVisible = prefs.controls !== false;
        var scale = CSS_UNITS;
        var pdfDoc = null, loadingTask = null, activeTask = null;
        var pageNum = Math.max(1, resumePosition || 1);
        var renderToken = 0, rafId = 0, wantKeepScroll = true, saveTimer = null, lastSaved = 0, lastShown = 0;
        var watchdog = null, busyTimer = null, lowQuality = false, lastW = 0, lastH = 0;

        function loadPrefs() { try { return JSON.parse(localStorage.getItem('reader.prefs') || '{}') || {}; } catch (e) { return {}; } }
        function savePrefs() { try { localStorage.setItem('reader.prefs', JSON.stringify({ fit: FITS.indexOf(fit) >= 0 ? fit : prefs.fit, controls: controlsVisible })); } catch (e) { /* storage unavailable */ } }
        function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

        // ---------- status / errors ----------
        function showError(msg) {
            loadingEl.hidden = true; canvas.hidden = true;
            errorMsg.textContent = msg; errorEl.hidden = false;
        }
        function setLoading(on, text) {
            loadingEl.hidden = !on;
            if (text) loadingText.textContent = text;
        }

        // ---------- controls visibility ----------
        function layoutToolbar() {
            stage.style.paddingBottom = (controlsVisible ? toolbar.offsetHeight + 28 : 12) + 'px';
        }
        function setControls(visible) {
            controlsVisible = visible;
            viewer.classList.toggle('pdf-controls-hidden', !visible);
            toolbar.setAttribute('aria-hidden', String(!visible));
            fab.hidden = visible;
            if (!visible) fab.focus({ preventScroll: true }); else $('pdf-hide-controls').focus({ preventScroll: true });
            layoutToolbar(); savePrefs(); schedule(true);
        }

        // ---------- scale maths ----------
        function computeScale(page) {
            var base = page.getViewport({ scale: 1 }), cs = getComputedStyle(stage);
            var w = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
            var h = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
            if (w < 50 || h < 50) return;                       // layout not ready; keep previous scale
            if (fit === 'width') scale = w / base.width;
            else if (fit === 'height') scale = h / base.height;
            else if (fit === 'page') scale = Math.min(w / base.width, h / base.height);
            else if (fit === 'actual') scale = CSS_UNITS;
            scale = clamp(scale, MIN_SCALE, MAX_SCALE);
        }
        function updateUi() {
            zoomLabel.textContent = Math.round((scale / CSS_UNITS) * 100) + '%';
            document.querySelectorAll('#pdf-toolbar [data-fit]').forEach(function (b) {
                b.setAttribute('aria-pressed', String(b.dataset.fit === fit));
            });
        }

        // ---------- busy indicator + watchdog (a render that never finishes must not freeze the reader) ----------
        function setBusy(on) {
            clearTimeout(busyTimer);
            if (!on) { viewer.classList.remove('pdf-busy'); viewer.removeAttribute('aria-busy'); return; }
            busyTimer = setTimeout(function () { viewer.classList.add('pdf-busy'); viewer.setAttribute('aria-busy', 'true'); }, 250);
        }

        // ---------- rendering (one at a time; superseded renders are cancelled) ----------
        function schedule(keepScroll) {
            wantKeepScroll = wantKeepScroll && keepScroll;
            if (rafId || !pdfDoc) return;
            rafId = setTimeout(function () { rafId = 0; var k = wantKeepScroll; wantKeepScroll = true; render(k, false); }, 40);
        }
        function render(keepScroll, retried) {
            if (!pdfDoc) return;
            var token = ++renderToken, num = pageNum;
            var cx = 0.5, cy = 0;
            if (keepScroll && stage.scrollWidth > 0 && stage.scrollHeight > 0) {
                cx = (stage.scrollLeft + stage.clientWidth / 2) / stage.scrollWidth;
                cy = (stage.scrollTop + stage.clientHeight / 2) / stage.scrollHeight;
            }
            if (activeTask) { try { activeTask.cancel(); } catch (e) { /* already done */ } activeTask = null; }
            clearTimeout(watchdog); setBusy(true);

            pdfDoc.getPage(num).then(function (page) {
                if (token !== renderToken) return null;
                computeScale(page);
                var vp = page.getViewport({ scale: scale });
                var dpr = lowQuality ? 1 : Math.min(window.devicePixelRatio || 1, 3);
                if (vp.width * vp.height * dpr * dpr > MAX_PIXELS) dpr = Math.sqrt(MAX_PIXELS / (vp.width * vp.height));
                var buf = document.createElement('canvas');          // draw off-screen, then swap: no blank flash
                buf.width = Math.max(1, Math.floor(vp.width * dpr));
                buf.height = Math.max(1, Math.floor(vp.height * dpr));
                var task = page.render({
                    canvasContext: buf.getContext('2d'), viewport: vp,
                    transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
                });
                activeTask = task;
                watchdog = setTimeout(function () {            // 20s without finishing: cancel and retry lighter
                    if (token !== renderToken) return;
                    try { task.cancel(); } catch (e) { /* ignore */ }
                    if (!lowQuality) { lowQuality = true; showToast('Large page: switching to faster rendering.', 'info'); render(true, retried); }
                    else { setBusy(false); showError('This page took too long to render. Try a smaller zoom or reload the page.'); }
                }, 20000);
                return task.promise.then(function () {
                    if (token !== renderToken) { buf.width = buf.height = 0; return; }
                    clearTimeout(watchdog); setBusy(false);
                    activeTask = null;
                    canvas.width = buf.width; canvas.height = buf.height;
                    canvas.style.width = vp.width + 'px'; canvas.style.height = vp.height + 'px';
                    canvas.style.transform = '';
                    ctx.drawImage(buf, 0, 0);
                    buf.width = buf.height = 0;                       // release the off-screen bitmap
                    canvas.hidden = false; setLoading(false); errorEl.hidden = true;
                    page.cleanup();                                   // free parsed page resources

                    if (fit === 'width' && !retried && stage.scrollWidth - stage.clientWidth > 1) {
                        render(false, true);                          // a scrollbar appeared: refit once
                        return;
                    }
                    if (num !== lastShown) { stage.scrollTop = 0; stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2; lastShown = num; }
                    else if (keepScroll) {
                        stage.scrollLeft = cx * stage.scrollWidth - stage.clientWidth / 2;
                        stage.scrollTop = cy * stage.scrollHeight - stage.clientHeight / 2;
                    } else { stage.scrollTop = 0; stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2; }

                    lastW = stage.clientWidth; lastH = stage.clientHeight;
                    pageInput.value = num;
                    updateUi();
                    queueSave(num);
                    if (num < pdfDoc.numPages) pdfDoc.getPage(num + 1).catch(function () {});   // warm next page
                });
            }).catch(function (err) {
                if (err && err.name === 'RenderingCancelledException') return;
                if (token === renderToken) { clearTimeout(watchdog); setBusy(false); showError('Could not render this page.'); }
            });
        }
        function queueSave(num) {                       // only on real page changes, debounced
            if (num === lastSaved) return;
            clearTimeout(saveTimer);
            saveTimer = setTimeout(function () { lastSaved = num; savePosition(num); }, 350);
        }

        // ---------- navigation / zoom ----------
        function goTo(num) {
            if (!pdfDoc) return;
            num = clamp(parseInt(num, 10) || pageNum, 1, pdfDoc.numPages);
            pageInput.value = num;
            if (num === pageNum) return;
            pageNum = num;
            schedule(false);
        }
        function zoomBy(factor) {
            if (!pdfDoc) return;
            fit = null;
            scale = clamp(scale * factor, MIN_SCALE, MAX_SCALE);
            updateUi(); schedule(true);
        }
        function setFit(mode) { fit = mode; savePrefs(); updateUi(); schedule(false); }

        // ---------- wiring (each listener registered exactly once) ----------
        $('pdf-prev').addEventListener('click', function () { goTo(pageNum - 1); });
        $('pdf-next').addEventListener('click', function () { goTo(pageNum + 1); });
        $('pdf-zoom-in').addEventListener('click', function () { zoomBy(1.25); });
        $('pdf-zoom-out').addEventListener('click', function () { zoomBy(1 / 1.25); });
        document.querySelectorAll('#pdf-toolbar [data-fit]').forEach(function (b) {
            b.addEventListener('click', function () { setFit(b.dataset.fit); });
        });
        $('pdf-hide-controls').addEventListener('click', function () { setControls(false); });
        fab.addEventListener('click', function () { setControls(true); });
        pageInput.addEventListener('focus', function () { pageInput.select(); });
        pageInput.addEventListener('change', function () { goTo(pageInput.value); });
        pageInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); goTo(pageInput.value); pageInput.blur(); stage.focus({ preventScroll: true }); } });

        document.addEventListener('keydown', function (e) {
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            var t = e.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) { if (e.key === 'Escape') t.blur(); return; }
            var canPanX = stage.scrollWidth - stage.clientWidth > 1, k = e.key;
            if (k === 'PageDown' || (k === 'ArrowRight' && !canPanX)) goTo(pageNum + 1);
            else if (k === 'PageUp' || (k === 'ArrowLeft' && !canPanX)) goTo(pageNum - 1);
            else if (k === 'Home') goTo(1);
            else if (k === 'End' && pdfDoc) goTo(pdfDoc.numPages);
            else if (k === '+' || k === '=') zoomBy(1.25);
            else if (k === '-' || k === '_') zoomBy(1 / 1.25);
            else if (k === '1') setFit('actual');
            else if (k === 'w' || k === 'W') setFit('width');
            else if (k === 'h' || k === 'H') setFit('height');
            else if (k === 'p' || k === 'P') setFit('page');
            else if (k === 'c' || k === 'C') setControls(!controlsVisible);
            else if (k === 'f' || k === 'F') $('toggle-fullscreen').click();
            else return;
            e.preventDefault();
        });

        // Ctrl/⌘ + wheel zooms the PDF instead of the whole browser page
        stage.addEventListener('wheel', function (e) {
            if (!e.ctrlKey) return;
            e.preventDefault();
            zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1);
        }, { passive: false });

        // Mouse drag-to-pan and two-finger pinch (touch scrolling stays native)
        var pointers = {}, pinch = null, drag = null;
        function pinchDistance() {
            var p = Object.keys(pointers).map(function (id) { return pointers[id]; });
            return Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) || 1;
        }
        stage.addEventListener('pointerdown', function (e) {
            pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
            if (Object.keys(pointers).length === 2) { pinch = { d: pinchDistance(), ratio: 1 }; drag = null; try { stage.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ } }
            else if (e.pointerType === 'mouse' && e.button === 0 && (stage.scrollWidth > stage.clientWidth + 1 || stage.scrollHeight > stage.clientHeight + 1)) {
                drag = { x: e.clientX, y: e.clientY, l: stage.scrollLeft, t: stage.scrollTop };
                stage.classList.add('panning');
                try { stage.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
            }
        });
        stage.addEventListener('pointermove', function (e) {
            if (!pointers[e.pointerId]) return;
            pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
            if (pinch && Object.keys(pointers).length === 2) {
                pinch.ratio = clamp(pinchDistance() / pinch.d, MIN_SCALE / scale, MAX_SCALE / scale);
                canvas.style.transform = 'scale(' + pinch.ratio + ')';       // instant visual feedback; real render on release
            } else if (drag) {
                stage.scrollLeft = drag.l - (e.clientX - drag.x);
                stage.scrollTop = drag.t - (e.clientY - drag.y);
            }
        });
        function endPointer(e) {
            delete pointers[e.pointerId];
            if (pinch && Object.keys(pointers).length < 2) {
                var r = pinch.ratio; pinch = null; canvas.style.transform = '';
                if (Math.abs(r - 1) > 0.03) zoomBy(r);
            }
            if (!Object.keys(pointers).length) { drag = null; stage.classList.remove('panning'); }
        }
        stage.addEventListener('pointerup', endPointer);
        stage.addEventListener('pointercancel', endPointer);
        stage.addEventListener('lostpointercapture', endPointer);
        window.addEventListener('blur', function () { pointers = {}; pinch = null; drag = null; canvas.style.transform = ''; stage.classList.remove('panning'); });

        // Resize / orientation / fullscreen changes: refit the SAME page (progress is untouched)
        var resizeTimer = null;
        function refit() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                layoutToolbar();
                var w = stage.clientWidth, h = stage.clientHeight;
                if (Math.abs(h - lastH) < 2 && Math.abs(w - lastW) <= 20) return;   // only a scrollbar appeared/vanished
                if (fit) schedule(true);
            }, 120);
        }
        if (window.ResizeObserver) new ResizeObserver(refit).observe(stage);
        window.addEventListener('resize', refit);
        window.addEventListener('orientationchange', refit);
        document.addEventListener('fullscreenchange', refit);
        document.addEventListener('webkitfullscreenchange', refit);

        // ---------- loading ----------
        function load() {
            if (loadingTask) return;                                   // never start two loads
            errorEl.hidden = true; setLoading(true, 'Opening book…');
            pdfjsLib.GlobalWorkerOptions.workerSrc = root.dataset.pdfWorkerSrc;
            var task = loadingTask = pdfjsLib.getDocument({
                url: root.dataset.pdfUrl, withCredentials: true,
                rangeChunkSize: 256 * 1024, disableAutoFetch: true,    // fetch only the byte ranges actually needed
                isEvalSupported: false,
            });
            var timedOut = false;
            var timer = setTimeout(function () {                       // a stalled network must not leave an endless spinner
                if (pdfDoc || loadingTask !== task) return;
                timedOut = true; loadingTask = null;
                try { task.destroy(); } catch (e) { /* ignore */ }
                showError('Loading is taking too long. Check your connection and try again.');
            }, 30000);
            task.onProgress = function (p) {
                if (p.total) loadingText.textContent = 'Opening book… ' + Math.min(99, Math.round((p.loaded / p.total) * 100)) + '%';
            };
            task.promise.then(function (doc) {
                clearTimeout(timer);
                pdfDoc = doc;
                pageCountEl.textContent = doc.numPages;
                pageNum = clamp(pageNum, 1, doc.numPages);
                pageInput.value = pageNum;
                render(false, false);
                stage.focus({ preventScroll: true });
            }).catch(function (err) {
                clearTimeout(timer);
                if (timedOut) return;
                if (loadingTask === task) loadingTask = null;
                var name = err && err.name;
                showError(name === 'MissingPDFException' ? 'This PDF file could not be found.'
                    : name === 'InvalidPDFException' ? 'This file is not a valid PDF.'
                    : name === 'PasswordException' ? 'This PDF is password-protected.'
                    : 'Could not load the PDF. Check your connection and try again.');
            });
        }
        $('pdf-retry').addEventListener('click', function () {
            if (typeof pdfjsLib === 'undefined') { window.location.reload(); return; }
            if (loadingTask) { try { loadingTask.destroy(); } catch (e) { /* ignore */ } loadingTask = null; }
            load();
        });
        window.addEventListener('pagehide', function () {          // free worker + memory
            try { if (pdfDoc) pdfDoc.destroy(); else if (loadingTask) loadingTask.destroy(); } catch (e) { /* ignore */ }
        });

        viewer.classList.toggle('pdf-controls-hidden', !controlsVisible);
        fab.hidden = controlsVisible;
        layoutToolbar(); updateUi();
        if (typeof pdfjsLib === 'undefined') {
            showError('The PDF viewer library could not be loaded. Check your connection, or open the file directly.');
        } else {
            load();
        }
    }

    // ===================================================================
    // TEXT MODE — highlighting (only runs when the text reader is present)
    // ===================================================================
    var contentEl = document.getElementById('reader-content');
    if (!contentEl) return;

    var existingHighlights = [];
    try { existingHighlights = JSON.parse(document.getElementById('highlights-data').textContent); } catch (e) { existingHighlights = []; }

    function getTextNodesIn(node) {
        var textNodes = [];
        var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
        var n;
        while ((n = walker.nextNode())) textNodes.push(n);
        return textNodes;
    }

    function getCaretOffset(container, targetNode, targetOffset) {
        var offset = 0;
        var nodes = getTextNodesIn(container);
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i] === targetNode) return offset + targetOffset;
            offset += nodes[i].textContent.length;
        }
        return offset;
    }

    function wrapRangeAsHighlight(container, start, end, color, highlightId) {
        var nodes = getTextNodesIn(container);
        var runningOffset = 0;
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            var nodeLen = node.textContent.length;
            var nodeStart = runningOffset;
            var nodeEnd = runningOffset + nodeLen;
            runningOffset = nodeEnd;

            var overlapStart = Math.max(start, nodeStart);
            var overlapEnd = Math.min(end, nodeEnd);
            if (overlapStart >= overlapEnd) continue;
            if (node.parentElement && node.parentElement.tagName === 'MARK') continue;

            var localStart = overlapStart - nodeStart;
            var localEnd = overlapEnd - nodeStart;

            var range = document.createRange();
            range.setStart(node, localStart);
            range.setEnd(node, localEnd);

            var mark = document.createElement('mark');
            mark.className = 'highlight-' + color;
            mark.dataset.highlightId = highlightId;
            try { range.surroundContents(mark); } catch (e) { /* skip nodes that can't be wrapped cleanly */ }
        }
    }

    existingHighlights.forEach(function (h) { wrapRangeAsHighlight(contentEl, h.start, h.end, h.color, h.id); });

    var popup = document.createElement('div');
    popup.className = 'highlight-popup';
    popup.style.display = 'none';
    popup.innerHTML =
        '<button data-color="yellow" title="Yellow"><span class="swatch" style="background:#fff2a8"></span></button>' +
        '<button data-color="green" title="Green"><span class="swatch" style="background:#c9f0d1"></span></button>' +
        '<button data-color="blue" title="Blue"><span class="swatch" style="background:#c6e2fb"></span></button>' +
        '<button data-color="pink" title="Pink"><span class="swatch" style="background:#fbd4e6"></span></button>';
    document.body.appendChild(popup);

    var deletePopup = document.createElement('div');
    deletePopup.className = 'highlight-popup';
    deletePopup.style.display = 'none';
    deletePopup.innerHTML = '<button id="delete-highlight-btn">Delete highlight</button>';
    document.body.appendChild(deletePopup);
    var activeMarkForDeletion = null;

    document.addEventListener('mouseup', function (e) {
        if (popup.contains(e.target)) return;
        var selection = window.getSelection();
        if (!selection || selection.isCollapsed || !contentEl.contains(selection.anchorNode)) { popup.style.display = 'none'; return; }
        var text = selection.toString().trim();
        if (!text) { popup.style.display = 'none'; return; }

        var range = selection.getRangeAt(0);
        var rect = range.getBoundingClientRect();
        popup.style.display = 'flex';
        popup.style.top = (window.scrollY + rect.top - 42) + 'px';
        popup.style.left = (window.scrollX + rect.left) + 'px';
        popup.dataset.start = getCaretOffset(contentEl, range.startContainer, range.startOffset);
        popup.dataset.end = getCaretOffset(contentEl, range.endContainer, range.endOffset);
        popup.dataset.text = text;
    });

    popup.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-color]');
        if (!btn) return;
        var color = btn.dataset.color;
        var start = parseInt(popup.dataset.start, 10);
        var end = parseInt(popup.dataset.end, 10);
        var text = popup.dataset.text;

        fetch('/reading/highlights/' + bookId + '/create/', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ text: text, start: start, end: end, color: color }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.id) {
                    window.getSelection().removeAllRanges();
                    wrapRangeAsHighlight(contentEl, data.start, data.end, data.color, data.id);
                    showToast('Highlight saved.', 'success');
                }
            });
        popup.style.display = 'none';
    });

    contentEl.addEventListener('click', function (e) {
        var mark = e.target.closest('mark');
        if (!mark) { deletePopup.style.display = 'none'; return; }
        activeMarkForDeletion = mark;
        var rect = mark.getBoundingClientRect();
        deletePopup.style.display = 'flex';
        deletePopup.style.top = (window.scrollY + rect.top - 42) + 'px';
        deletePopup.style.left = (window.scrollX + rect.left) + 'px';
    });

    deletePopup.addEventListener('click', function (e) {
        if (!e.target.closest('#delete-highlight-btn') || !activeMarkForDeletion) return;
        var highlightId = activeMarkForDeletion.dataset.highlightId;
        fetch('/reading/highlights/' + highlightId + '/delete/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
            .then(function (r) { return r.json(); })
            .then(function () {
                var parent = activeMarkForDeletion.parentNode;
                while (activeMarkForDeletion.firstChild) parent.insertBefore(activeMarkForDeletion.firstChild, activeMarkForDeletion);
                parent.removeChild(activeMarkForDeletion);
                parent.normalize();
                deletePopup.style.display = 'none';
                showToast('Highlight removed.', 'info');
            });
    });

    document.addEventListener('click', function (e) {
        if (!popup.contains(e.target) && !e.target.closest('mark')) popup.style.display = 'none';
        if (!deletePopup.contains(e.target) && !e.target.closest('mark')) deletePopup.style.display = 'none';
    });

    // ---------------- Copy-protection (UI-level only, not real DRM) ----------------
    contentEl.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    contentEl.addEventListener('copy', function (e) { e.preventDefault(); });
    contentEl.addEventListener('keydown', function (e) {
        var key = e.key.toLowerCase();
        if ((e.ctrlKey || e.metaKey) && (key === 'c' || key === 'a')) e.preventDefault();
    });

    var darkToggle = document.getElementById('toggle-dark-mode');
    if (darkToggle) darkToggle.addEventListener('click', function () { contentEl.classList.toggle('dark-reader'); });
})();

// ---------------- Fullscreen (shared by both reader modes) ----------------
document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('toggle-fullscreen');
    var wrap = document.querySelector('.reader-wrap');
    if (!btn || !wrap) return;
    var icon = btn.querySelector('use');
    function isFs() { return !!(document.fullscreenElement || document.webkitFullscreenElement) || wrap.classList.contains('reader-immersive'); }
    function sync() {
        var on = isFs();
        btn.setAttribute('aria-pressed', String(on));
        if (icon) icon.setAttribute('href', on ? '#i-minimize' : '#i-maximize');
        var label = on ? 'Exit full screen (F)' : 'Full screen (F)';
        btn.title = label; btn.setAttribute('aria-label', label);
    }
    document.addEventListener('fullscreenchange', sync);
    document.addEventListener('webkitfullscreenchange', sync);
    btn.addEventListener('click', function () {
        if (document.fullscreenElement || document.webkitFullscreenElement) {
            Promise.resolve((document.exitFullscreen || document.webkitExitFullscreen).call(document)).catch(function () {});
        } else if (wrap.classList.contains('reader-immersive')) {
            wrap.classList.remove('reader-immersive'); sync();
        } else {
            var request = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
            if (!request) {                       // e.g. iPhone Safari: fall back to an edge-to-edge layout
                wrap.classList.add('reader-immersive'); sync(); return;
            }
            Promise.resolve(request.call(wrap)).catch(function () { wrap.classList.add('reader-immersive'); sync(); });
        }
    });
    sync();
});
