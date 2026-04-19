// src/components/common/MainLayout.tsx
import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, AppBar, Toolbar, Typography, IconButton,
  Avatar, Menu, MenuItem, Divider, Chip,
  Badge, Drawer, List, ListItemButton, ListItemIcon,
  ListItemText, Collapse, Tooltip,
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  SwapHoriz,
  Inventory2,
  Assessment,
  People,
  Settings,
  Notifications,
  ExpandLess, ExpandMore,
  Logout,
  Person,
  CurrencyExchange,
  AdminPanelSettings,
  Menu as MenuIcon,
  ChevronLeft,
  Circle,
} from '@mui/icons-material';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import NotificationPanel from './NotificationPanel';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';

const DRAWER_W   = 252;
const COLLAPSED_W = 68;

// ── Nav config ────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  {
    id: 'dashboard', label: 'Dashboard', path: '/dashboard',
    icon: <DashboardIcon fontSize="small" />,
  },
  {
    id: 'operaciones', label: 'Operaciones', path: '/transactions',
    icon: <SwapHoriz fontSize="small" />,
    children: [
      { label: 'Transacciones', path: '/transactions' },
      { label: 'Aprobaciones',  path: '/transactions/pending' },
    ],
  },
  {
    id: 'inventory', label: 'Inventario', path: '/inventory',
    icon: <Inventory2 fontSize="small" />,
    children: [
      { label: 'Resumen',        path: '/inventory' },
      { label: 'Movimientos',    path: '/inventory/movements' },
      { label: 'Transferencias', path: '/inventory/transfers' },
    ],
  },
  {
    id: 'rates', label: 'Tasas de Cambio', path: '/rates',
    icon: <CurrencyExchange fontSize="small" />,
  },
  {
    id: 'customers', label: 'Clientes', path: '/customers',
    icon: <People fontSize="small" />,
  },
  {
    id: 'reports', label: 'Reportes', path: '/reports',
    icon: <Assessment fontSize="small" />,
  },
];

// Titles for routes not listed in NAV_ITEMS (still accessible via direct links)
const EXTRA_TITLES: Record<string, string> = {
  '/ganancias':  'Ganancias',
  '/analytics':  'Analytics',
  '/executive':  'CEO Dashboard',
  '/tarjetas':   'Tarjetas',
  '/capital':    'Capital & Gastos',
  '/predictions':'Predicciones',
  '/import':     'Importar Datos',
  '/alertas':    'Alertas',
  '/decisiones': 'Motor IA',
};

const BOTTOM_ITEMS = [
  { id: 'settings', label: 'Configuración', path: '/settings', icon: <Settings fontSize="small" /> },
  {
    id: 'admin', label: 'Administración', path: '/admin/users',
    icon: <AdminPanelSettings fontSize="small" />, adminOnly: true,
    children: [
      { label: 'Usuarios',      path: '/admin/users' },
      { label: 'Auditoría',     path: '/admin/audit' },
      { label: 'Mantenimiento', path: '/admin/maintenance' },
    ],
  },
];

// ── Role badge ────────────────────────────────────────────────────────────────
const ROLE_COLOR: Record<string, string> = {
  ADMIN:       TOKENS.red,
  SUPERVISOR:  TOKENS.amber,
  CASHIER:     TOKENS.green,
};
const ROLE_LABEL: Record<string, string> = {
  ADMIN: 'Admin', SUPERVISOR: 'Supervisor', CASHIER: 'Cajero',
};

// ── NavItem ───────────────────────────────────────────────────────────────────
const NavItem = ({
  item, active, collapsed, expanded, onToggle, onNavigate, badge,
}: {
  item: typeof NAV_ITEMS[0];
  active: (path: string) => boolean;
  collapsed: boolean;
  expanded: string[];
  onToggle: (id: string) => void;
  onNavigate: (path: string) => void;
  badge?: number;
}) => {
  const isActive  = active(item.path);
  const isExpanded = expanded.includes(item.id);
  const hasChildren = !!item.children;

  const itemContent = (
    <ListItemButton
      selected={isActive && !hasChildren}
      onClick={() => hasChildren ? onToggle(item.id) : onNavigate(item.path)}
      sx={{
        mx: 1, mb: 0.25, borderRadius: '8px',
        minHeight: 40,
        color: isActive ? 'white' : alpha('#fff', 0.6),
        backgroundColor: isActive && !hasChildren ? alpha(TOKENS.blue, 0.9) : 'transparent',
        '&:hover': {
          backgroundColor: isActive && !hasChildren
            ? alpha(TOKENS.blue, 1)
            : alpha('#fff', 0.07),
          color: 'white',
        },
        '&.Mui-selected': {
          backgroundColor: alpha(TOKENS.blue, 0.9),
          '&:hover': { backgroundColor: alpha(TOKENS.blue, 1) },
        },
        px: collapsed ? 1.5 : 1.5,
        justifyContent: collapsed ? 'center' : 'flex-start',
        transition: 'all 0.15s ease',
      }}
    >
      <ListItemIcon sx={{
        minWidth: collapsed ? 0 : 34,
        color: isActive ? 'white' : alpha('#fff', 0.55),
        justifyContent: 'center',
      }}>
        <Badge badgeContent={badge || 0} color="error" max={9}
          sx={{ '& .MuiBadge-badge': { fontSize: '0.6rem', height: 14, minWidth: 14 } }}>
          {item.icon}
        </Badge>
      </ListItemIcon>
      {!collapsed && (
        <>
          <ListItemText
            primary={item.label}
            primaryTypographyProps={{ fontSize: '0.8125rem', fontWeight: isActive ? 700 : 500 }}
            sx={{ m: 0 }}
          />
          {hasChildren && (isExpanded ? <ExpandLess sx={{ fontSize: 16, opacity: 0.6 }} /> : <ExpandMore sx={{ fontSize: 16, opacity: 0.6 }} />)}
        </>
      )}
    </ListItemButton>
  );

  return (
    <>
      {collapsed
        ? <Tooltip title={item.label} placement="right" arrow>{itemContent}</Tooltip>
        : itemContent
      }

      {/* Children */}
      {hasChildren && !collapsed && (
        <Collapse in={isExpanded} timeout="auto">
          <List disablePadding sx={{ pl: 2.5 }}>
            {item.children!.map(child => (
              <ListItemButton
                key={child.path}
                selected={active(child.path) && child.path !== item.path ? true : false}
                onClick={() => onNavigate(child.path)}
                sx={{
                  mx: 1, mb: 0.25, borderRadius: '8px',
                  minHeight: 34, pl: 1.5,
                  color: alpha('#fff', 0.55),
                  '&.Mui-selected': {
                    backgroundColor: alpha('#fff', 0.08),
                    color: 'white',
                  },
                  '&:hover': { backgroundColor: alpha('#fff', 0.06), color: alpha('#fff', 0.9) },
                }}
              >
                <Box sx={{ width: 4, height: 4, borderRadius: '50%', bgcolor: 'currentColor', mr: 1.5, opacity: 0.5 }} />
                <ListItemText
                  primary={child.label}
                  primaryTypographyProps={{ fontSize: '0.8125rem', fontWeight: 500 }}
                  sx={{ m: 0 }}
                />
              </ListItemButton>
            ))}
          </List>
        </Collapse>
      )}
    </>
  );
};

// ── Main ──────────────────────────────────────────────────────────────────────
export default function MainLayout() {
  const [mobileOpen,    setMobileOpen]    = useState(false);
  const [collapsed,     setCollapsed]     = useState(false);
  const [expanded,      setExpanded]      = useState<string[]>(['operaciones', 'inventory']);
  const [anchorEl,      setAnchorEl]      = useState<null | HTMLElement>(null);
  const [notifOpen,     setNotifOpen]     = useState(false);

  const navigate           = useNavigate();
  const location           = useLocation();
  const { user, logout }   = useAuth();
  const { connected, alerts } = useWebSocket();

  const unread = alerts.filter(a => !a.read).length;
  const drawerW = collapsed ? COLLAPSED_W : DRAWER_W;

  const isActive = (path: string) => {
    if (path === '/transactions' || path === '/inventory') {
      return location.pathname === path;
    }
    return location.pathname.startsWith(path) && path !== '/';
  };

  const handleToggle = (id: string) =>
    setExpanded(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);

  const handleNav = (path: string) => {
    navigate(path);
    setMobileOpen(false);
  };

  const pageTitle = () => {
    const all = [...NAV_ITEMS, ...BOTTOM_ITEMS];
    for (const item of all) {
      if ('children' in item && item.children) {
        const child = item.children.find(c => location.pathname === c.path);
        if (child) return `${item.label} · ${child.label}`;
      }
      if (location.pathname.startsWith(item.path) && item.path !== '/') return item.label;
    }
    for (const [path, title] of Object.entries(EXTRA_TITLES)) {
      if (location.pathname.startsWith(path)) return title;
    }
    return 'Kapitalya';
  };

  // ── Sidebar content ───────────────────────────────────────────────────────
  const sidebarContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: TOKENS.navy }}>
      {/* Logo */}
      <Box sx={{
        px: 2, py: 2,
        display: 'flex', alignItems: 'center',
        justifyContent: collapsed ? 'center' : 'space-between',
        borderBottom: `1px solid ${alpha('#fff', 0.07)}`,
        minHeight: 64,
      }}>
        {!collapsed && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Box sx={{
              width: 32, height: 32, borderRadius: '8px',
              bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <Typography sx={{ fontSize: 16, lineHeight: 1, color: 'white' }}>₿</Typography>
            </Box>
            <Box>
              <Typography variant="subtitle1" fontWeight={800} color="white" lineHeight={1.2}>
                Kapitalya
              </Typography>
              <Typography variant="caption" sx={{ color: alpha('#fff', 0.4), fontSize: '0.65rem', lineHeight: 1 }}>
                SISTEMA FINANCIERO
              </Typography>
            </Box>
          </Box>
        )}
        {collapsed && (
          <Box sx={{ width: 32, height: 32, borderRadius: '8px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Typography sx={{ fontSize: 16, lineHeight: 1, color: 'white' }}>₿</Typography>
          </Box>
        )}
        {!collapsed && (
          <IconButton size="small" onClick={() => setCollapsed(true)}
            sx={{ color: alpha('#fff', 0.4), '&:hover': { color: 'white', bgcolor: alpha('#fff', 0.07) } }}>
            <ChevronLeft fontSize="small" />
          </IconButton>
        )}
      </Box>

      {/* User info */}
      {!collapsed && (
        <Box sx={{
          px: 2, py: 1.5, mx: 1, my: 1, borderRadius: '10px',
          bgcolor: alpha('#fff', 0.05),
          border: `1px solid ${alpha('#fff', 0.07)}`,
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Avatar sx={{ width: 34, height: 34, bgcolor: TOKENS.blue, fontSize: '0.875rem', fontWeight: 700 }}>
              {user?.first_name?.[0] ?? user?.username?.[0] ?? 'U'}
            </Avatar>
            <Box flex={1} minWidth={0}>
              <Typography variant="body2" fontWeight={700} color="white" noWrap>
                {user?.first_name ?? user?.username}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: ROLE_COLOR[user?.role ?? 'CASHIER'] }} />
                <Typography variant="caption" sx={{ color: alpha('#fff', 0.5), fontSize: '0.7rem' }}>
                  {ROLE_LABEL[user?.role ?? 'CASHIER']} · {user?.branch?.name ?? 'Sin sucursal'}
                </Typography>
              </Box>
            </Box>
          </Box>
        </Box>
      )}

      {/* Nav items */}
      <Box sx={{ flex: 1, overflow: 'auto', py: 1,
        '&::-webkit-scrollbar': { width: 3 },
        '&::-webkit-scrollbar-track': { background: 'transparent' },
        '&::-webkit-scrollbar-thumb': { background: alpha('#fff', 0.1), borderRadius: 2 },
      }}>
        {/* Main label */}
        {!collapsed && (
          <Typography sx={{ px: 2.5, py: 0.5, fontSize: '0.625rem', fontWeight: 700, letterSpacing: '0.12em', color: alpha('#fff', 0.3), textTransform: 'uppercase' }}>
            Principal
          </Typography>
        )}
        <List disablePadding>
          {NAV_ITEMS
            .filter(item => !('adminOnly' in item) || !(item as any).adminOnly || user?.role === 'ADMIN')
            .map(item => (
              <NavItem key={item.id} item={item}
                active={isActive} collapsed={collapsed}
                expanded={expanded} onToggle={handleToggle} onNavigate={handleNav}
                badge={undefined} />
            ))}
        </List>

        <Divider sx={{ my: 1, borderColor: alpha('#fff', 0.07) }} />

        {/* System label */}
        {!collapsed && (
          <Typography sx={{ px: 2.5, py: 0.5, fontSize: '0.625rem', fontWeight: 700, letterSpacing: '0.12em', color: alpha('#fff', 0.3), textTransform: 'uppercase' }}>
            Sistema
          </Typography>
        )}
        <List disablePadding>
          {BOTTOM_ITEMS
            .filter(item => !item.adminOnly || user?.role === 'ADMIN')
            .map(item => (
              <NavItem key={item.id} item={item}
                active={isActive} collapsed={collapsed}
                expanded={expanded} onToggle={handleToggle} onNavigate={handleNav} />
            ))}
        </List>
      </Box>

      {/* Logout */}
      <Box sx={{ p: 1, borderTop: `1px solid ${alpha('#fff', 0.07)}` }}>
        {collapsed ? (
          <Tooltip title="Cerrar sesión" placement="right" arrow>
            <IconButton onClick={logout} sx={{ width: '100%', borderRadius: '8px', color: alpha('#fff', 0.4), '&:hover': { color: TOKENS.red, bgcolor: alpha(TOKENS.red, 0.1) } }}>
              <Logout fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : (
          <ListItemButton onClick={logout} sx={{
            borderRadius: '8px', color: alpha('#fff', 0.4),
            '&:hover': { color: TOKENS.red, bgcolor: alpha(TOKENS.red, 0.08) },
          }}>
            <ListItemIcon sx={{ minWidth: 34, color: 'inherit' }}><Logout fontSize="small" /></ListItemIcon>
            <ListItemText primary="Cerrar sesión" primaryTypographyProps={{ fontSize: '0.8125rem', fontWeight: 600 }} />
          </ListItemButton>
        )}
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex' }}>
      {/* ── Desktop Drawer ── */}
      <Box component="nav" sx={{ width: { sm: drawerW }, flexShrink: { sm: 0 }, transition: 'width 0.2s ease' }}>
        <Drawer
          variant="permanent" open
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': {
              width: drawerW, border: 'none',
              overflow: 'hidden',
              transition: 'width 0.2s ease',
              boxShadow: '2px 0 20px rgba(0,0,0,0.15)',
            },
          }}
        >
          {sidebarContent}
        </Drawer>

        {/* Mobile */}
        <Drawer
          variant="temporary" open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { width: DRAWER_W, border: 'none' },
          }}
        >
          {sidebarContent}
        </Drawer>
      </Box>

      {/* ── AppBar ── */}
      <AppBar position="fixed" elevation={0} sx={{
        width: { sm: `calc(100% - ${drawerW}px)` },
        ml: { sm: `${drawerW}px` },
        bgcolor: TOKENS.bg,
        borderBottom: `1px solid ${TOKENS.border}`,
        color: TOKENS.text,
        transition: 'width 0.2s ease, margin-left 0.2s ease',
        backdropFilter: 'blur(12px)',
      }}>
        <Toolbar sx={{ gap: 2, minHeight: '56px !important' }}>
          {/* Mobile menu toggle */}
          <IconButton edge="start" onClick={() => setMobileOpen(true)}
            sx={{ display: { sm: 'none' }, color: TOKENS.text }}>
            <MenuIcon />
          </IconButton>

          {/* Desktop: expand collapsed sidebar */}
          {collapsed && (
            <IconButton size="small" onClick={() => setCollapsed(false)}
              sx={{ display: { xs: 'none', sm: 'flex' }, color: TOKENS.textSub, '&:hover': { color: TOKENS.text } }}>
              <MenuIcon fontSize="small" />
            </IconButton>
          )}

          <Typography variant="subtitle1" fontWeight={700} sx={{ flex: 1 }}>
            {pageTitle()}
          </Typography>

          {/* Connection indicator */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <Circle sx={{ fontSize: 7, color: connected ? TOKENS.green : TOKENS.red }} />
            <Typography variant="caption" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
              {connected ? 'En línea' : 'Sin conexión'}
            </Typography>
          </Box>

          {/* Notifications */}
          <Tooltip title="Notificaciones" arrow>
            <IconButton size="small" onClick={() => setNotifOpen(true)}
              sx={{ color: TOKENS.textSub, '&:hover': { color: TOKENS.text, bgcolor: TOKENS.border } }}>
              <Badge badgeContent={unread} color="error" max={9}
                sx={{ '& .MuiBadge-badge': { fontSize: '0.625rem', height: 16, minWidth: 16 } }}>
                <Notifications fontSize="small" />
              </Badge>
            </IconButton>
          </Tooltip>

          {/* Avatar menu */}
          <Tooltip title="Perfil" arrow>
            <IconButton size="small" onClick={e => setAnchorEl(e.currentTarget)} sx={{ p: 0 }}>
              <Avatar sx={{ width: 32, height: 32, bgcolor: TOKENS.blue, fontSize: '0.8125rem', fontWeight: 700 }}>
                {user?.first_name?.[0] ?? user?.username?.[0] ?? 'U'}
              </Avatar>
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      {/* Avatar menu */}
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}
        PaperProps={{ sx: { mt: 1, minWidth: 200, border: `1px solid ${TOKENS.border}` } }}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
        <Box sx={{ px: 2, py: 1.5 }}>
          <Typography variant="body2" fontWeight={700}>{user?.first_name} {user?.last_name}</Typography>
          <Typography variant="caption" color="text.secondary">{user?.email}</Typography>
          <Box mt={0.5}>
            <Chip label={ROLE_LABEL[user?.role ?? 'CASHIER']} size="small"
              sx={{ height: 18, fontSize: '0.65rem', bgcolor: alpha(ROLE_COLOR[user?.role ?? 'CASHIER'], 0.12), color: ROLE_COLOR[user?.role ?? 'CASHIER'] }} />
          </Box>
        </Box>
        <Divider />
        <MenuItem onClick={() => { setAnchorEl(null); navigate('/settings'); }} sx={{ fontSize: '0.875rem', gap: 1.5 }}>
          <Person fontSize="small" /> Mi Perfil
        </MenuItem>
        <Divider />
        <MenuItem onClick={() => { setAnchorEl(null); logout(); }}
          sx={{ fontSize: '0.875rem', gap: 1.5, color: TOKENS.red }}>
          <Logout fontSize="small" /> Cerrar sesión
        </MenuItem>
      </Menu>

      {/* ── Main content ── */}
      <Box component="main" sx={{
        flexGrow: 1,
        mt: '56px',
        minHeight: 'calc(100vh - 56px)',
        bgcolor: TOKENS.bg,
        transition: 'margin-left 0.2s ease',
        overflow: 'auto',
      }}>
        <Box sx={{ p: { xs: 2, sm: 3 }, maxWidth: 1400, mx: 'auto' }}>
          <Outlet />
        </Box>
      </Box>

      {/* Notification panel */}
      <NotificationPanel open={notifOpen} onClose={() => setNotifOpen(false)} />
    </Box>
  );
}
