// The bench owns its render loop and virtual project. Unloading its document releases the GPU.
export function mount(container) {
  let frame;
  return {
    show() {
      if (frame) return;
      frame = document.createElement('iframe');
      frame.className = 'assembly-frame';
      frame.title = 'F450 assembly and wiring workbench';
      frame.src = new URL('./viewer.html', import.meta.url).href;
      container.replaceChildren(frame);
    },
    suspend() {
      // Flush a just-completed edit before the child document is detached.
      try { frame?.contentWindow?.dispatchEvent(new Event('areion-bench-leave')); } finally {
        frame?.remove();
        frame = undefined;
      }
    }
  };
}
