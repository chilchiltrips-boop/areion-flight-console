// Install only for this example's directory on the embedding website.
const status = document.getElementById('host-status');
const workerUrl = new URL('./host-worker.js', location.href).href;
function ready() {
  if (navigator.serviceWorker.controller?.scriptURL === workerUrl) {
    status.textContent = 'Host page ready offline';
    return true;
  }
  return false;
}
async function enableOffline() {
  let cached = false;
  try {
    if (!window.isSecureContext || !navigator.serviceWorker) throw Error();
    navigator.serviceWorker.addEventListener('controllerchange', ready);
    cached = ready();
    if (!cached) status.textContent = 'Preparing host page…';
    const registration = await navigator.serviceWorker.register(workerUrl);
    function watch() {
      const installing = registration.installing;
      installing?.addEventListener('statechange', () => {
        if (installing.state === 'redundant' && !ready()) status.textContent = 'Host page needs internet to reopen';
      });
    }
    registration.addEventListener('updatefound', watch);
    watch();
    ready();
  } catch {
    if (!cached) status.textContent = 'Host page needs internet to reopen';
  }
}
void enableOffline();
