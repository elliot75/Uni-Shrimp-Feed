import { useEffect, useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function AnnouncementsPage() {
    const { user } = useAuth();
    const tr = (key) => t(user?.locale || 'vi', key);
    const [users, setUsers] = useState([]);
    const [scope, setScope] = useState('all');
    const [selected, setSelected] = useState([]);
    const [message, setMessage] = useState('');
    const [loading, setLoading] = useState(true);
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState(null);
    const [job, setJob] = useState(() => {
        try { return JSON.parse(localStorage.getItem(`announcement_job_${user.id}`) || 'null'); }
        catch { return null; }
    });

    useEffect(() => {
        api.get('/users').then(({ data }) => setUsers(data.filter((u) => u.is_active && u.telegram_bound)))
            .catch(() => setError('announcementLoadError')).finally(() => setLoading(false));
    }, []);

    const recipients = users.filter((u) => scope === 'all' || (scope === 'selected' ? selected.includes(u.id) : u.role === scope));
    const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
    const submitJob = async (payload) => {
        try {
            const response = await api.post('/announcements/telegram', payload);
            setResult(response.data);
            setError('');
        } catch (err) {
            if ([409, 422, 503].includes(err.response?.status)) {
                localStorage.removeItem(`announcement_job_${user.id}`);
                setJob(null);
            }
            setError(err.response?.status === 409 ? 'announcementChanged' : err.response?.status === 503 ? 'announcementBotMissing' : 'announcementSendError');
        }
    };

    useEffect(() => {
        if (!job) return;
        let cancelled = false;
        const refresh = async () => {
            try {
                const response = await api.get(`/announcements/telegram/${job.id}`);
                if (!cancelled) { setResult(response.data); setError(''); }
            } catch (err) {
                if (!cancelled && err.response?.status === 404) await submitJob(job);
                else if (!cancelled) setError('announcementSendError');
            }
        };
        refresh();
        const timer = window.setInterval(refresh, 5000);
        return () => { cancelled = true; window.clearInterval(timer); };
    }, [job]);

    const send = async (e) => {
        e.preventDefault();
        if (sending || !message.trim() || !recipients.length) return;
        const names = recipients.map((u) => `${u.display_name || u.username} (${u.username})`).join('\n');
        if (!window.confirm(`${tr('announcementConfirm')} ${recipients.length} ${tr('announcementPeople')}?\n\n${names}\n\n${message.trim()}`)) return;
        setSending(true);
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
        const hex = [...bytes].map((n) => n.toString(16).padStart(2, '0')).join('');
        const id = `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
        const payload = { id, message: message.trim(), user_ids: recipients.map((u) => u.id) };
        localStorage.setItem(`announcement_job_${user.id}`, JSON.stringify(payload));
        setError('');
        setResult(null);
        setJob(payload);
        setSending(false);
    };

    return (
        <div className="max-w-2xl space-y-4">
            <h1 className="text-2xl font-semibold">{tr('telegramAnnouncement')}</h1>
            <form onSubmit={send} className="card p-4 space-y-4 text-sm">
                <label className="block">{tr('announcementRecipients')}
                    <select className="field mt-1 w-full" value={scope} onChange={(e) => setScope(e.target.value)} disabled={sending}>
                        <option value="all">{tr('announcementAll')}</option>
                        <option value="farmer">{tr('farmer')}</option>
                        <option value="salesperson">{tr('salesperson')}</option>
                        <option value="admin">{tr('admin')}</option>
                        <option value="selected">{tr('announcementSelected')}</option>
                    </select>
                </label>
                <p className="muted">{tr('announcementEligible')}</p>
                {scope === 'selected' && <div className="max-h-60 overflow-y-auto space-y-1 border border-slate-200 dark:border-slate-700 rounded p-2">
                    {users.map((u) => <label key={u.id} className="flex items-center gap-2 py-1">
                        <input type="checkbox" checked={selected.includes(u.id)} onChange={() => toggle(u.id)} disabled={sending} />
                        <span className="break-words">{u.display_name || u.username} · {u.username} · {tr(u.role)}</span>
                    </label>)}
                </div>}
                <p>{tr('announcementCount')}: <strong>{recipients.length}</strong></p>
                {!loading && !recipients.length && <p className="muted">{tr('announcementNoRecipients')}</p>}
                <label className="block">{tr('announcementContent')}
                    <textarea required maxLength={3000} rows={6} className="field mt-1 w-full" value={message} onChange={(e) => setMessage(e.target.value)} disabled={sending} />
                </label>
                <button className="btn min-h-11" disabled={loading || sending || (job && !result) || result?.recipients.some((r) => r.status === 'pending' || r.status === 'processing') || !recipients.length || !message.trim()}>{tr('announcementSend')}</button>
                {error && <p role="alert" className="text-rose-600 dark:text-rose-400">{tr(error)}</p>}
                {result && <div role="status" className="space-y-1">
                    <p>{tr('announcementProgress')}</p>
                    {['pending', 'processing', 'sent', 'skipped', 'unknown'].map((status) => {
                        const entries = result.recipients.filter((r) => r.status === status);
                        return entries.length > 0 && <p key={status}>{tr(`announcement_${status}`)}: {entries.length}{['skipped', 'unknown'].includes(status) && ` — ${entries.map((r) => `${r.name} (${r.username})`).join(', ')}`}</p>;
                    })}
                    {result.recipients.some((r) => r.status === 'unknown') && <p>{tr('announcementFailureAdvice')}</p>}
                </div>}
            </form>
        </div>
    );
}
