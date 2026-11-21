// Areion Link publishes each group in P-row, I-row, D-row order.
export const banks = ['rateRoll', 'ratePitch', 'rateYaw', 'angleRoll', 'anglePitch'];
export const terms = ['p', 'i', 'd'];
export const limits = {p: 100, i: 500, d: 20};
export function validGains(values) {
  return terms.every(key => Number.isFinite(values?.[key]) && values[key] >= 0 && values[key] <= limits[key]);
}
export function unpackGains(rate, angle) {
  const result = {};
  for (const [group, names] of [[rate, banks.slice(0, 3)], [angle, banks.slice(3)]]) {
    if (!Array.isArray(group) || group.length !== names.length * 3) return null;
    for (const [axis, name] of names.entries()) {
      const values = Object.fromEntries(terms.map((term, i) => [term, group[i * names.length + axis]]));
      if (!validGains(values)) return null;
      result[name] = values;
    }
  }
  return result;
}
export function packGains(gains, group) {
  const names = group === 2 ? banks.slice(0, 3) : group === 3 ? banks.slice(3) : [];
  if (!names.length || !names.every(name => validGains(gains?.[name]))) return null;
  return terms.flatMap(term => names.map(name => gains[name][term]));
}
