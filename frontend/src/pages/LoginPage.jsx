import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import ThemeToggle from '../components/ThemeToggle';
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
        <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 p-4">
            <form onSubmit={submit} className="card w-full max-w-sm p-6 sm:p-8 space-y-4">
                <div className="flex justify-between items-center gap-2">
                    <h1 className="text-xl font-semibold text-teal-700 dark:text-teal-400">Uni-Shrimp</h1>
                    <div className="flex items-center gap-2">
                        <select
                            className="field text-xs py-1 px-2"
                            value={locale}
                            onChange={(e) => setLocale(e.target.value)}
                        >
                            <option value="vi">VI</option>
                            <option value="zh-TW">中文</option>
                        </select>
                        <ThemeToggle locale={locale} />
                    </div>
                </div>
                {error && <div className="text-rose-600 dark:text-rose-400 text-sm">{error}</div>}
                <label className="block text-sm">
                    {tr('username')}
                    <input
                        className="field mt-1 w-full"
                        autoComplete="username"
                        value={form.username}
                        onChange={(e) => setForm({ ...form, username: e.target.value })}
                    />
                </label>
                <label className="block text-sm">
                    {tr('password')}
                    <input
                        type="password"
                        className="field mt-1 w-full"
                        autoComplete="current-password"
                        value={form.password}
                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                    />
                </label>
                <button disabled={loading} className="btn w-full min-h-11">
                    {tr('login')}
                </button>
            </form>
        </div>
    );
}
