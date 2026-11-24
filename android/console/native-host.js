// Installed before the bundled console's ES modules. Browser builds do not load this adapter.
(() => {
  'use strict';
  const host = window.AreionAndroid;
  if (!host || typeof host.openSocket !== 'function') return;
  const sessions = new Map();
  let next = crypto.getRandomValues(new Uint32Array(1))[0] & 0x3fffffff;

  class AreionNativeSocket extends EventTarget {
    static receive(id, type, message) {
      const socket = sessions.get(id);
      if (!socket) return;
      if (type === 'open' && socket.readyState === WebSocket.CONNECTING) {
        socket.readyState = WebSocket.OPEN;
        socket.protocol = message;
        socket.emit('open', new Event('open'));
      } else if (type === 'message' && socket.readyState === WebSocket.OPEN) {
        const decoded = atob(message);
        const bytes = Uint8Array.from(decoded, char => char.charCodeAt(0));
        socket.emit('message', new MessageEvent('message', {data: bytes.buffer}));
      } else if (type === 'close' || type === 'error') {
        sessions.delete(id);
        socket.readyState = WebSocket.CLOSED;
        if (type === 'error') socket.emit('error', new Event('error'));
        socket.emit('close', new CloseEvent('close', {
          code:type === 'error' ? 1006 : Number(message) || 1000, wasClean:type === 'close'
        }));
      }
    }

    constructor(url, protocol) {
      super();
      if (protocol !== 'areion-link-v2') throw Error('Unsupported kit protocol.');
      this.id = next = (next % 0x7ffffffe) + 1;
      this.readyState = WebSocket.CONNECTING;
      this.protocol = '';
      this.binaryType = 'arraybuffer';
      sessions.set(this.id, this);
      const error = host.openSocket(this.id, url);
      if (error) {
        sessions.delete(this.id);
        this.readyState = WebSocket.CLOSED;
        throw Error(error);
      }
    }

    emit(type, event) {
      this['on' + type]?.(event);
      this.dispatchEvent(event);
    }
    get bufferedAmount() { return this.readyState === WebSocket.OPEN ? host.queuedSocket(this.id) : 0; }
    send(data) {
      if (!(data instanceof Uint8Array) || data.length > 1557 || this.readyState !== WebSocket.OPEN)
        throw Error('Kit socket is closed.');
      const encoded = btoa(String.fromCharCode(...data));
      if (!host.sendSocket(this.id, encoded)) throw Error('Kit Wi-Fi write refused.');
    }
    close() {
      if (this.readyState >= WebSocket.CLOSING) return;
      this.readyState = WebSocket.CLOSING;
      host.closeSocket(this.id);
    }
  }
  window.AreionNativeSocket = AreionNativeSocket;
})();
