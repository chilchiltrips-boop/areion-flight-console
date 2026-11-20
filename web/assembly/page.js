// The bench owns its render loop and virtual project. Unloading its document releases the GPU.
export function mount(container) {
  let frame;
  const layout = document.createElement('link');
  layout.rel = 'stylesheet';
  layout.href = new URL('./host.css', import.meta.url).href;
  return {
    show() {
      if (frame) return;
      frame = document.createElement('iframe');
      frame.className = 'assembly-frame';
      frame.title = 'F450 assembly and wiring workbench';
      frame.src = new URL('./viewer.html', import.meta.url).href;
      container.replaceChildren(layout, frame);
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
