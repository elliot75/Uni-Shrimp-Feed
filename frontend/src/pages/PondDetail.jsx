import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';
import Spark from '../components/Spark';

export default function PondDetail() {
    const { id } = useParams();
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [pond, setPond] = useState(null);
    const [range, setRange] = useState('24h');
    const [readings, setReadings] = useState([]);
    const [labs, setLabs] = useState([]);
    const [showLab, setShowLab] = useState(false);
    const [labForm, setLabForm] = useState(() => {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return { sampled_at: local.toISOString().slice(0, 16) };
    });
    const [cycleForm, setCycleForm] = useState({ stage: 'nursery', stocked_at: '', stocked_count: '', density_per_m2: '' });

    const load = async () => {
        const [p, r, l] = await Promise.all([
            api.get(`/ponds/${id}`),
            api.get(`/ponds/${id}/readings`, { params: { range } }),
            api.get(`/ponds/${id}/lab-tests`),
        ]);
        setPond(p.data);
        setReadings(r.data);
        setLabs(l.data);
    };

    useEffect(() => { load(); }, [id, range]);

    const submitLab = async (e) => {
        e.preventDefault();
        const payload = { ...labForm, sampled_at: new Date(labForm.sampled_at).toISOString() };
        ['no2_ppm', 'nh3_ppm', 'alkalinity_ppm', 'ca_ppm', 'mg_ppm', 'k_ppm'].forEach((k) => {
            if (payload[k] === '' || payload[k] == null) delete payload[k];
            else payload[k] = Number(payload[k]);
        });
        await api.post(`/ponds/${id}/lab-tests`, payload);
        setShowLab(false);
        load();
    };

    const submitCycle = async (e) => {
        e.preventDefault();
        await api.post(`/ponds/${id}/cycles`, {
            stage: cycleForm.stage,
            status: 'active',
            stocked_at: cycleForm.stocked_at || null,
            stocked_count: cycleForm.stocked_count ? Number(cycleForm.stocked_count) : null,
            density_per_m2: cycleForm.density_per_m2 ? Number(cycleForm.density_per_m2) : null,
        });
        load();
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

            <section className="card p-4">
                <h2 className="font-medium mb-2">{tr('cycle')}</h2>
                {pond.cycle ? (
                    <div className="text-sm text-slate-600 dark:text-slate-300">
                        {tr(pond.cycle.stage)} · DOC {pond.cycle.doc ?? '—'} · {pond.cycle.stocked_at || ''}
                    </div>
                ) : <div className="muted text-sm mb-2">{tr('noData')}</div>}
                <form onSubmit={submitCycle} className="flex flex-col sm:flex-row flex-wrap gap-2 mt-3 text-sm">
                    <select className="field" value={cycleForm.stage} onChange={(e) => setCycleForm({ ...cycleForm, stage: e.target.value })}>
                        <option value="nursery">{tr('nursery')}</option>
                        <option value="growout">{tr('growout')}</option>
                    </select>
                    <input type="date" className="field" value={cycleForm.stocked_at} onChange={(e) => setCycleForm({ ...cycleForm, stocked_at: e.target.value })} />
                    <input placeholder={tr('stockedCount')} className="field sm:w-28" value={cycleForm.stocked_count} onChange={(e) => setCycleForm({ ...cycleForm, stocked_count: e.target.value })} />
                    <button className="btn min-h-11">{tr('newCycle')}</button>
                </form>
            </section>

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
                <div className="grid sm:grid-cols-2 gap-4">
                    <div><div className="text-xs muted">{tr('ph')}</div><Spark points={readings.map((x) => x.ph)} color="#f43f5e" /></div>
                    <div><div className="text-xs muted">{tr('salinity')}</div><Spark points={readings.map((x) => x.salinity_ppt)} /></div>
                    <div><div className="text-xs muted">{tr('do')}</div><Spark points={readings.map((x) => x.do_mg_l)} color="#38bdf8" /></div>
                    <div><div className="text-xs muted">{tr('temp')}</div><Spark points={readings.map((x) => x.ph_temp_c || x.cond_temp_c)} color="#fbbf24" /></div>
                </div>
            </section>

            <section className="card p-4">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-2 mb-3">
                    <h2 className="font-medium">{tr('lab')}</h2>
                    <button type="button" onClick={() => setShowLab(!showLab)} className="btn text-sm min-h-11">{tr('addLab')}</button>
                </div>
                {showLab && (
                    <form onSubmit={submitLab} className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 mb-4 text-sm">
                        <input required type="datetime-local" className="field" value={labForm.sampled_at} onChange={(e) => setLabForm({ ...labForm, sampled_at: e.target.value })} />
                        {[['no2_ppm', 'no2'], ['nh3_ppm', 'nh3'], ['alkalinity_ppm', 'alk'], ['ca_ppm', 'ca'], ['mg_ppm', 'mg'], ['k_ppm', 'k']].map(([k, label]) => (
                            <input key={k} placeholder={tr(label)} className="field" value={labForm[k] || ''} onChange={(e) => setLabForm({ ...labForm, [k]: e.target.value })} />
                        ))}
                        <button className="btn min-h-11">{tr('save')}</button>
                    </form>
                )}
                <div className="overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
                    <table className="w-full min-w-[36rem] text-sm">
                        <thead className="muted text-left">
                            <tr>
                                <th className="py-1">{tr('sampledAt')}</th>
                                <th>NO₂</th><th>NH₃</th><th>{tr('alk')}</th><th>Ca</th><th>Mg</th>
                            </tr>
                        </thead>
                        <tbody>
                            {labs.map((row) => (
                                <tr key={row.id} className="border-t border-slate-200 dark:border-slate-800">
                                    <td className="py-1 whitespace-nowrap">{new Date(row.sampled_at).toLocaleString(user?.locale || 'vi')}</td>
                                    <td>{row.no2_ppm ?? '—'}</td>
                                    <td>{row.nh3_ppm ?? '—'}</td>
                                    <td>{row.alkalinity_ppm ?? '—'}</td>
                                    <td>{row.ca_ppm ?? '—'}</td>
                                    <td>{row.mg_ppm ?? '—'}</td>
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
