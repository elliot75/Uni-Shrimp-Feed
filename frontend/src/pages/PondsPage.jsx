import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function PondsPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [ponds, setPonds] = useState([]);
    const [farmers, setFarmers] = useState([]);
    const [form, setForm] = useState({ code: '', name: '', pond_type: 'growout', farmer_id: user.role === 'farmer' ? user.id : '' });

    const load = async () => {
        const [p, u] = await Promise.all([api.get('/ponds'), api.get('/users')]);
        setPonds(p.data);
        setFarmers(u.data.filter((x) => x.role === 'farmer'));
        if (!form.farmer_id && user.role === 'farmer') setForm((f) => ({ ...f, farmer_id: user.id }));
    };
    useEffect(() => { load(); }, []);

    const submit = async (e) => {
        e.preventDefault();
        await api.post('/ponds', form);
        setForm({ ...form, code: '', name: '' });
        load();
    };

    return (
        <div>
            <h1 className="text-2xl font-semibold mb-4">{tr('ponds')}</h1>
            <form onSubmit={submit} className="card p-4 mb-4 grid sm:grid-cols-2 lg:grid-cols-5 gap-2 text-sm">
                {user.role !== 'farmer' && (
                    <select className="field" value={form.farmer_id} onChange={(e) => setForm({ ...form, farmer_id: e.target.value })} required>
                        <option value="">{tr('farmer')}</option>
                        {farmers.map((f) => <option key={f.id} value={f.id}>{f.display_name}</option>)}
                    </select>
                )}
                <input required placeholder={tr('code')} className="field" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
                <input required placeholder={tr('name')} className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                <select className="field" value={form.pond_type} onChange={(e) => setForm({ ...form, pond_type: e.target.value })}>
                    <option value="nursery">{tr('nursery')}</option>
                    <option value="growout">{tr('growout')}</option>
                    <option value="treatment">{tr('treatment')}</option>
                    <option value="settling">{tr('settling')}</option>
                    <option value="other">{tr('other')}</option>
                </select>
                <button className="btn min-h-11">{tr('newPond')}</button>
            </form>
            <div className="space-y-2">
                {ponds.map((p) => (
                    <Link key={p.id} to={`/ponds/${p.id}`} className="card block px-4 py-3 hover:border-teal-600">
                        <div className="font-medium break-words">{p.code} · {p.name}</div>
                        <div className="text-xs muted">{p.farmer_name} · {tr(p.pond_type)} · {p.open_alerts} {tr('alerts')}</div>
                    </Link>
                ))}
            </div>
        </div>
    );
}
