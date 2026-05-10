import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import './App.css';
import AccountantDashboard from './components/AccountantDashboard';

// We will create these actual page components next!
// For now, these are just simple placeholders so the router works.
const Login = () => <h2>Login Page (Enter credentials here)</h2>;
const AdminDashboard = () => <h2>Admin Dashboard (Monitor Logs & Users)</h2>;

function App() {
  return (
    <Router>
      <div className="app-container">
        {/* A simple navigation bar just to help us test */}
        <nav style={{ padding: '10px', background: '#eee', marginBottom: '20px' }}>
          <strong>Diva Software OCR </strong> | 
          <a href="/login" style={{ margin: '0 10px' }}>Login</a> | 
          <a href="/accountant" style={{ margin: '0 10px' }}>Accountant</a> | 
          <a href="/admin" style={{ margin: '0 10px' }}>Admin</a>
        </nav>

        {/* The Routes handle which page to show based on the URL */}
        <Routes>
          <Route path="/" element={<Navigate to="/login" />} />
          <Route path="/login" element={<Login />} />
          <Route path="/accountant" element={<AccountantDashboard />} />
          <Route path="/admin" element={<AdminDashboard />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;