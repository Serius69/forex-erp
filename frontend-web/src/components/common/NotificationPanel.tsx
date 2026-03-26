import React from 'react';
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Chip,
  Divider,
  Button,
} from '@mui/material';
import {
  Close,
  Warning,
  Error,
  Info,
  CheckCircle,
  Delete,
} from '@mui/icons-material';
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

interface Alert {
  id: string;
  type: 'warning' | 'error' | 'info' | 'success';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
}

interface NotificationPanelProps {
  open: boolean;
  onClose: () => void;
  alerts: Alert[];
}

const NotificationPanel: React.FC<NotificationPanelProps> = ({
  open,
  onClose,
  alerts,
}) => {
  const getAlertIcon = (type: string) => {
    switch (type) {
      case 'warning':
        return <Warning color="warning" />;
      case 'error':
        return <Error color="error" />;
      case 'success':
        return <CheckCircle color="success" />;
      default:
        return <Info color="info" />;
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return 'error';
      case 'HIGH':
        return 'warning';
      case 'MEDIUM':
        return 'info';
      default:
        return 'default';
    }
  };

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{
        sx: { width: 400 },
      }}
    >
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">Notificaciones</Typography>
          <IconButton onClick={onClose}>
            <Close />
          </IconButton>
        </Box>

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Chip
            label={`${alerts.filter(a => !a.read).length} sin leer`}
            size="small"
            color="primary"
          />
          <Button size="small" startIcon={<Delete />}>
            Limpiar todas
          </Button>
        </Box>

        <Divider />

        <List>
          {alerts.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body2" color="text.secondary">
                No hay notificaciones
              </Typography>
            </Box>
          ) : (
            alerts.map((alert) => (
              <ListItem
                key={alert.id}
                sx={{
                  bgcolor: alert.read ? 'transparent' : 'action.hover',
                  borderRadius: 1,
                  mb: 1,
                }}
              >
                <ListItemIcon>{getAlertIcon(alert.type)}</ListItemIcon>
                <ListItemText
                  primary={alert.title}
                  secondary={
                    <>
                      <Typography variant="body2" color="text.secondary">
                        {alert.message}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatDistanceToNow(alert.timestamp, {
                          addSuffix: true,
                          locale: es,
                        })}
                      </Typography>
                    </>
                  }
                />
              </ListItem>
            ))
          )}
        </List>
      </Box>
    </Drawer>
  );
};

export default NotificationPanel;