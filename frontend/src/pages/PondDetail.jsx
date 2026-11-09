import LabNh3Cells from '../components/LabNh3Cells';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';
import Spark from '../components/Spark';
import ProbeSummary, { PROBE_METRICS } from '../components/ProbeSummary';
import CycleManager from '../components/CycleManager';
import { farmDateTimeInput, farmInputToIso, formatFarmTime } from '../utils/time';

export default function PondDetail() {
    const { id } = useParams();
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [pond, setPond] = useState(null);
    const [range, setRange] = useState('24h');
    const [readings, setReadings] = useState([]);
    const [labs, setLabs] = useState([]);
    const [cycles, setCycles] = useState([]);
    const [showLab, setShowLab] = useState(false);
    const [labError, setLabError] = useState('');
    const [labSaving, setLabSaving] = useState(false);
    const [labForm, setLabForm] = useState(() => ({ sampled_at: farmDateTimeInput(), cycle_id: 'auto' }));

    const load = async () => {
        const [p, r, l, c] = await Promise.all([
            api.get(`/ponds/${id}`),
            api.get(`/ponds/${id}/readings`, { params: { range } }),
            api.get(`/ponds/${id}/lab-tests`),
            api.get(`/ponds/${id}/cycles`),
        ]);
        setPond(p.data);
        setReadings(r.data);
        setLabs(l.data);
        setCycles(c.data);
    };

    useEffect(() => { load(); }, [id, range]);

    const submitLab = async (e) => {
        e.preventDefault();
        setLabError('');
        const payload = { ...labForm, sampled_at: farmInputToIso(labForm.sampled_at) };
        if (payload.cycle_id === 'auto') delete payload.cycle_id;
        else if (payload.cycle_id === 'none') payload.cycle_id = null;
        ['no2_ppm', 'nh3_ppm', 'alkalinity_ppm', 'ca_ppm', 'mg_ppm', 'k_ppm'].forEach((k) => {
            if (payload[k] === '' || payload[k] == null) delete payload[k];
            else payload[k] = Number(payload[k]);
        });
        setLabSaving(true);
        try {
            await api.post(`/ponds/${id}/lab-tests`, payload);
            setShowLab(false);
            await load();
        } catch {
            setLabError(tr('labSaveFailed'));
        } finally {
            setLabSaving(false);
        }
    };

    if (!pond) return <div>…</div>;
    const msg = user?.locale === 'zh-TW' ? 'message_zh' : 'message_vi';

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-2xl font-semibold break-words">{pond.code} · {pond.name}</h1>
                <p className="muted text-sm">{pond.farmer_name} · {tr(pond.pond_type)}</p>
            </div>

            {pond.open_alerts?.length > 0 && (
                <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 rounded-xl p-4 space-y-1">
                    {pond.open_alerts.map((a) => (
                        <div key={a.id} className="text-sm break-words">{a[msg]}</div>
                    ))}
                </div>
            )}

            <CycleManager pond={pond} cycles={cycles} reload={load} tr={tr} />

            <section className="card p-4">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 mb-2">
                    <h2 className="font-medium">{tr('readings')}</h2>
                    <div className="flex flex-wrap gap-1 text-xs">
                        {['24h', '7d', '30d'].map((r) => (
                            <button
                                type="button"
                                key={r}
                                onClick={() => setRange(r)}
                                className={`px-3 py-2 rounded min-h-11 ${range === r ? 'bg-teal-700 text-white' : 'bg-slate-100 dark:bg-slate-800'}`}
                            >
                                {tr(r === '24h' ? 'range24h' : r === '7d' ? 'range7d' : 'range30d')}
                            </button>
                        ))}
                    </div>
                </div>
                <div className="mb-4">
                    <h3 className="text-sm font-medium mb-2">{tr('latest')}</h3>
                    <ProbeSummary reading={pond.latest_reading} tr={tr} />
                    {pond.latest_reading?.recorded_at && (
                        <p className="text-xs muted mt-2">{formatFarmTime(pond.latest_reading.recorded_at, user?.locale)}</p>
                    )}
                    {pond.latest_reading && (
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs muted mt-2 break-all">
                            <span>MAC: {pond.latest_reading.device_serial}</span>
                            {pond.latest_reading.raw?.ip && <span>IP: {pond.latest_reading.raw.ip}</span>}
                            {pond.latest_reading.raw?.rssi_dbm != null && <span>RSSI: {pond.latest_reading.raw.rssi_dbm} dBm</span>}
                            {pond.latest_reading.raw?.hostname && <span>mDNS: {pond.latest_reading.raw.hostname}</span>}
                        </div>
                    )}
                </div>
                {pond.diurnal && (
                    <p className="text-sm text-slate-600 dark:text-slate-300 mb-3">
                        {tr('diurnalPh')}: {pond.diurnal.delta_ph ?? '—'}
                        {' · '}
                        {tr('diurnalDo')}: {pond.diurnal.delta_do ?? '—'}
                    </p>
                )}
                <div className="grid sm:grid-cols-2 gap-4">
                    {PROBE_METRICS.map(({ field, label, unit, color }) => (
                        <div key={field}>
                            <div className="text-xs muted">{tr(label)}{unit && ` (${unit})`}</div>
                            <Spark points={readings} field={field} color={color} />
                        </div>
                    ))}
                </div>
            </section>

            <section className="card p-4">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 mb-3">
                    <h2 className="font-medium">{tr('lab')}</h2>
                    <button type="button" onClick={() => setShowLab(!showLab)} className="btn text-sm min-h-11">{tr('addLab')}</button>
                </div>
                {showLab && (
                    <form onSubmit={submitLab} className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 mb-4 text-sm">
                        <label>{tr('sampledAt')} · {tr('vietnamTime')}<input required type="datetime-local" className="field w-full" value={labForm.sampled_at} onChange={(e) => setLabForm({ ...labForm, sampled_at: e.target.value })} /></label>
                        <select aria-label={tr('cycle')} className="field" value={labForm.cycle_id} onChange={(e) => setLabForm({ ...labForm, cycle_id: e.target.value })}>
                            <option value="auto">{tr('cycleByDate')}</option>
                            <option value="none">{tr('noCycle')}</option>
                            {cycles.filter((c) => c.status !== 'planned').map((c) => (
                                <option key={c.id} value={c.id}>{tr(c.stage)} · {c.stocked_at || tr('noDate')} · {tr(c.status)} · {c.id.slice(0, 8)}</option>
                            ))}
                        </select>
                        {[['no2_ppm', 'no2'], ['nh3_ppm', 'nh3Tan'], ['alkalinity_ppm', 'alk'], ['ca_ppm', 'ca'], ['mg_ppm', 'mg'], ['k_ppm', 'k']].map(([k, label]) => (
                            <input key={k} placeholder={tr(label)} className="field" value={labForm[k] || ''} onChange={(e) => setLabForm({ ...labForm, [k]: e.target.value })} />
                        ))}
                        <button disabled={labSaving} className="btn min-h-11">{tr('save')}</button>
                        {labError && <p role="alert" className="text-rose-600 sm:col-span-2 lg:col-span-4">{labError}</p>}
                    </form>
                )}
                <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
                    <table className="w-full min-w-[36rem] text-sm">
                        <thead className="muted text-left">
                            <tr>
                                <th className="py-1">{tr('sampledAt')}</th>
                                <th>NO₂</th><th>{tr('nh3Tan')}</th><th>{tr('nh3Handbook')}</th><th>{tr('nh3TempAdjusted')}</th><th>{tr('nh3ForThreshold')}</th><th>{tr('alk')}</th><th>Ca</th><th>Mg</th><th>K⁺</th>
                            </tr>
                        </thead>
                        <tbody>
                            {labs.map((row) => (
                                <tr key={row.id} className="border-t border-slate-200 dark:border-slate-800">
                                    <td className="py-1 whitespace-nowrap">{formatFarmTime(row.sampled_at, user?.locale)}</td>
                                    <td>{row.no2_ppm ?? '—'}</td>
                                    <td>{row.nh3_ppm ?? '—'}</td>
                                    <LabNh3Cells row={row} tr={tr} locale={user?.locale} />
                                    <td>{row.alkalinity_ppm ?? '—'}</td>
                                    <td>{row.ca_ppm ?? '—'}</td>
                                    <td>{row.mg_ppm ?? '—'}</td>
                                    <td>{row.k_ppm ?? '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {labs.length === 0 && <p className="muted text-sm mt-2">{tr('noData')}</p>}
                </div>
            </section>
        </div>
    );
}
