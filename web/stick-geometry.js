// Each RC axis has independent travel, including at the corners of the gimbal.
export function stickPoint(rect, clientX, clientY, travel) {
  const radius = Math.max(1, Math.min(rect.width, rect.height) * travel);
  const axis = value => Math.max(-1, Math.min(1, value / radius));
  return {x:axis(clientX - rect.left - rect.width / 2), y:axis(rect.top + rect.height / 2 - clientY)};
}
export function pulseForAxis(value) {
  return Math.round(1500 + 500 * Math.max(-1, Math.min(1, value)));
}
