export default function Spark({ points, field, color = '#14b8a6' }) {
    const vals = points.map((point) => ({
        time: new Date(point.recorded_at).getTime(),
        value: point[field] == null ? null : Number(point[field]),
        segment: point[`segment_${field}`],
    })).filter((point) => Number.isFinite(point.time));
    const present = vals.filter((point) => point.value != null && Number.isFinite(point.value));
    if (present.length < 2) {
        return <div className="h-24 muted text-xs flex items-center">{present.length ? present[0].value : '—'}</div>;
    }
    let min = Infinity;
    let max = -Infinity;
    for (const { value } of present) {
        min = Math.min(min, value);
        max = Math.max(max, value);
    }
    const span = max - min || 1;
    const firstTime = vals[0].time;
    const lastTime = vals[vals.length - 1].time;
    const timeSpan = lastTime - firstTime || 1;
    const intervals = vals.slice(1).map((point, index) => point.time - vals[index].time).filter((gap) => gap > 0).sort((a, b) => a - b);
    const medianInterval = intervals[Math.floor(intervals.length / 2)] || Infinity;
    const maxGap = medianInterval * 1.5;
    const w = 320;
    const h = 96;
    let previousTime = null;
    let previousSegment;
    let startSegment = true;
    const d = vals.map((point) => {
        if (point.value == null || !Number.isFinite(point.value)) {
            startSegment = true;
            previousTime = point.time;
            return '';
        }
        if (point.segment != null) {
            if (previousSegment != null && point.segment !== previousSegment) startSegment = true;
            previousSegment = point.segment;
        } else if (previousTime != null && point.time - previousTime > maxGap) {
            startSegment = true;
        }
        const x = ((point.time - firstTime) / timeSpan) * w;
        const y = h - ((point.value - min) / span) * (h - 8) - 4;
        const command = `${startSegment ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
        startSegment = false;
        previousTime = point.time;
        return command;
    }).filter(Boolean).join(' ');
    return (
        <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-24">
            <path d={d} fill="none" stroke={color} strokeWidth="2" />
        </svg>
    );
}
