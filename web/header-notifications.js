const ACKNOWLEDGED_UPDATE = 'areion.console.read-update.v1';
const captions = {
  preparing: 'Preparing offline files',
  ready: 'Offline ready',
  failed: 'Offline setup incomplete',
  unavailable: 'Offline storage unavailable',
  update: 'Console update ready'
};

export function mountNotifications(root, {release, storage, retry}) {
  root.innerHTML = `
    <button type="button" class="bell-button" aria-label="Notifications" title="Notifications"
      aria-haspopup="dialog" aria-expanded="false" aria-controls="console-notifications">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 6-2 7-2 9h16c0-2-2-3-2-9ZM10 20a2.2 2.2 0 0 0 4 0"/>
      </svg><i class="unread-dot" hidden></i>
    </button>
    <span class="bell-announcement" role="status"></span>
    <section id="console-notifications" class="notification-panel" role="dialog" aria-labelledby="notification-title" hidden>
      <div class="notification-heading"><h2 id="notification-title">Notifications</h2>
        <button type="button" class="dismiss-notifications" aria-label="Close notifications">×</button></div>
      <div class="notification-entry"><strong id="offline-state">Preparing offline files</strong>
        <p id="offline-detail"></p><button type="button" id="offline-retry" hidden>Retry offline setup</button></div>
      <div id="connection-notice" class="notification-entry" hidden><strong>Kit connection</strong><p id="hardware-hint"></p></div>
      <a id="open-console" target="_blank" rel="noopener" hidden>Open console in a tab</a>
    </section>`;
  const doc = root.ownerDocument, win = doc.defaultView;
  const find = selector => root.querySelector(selector);
  const bell = find('.bell-button'), panel = find('.notification-panel'), dot = find('.unread-dot');
  const close = find('.dismiss-notifications'), state = find('#offline-state'), detail = find('#offline-detail');
  const retryButton = find('#offline-retry'), connection = find('#connection-notice'), hint = find('#hardware-hint');
  const standalone = find('#open-console'), announcement = find('.bell-announcement');
  const active = new Map(), unread = new Set();
  let updateKey = '', readUpdate = '';
  try { readUpdate = storage?.getItem(ACKNOWLEDGED_UPDATE) || ''; } catch {}

  function refreshBell() {
    const count = unread.size;
    dot.hidden = !count;
    const label = count ? 'Notifications · ' + count + ' unread' : 'Notifications';
    bell.title = label;
    bell.setAttribute('aria-label', label);
    announcement.textContent = count ? count + ' unread notification' + (count === 1 ? '' : 's') : '';
  }

  function markRead() {
    if (updateKey && readUpdate !== updateKey) {
      readUpdate = updateKey;
      try { storage?.setItem(ACKNOWLEDGED_UPDATE, readUpdate); } catch {}
    }
    unread.clear();
    refreshBell();
  }

  function setAttention(source, key) {
    if (active.get(source) === key) return;
    active.set(source, key);
    if (key && panel.hidden && !(source === 'offline' && updateKey && readUpdate === updateKey)) {
      unread.add(source);
    } else {
      unread.delete(source);
    }
    if (panel.hidden) refreshBell(); else markRead();
  }

  function setOpen(open, restoreFocus = false) {
    if (panel.hidden === !open) return;
    panel.hidden = !open;
    bell.setAttribute('aria-expanded', String(open));
    if (open) { markRead(); close.focus({preventScroll:true}); }
    else if (restoreFocus) bell.focus({preventScroll:true});
  }
  bell.addEventListener('click', () => setOpen(panel.hidden));
  close.addEventListener('click', () => setOpen(false, true));
  retryButton.addEventListener('click', retry);
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); setOpen(false, true); }
  });
  root.addEventListener('focusout', event => {
    if (event.relatedTarget && !root.contains(event.relatedTarget)) setOpen(false);
  });
  const outside = event => { if (!root.contains(event.target)) setOpen(false); };
  const acknowledgeOtherTab = event => {
    if (event.key !== ACKNOWLEDGED_UPDATE) return;
    readUpdate = event.newValue || '';
    if (updateKey && readUpdate === updateKey && unread.delete('offline')) refreshBell();
  };
  doc.addEventListener('pointerdown', outside);
  win.addEventListener('storage', acknowledgeOtherTab);
  return {
    setOffline(value) {
      state.textContent = captions[value.state];
      state.dataset.state = value.state;
      detail.textContent = value.detail;
      retryButton.hidden = value.state !== 'failed';
      updateKey = value.state === 'update' ? release + '/' + value.state : '';
      const attention = ['update', 'failed', 'unavailable'].includes(value.state);
      setAttention('offline', attention ? value.state + '/' + value.detail : '');
    },
    setConnection(message, attention, openInTab) {
      if (hint.textContent !== message) hint.textContent = message;
      if (connection.hidden !== !message) connection.hidden = !message;
      if (standalone.hidden !== !openInTab) standalone.hidden = !openInTab;
      if (openInTab && standalone.href !== win.location.href) standalone.href = win.location.href;
      setAttention('connection', attention ? message : '');
    },
    destroy() {
      doc.removeEventListener('pointerdown', outside);
      win.removeEventListener('storage', acknowledgeOtherTab);
    }
  };
}
