import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

const blank = { code: '', name: '', pond_type: 'growout', farmer_id: '', area_m2: '', depth_m: '', volume_m3: '', location_text: '' };
const numericFields = ['area_m2', 'depth_m', 'volume_m3'];

function PondFields({ form, setForm, tr, creating }) {
    const field = (key) => (e) => setForm((previous) => ({ ...previous, [key]: e.target.value }));
    return <>
        {creating && <label>{tr('code')}<input required className="field w-full" value={form.code} onChange={field('code')} /></label>}
        <label>{tr('name')}<input required className="field w-full" value={form.name} onChange={field('name')} /></label>
        <label>{tr('type')}<select className="field w-full" value={form.pond_type} onChange={field('pond_type')}>
            {['nursery', 'growout', 'treatment', 'settling', 'other'].map((type) => <option key={type} value={type}>{tr(type)}</option>)}
        </select></label>
        {numericFields.map((key, i) => <label key={key}>{tr(['area', 'depth', 'volume'][i])}<input type="number" min="0" step="any" className="field w-full" value={form[key] ?? ''} onChange={field(key)} /></label>)}
        <label>{tr('location')}<input className="field w-full" value={form.location_text ?? ''} onChange={field('location_text')} /></label>
    </>;
}

export default function PondsPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [ponds, setPonds] = useState([]);
    const [farmers, setFarmers] = useState([]);
    const [form, setForm] = useState({ ...blank, farmer_id: user.role === 'farmer' ? user.id : '' });
    const [editing, setEditing] = useState(null);
    const [editForm, setEditForm] = useState(blank);
    const [error, setError] = useState('');

    const load = async () => {
        const [p, u] = await Promise.all([api.get('/ponds'), api.get('/users')]);
        setPonds(p.data);
        setFarmers(u.data.filter((x) => x.role === 'farmer'));
    };
    useEffect(() => { load().catch(() => setError(tr('managementFailed'))); }, []);

    const payload = (data) => Object.fromEntries(Object.entries(data).map(([key, value]) => [key,
        numericFields.includes(key) ? (value === '' || value == null ? null : Number(value)) : value]));
    const submit = async (e) => {
        e.preventDefault(); setError('');
        try {
            await api.post('/ponds', payload(form));
            setForm({ ...blank, farmer_id: user.role === 'farmer' ? user.id : form.farmer_id });
            await load();
        } catch { setError(tr('managementFailed')); }
    };
    const save = async (e) => {
        e.preventDefault(); setError('');
        try {
            await api.patch(`/ponds/${editing}`, payload(editForm));
            setEditing(null); await load();
        } catch { setError(tr('managementFailed')); }
    };
    const toggle = async (pond) => {
        setError('');
        try { await api.patch(`/ponds/${pond.id}`, { is_active: !pond.is_active }); await load(); }
        catch { setError(tr('managementFailed')); }
    };
    const startEdit = (pond) => {
        setEditing(pond.id);
        setEditForm(Object.fromEntries(['name', 'pond_type', ...numericFields, 'location_text'].map((key) => [key, pond[key] ?? ''])));
    };

    return <div>
        <h1 className="text-2xl font-semibold mb-4">{tr('ponds')}</h1>
        {error && <p role="alert" className="text-rose-600 mb-3">{error}</p>}
        <form onSubmit={submit} className="card p-4 mb-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-sm">
            {user.role !== 'farmer' && <label>{tr('farmer')}<select className="field w-full" value={form.farmer_id} onChange={(e) => setForm({ ...form, farmer_id: e.target.value })} required>
                <option value="">{tr('farmer')}</option>{farmers.map((f) => <option key={f.id} value={f.id}>{f.display_name}</option>)}
            </select></label>}
            <PondFields form={form} setForm={setForm} tr={tr} creating />
            <button className="btn min-h-11 self-end">{tr('newPond')}</button>
        </form>
        <div className="space-y-2">{ponds.map((p) => <div key={p.id} className="card px-4 py-3 text-sm">
            <Link to={`/ponds/${p.id}`} className="font-medium text-teal-700 dark:text-teal-400 break-words">{p.code} · {p.name}</Link>
            <div className="muted">{p.farmer_name} · {tr(p.pond_type)} · {p.open_alerts} {tr('alerts')} · {p.is_active ? tr('enabled') : tr('disabled')}</div>
            {!p.is_active && <p className="muted">{tr('pondInactive')}</p>}
            {editing === p.id ? <form onSubmit={save} className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 mt-3">
                <PondFields form={editForm} setForm={setEditForm} tr={tr} />
                <div className="flex gap-2 self-end"><button className="btn min-h-11">{tr('save')}</button><button type="button" className="btn-ghost" onClick={() => setEditing(null)}>{tr('cancel')}</button></div>
            </form> : <div className="flex flex-wrap gap-2 mt-2"><button type="button" className="btn-ghost min-h-11" onClick={() => startEdit(p)}>{tr('edit')}</button><button type="button" className="btn-ghost min-h-11" onClick={() => toggle(p)}>{tr(p.is_active ? 'disablePond' : 'enablePond')}</button></div>}
        </div>)}</div>
    </div>;
}
