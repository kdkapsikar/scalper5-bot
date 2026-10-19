import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import { useAuth } from './context/Auth.jsx';
import Account from './pages/Account.jsx';
import Admin from './pages/Admin.jsx';
import Backtest from './pages/Backtest.jsx';
import Connect from './pages/Connect.jsx';
import Landing from './pages/Landing.jsx';
import Mood from './pages/Mood.jsx';
import Scanner from './pages/Scanner.jsx';
import SignIn from './pages/SignIn.jsx';
import UpstoxCallback from './pages/UpstoxCallback.jsx';

function Home() {
  // Someone with nothing connected yet lands on Connect first.
  const { connections } = useAuth();
  const ready = connections?.upstox?.token || connections?.coinswitch;
  return <Navigate to={ready ? '/app/scanner' : '/app/connect'} replace />;
}

function AdminOnly({ children }) {
  const { user } = useAuth();
  return user?.is_admin ? children : <Navigate to="/app" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/signin" element={<SignIn />} />
      <Route path="/upstox/callback" element={<UpstoxCallback />} />
      <Route path="/app" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="scanner" element={<Scanner />} />
        <Route path="mood" element={<Mood />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="connect" element={<Connect />} />
        <Route path="account" element={<Account />} />
        <Route path="admin" element={<AdminOnly><Admin /></AdminOnly>} />
      </Route>
      <Route path="*" element={
        <div className="grid min-h-screen place-items-center text-center">
          <div><h1 className="page-title">Page not found</h1><Link className="btn primary mt-3" to="/">Go home</Link></div>
        </div>} />
    </Routes>
  );
}
