import { useEffect, useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function UsersPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [users, setUsers] = useState([]);
    const [assignments, setAssignments] = useState([]);
    const [form, setForm] = useState({ username: '', password: '', email: '', display_name: '', role: 'farmer', locale: 'vi' });
    const [pair, setPair] = useState({ salesperson_id: '', farmer_id: '' });

    const load = async () => {
        const [u, a] = await Promise.all([api.get('/users'), api.get('/users/assignments')]);
        setUsers(u.data);
        setAssignments(a.data);
    };
    useEffect(() => { load(); }, []);

    const submit = async (e) => {
        e.preventDefault();
        await api.post('/users', form);
        setForm({ username: '', password: '', email: '', display_name: '', role: 'farmer', locale: 'vi' });
        load();
    };

    const toggle = async (u) => {
        await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
        load();
    };

    const assign = async (e) => {
        e.preventDefault();
        await api.post('/users/assignments', pair);
        load();
    };

    const unassign = async (s, f) => {
        await api.delete(`/users/assignments/${s}/${f}`);
        load();
    };

    const sales = users.filter((u) => u.role === 'salesperson');
    const farmers = users.filter((u) => u.role === 'farmer');

    return (
        <div className="space-y-8">
            <h1 className="text-2xl font-semibold">{tr('users')}</h1>
            <form onSubmit={submit} className="bg-slate-900 border border-slate-800 rounded-xl p-4 grid md:grid-cols-3 gap-2 text-sm">
                <input required placeholder={tr('username')} className="bg-slate-800 rounded px-2 py-2" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
                <input required type="password" placeholder={tr('password')} className="bg-slate-800 rounded px-2 py-2" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                <input required type="email" placeholder={tr('email')} className="bg-slate-800 rounded px-2 py-2" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                <input required placeholder={tr('displayName')} className="bg-slate-800 rounded px-2 py-2" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
                <select className="bg-slate-800 rounded px-2 py-2" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                    <option value="farmer">{tr('farmer')}</option>
                    <option value="salesperson">{tr('salesperson')}</option>
                    <option value="admin">{tr('admin')}</option>
                </select>
                <select className="bg-slate-800 rounded px-2 py-2" value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                    <option value="vi">VI</option>
                    <option value="zh-TW">中文</option>
                </select>
                <button className="bg-teal-700 rounded py-2">{tr('newUser')}</button>
            </form>
            <div className="space-y-2">
                {users.map((u) => (
                    <div key={u.id} className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3 flex justify-between text-sm">
                        <div>
                            <div className="font-medium">{u.display_name} · {u.username}</div>
                            <div className="text-slate-400">{tr(u.role)} · {u.email} · {u.is_active ? tr('enabled') : tr('disabled')}</div>
                        </div>
                        <button onClick={() => toggle(u)} className="text-xs bg-slate-800 rounded px-3">{u.is_active ? tr('disabled') : tr('enabled')}</button>
                    </div>
                ))}
            </div>
            <section>
                <h2 className="font-medium mb-2">{tr('assign')}</h2>
                <form onSubmit={assign} className="flex gap-2 mb-3 text-sm">
                    <select required className="bg-slate-800 rounded px-2 py-2" value={pair.salesperson_id} onChange={(e) => setPair({ ...pair, salesperson_id: e.target.value })}>
                        <option value="">{tr('salesperson')}</option>
                        {sales.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
                    </select>
                    <select required className="bg-slate-800 rounded px-2 py-2" value={pair.farmer_id} onChange={(e) => setPair({ ...pair, farmer_id: e.target.value })}>
                        <option value="">{tr('farmer')}</option>
                        {farmers.map((f) => <option key={f.id} value={f.id}>{f.display_name}</option>)}
                    </select>
                    <button className="bg-teal-700 rounded px-3">{tr('save')}</button>
                </form>
                {assignments.map((a) => (
                    <div key={`${a.salesperson_id}-${a.farmer_id}`} className="text-sm flex justify-between bg-slate-900 border border-slate-800 rounded px-3 py-2 mb-1">
                        <span>{a.salesperson_name} → {a.farmer_name}</span>
                        <button onClick={() => unassign(a.salesperson_id, a.farmer_id)} className="text-rose-400">{tr('cancel')}</button>
                    </div>
                ))}
            </section>
        </div>
    );
}
