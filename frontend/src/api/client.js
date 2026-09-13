import axios from 'axios';

const api = axios.create({
    baseURL: '/api',
    headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
    const token = localStorage.getItem('uni_shrimp_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});

api.interceptors.response.use(
    (res) => res,
    (err) => {
        if (err.response?.status === 401) {
            localStorage.removeItem('uni_shrimp_token');
            localStorage.removeItem('uni_shrimp_user');
            if (window.location.pathname !== '/login') window.location.href = '/login';
        }
        return Promise.reject(err);
    }
);

export default api;
