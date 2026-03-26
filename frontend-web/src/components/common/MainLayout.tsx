import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, Drawer, AppBar, Toolbar, List, Typography, Divider,
  IconButton, ListItem, ListItemButton, ListItemIcon, ListItemText,
  Badge, Avatar, Menu, MenuItem, Collapse, Chip,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard as DashboardIcon,
  SwapHoriz as SwapHorizIcon,
  Inventory as InventoryIcon,
  TrendingUp as TrendingUpIcon,
  Assessment as AssessmentIcon,
  People as PeopleIcon,
  Settings as SettingsIcon,
  Notifications as NotificationsIcon,
  ExpandLess, ExpandMore,
  Logout as LogoutIcon,
  Person as PersonIcon,
  CurrencyExchange,
  AdminPanelSettings,
} from '@mui/icons-material';
import { useAuth }      from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import NotificationPanel from './NotificationPanel';

const DRAWER_WIDTH = 240;

const menuItems = [
  {
    title: 'Dashboard',
    path:  '/dashboard',
    icon:  <DashboardIcon />,
  },
  {
    title: 'Transacciones',
    path:  '/transactions',
    icon:  <SwapHorizIcon />,
    children: [
      { title: 'Lista',           path: '/transactions' },
      { title: 'Historial',       path: '/transactions/history' },
      { title: 'Pendientes',      path: '/transactions/pending' },
    ],
  },
  {
    title: 'Clientes',
    path:  '/customers',
    icon:  <PeopleIcon />,
  },
  {
    title: 'Tasas de Cambio',
    path:  '/rates',
    icon:  <CurrencyExchange />,
  },
  {
    title: 'Inventario',
    path:  '/inventory',
    icon:  <InventoryIcon />,
    children: [
      { title: 'Stock',           path: '/inventory' },
      { title: 'Movimientos',     path: '/inventory/movements' },
      { title: 'Transferencias',  path: '/inventory/transfers' },
    ],
  },
  {
    title: 'Predicciones',
    path:  '/predictions',
    icon:  <TrendingUpIcon />,
  },
  {
    title: 'Reportes',
    path:  '/reports',
    icon:  <AssessmentIcon />,
    children: [
      { title: 'Generar',         path: '/reports' },
      { title: 'Historial',       path: '/reports/history' },
      { title: 'Programados',     path: '/reports/scheduled' },
    ],
  },
  {
    title: 'Configuración',
    path:  '/settings',
    icon:  <SettingsIcon />,
  },
  {
    title:     'Administración',
    path:      '/admin/users',
    icon:      <AdminPanelSettings />,
    adminOnly: true,
  },
];

export default function MainLayout() {
  const [mobileOpen,       setMobileOpen]       = useState(false);
  const [anchorEl,         setAnchorEl]         = useState<null | HTMLElement>(null);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [expandedItems,    setExpandedItems]    = useState<string[]>([
    '/transactions', '/inventory', '/reports',  // abiertos por defecto
  ]);

  const navigate          = useNavigate();
  const location          = useLocation();
  const { user, logout }  = useAuth();
  const { connected, alerts } = useWebSocket();

  const unreadAlerts = alerts.filter(a => !a.read).length;

  const isActive = (path: string) =>
    path === '/transactions' || path === '/inventory' || path === '/reports'
      ? location.pathname === path || location.pathname.startsWith(path + '/')
      : location.pathname.startsWith(path);

  const handleItemClick = (path: string, hasChildren: boolean) => {
    if (hasChildren) {
      setExpandedItems(prev =>
        prev.includes(path) ? prev.filter(p => p !== path) : [...prev, path]
      );
      // También navega al path padre para activar la ruta
      navigate(path);
    } else {
      navigate(path);
      setMobileOpen(false);
    }
  };

  const pageTitle = () => {
    for (const item of menuItems) {
      if (item.children) {
        const child = item.children.find(c => location.pathname === c.path);
        if (child) return `${item.title} — ${child.title}`;
      }
      if (isActive(item.path)) return item.title;
    }
    return 'Forex ERP';
  };

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Logo */}
      <Toolbar sx={{ bgcolor: 'primary.main' }}>
        <CurrencyExchange sx={{ color: 'white', mr: 1 }} />
        <Typography variant="h6" noWrap color="white" fontWeight="bold">
          Forex ERP
        </Typography>
      </Toolbar>

      {/* Usuario */}
      <Box sx={{ px: 2, py: 1.5, bgcolor: 'primary.dark' }}>
        <Typography variant="caption" color="primary.contrastText" sx={{ opacity: 0.7 }}>
          {user?.role}
        </Typography>
        <Typography variant="body2" color="white" fontWeight="medium">
          {user?.first_name} {user?.last_name}
        </Typography>
        <Typography variant="caption" color="primary.contrastText" sx={{ opacity: 0.7 }}>
          {user?.branch?.name ?? 'Sin sucursal'}
        </Typography>
      </Box>
      

      <Divider />

      {/* Menú */}
      <List sx={{ flexGrow: 1, py: 0 }}>
        {menuItems
        .filter(item => item.adminOnly ? user?.role === 'ADMIN' : true)
        .map((item) => (
          <React.Fragment key={item.path}>
            <ListItem disablePadding>
              <ListItemButton
                selected={isActive(item.path)}
                onClick={() => handleItemClick(item.path, !!item.children)}
                sx={{
                  '&.Mui-selected': {
                    bgcolor: 'primary.light',
                    '& .MuiListItemIcon-root': { color: 'primary.main' },
                    '& .MuiListItemText-primary': { fontWeight: 'bold', color: 'primary.main' },
                  },
                  '&:hover': { bgcolor: 'action.hover' },
                  py: 1,
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                <ListItemText
                  primary={item.title}
                  primaryTypographyProps={{ fontSize: 14 }}
                />
                {item.children && (
                  expandedItems.includes(item.path) ? <ExpandLess /> : <ExpandMore />
                )}
              </ListItemButton>
            </ListItem>

            {/* Subitems */}
            {item.children && (
              <Collapse in={expandedItems.includes(item.path)} timeout="auto" unmountOnExit>
                <List component="div" disablePadding>
                  {item.children.map((child) => (
                    <ListItemButton
                      key={child.path}
                      sx={{
                        pl: 6, py: 0.5,
                        '&.Mui-selected': {
                          bgcolor: 'primary.50',
                          '& .MuiListItemText-primary': { color: 'primary.main', fontWeight: 'bold' },
                        },
                      }}
                      selected={location.pathname === child.path}
                      onClick={() => { navigate(child.path); setMobileOpen(false); }}
                    >
                      <ListItemText
                        primary={child.title}
                        primaryTypographyProps={{ fontSize: 13 }}
                      />
                    </ListItemButton>
                  ))}
                </List>
              </Collapse>
            )}
          </React.Fragment>
        ))}
      </List>
        
      <Divider />

      {/* Footer del drawer */}
      <Box sx={{ p: 1 }}>
        <ListItemButton onClick={logout} sx={{ borderRadius: 1 }}>
          <ListItemIcon sx={{ minWidth: 40 }}>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary="Cerrar Sesión"
            primaryTypographyProps={{ fontSize: 13 }}
          />
        </ListItemButton>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex' }}>
      {/* AppBar */}
      <AppBar
        position="fixed"
        sx={{
          width:   { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          ml:      { sm: `${DRAWER_WIDTH}px` },
          bgcolor: 'white',
          color:   'text.primary',
          boxShadow: 1,
        }}
      >
        <Toolbar>
          <IconButton
            edge="start" color="inherit"
            onClick={() => setMobileOpen(!mobileOpen)}
            sx={{ mr: 2, display: { sm: 'none' } }}
          >
            <MenuIcon />
          </IconButton>

          <Typography variant="h6" noWrap sx={{ flexGrow: 1, fontWeight: 'bold' }}>
            {pageTitle()}
          </Typography>

          <Box display="flex" alignItems="center" gap={1.5}>
            {/* Estado conexión */}
            <Chip
              label={connected ? 'En línea' : 'Sin conexión'}
              color={connected ? 'success' : 'error'}
              size="small"
              variant="outlined"
            />

            {/* Notificaciones */}
            <IconButton color="inherit" onClick={() => setNotificationOpen(true)}>
              <Badge badgeContent={unreadAlerts} color="error">
                <NotificationsIcon />
              </Badge>
            </IconButton>

            {/* Avatar usuario */}
            <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} size="small">
              <Avatar sx={{ width: 34, height: 34, bgcolor: 'primary.main', fontSize: 14 }}>
                {user?.first_name?.[0] ?? user?.username?.[0] ?? 'U'}
              </Avatar>
            </IconButton>
          </Box>
        </Toolbar>
      </AppBar>
      
        
      {/* Menú usuario */}
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Box sx={{ px: 2, py: 1, minWidth: 180 }}>
          <Typography variant="body2" fontWeight="bold">
            {user?.first_name} {user?.last_name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {user?.email}
          </Typography>
        </Box>
        <Divider />
        <MenuItem onClick={() => { setAnchorEl(null); navigate('/settings'); }}>
          <ListItemIcon><PersonIcon fontSize="small" /></ListItemIcon>
          Mi Perfil
        </MenuItem>
        <MenuItem onClick={() => { setAnchorEl(null); logout(); }}>
          <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
          Cerrar Sesión
        </MenuItem>
      </Menu>

      {/* Drawer mobile */}
      <Box component="nav" sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}>
        <Drawer
          variant="temporary" open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH },
          }}
        >
          {drawer}
        </Drawer>

        {/* Drawer desktop */}
        <Drawer
          variant="permanent" open
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH, borderRight: '1px solid', borderColor: 'divider' },
          }}
        >
          {drawer}
        </Drawer>
      </Box>

      {/* Contenido principal */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p:        3,
          width:    { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          mt:       8,
          bgcolor:  'background.default',
          minHeight:'100vh',
        }}
      >
        <Outlet />
      </Box>

      {/* Panel notificaciones */}
      <NotificationPanel
        open={notificationOpen}
        onClose={() => setNotificationOpen(false)}
        alerts={alerts}
      />
    </Box>
  );
}