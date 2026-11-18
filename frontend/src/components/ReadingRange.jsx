import { useState } from 'react';

const presets = [
    ['all', 'rangeAll'],
    ['24h', 'range24h'],
    ['7d', 'range7d'],
    ['30d', 'range30d'],
];

export default function ReadingRange({ value, onChange, tr }) {
    const [showDates, setShowDates] = useState(false);
    const [start, setStart] = useState('');
    const [end, setEnd] = useState('');
    const buttonClass = (selected) => `px-3 py-2 rounded min-h-11 ${selected ? 'bg-teal-700 text-white' : 'bg-slate-100 dark:bg-slate-800'}`;

    return (
        <div className="space-y-2 text-xs">
            <div className="flex flex-wrap gap-1">
                {presets.map(([range, label]) => (
                    <button key={range} type="button" aria-pressed={value.range === range} className={buttonClass(value.range === range)}
                        onClick={() => { setShowDates(false); if (value.range !== range) onChange({ range }); }}>
                        {tr(label)}
                    </button>
                ))}
                <button type="button" aria-expanded={showDates} aria-pressed={value.range === 'custom'}
                    className={buttonClass(value.range === 'custom')} onClick={() => setShowDates(!showDates)}>
                    {tr('rangeCustom')}
                </button>
            </div>
            {showDates && (
                <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
                    e.preventDefault();
                    if (start && end && start <= end) onChange({ range: 'custom', start_date: start, end_date: end });
                }}>
                    <label>{tr('startDate')}<input className="field block" type="date" required max={end || undefined} value={start} onChange={(e) => setStart(e.target.value)} /></label>
                    <label>{tr('endDate')}<input className="field block" type="date" required min={start || undefined} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
                    <button className="btn min-h-11" type="submit">{tr('applyRange')}</button>
                </form>
            )}
            {value.range === 'custom' && (
                <p className="muted">{value.start_date} – {value.end_date} · {tr('vietnamTime')}</p>
            )}
        </div>
    );
}
