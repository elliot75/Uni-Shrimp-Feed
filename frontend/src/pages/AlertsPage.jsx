import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function AlertsPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [rows, setRows] = useState([]);
    const [status, setStatus] = useState('open');
    const msg = user?.locale === 'zh-TW' ? 'message_zh' : 'message_vi';

    const load = () => api.get('/alerts', { params: { status } }).then((r) => setRows(r.data));
    useEffect(() => { load(); }, [status]);

    const ack = async (id) => {
        await api.post(`/alerts/${id}/ack`);
        load();
    };

    return (
        <div>
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3 mb-4">
                <h1 className="text-2xl font-semibold">{tr('alerts')}</h1>
                <select className="field w-full sm:w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
                    <option value="open">{tr('open')}</option>
                    <option value="all">{tr('all')}</option>
                </select>
            </div>
            <div className="space-y-2">
                {rows.map((a) => (
                    <div key={a.id} className="card p-4 flex flex-col sm:flex-row sm:justify-between gap-3">
                        <div className="min-w-0">
                            <Link to={`/ponds/${a.pond_id}`} className="text-teal-700 dark:text-teal-400 text-sm">{a.pond_code}</Link>
                            <div className="break-words">{a[msg]}</div>
                            <div className="text-xs muted">{a.severity} · {a.opened_at?.slice(0, 16)}</div>
                        </div>
                        {!a.acknowledged_at && !a.resolved_at && (
                            <button onClick={() => ack(a.id)} className="btn-ghost text-xs min-h-11 shrink-0">{tr('ack')}</button>
                        )}
                    </div>
                ))}
                {rows.length === 0 && <p className="muted">{tr('noData')}</p>}
            </div>
        </div>
    );
}
