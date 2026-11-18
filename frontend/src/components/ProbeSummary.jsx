export const PROBE_METRICS = [
    { field: 'ph', label: 'ph', unit: '', color: '#f43f5e' },
    { field: 'do_mg_l', label: 'do', unit: 'mg/L', color: '#38bdf8' },
    { field: 'salinity_ppt', label: 'salinity', unit: 'ppt', color: '#14b8a6' },
    { field: 'temp_c', label: 'doWaterTemp', unit: '°C', color: '#fbbf24' },
    { field: 'ph_mv', label: 'phPotential', unit: 'mV', color: '#a78bfa' },
];

export default function ProbeSummary({ reading, tr }) {
    return (
        <div className="probe-metrics grid gap-3 text-sm">
            {PROBE_METRICS.map(({ field, label, unit }) => (
                <div key={field} className="min-w-0">
                    <div className="muted text-xs">{tr(label)}</div>
                    <div className="[overflow-wrap:anywhere]">{reading?.[field] ?? '—'}{reading?.[field] != null && unit && <> <span className="text-xs muted">{unit}</span></>}</div>
                </div>
            ))}
        </div>
    );
}
