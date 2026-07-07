import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { PageErrorPage } from '../troubleshooting/PageErrorPage';

interface RoleRouteProps {
  roles:    string[];
  children: React.ReactNode;
}

const RoleRoute: React.FC<RoleRouteProps> = ({ roles, children }) => {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!roles.includes(user.role)) return <PageErrorPage type="forbidden" />;
  return <>{children}</>;
};

export default RoleRoute;
