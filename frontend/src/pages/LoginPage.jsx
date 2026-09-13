import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function LoginPage() {
    const { login } = useAuth();
    const [form, setForm] = useState({ username: '', password: '' });
    const [locale, setLocale] = useState('zh-TW');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const tr = (k) => t(locale, k);

    const submit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await login(form.username, form.password);
        } catch {
            setError(tr('loginFailed'));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
            <form onSubmit={submit} className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-8 space-y-4">
                <div className="flex justify-between items-center">
                    <h1 className="text-xl font-semibold text-teal-400">Uni-Shrimp</h1>
                    <select
                        className="bg-slate-800 text-xs rounded px-2 py-1"
                        value={locale}
                        onChange={(e) => setLocale(e.target.value)}
                    >
                        <option value="vi">VI</option>
                        <option value="zh-TW">中文</option>
                    </select>
                </div>
                {error && <div className="text-rose-400 text-sm">{error}</div>}
                <label className="block text-sm">
                    {tr('username')}
                    <input
                        className="mt-1 w-full bg-slate-800 rounded px-3 py-2"
                        value={form.username}
                        onChange={(e) => setForm({ ...form, username: e.target.value })}
                    />
                </label>
                <label className="block text-sm">
                    {tr('password')}
                    <input
                        type="password"
                        className="mt-1 w-full bg-slate-800 rounded px-3 py-2"
                        value={form.password}
                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                    />
                </label>
                <button disabled={loading} className="w-full bg-teal-600 hover:bg-teal-500 rounded py-2 font-medium">
                    {tr('login')}
                </button>
            </form>
        </div>
    );
}
