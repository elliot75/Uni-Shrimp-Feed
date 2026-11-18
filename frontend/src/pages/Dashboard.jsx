import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';
import ProbeSummary from '../components/ProbeSummary';
import ReadingRange from '../components/ReadingRange';
import { formatFarmTime } from '../utils/time';

function badge(severity) {
    if (severity === 'critical') return 'bg-rose-600 text-white';
    if (severity === 'warn') return 'bg-amber-500 text-white';
    return 'bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100';
}

export default function Dashboard() {
    const { user } = useAuth();
    const tr = (k) => t(user?.locale || 'vi', k);
    const [data, setData] = useState({ ponds: [], stats: {} });

    const [range, setRange] = useState({ range: 'all' });
    const [loading, setLoading] = useState(true);
    const [readingsError, setReadingsError] = useState(false);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setReadingsError(false);
        api.get('/dashboard', { params: range, signal: controller.signal })
            .then(({ data }) => { if (!controller.signal.aborted) setData(data); })
            .catch(() => { if (!controller.signal.aborted) setReadingsError(true); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [range]);

    return (
        <div>
            <h1 className="text-2xl font-semibold mb-4">{tr('dashboard')}</h1>
            <div className="flex flex-wrap gap-4 mb-6">
                <div className="card px-4 py-3 flex-1 min-w-[8.5rem]">
                    <div className="text-xs muted">{tr('openAlerts')}</div>
                    <div className="text-2xl">{data.stats.open_count || 0}</div>
                </div>
                <div className="card px-4 py-3 flex-1 min-w-[8.5rem]">
                    <div className="text-xs muted">{tr('critical')}</div>
                    <div className="text-2xl text-rose-600 dark:text-rose-400">{data.stats.critical_count || 0}</div>
                </div>
            </div>
            <div className="mb-4"><ReadingRange value={range} onChange={setRange} tr={tr} /></div>
            {readingsError && <p role="alert" className="text-sm text-rose-600">{tr('readingsLoadFailed')}</p>}
            {!loading && !readingsError && data.ponds.length === 0 && <p className="muted">{tr('noPonds')}</p>}
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {data.ponds.map((p) => (
                    <Link key={p.id} to={`/ponds/${p.id}`} className="card block p-4 hover:border-teal-600">
                        <div className="flex justify-between items-start gap-2">
                            <div className="min-w-0">
                                <div className="font-semibold break-words">{p.code} · {p.name}</div>
                                <div className="text-xs muted">{p.farmer_name} · {tr(p.pond_type)}</div>
                            </div>
                            {p.open_alerts > 0 && (
                                <span className={`text-xs px-2 py-1 rounded shrink-0 ${badge(p.worst_severity)}`}>{p.open_alerts}</span>
                            )}
                        </div>
                        <div className="mt-4">
                            <ProbeSummary reading={loading || readingsError ? null : p} tr={tr} />
                            {!loading && !readingsError && (
                                <p className="muted text-xs mt-2">{p.recorded_at ? formatFarmTime(p.recorded_at, user?.locale) : tr('noData')}</p>
                            )}
                        </div>
                    </Link>
                ))}
            </div>
        </div>
    );
}
