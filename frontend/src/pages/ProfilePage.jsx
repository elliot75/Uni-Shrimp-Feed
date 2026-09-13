import { useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function ProfilePage() {
    const { user, updateMe } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [form, setForm] = useState({ display_name: user.display_name || '', email: user.email || '', phone: user.phone || '', locale: user.locale || 'vi' });
    const [bind, setBind] = useState(null);
    const [msg, setMsg] = useState('');

    const save = async (e) => {
        e.preventDefault();
        await updateMe(form);
        setMsg(tr('save'));
    };

    const startBind = async () => {
        try {
            const res = await api.post('/auth/telegram/bind');
            setBind(res.data);
        } catch (err) {
            setMsg(err.response?.data?.detail || 'Telegram bot is not configured');
        }
    };

    return (
        <div className="max-w-lg space-y-6">
            <h1 className="text-2xl font-semibold">{tr('profile')}</h1>
            <form onSubmit={save} className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3 text-sm">
                <label className="block">{tr('displayName')}
                    <input className="mt-1 w-full bg-slate-800 rounded px-3 py-2" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
                </label>
                <label className="block">{tr('email')}
                    <input className="mt-1 w-full bg-slate-800 rounded px-3 py-2" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </label>
                <label className="block">{tr('phone')}
                    <input className="mt-1 w-full bg-slate-800 rounded px-3 py-2" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                </label>
                <label className="block">{tr('language')}
                    <select className="mt-1 w-full bg-slate-800 rounded px-3 py-2" value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                        <option value="vi">Tiếng Việt</option>
                        <option value="zh-TW">繁體中文</option>
                    </select>
                </label>
                <button className="bg-teal-700 rounded px-4 py-2">{tr('save')}</button>
                {msg && <div className="text-teal-400">{msg}</div>}
            </form>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm">
                <div className="mb-2">{tr('telegram')}: {user.telegram_bound ? tr('bound') : tr('notBound')}</div>
                <button onClick={startBind} className="bg-slate-800 rounded px-3 py-2">{tr('bindTelegram')}</button>
                {bind && (
                    <div className="mt-3 text-slate-300">
                        <div>{tr('telegramCode')}: <b>{bind.code}</b></div>
                        {bind.link && <a className="text-teal-400" href={bind.link} target="_blank" rel="noreferrer">{bind.link}</a>}
                    </div>
                )}
            </div>
        </div>
    );
}
