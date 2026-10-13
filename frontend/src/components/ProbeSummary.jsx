export const PROBE_METRICS = [
    { field: 'ph', label: 'ph', unit: '', color: '#f43f5e' },
    { field: 'do_mg_l', label: 'do', unit: 'mg/L', color: '#38bdf8' },
    { field: 'salinity_ppt', label: 'salinity', unit: 'ppt', color: '#14b8a6' },
    { field: 'temp_c', label: 'doWaterTemp', unit: '°C', color: '#fbbf24' },
    { field: 'ph_mv', label: 'phPotential', unit: 'mV', color: '#a78bfa' },
    { field: 'do_sat_pct', label: 'doSaturation', unit: '%', color: '#38bdf8' },
    { field: 'conductivity_us_cm', label: 'conductivity', unit: 'μS/cm', color: '#f59e0b' },
    { field: 'tds_mg_l', label: 'tds', unit: 'mg/L', color: '#14b8a6' },
];

export default function ProbeSummary({ reading, tr }) {
    return (
        <div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                {PROBE_METRICS.map(({ field, label, unit }) => (
                    <div key={field}>
                        <div className="muted text-xs">{tr(label)}</div>
                        <div>{reading?.[field] ?? '—'}{reading?.[field] != null && unit && <span className="text-xs muted ml-1">{unit}</span>}</div>
                    </div>
                ))}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs muted mt-3">
                <span>{tr('phProbeTemp')}: {reading?.ph_temp_c ?? '—'} °C</span>
                <span>{tr('condProbeTemp')}: {reading?.cond_temp_c ?? '—'} °C</span>
            </div>
        </div>
    );
}
