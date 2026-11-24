// Keep binder calls small even when a complete diagnostic journal spans megabytes.
const CHUNK_BYTES = 48 * 1024;
const MAX_BYTES = 24 * 1024 * 1024;

export function mobileFiles(bridge) {
  return {
    async saveFile(file, name) {
      if (file.size > MAX_BYTES) throw Error('This export exceeds the Android 24 MiB limit.');
      const token = bridge.beginExport(name, file.size);
      if (!token) throw Error('Finish the current file export and try again.');
      try {
        for (let start = 0; start < file.size; start += CHUNK_BYTES) {
          const bytes = new Uint8Array(await file.slice(start, start + CHUNK_BYTES).arrayBuffer());
          // A smaller stride keeps fromCharCode within the WebView argument limit.
          let binary = '';
          for (let pos = 0; pos < bytes.length; pos += 8192) {
            binary += String.fromCharCode(...bytes.subarray(pos, pos + 8192));
          }
          if (!bridge.appendExport(token, btoa(binary))) throw Error('The file export was interrupted.');
        }
        if (!bridge.finishExport(token)) throw Error('Android could not open the save dialog.');
      } catch (error) {
        bridge.cancelExport(token);
        throw error;
      }
    },
    copyText(text) {
      if (text.length > 128 * 1024 || !bridge.copyText(text)) {
        throw Error('Use the selected text or export the diagnostics CSV.');
      }
    }
  };
}
