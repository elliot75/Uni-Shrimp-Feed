import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import ThemeToggle from './ThemeToggle';
import { t } from '../i18n';

const linkClass = ({ isActive }) =>
    `block px-3 py-2.5 rounded-lg text-sm min-h-11 ${
        isActive
            ? 'bg-teal-700 text-white'
            : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
    }`;

export default function Layout() {
    const { user, logout, updateMe } = useAuth();
    const nav = useNavigate();
    const location = useLocation();
    const [menuOpen, setMenuOpen] = useState(false);
    const locale = user?.locale || 'vi';
    const tr = (k) => t(locale, k);
    const closeMenu = () => setMenuOpen(false);

    useEffect(() => {
        setMenuOpen(false);
    }, [location.pathname]);

    const onLocale = async (next) => {
        await updateMe({ locale: next });
    };

    const links = (
        <nav className="flex flex-col gap-1">
            <NavLink to="/" end className={linkClass} onClick={closeMenu}>{tr('dashboard')}</NavLink>
            <NavLink to="/ponds" className={linkClass} onClick={closeMenu}>{tr('ponds')}</NavLink>
            <NavLink to="/alerts" className={linkClass} onClick={closeMenu}>{tr('alerts')}</NavLink>
            <NavLink to="/devices" className={linkClass} onClick={closeMenu}>{tr('devices')}</NavLink>
            {user?.role === 'admin' && <NavLink to="/users" className={linkClass} onClick={closeMenu}>{tr('users')}</NavLink>}
            {user?.role === 'admin' && <NavLink to="/rules" className={linkClass} onClick={closeMenu}>{tr('rules')}</NavLink>}
            <NavLink to="/profile" className={linkClass} onClick={closeMenu}>{tr('profile')}</NavLink>
        </nav>
    );

    const footer = (
        <div className="mt-auto space-y-2">
            <div className="flex items-center gap-2">
                <select
                    className="field flex-1 text-xs min-h-11"
                    value={locale}
                    onChange={(e) => onLocale(e.target.value)}
                >
                    <option value="vi">Tiếng Việt</option>
                    <option value="zh-TW">繁體中文</option>
                </select>
                <div className="hidden md:block">
                    <ThemeToggle locale={locale} />
                </div>
            </div>
            <button
                type="button"
                className="w-full text-left text-sm text-slate-500 dark:text-slate-400 hover:text-teal-700 dark:hover:text-white min-h-11"
                onClick={() => { logout(); nav('/login'); }}
            >
                {tr('logout')}
            </button>
        </div>
    );

    return (
        <div className="min-h-screen flex bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
            {menuOpen && (
                <button
                    type="button"
                    className="fixed inset-0 bg-black/40 z-40 md:hidden"
                    aria-label={tr('closeMenu')}
                    onClick={closeMenu}
                />
            )}
            <aside
                className={`fixed inset-y-0 left-0 z-50 w-60 flex flex-col gap-4 p-4 bg-white dark:bg-slate-950 border-r border-slate-200 dark:border-slate-800 transform transition-transform duration-200 ${
                    menuOpen ? 'translate-x-0' : '-translate-x-full'
                } md:static md:translate-x-0 md:flex md:shrink-0`}
            >
                <div>
                    <div className="text-lg font-semibold text-teal-700 dark:text-teal-400">Uni-Shrimp</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{user?.display_name} · {tr(user?.role)}</div>
                </div>
                {links}
                {footer}
            </aside>
            <div className="flex-1 min-w-0 flex flex-col">
                <header className="md:hidden sticky top-0 z-30 flex items-center gap-2 px-3 py-2 bg-white/95 dark:bg-slate-950/95 backdrop-blur border-b border-slate-200 dark:border-slate-800">
                    <button
                        type="button"
                        className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 min-h-11 min-w-11"
                        onClick={() => setMenuOpen(true)}
                        aria-label={tr('menu')}
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                        </svg>
                    </button>
                    <div className="font-semibold text-teal-700 dark:text-teal-400 flex-1">Uni-Shrimp</div>
                    <ThemeToggle locale={locale} />
                </header>
                <main className="flex-1 p-4 md:p-6 overflow-auto">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}
