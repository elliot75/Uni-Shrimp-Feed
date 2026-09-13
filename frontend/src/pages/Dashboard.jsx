import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

function badge(severity) {
    if (severity === 'critical') return 'bg-rose-600';
    if (severity === 'warn') return 'bg-amber-500';
    return 'bg-slate-700';
}

export default function Dashboard() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [data, setData] = useState({ ponds: [], stats: {} });

    useEffect(() => {
        api.get('/dashboard').then((res) => setData(res.data));
    }, []);

    return (
        <div>
            <h1 className="text-2xl font-semibold mb-4">{tr('dashboard')}</h1>
            <div className="flex gap-4 mb-6">
                <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
                    <div className="text-xs text-slate-400">{tr('openAlerts')}</div>
                    <div className="text-2xl">{data.stats.open_count || 0}</div>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-xl px-4 py-3">
                    <div className="text-xs text-slate-400">{tr('critical')}</div>
                    <div className="text-2xl text-rose-400">{data.stats.critical_count || 0}</div>
                </div>
            </div>
            {data.ponds.length === 0 && <p className="text-slate-400">{tr('noPonds')}</p>}
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
                {data.ponds.map((p) => (
                    <Link key={p.id} to={`/ponds/${p.id}`} className="block bg-slate-900 border border-slate-800 rounded-xl p-4 hover:border-teal-600">
                        <div className="flex justify-between items-start">
                            <div>
                                <div className="font-semibold">{p.code} · {p.name}</div>
                                <div className="text-xs text-slate-400">{p.farmer_name} · {tr(p.pond_type)}</div>
                            </div>
                            {p.open_alerts > 0 && (
                                <span className={`text-xs px-2 py-1 rounded ${badge(p.worst_severity)}`}>{p.open_alerts}</span>
                            )}
                        </div>
                        <div className="grid grid-cols-4 gap-2 mt-4 text-sm">
                            <div><div className="text-slate-400 text-xs">{tr('ph')}</div>{p.ph ?? '—'}</div>
                            <div><div className="text-slate-400 text-xs">{tr('salinity')}</div>{p.salinity_ppt ?? '—'}</div>
                            <div><div className="text-slate-400 text-xs">{tr('do')}</div>{p.do_mg_l ?? '—'}</div>
                            <div><div className="text-slate-400 text-xs">{tr('temp')}</div>{p.temp_c ?? '—'}</div>
                        </div>
                    </Link>
                ))}
            </div>
        </div>
    );
}
