export const DEFAULT_RULES = {
  dema_cross_mode: 'both', require_supertrend: true, require_dema_bias: true, require_rsi: true, require_pivot_room: true,
};

const SWITCHES = [
  ['require_supertrend', 'Supertrend must agree'],
  ['require_dema_bias', 'Price on the right side of the 200 DEMA'],
  ['require_rsi', 'RSI zone and direction'],
  ['require_pivot_room', 'Room to the next pivot level'],
];

/** The strategy switches (same meaning as the CLI's --dema-cross and --no-* flags). */
export default function Rules({ value, onChange }) {
  const set = (k, v) => onChange({ ...value, [k]: v });
  return (
    <details className="fold">
      <summary>Strategy rules</summary>
      <div className="grid gap-3">
        <label className="field">
          <span>200 DEMA cross trigger</span>
          <select className="input" value={value.dema_cross_mode} onChange={(e) => set('dema_cross_mode', e.target.value)}>
            <option value="both">both: either line crossing counts, once both are on the new side</option>
            <option value="fast">fast: the 22 line crossing is enough</option>
            <option value="off">off: SMA 22/33 cross only</option>
          </select>
        </label>
        {SWITCHES.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2.5 text-sm">
            <input type="checkbox" checked={value[k]} onChange={(e) => set(k, e.target.checked)} className="h-4 w-4 accent-[var(--brand)]" />
            {label}
          </label>
        ))}
      </div>
    </details>
  );
}
