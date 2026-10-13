export default function Spark({ points, color = '#14b8a6' }) {
    const vals = points.filter((p) => p != null && !Number.isNaN(Number(p))).map(Number);
    if (vals.length < 2) {
        return <div className="h-24 muted text-xs flex items-center">{vals.length ? vals[0] : '—'}</div>;
    }
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const w = 320;
    const h = 96;
    const d = vals
        .map((v, i) => {
            const x = (i / (vals.length - 1)) * w;
            const y = h - ((v - min) / span) * (h - 8) - 4;
            return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');
    return (
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24">
            <path d={d} fill="none" stroke={color} strokeWidth="2" />
        </svg>
    );
}
