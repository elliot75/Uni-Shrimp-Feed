import { useState } from 'react';
import api from '../api/client';

const empty = { stage: 'nursery', stocked_at: '', stocked_count: '', density_per_m2: '', sample_avg_weight_g: '', species: 'whiteleg', notes: '' };
const numbers = ['stocked_count', 'density_per_m2', 'sample_avg_weight_g'];

export default function CycleManager({ pond, cycles, reload, tr }) {
    const [form, setForm] = useState(empty);
    const [editing, setEditing] = useState(null);
    const [editEnd, setEditEnd] = useState('');
    const [date, setDate] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const change = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }));
    const edit = (cycle) => {
        setEditing(cycle.id);
        setEditEnd(cycle.harvested_at || '');
        setForm(Object.fromEntries(Object.keys(empty).map((key) => [key, cycle[key] ?? ''])));
        setError('');
    };
    const save = async (e) => {
        e.preventDefault(); setBusy(true); setError('');
        const payload = Object.fromEntries(Object.entries(form).map(([key, value]) => [key,
            numbers.includes(key) ? (value === '' ? null : Number(value)) : key === 'stocked_at' && !value ? null : value]));
        const selected = cycles.find((cycle) => cycle.id === editing);
        if (selected && ['harvested', 'aborted'].includes(selected.status)) payload.harvested_at = editEnd;
        try {
            if (editing) await api.patch(`/cycles/${editing}`, payload);
            else await api.post(`/ponds/${pond.id}/cycles`, { ...payload, status: 'active' });
            setEditing(null); setForm(empty); await reload();
        } catch { setError(tr('managementFailed')); }
        finally { setBusy(false); }
    };
    const close = async (status) => {
        if (!pond.cycle) return;
        setBusy(true); setError('');
        try {
            await api.patch(`/cycles/${pond.cycle.id}`, { status, harvested_at: date || null });
            setDate(''); setEditing(null); setForm(empty); await reload();
        } catch { setError(tr('managementFailed')); }
        finally { setBusy(false); }
    };
    const showForm = editing || !pond.cycle;
    return <section className="card p-4">
        <h2 className="font-medium mb-2">{tr('cycle')}</h2>
        {error && <p role="alert" className="text-rose-600 mb-2">{error}</p>}
        {pond.cycle ? <div className="text-sm muted">{tr(pond.cycle.stage)} · DOC {pond.cycle.doc ?? '—'} · {pond.cycle.stocked_at || tr('noDate')} · {tr('weight')}: {pond.cycle.sample_avg_weight_g ?? '—'}</div> : <div className="muted text-sm">{tr('noData')}</div>}
        {showForm && <form onSubmit={save} className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 mt-3 text-sm">
            <label>{tr('stage')}<select className="field w-full" value={form.stage} onChange={change('stage')}><option value="nursery">{tr('nursery')}</option><option value="growout">{tr('growout')}</option></select></label>
            <label>{tr('stockedAt')}<input type="date" className="field w-full" value={form.stocked_at} onChange={change('stocked_at')} /></label>
            {editing && cycles.some((cycle) => cycle.id === editing && ['harvested', 'aborted'].includes(cycle.status)) && <label>{tr('endDate')}<input required type="date" className="field w-full" value={editEnd} onChange={(e) => setEditEnd(e.target.value)} /></label>}
            <label>{tr('stockedCount')}<input type="number" min="0" step="1" className="field w-full" value={form.stocked_count} onChange={change('stocked_count')} /></label>
            <label>{tr('density')}<input type="number" min="0" step="any" className="field w-full" value={form.density_per_m2} onChange={change('density_per_m2')} /></label>
            <label>{tr('weight')}<input type="number" min="0" step="any" className="field w-full" value={form.sample_avg_weight_g} onChange={change('sample_avg_weight_g')} /></label>
            <label>{tr('species')}<input required className="field w-full" value={form.species} onChange={change('species')} /></label>
            <label>{tr('notes')}<input className="field w-full" value={form.notes} onChange={change('notes')} /></label>
            <div className="flex gap-2 self-end"><button disabled={busy} className="btn min-h-11">{tr(editing ? 'save' : 'newCycle')}</button>{editing && <button type="button" className="btn-ghost" onClick={() => { setEditing(null); setForm(empty); }}>{tr('cancel')}</button>}</div>
            {editing && <p className="muted sm:col-span-2 lg:col-span-4">{tr('cycleDateNotice')}</p>}
        </form>}
        {pond.cycle && <div className="flex flex-wrap gap-2 items-end mt-3 text-sm">
            <label>{tr('closeDate')}<input type="date" className="field block" value={date} onChange={(e) => setDate(e.target.value)} /></label>
            <button type="button" disabled={busy} className="btn min-h-11" onClick={() => close('harvested')}>{tr('closeCycle')}</button>
            <button type="button" disabled={busy} className="btn-ghost min-h-11" onClick={() => close('aborted')}>{tr('abortCycle')}</button>
        </div>}
        <h3 className="font-medium mt-4">{tr('cycleHistory')}</h3>
        <div className="space-y-1 mt-2">{cycles.map((cycle) => <div key={cycle.id} className="flex flex-wrap justify-between gap-2 text-sm border-t border-slate-200 dark:border-slate-800 py-1">
            <span>{tr(cycle.stage)} · {tr(cycle.status)} · {cycle.stocked_at || tr('noDate')} → {cycle.harvested_at || '—'} · {tr('weight')}: {cycle.sample_avg_weight_g ?? '—'}</span>
            <button type="button" className="btn-ghost min-h-11" onClick={() => edit(cycle)}>{tr('edit')}</button>
        </div>)}</div>
    </section>;
}
