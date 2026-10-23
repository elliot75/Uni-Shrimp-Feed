// The API owns NH3 selection, calculation and the handbook range gate.
// Never fall back to a saved alert value in the handbook column.
export default function LabNh3Cells({ row, tr }) {
    const missing = {
        missing_tan: '—',
        missing_ph: tr('nh3NoPh'),
        missing_lookup: tr('nh3NoLookup'),
        outside_handbook: tr('nh3OutsideHandbook'),
    };
    const sources = [
        ['sample_ph', 'pH', ''],
        ['sample_temp_c', tr('temp'), ' °C'],
        ['sample_salinity_ppt', tr('salinity'), ' ppt'],
    ].filter(([field]) => row[field] != null).map(([field, label, unit]) => (
        `${label}: ${row[field]}${unit} (${row[`${field}_recorded_at`] || '—'})`
    )).join('\n');
    const estimate = row.nh3_status === 'missing_tan' || row.nh3_status === 'missing_ph'
        ? missing[row.nh3_status]
        : row.nh3_temp_adjusted
            ? row.nh3_emerson_ppm ?? '—'
            : tr('nh3NoTemp');

    return <>
        <td data-nh3="handbook">{row.nh3_handbook_ppm ?? '—'}</td>
        <td data-nh3="estimate" title={sources}>
            {estimate}
            {row.nh3_temp_adjusted && <span className="block text-xs muted">
                {tr(row.nh3_salinity_adjusted ? 'nh3WithSalinity' : 'nh3WithoutSalinity')}
            </span>}
            {row.nh3_outside_handbook && <span className="block text-xs muted">{tr('nh3ReferenceOnly')}</span>}
        </td>
        <td data-nh3="threshold" title={sources}>
            {missing[row.nh3_status] ?? row.nh3_unionized_ppm ?? '—'}
        </td>
    </>;
}
