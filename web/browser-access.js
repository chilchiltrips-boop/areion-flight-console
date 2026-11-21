// Feature presence alone cannot tell whether an embedding platform delegated it.
function permitted(doc, names) {
  const policy = doc.permissionsPolicy || doc.featurePolicy;
  if (!policy?.features || !policy.allowsFeature) return true;
  try {
    const known = policy.features();
    const supported = names.find(name => known.includes(name));
    return !supported || policy.allowsFeature(supported);
  } catch { return true; }
}

export function browserAccess(win) {
  const embedded = win.self !== win.top;
  const insecure = !win.isSecureContext ? 'Open the console and its host over HTTPS.' :
    win.origin === 'null' ? 'The host must allow scripts and a same-origin sandbox identity.' : '';
  let serial = null, workers = null;
  try { if (!insecure) serial = win.navigator.serial; } catch {}
  try { if (!insecure) workers = win.navigator.serviceWorker; } catch {}
  const serialAllowed = permitted(win.document, ['serial']);
  const apAllowed = permitted(win.document, ['local-network', 'local-network-access']);
  const usbIssue = insecure || (!serialAllowed ? 'The host must allow serial for this console.' :
    !serial?.requestPort ? 'Use desktop Chrome or Edge with Web Serial.' : '');
  const apIssue = insecure || (!apAllowed ? 'The host must allow local-network access for this console.' :
    !win.WebSocket ? 'This browser does not provide WebSocket.' : '');
  return {embedded, serial:usbIssue ? null : serial, workers, usbIssue, apIssue};
}
