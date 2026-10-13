import { useEffect, useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function DevicesPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [devices, setDevices] = useState([]);
    const [ponds, setPonds] = useState([]);
    const [form, setForm] = useState({ serial: '', name: '', pond_id: '' });
    const canEdit = user.role === 'admin' || user.role === 'salesperson';

    const load = async () => {
        const [d, p] = await Promise.all([api.get('/devices'), api.get('/ponds')]);
        setDevices(d.data);
        setPonds(p.data);
    };
    useEffect(() => { load(); }, []);

    const submit = async (e) => {
        e.preventDefault();
        await api.post('/devices', { ...form, pond_id: form.pond_id || null });
        setForm({ serial: '', name: '', pond_id: '' });
        load();
    };

    const bind = async (id, pond_id) => {
        await api.patch(`/devices/${id}`, pond_id ? { pond_id } : { unbind: true });
        load();
    };

    const rename = async (device, name) => {
        const nextName = name.trim();
        if (nextName === (device.name || '')) return;
        await api.patch(`/devices/${device.id}`, { name: nextName || null });
        load();
    };

    return (
        <div>
            <h1 className="text-2xl font-semibold mb-4">{tr('devices')}</h1>
            {canEdit && (
                <form onSubmit={submit} className="card p-4 mb-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-sm">
                    <input required placeholder={tr('deviceMac')} autoCapitalize="characters" spellCheck="false" className="field" value={form.serial} onChange={(e) => setForm({ ...form, serial: e.target.value })} />
                    <input placeholder={tr('deviceAlias')} className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                    <select className="field" value={form.pond_id} onChange={(e) => setForm({ ...form, pond_id: e.target.value })}>
                        <option value="">{tr('bindPond')}</option>
                        {ponds.map((p) => <option key={p.id} value={p.id}>{p.code}</option>)}
                    </select>
                    <button className="btn min-h-11">{tr('newDevice')}</button>
                </form>
            )}
            <div className="space-y-2">
                {devices.map((d) => (
                    <div key={d.id} className="card p-4 text-sm flex flex-col sm:flex-row sm:justify-between gap-3">
                        <div className="min-w-0">
                            <div className="font-medium break-words">{d.serial}</div>
                            {canEdit ? (
                                <input aria-label={tr('deviceAlias')} placeholder={tr('deviceAlias')} defaultValue={d.name || ''} onBlur={(e) => rename(d, e.target.value)} className="field mt-1" />
                            ) : d.name && <div className="muted">{d.name}</div>}
                            <div className="muted">{d.pond_code || tr('unbind')} · {tr('lastSeen')}: {d.last_seen_at?.slice(0, 16) || '—'}</div>
                        </div>
                        {canEdit && (
                            <select className="field sm:w-40" value={d.pond_id || ''} onChange={(e) => bind(d.id, e.target.value)}>
                                <option value="">{tr('unbind')}</option>
                                {ponds.map((p) => <option key={p.id} value={p.id}>{p.code}</option>)}
                            </select>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
