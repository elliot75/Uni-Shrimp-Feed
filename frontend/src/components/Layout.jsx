import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n';

const linkClass = ({ isActive }) =>
    `block px-3 py-2 rounded-lg text-sm ${isActive ? 'bg-teal-700 text-white' : 'text-slate-300 hover:bg-slate-800'}`;

export default function Layout() {
    const { user, logout, updateMe } = useAuth();
    const nav = useNavigate();
    const locale = user?.locale || 'vi';
    const tr = (k) => t(locale, k);

    const onLocale = async (next) => {
        await updateMe({ locale: next });
    };

    return (
        <div className="min-h-screen flex bg-slate-950 text-slate-100">
            <aside className="w-56 shrink-0 border-r border-slate-800 p-4 flex flex-col gap-4">
                <div>
                    <div className="text-lg font-semibold text-teal-400">Uni-Shrimp</div>
                    <div className="text-xs text-slate-400 mt-1">{user?.display_name} · {tr(user?.role)}</div>
                </div>
                <nav className="flex flex-col gap-1">
                    <NavLink to="/" end className={linkClass}>{tr('dashboard')}</NavLink>
                    <NavLink to="/ponds" className={linkClass}>{tr('ponds')}</NavLink>
                    <NavLink to="/alerts" className={linkClass}>{tr('alerts')}</NavLink>
                    <NavLink to="/devices" className={linkClass}>{tr('devices')}</NavLink>
                    {user?.role === 'admin' && <NavLink to="/users" className={linkClass}>{tr('users')}</NavLink>}
                    {user?.role === 'admin' && <NavLink to="/rules" className={linkClass}>{tr('rules')}</NavLink>}
                    <NavLink to="/profile" className={linkClass}>{tr('profile')}</NavLink>
                </nav>
                <div className="mt-auto space-y-2">
                    <select
                        className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                        value={locale}
                        onChange={(e) => onLocale(e.target.value)}
                    >
                        <option value="vi">Tiếng Việt</option>
                        <option value="zh-TW">繁體中文</option>
                    </select>
                    <button
                        className="w-full text-left text-xs text-slate-400 hover:text-white"
                        onClick={() => { logout(); nav('/login'); }}
                    >
                        {tr('logout')}
                    </button>
                </div>
            </aside>
            <main className="flex-1 p-6 overflow-auto">
                <Outlet />
            </main>
        </div>
    );
}
