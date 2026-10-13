import { createContext, useContext, useState } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(() => {
        const saved = localStorage.getItem('uni_shrimp_user');
        return saved ? JSON.parse(saved) : null;
    });

    const login = async (username, password) => {
        const res = await api.post('/auth/login', { username, password });
        localStorage.setItem('uni_shrimp_token', res.data.access_token);
        localStorage.setItem('uni_shrimp_user', JSON.stringify(res.data.user));
        setUser(res.data.user);
        return res.data.user;
    };

    const logout = () => {
        localStorage.removeItem('uni_shrimp_token');
        localStorage.removeItem('uni_shrimp_user');
        setUser(null);
    };

    const refreshMe = async () => {
        const res = await api.get('/auth/me');
        const next = { ...user, ...res.data, telegram_bound: res.data.telegram_bound };
        localStorage.setItem('uni_shrimp_user', JSON.stringify(next));
        setUser(next);
        return next;
    };

    const updateMe = async (payload) => {
        const res = await api.patch('/auth/me', payload);
        const next = { ...user, ...res.data };
        localStorage.setItem('uni_shrimp_user', JSON.stringify(next));
        setUser(next);
        return next;
    };

    const changePassword = async (current_password, new_password) => {
        await api.post('/auth/me/password', { current_password, new_password });
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, refreshMe, updateMe, changePassword, setUser }}>
            {children}
        </AuthContext.Provider>
    );
}

export const useAuth = () => useContext(AuthContext);
