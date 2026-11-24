const UPDATE_MESSAGE = 'Close the open console tabs and reopen this page online to finish the update.';
const WORKER = new URL('./offline-worker.js', import.meta.url).href;

export function askWorker(controller, core, repair) {
  return new Promise((resolve, reject) => {
    const {port1, port2} = new MessageChannel();
    const finish = () => { clearTimeout(timer); port1.close(); };
    const timer = setTimeout(() => { finish(); reject(Error('No offline status reply')); }, repair ? 60000 : 5000);
    port1.onmessage = event => { finish(); resolve(event.data); };
    try { controller.postMessage({type:'AREION_OFFLINE_CHECK', core, repair}, [port2]); }
    catch (error) { finish(); port2.close(); reject(error); }
  });
}

export function monitorOffline({workers, core, update, workerURL = WORKER, ask = askWorker}) {
  let serial = 0, attempt = 0, deadline, registration;
  const watched = new WeakSet();
  const set = (state, detail) => {
    if (state !== 'preparing') clearTimeout(deadline);
    update({state, detail});
  };
  // A complete cache in the old controller cannot dismiss a waiting release.
  function reportWaiting() {
    const waiting = registration?.waiting;
    if (!waiting || (waiting.state && waiting.state !== 'installed')) return false;
    set('update', UPDATE_MESSAGE);
    return true;
  }
  const fail = () => {
    if (!reportWaiting()) set('failed', 'Reconnect to the internet and retry offline setup.');
  };
  const ourController = () => workers?.controller?.scriptURL === workerURL ? workers.controller : null;

  async function check(repair = false) {
    const worker = ourController();
    if (!worker) return;
    const revision = ++serial;
    try {
      const result = await ask(worker, core, repair);
      if (revision !== serial || worker !== ourController()) return;
      if (reportWaiting()) return;
      if (result?.error) return fail();
      if (result?.core !== core) {
        set('update', UPDATE_MESSAGE);
      } else if (Number.isInteger(result.total) && result.total > 0 && result.cached === result.total) {
        set('ready', result.total + ' console files available offline in this window.');
      } else {
        set('failed', 'Some console files are missing. Retry while online.');
      }
    } catch {
      if (revision === serial && worker === ourController()) fail();
    }
  }

  function watch(reg) {
    if (watched.has(reg)) return;
    watched.add(reg);
    const follow = worker => {
      if (!worker || watched.has(worker)) return;
      watched.add(worker);
      worker.addEventListener('statechange', () => {
        if (registration !== reg || reportWaiting()) return;
        if (worker.state === 'installed' && reg.active && worker !== reg.active) set('update', UPDATE_MESSAGE);
        if (worker.state === 'activated') void check();
        if (worker.state === 'redundant' && !reg.installing) {
          if (ourController()) void check(); else fail();
        }
      });
    };
    reg.addEventListener('updatefound', () => follow(reg.installing));
    follow(reg.installing);
    follow(reg.waiting);
  }

  async function prepare(repair = false) {
    if (!workers || !core || core.startsWith('__')) {
      set('unavailable', 'Offline storage needs the published console on HTTPS and browser storage access.');
      return;
    }
    const revision = ++attempt;
    clearTimeout(deadline);
    set('preparing', 'Keep this window online while it prepares the console.');
    deadline = setTimeout(fail, 90000);
    if (ourController()) void check(repair);
    try {
      const reg = await workers.register(workerURL);
      if (revision !== attempt) return;
      registration = reg;
      watch(reg);
      reportWaiting();
      if (repair) await reg.update();
    } catch (error) {
      if (revision !== attempt || ourController()) return;
      if (error.name === 'SecurityError' || error.name === 'NotAllowedError') {
        set('unavailable', 'This browser or host blocks offline storage. Open the console in a tab while online.');
      } else fail();
    }
  }
  workers?.addEventListener('controllerchange', () => {
    ++serial;
    if (ourController()) void check(); else fail();
  });
  void prepare();
  return () => prepare(true);
}
