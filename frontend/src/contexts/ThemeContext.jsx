import { createContext, useContext, useEffect, useState } from 'react';

const STORAGE_KEY = 'uni_shrimp_theme';
const ThemeContext = createContext({ theme: 'light', toggleTheme: () => {} });

function readTheme() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === 'dark' || saved === 'light') return saved;
    } catch {
        /* ignore */
    }
    return 'light';
}

function applyTheme(theme) {
    const root = document.documentElement;
    root.classList.toggle('dark', theme === 'dark');
    root.dataset.theme = theme;
}

export function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(readTheme);

    useEffect(() => {
        applyTheme(theme);
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch {
            /* ignore */
        }
    }, [theme]);

    const toggleTheme = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'));

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    );
}

export const useTheme = () => useContext(ThemeContext);
