import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import Dashboard from './pages/Dashboard';
import PondDetail from './pages/PondDetail';
import PondsPage from './pages/PondsPage';
import AlertsPage from './pages/AlertsPage';
import UsersPage from './pages/UsersPage';
import DevicesPage from './pages/DevicesPage';
import ProfilePage from './pages/ProfilePage';
import RulesPage from './pages/RulesPage';

function Protected({ children, roles }) {
    const { user } = useAuth();
    if (!user) return <Navigate to="/login" replace />;
    if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
    return children;
}

function AppRoutes() {
    const { user } = useAuth();
    return (
        <Routes>
            <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
            <Route
                path="/"
                element={
                    <Protected>
                        <Layout />
                    </Protected>
                }
            >
                <Route index element={<Dashboard />} />
                <Route path="ponds" element={<PondsPage />} />
                <Route path="ponds/:id" element={<PondDetail />} />
                <Route path="alerts" element={<AlertsPage />} />
                <Route path="devices" element={<DevicesPage />} />
                <Route path="profile" element={<ProfilePage />} />
                <Route
                    path="users"
                    element={
                        <Protected roles={['admin']}>
                            <UsersPage />
                        </Protected>
                    }
                />
                <Route
                    path="rules"
                    element={
                        <Protected roles={['admin']}>
                            <RulesPage />
                        </Protected>
                    }
                />
            </Route>
        </Routes>
    );
}

export default function App() {
    return (
        <BrowserRouter>
            <AuthProvider>
                <AppRoutes />
            </AuthProvider>
        </BrowserRouter>
    );
}
