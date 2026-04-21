import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { Box, Typography } from '@mui/material';
import { LockOutlined } from '@mui/icons-material';

interface RoleRouteProps {
  roles:    string[];
  children: React.ReactNode;
}

const RoleRoute: React.FC<RoleRouteProps> = ({ roles, children }) => {
  const { user } = useAuth();

  if (!user) return <Navigate to="/login" replace />;

  if (!roles.includes(user.role)) {
    return (
      <Box
        display="flex" flexDirection="column"
        alignItems="center" justifyContent="center"
        height="60vh" gap={2}
      >
        <LockOutlined sx={{ fontSize: 56, color: 'text.disabled' }} />
        <Typography variant="h6" color="text.secondary" fontWeight={600}>
          Acceso restringido
        </Typography>
        <Typography variant="body2" color="text.disabled">
          Tu rol <strong>{user.role}</strong> no tiene permiso para esta sección.
        </Typography>
      </Box>
    );
  }

  return <>{children}</>;
};

export default RoleRoute;
