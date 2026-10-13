import { useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function ProfilePage() {
    const { user, updateMe, changePassword } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [form, setForm] = useState({ display_name: user.display_name || '', email: user.email || '', phone: user.phone || '', locale: user.locale || 'vi' });
    const [bind, setBind] = useState(null);
    const [msg, setMsg] = useState('');
    const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' });
    const [pwMsg, setPwMsg] = useState('');
    const [pwError, setPwError] = useState('');
    const [pwSaving, setPwSaving] = useState(false);

    const save = async (e) => {
        e.preventDefault();
        await updateMe(form);
        setMsg(tr('save'));
    };

    const savePassword = async (e) => {
        e.preventDefault();
        setPwMsg('');
        setPwError('');
        if (pw.new_password.length < 8) {
            setPwError(tr('passwordTooShort'));
            return;
        }
        if (pw.new_password !== pw.confirm) {
            setPwError(tr('passwordMismatch'));
            return;
        }
        setPwSaving(true);
        try {
            await changePassword(pw.current_password, pw.new_password);
            setPw({ current_password: '', new_password: '', confirm: '' });
            setPwMsg(tr('passwordChanged'));
        } catch (err) {
            const detail = err.response?.data?.detail;
            if (detail === 'current_password_incorrect') setPwError(tr('currentPasswordWrong'));
            else if (detail === 'password_unchanged') setPwError(tr('passwordUnchanged'));
            else if (err.response?.status === 422) setPwError(tr('passwordTooShort'));
            else setPwError(typeof detail === 'string' ? detail : tr('currentPasswordWrong'));
        } finally {
            setPwSaving(false);
        }
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
            <form onSubmit={save} className="card p-4 space-y-3 text-sm">
                <label className="block">{tr('displayName')}
                    <input className="field mt-1 w-full" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
                </label>
                <label className="block">{tr('email')}
                    <input className="field mt-1 w-full" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </label>
                <label className="block">{tr('phone')}
                    <input className="field mt-1 w-full" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                </label>
                <label className="block">{tr('language')}
                    <select className="field mt-1 w-full" value={form.locale} onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                        <option value="vi">Tiếng Việt</option>
                        <option value="zh-TW">繁體中文</option>
                    </select>
                </label>
                <button className="btn min-h-11">{tr('save')}</button>
                {msg && <div className="text-teal-700 dark:text-teal-400">{msg}</div>}
            </form>
            <form onSubmit={savePassword} className="card p-4 space-y-3 text-sm">
                <h2 className="font-medium">{tr('changePassword')}</h2>
                <label className="block">{tr('currentPassword')}
                    <input type="password" autoComplete="current-password" className="field mt-1 w-full" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
                </label>
                <label className="block">{tr('newPassword')}
                    <input type="password" autoComplete="new-password" className="field mt-1 w-full" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required />
                </label>
                <label className="block">{tr('confirmPassword')}
                    <input type="password" autoComplete="new-password" className="field mt-1 w-full" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
                </label>
                <button disabled={pwSaving} className="btn min-h-11">{tr('save')}</button>
                {pwMsg && <div className="text-teal-700 dark:text-teal-400">{pwMsg}</div>}
                {pwError && <div role="alert" className="text-rose-600 dark:text-rose-400">{pwError}</div>}
            </form>
            <div className="card p-4 text-sm">
                <div className="mb-2">{tr('telegram')}: {user.telegram_bound ? tr('bound') : tr('notBound')}</div>
                <button type="button" onClick={startBind} className="btn-ghost min-h-11">{tr('bindTelegram')}</button>
                {bind && (
                    <div className="mt-3 text-slate-600 dark:text-slate-300">
                        <div>{tr('telegramCode')}: <b>{bind.code}</b></div>
                        {bind.link && <a className="text-teal-700 dark:text-teal-400 break-all" href={bind.link} target="_blank" rel="noreferrer">{bind.link}</a>}
                    </div>
                )}
            </div>
        </div>
    );
}
