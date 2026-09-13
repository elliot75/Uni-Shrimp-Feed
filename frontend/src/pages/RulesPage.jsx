import { useEffect, useState } from 'react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

export default function RulesPage() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [rules, setRules] = useState([]);
    const [error, setError] = useState('');

    const load = () => api.get('/alert-rules').then((r) => setRules(r.data));
    useEffect(() => { load(); }, []);

    const save = async (rule, patch) => {
        try {
            await api.patch(`/alert-rules/${rule.id}`, patch);
            setError('');
            await load();
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : err.message);
        }
    };

    return (
        <div>
            <h1 className="text-2xl font-semibold mb-4">{tr('rules')}</h1>
            {error && <p role="alert" className="text-rose-400 mb-4">{error}</p>}
            <div className="space-y-2">
                {rules.map((r) => (
                    <div key={r.id} className="bg-slate-900 border border-slate-800 rounded-xl p-4 grid md:grid-cols-6 gap-2 text-sm items-center">
                        <div className="font-mono text-teal-400">{r.code}</div>
                        <label>{tr('min')}
                            <input className="w-full bg-slate-800 rounded px-2 py-1" defaultValue={r.min_value ?? ''} onBlur={(e) => save(r, { min_value: e.target.value === '' ? null : Number(e.target.value) })} />
                        </label>
                        <label>{tr('max')}
                            <input className="w-full bg-slate-800 rounded px-2 py-1" defaultValue={r.max_value ?? ''} onBlur={(e) => save(r, { max_value: e.target.value === '' ? null : Number(e.target.value) })} />
                        </label>
                        <select className="bg-slate-800 rounded px-2 py-1" value={r.severity} onChange={(e) => save(r, { severity: e.target.value })}>
                            <option value="info">{tr('info')}</option>
                            <option value="warn">{tr('warn')}</option>
                            <option value="critical">{tr('critical')}</option>
                        </select>
                        <label className="flex items-center gap-2">
                            <input type="checkbox" checked={r.is_active} onChange={(e) => save(r, { is_active: e.target.checked })} />
                            {tr('enabled')}
                        </label>
                    </div>
                ))}
            </div>
        </div>
    );
}
