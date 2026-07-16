// src/components/common/MainLayout.tsx
import React, { useState, useMemo } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, AppBar, Toolbar, Typography, IconButton,
  Avatar, Menu, MenuItem, Divider, Chip, Button,
  Badge, Drawer, List, ListItemButton, ListItemIcon,
  ListItemText, Collapse, Tooltip, Breadcrumbs, Link,
  SpeedDial, SpeedDialAction, SpeedDialIcon,
  Select, FormControl,
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
  Psychology,
  TrendingUp,
  AccountBalance,
  CreditCard,
  NotificationsActive,
  BarChart,
  SmartToy,
  BusinessCenter,
  CloudUpload,
  Language,
  Business,
  Store,
  AutoAwesome,
  NavigateNext,
  Add,
  Close,
  Casino,
  Public,
  Insights,
} from '@mui/icons-material';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { useBranchScope } from '../../contexts/BranchScopeContext';
import NotificationPanel from './NotificationPanel';
import { SystemStatusBar } from './SystemStatusBar';
import { OfflineBanner } from '../troubleshooting/OfflineBanner';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';

const DRAWER_W    = 252;
const COLLAPSED_W = 68;

// ── Breadcrumb map ────────────────────────────────────────────────────────────
const BREADCRUMB_LABELS: Record<string, string> = {
  dashboard:         'Dashboard',
  transactions:      'Transacciones',
  pending:           'Aprobaciones',
  customers:         'Clientes',
  inventory:         'Inventario',
  movements:         'Movimientos',
  transfers:         'Transferencias',
  cards:             'Tarjetas',
  rates:             'Tasas de Cambio',
  capital:           'Capital',
  ganancias:         'Ganancias',
  predictions:       'Predicciones',
  simulator:         'Simulador',
  macro:             'Macro Bolivia',
  advisor:           'Asesor',
  analista:          'Analista',
  analytics:         'Analytics',
  decisiones:        'Motor IA',
  'ai-insights':     'IA Insights',
  'branch-analytics':'Analítica Sucursal',
  executive:         'CEO Dashboard',
  reports:           'Reportes',
  alertas:           'Alertas',
  settings:          'Configuración',
  import:            'Importar',
  admin:             'Admin',
  users:             'Usuarios',
  branches:          'Sucursales',
  company:           'Empresa',
  audit:             'Auditoría',
  maintenance:       'Mantenimiento',
  tarjetas:          'Tarjetas',
};

interface Crumb { label: string; path: string; isLast: boolean; }
const buildCrumbs = (pathname: string): Crumb[] => {
  const segs = pathname.split('/').filter(Boolean);
  if (segs.length <= 1) return [];
  return segs.map((seg, i) => ({
    label:  BREADCRUMB_LABELS[seg] ?? seg,
    path:   '/' + segs.slice(0, i + 1).join('/'),
    isLast: i === segs.length - 1,
  }));
};

// ── Global Quick-Action FAB ───────────────────────────────────────────────────
const SPEED_ACTIONS = [
  { name: 'Nueva transacción', icon: <SwapHoriz />,       path: '/transactions' },
  { name: 'Tasas de cambio',   icon: <CurrencyExchange />, path: '/rates' },
  { name: 'Inventario',        icon: <Inventory2 />,       path: '/inventory' },
  { name: 'Clientes',          icon: <People />,            path: '/customers' },
];

// ── Nav section types ─────────────────────────────────────────────────────────
interface NavGroup  { label: string; items: NavItemDef[]; roles?: string[]; }
interface NavItemDef {
  id: string; label: string; path: string; icon: React.ReactNode;
  children?: { label: string; path: string }[];
  roles?: string[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Principal',
    items: [
      { id: 'dashboard', label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon fontSize="small" /> },
    ],
  },
  {
    label: 'Operaciones',
    items: [
      {
        id: 'operaciones', label: 'Transacciones', path: '/transactions',
        icon: <SwapHoriz fontSize="small" />,
        children: [
          { label: 'Transacciones', path: '/transactions' },
          { label: 'Aprobaciones',  path: '/transactions/pending' },
        ],
      },
      { id: 'customers', label: 'Clientes', path: '/customers', icon: <People fontSize="small" /> },
    ],
  },
  {
    label: 'Inventario',
    items: [
      {
        id: 'inventory', label: 'Inventario', path: '/inventory',
        icon: <Inventory2 fontSize="small" />,
        children: [
          { label: 'Resumen',        path: '/inventory' },
          { label: 'Movimientos',    path: '/inventory/movements' },
          { label: 'Transferencias', path: '/inventory/transfers' },
          { label: 'Tarjetas',       path: '/inventory/cards' },
        ],
      },
    ],
  },
  {
    label: 'Finanzas',
    items: [
      { id: 'rates',    label: 'Tasas de Cambio', path: '/rates',    icon: <CurrencyExchange fontSize="small" /> },
      { id: 'tarjetas', label: 'Tarjetas',         path: '/tarjetas', icon: <CreditCard fontSize="small" /> },
      { id: 'capital',  label: 'Capital & Gastos', path: '/capital',  icon: <AccountBalance fontSize="small" />, roles: ['ADMIN','SUPERVISOR'] },
      { id: 'ganancias',label: 'Ganancias',         path: '/ganancias',icon: <TrendingUp fontSize="small" />, roles: ['ADMIN','SUPERVISOR'] },
    ],
  },
  {
    label: 'Inteligencia',
    roles: ['ADMIN', 'SUPERVISOR'],
    items: [
      { id: 'predictions',     label: 'Predicciones',       path: '/predictions',      icon: <Psychology fontSize="small" />, roles: ['ADMIN','SUPERVISOR'] },
      { id: 'analista',        label: 'Analista',            path: '/analista',         icon: <Insights fontSize="small" />,   roles: ['ADMIN','SUPERVISOR'] },
      { id: 'advisor',         label: 'Asesor',              path: '/advisor',          icon: <SmartToy fontSize="small" />,   roles: ['ADMIN','SUPERVISOR'] },
      { id: 'simulator',       label: 'Simulador',           path: '/simulator',        icon: <Casino fontSize="small" />,     roles: ['ADMIN','SUPERVISOR'] },
      { id: 'macro',           label: 'Macro Bolivia',       path: '/macro',            icon: <Public fontSize="small" />,     roles: ['ADMIN','SUPERVISOR'] },
      { id: 'analytics',       label: 'Analytics',           path: '/analytics',        icon: <BarChart fontSize="small" />,   roles: ['ADMIN','SUPERVISOR'] },
      { id: 'decisiones',      label: 'Motor IA',            path: '/decisiones',       icon: <SmartToy fontSize="small" />,   roles: ['ADMIN','SUPERVISOR'] },
      { id: 'ai-insights',     label: 'IA Insights',         path: '/ai-insights',      icon: <AutoAwesome fontSize="small" />, roles: ['ADMIN','SUPERVISOR'] },
      { id: 'branch-analytics',label: 'Analítica Sucursal',  path: '/branch-analytics', icon: <Store fontSize="small" />,      roles: ['ADMIN','SUPERVISOR'] },
      { id: 'executive',       label: 'CEO Dashboard',       path: '/executive',        icon: <BusinessCenter fontSize="small" />, roles: ['ADMIN'] },
    ],
  },
  {
    label: 'Reportes',
    items: [
      { id: 'reports', label: 'Reportes', path: '/reports', icon: <Assessment fontSize="small" />, roles: ['ADMIN','SUPERVISOR'] },
      { id: 'alertas', label: 'Alertas',  path: '/alertas', icon: <NotificationsActive fontSize="small" /> },
    ],
  },
];

const BOTTOM_ITEMS: NavItemDef[] = [
  { id: 'settings', label: 'Configuración', path: '/settings', icon: <Settings fontSize="small" /> },
  { id: 'import',   label: 'Importar Datos', path: '/import',  icon: <CloudUpload fontSize="small" />, roles: ['ADMIN'] },
  {
    id: 'admin', label: 'Administración', path: '/admin/users',
    icon: <AdminPanelSettings fontSize="small" />,
    roles: ['ADMIN'],
    children: [
      { label: 'Usuarios',      path: '/admin/users' },
      { label: 'Sucursales',    path: '/admin/branches' },
      { label: 'Empresa',       path: '/admin/company' },
      { label: 'Auditoría',     path: '/admin/audit' },
      { label: 'Mantenimiento', path: '/admin/maintenance' },
    ],
  },
];

const ALL_NAV_ITEMS: NavItemDef[] = [
  ...NAV_GROUPS.flatMap(g => g.items),
  ...BOTTOM_ITEMS,
];

// ── Role badge ────────────────────────────────────────────────────────────────
const ROLE_COLOR: Record<string, string> = {
  ADMIN: TOKENS.red, SUPERVISOR: TOKENS.amber, CASHIER: TOKENS.green,
};
const ROLE_LABEL: Record<string, string> = {
  ADMIN: 'Admin', SUPERVISOR: 'Supervisor', CASHIER: 'Cajero',
};

// ── NavItem ───────────────────────────────────────────────────────────────────
const NavItem = ({
  item, active, collapsed, expanded, onToggle, onNavigate, badge,
}: {
  item: NavItemDef; active: (path: string) => boolean; collapsed: boolean;
  expanded: string[]; onToggle: (id: string) => void;
  onNavigate: (path: string) => void; badge?: number;
}) => {
  const isActive   = active(item.path);
  const isExpanded = expanded.includes(item.id);
  const hasChildren = !!item.children;

  const itemContent = (
    <ListItemButton
      selected={isActive && !hasChildren}
      onClick={() => hasChildren ? onToggle(item.id) : onNavigate(item.path)}
      sx={{
        mx: 1, mb: 0.25, borderRadius: '8px', minHeight: 40,
        color: isActive ? 'white' : alpha('#fff', 0.6),
        backgroundColor: isActive && !hasChildren ? alpha(TOKENS.blue, 0.9) : 'transparent',
        '&:hover': {
          backgroundColor: isActive && !hasChildren ? alpha(TOKENS.blue, 1) : alpha('#fff', 0.07),
          color: 'white',
        },
        '&.Mui-selected': {
          backgroundColor: alpha(TOKENS.blue, 0.9),
          '&:hover': { backgroundColor: alpha(TOKENS.blue, 1) },
        },
        px: 1.5,
        justifyContent: collapsed ? 'center' : 'flex-start',
        transition: 'all 0.15s ease',
      }}
    >
      <ListItemIcon sx={{ minWidth: collapsed ? 0 : 34, color: isActive ? 'white' : alpha('#fff', 0.55), justifyContent: 'center' }}>
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
          {hasChildren && (isExpanded
            ? <ExpandLess sx={{ fontSize: 16, opacity: 0.6 }} />
            : <ExpandMore sx={{ fontSize: 16, opacity: 0.6 }} />
          )}
        </>
      )}
    </ListItemButton>
  );

  return (
    <>
      {collapsed ? <Tooltip title={item.label} placement="right" arrow>{itemContent}</Tooltip> : itemContent}
      {hasChildren && !collapsed && (
        <Collapse in={isExpanded} timeout="auto">
          <List disablePadding sx={{ pl: 2.5 }}>
            {item.children!.map(child => (
              <ListItemButton
                key={child.path}
                selected={active(child.path) && child.path !== item.path}
                onClick={() => onNavigate(child.path)}
                sx={{
                  mx: 1, mb: 0.25, borderRadius: '8px', minHeight: 34, pl: 1.5,
                  color: alpha('#fff', 0.55),
                  '&.Mui-selected': { backgroundColor: alpha('#fff', 0.08), color: 'white' },
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
  const [mobileOpen,  setMobileOpen]  = useState(false);
  const [collapsed,   setCollapsed]   = useState(false);
  const [expanded,    setExpanded]    = useState<string[]>(['operaciones', 'inventory', 'admin']);
  const [anchorEl,    setAnchorEl]    = useState<null | HTMLElement>(null);
  const [notifOpen,   setNotifOpen]   = useState(false);
  const [dialOpen,    setDialOpen]    = useState(false);

  const navigate           = useNavigate();
  const location           = useLocation();
  const { user, logout }   = useAuth();
  const { connected, alerts } = useWebSocket();
  const { branchId, setBranchId, branches, canSelectBranch } = useBranchScope();
  const { i18n }           = useTranslation();

  const role    = user?.role ?? 'CASHIER';
  const unread  = alerts.filter((a: any) => !a.read).length;
  const drawerW = collapsed ? COLLAPSED_W : DRAWER_W;

  const breadcrumbs = useMemo(() => buildCrumbs(location.pathname), [location.pathname]);

  const isActive = (path: string) => {
    if (path === '/transactions' || path === '/inventory') return location.pathname === path;
    return location.pathname.startsWith(path) && path !== '/';
  };

  const handleToggle = (id: string) =>
    setExpanded(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);

  const handleNav = (path: string) => { navigate(path); setMobileOpen(false); };

  const itemVisible = (item: NavItemDef) => !item.roles || item.roles.includes(role);

  const pageTitle = () => {
    for (const item of ALL_NAV_ITEMS) {
      if (item.children) {
        const child = item.children.find(c => location.pathname === c.path);
        if (child) return `${item.label} · ${child.label}`;
      }
      if (location.pathname.startsWith(item.path) && item.path !== '/') return item.label;
    }
    return 'Kapitalya';
  };

  // ── Sidebar ───────────────────────────────────────────────────────────────
  const sidebarContent = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: TOKENS.navy }}>
      {/* Logo */}
      <Box sx={{
        px: 2, py: 2, display: 'flex', alignItems: 'center',
        justifyContent: collapsed ? 'center' : 'space-between',
        borderBottom: `1px solid ${alpha('#fff', 0.07)}`, minHeight: 64,
      }}>
        {!collapsed && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Box sx={{ width: 32, height: 32, borderRadius: '8px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <Typography sx={{ fontSize: 16, lineHeight: 1, color: 'white', fontWeight: 800 }}>K</Typography>
            </Box>
            <Box>
              <Typography variant="subtitle1" fontWeight={800} color="white" lineHeight={1.2}>Kapitalya</Typography>
              <Typography variant="caption" sx={{ color: alpha('#fff', 0.4), fontSize: '0.65rem', lineHeight: 1 }}>SISTEMA FINANCIERO</Typography>
            </Box>
          </Box>
        )}
        {collapsed && (
          <Box sx={{ width: 32, height: 32, borderRadius: '8px', bgcolor: TOKENS.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Typography sx={{ fontSize: 16, lineHeight: 1, color: 'white', fontWeight: 800 }}>K</Typography>
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
        <Box sx={{ px: 2, py: 1.5, mx: 1, my: 1, borderRadius: '10px', bgcolor: alpha('#fff', 0.05), border: `1px solid ${alpha('#fff', 0.07)}` }}>
          {user?.company && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 1, pb: 1, borderBottom: `1px solid ${alpha('#fff', 0.07)}` }}>
              <Business sx={{ fontSize: 11, color: alpha('#fff', 0.4) }} />
              <Typography variant="caption" sx={{ color: alpha('#fff', 0.45), fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.04em' }} noWrap>
                {user.company.name}
              </Typography>
            </Box>
          )}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Avatar sx={{ width: 34, height: 34, bgcolor: TOKENS.blue, fontSize: '0.875rem', fontWeight: 700 }}>
              {user?.first_name?.[0] ?? user?.username?.[0] ?? 'U'}
            </Avatar>
            <Box flex={1} minWidth={0}>
              <Typography variant="body2" fontWeight={700} color="white" noWrap>
                {user?.first_name ?? user?.username}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: ROLE_COLOR[role] }} />
                <Typography variant="caption" sx={{ color: alpha('#fff', 0.5), fontSize: '0.7rem' }}>
                  {ROLE_LABEL[role]}
                </Typography>
              </Box>
              {canSelectBranch && branches.length > 0 ? (
                /* ADMIN: selector global de sucursal (null = todas) */
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                  <Store sx={{ fontSize: 10, color: alpha('#fff', 0.3) }} />
                  <FormControl variant="standard" size="small" sx={{ minWidth: 0, flex: 1 }}>
                    <Select
                      disableUnderline
                      value={branchId ?? 0}
                      onChange={(e) => setBranchId(Number(e.target.value) || null)}
                      sx={{
                        fontSize: '0.65rem',
                        color: alpha('#fff', 0.55),
                        '& .MuiSelect-icon': { color: alpha('#fff', 0.35), fontSize: 14 },
                        '& .MuiSelect-select': { py: 0, pr: '18px !important' },
                      }}
                      MenuProps={{ PaperProps: { sx: { maxHeight: 280 } } }}
                    >
                      <MenuItem value={0} sx={{ fontSize: '0.75rem' }}>
                        Todas las sucursales
                      </MenuItem>
                      {branches.map((b) => (
                        <MenuItem key={b.id} value={b.id} sx={{ fontSize: '0.75rem' }}>
                          {b.name}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Box>
              ) : user?.branch && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}>
                  <Store sx={{ fontSize: 10, color: alpha('#fff', 0.3) }} />
                  <Typography variant="caption" sx={{ color: alpha('#fff', 0.35), fontSize: '0.65rem' }} noWrap>
                    {user.branch.name}
                  </Typography>
                </Box>
              )}
            </Box>
          </Box>
        </Box>
      )}

      {/* Nav groups */}
      <Box sx={{
        flex: 1, overflow: 'auto', py: 1,
        '&::-webkit-scrollbar': { width: 3 },
        '&::-webkit-scrollbar-track': { background: 'transparent' },
        '&::-webkit-scrollbar-thumb': { background: alpha('#fff', 0.1), borderRadius: 2 },
      }}>
        {NAV_GROUPS.map((group, gi) => {
          const visibleItems = group.items.filter(itemVisible);
          if (visibleItems.length === 0) return null;
          if (group.roles && !group.roles.includes(role)) return null;
          return (
            <Box key={group.label}>
              {gi > 0 && <Divider sx={{ my: 0.75, borderColor: alpha('#fff', 0.07) }} />}
              {!collapsed && (
                <Typography sx={{ px: 2.5, py: 0.5, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.12em', color: alpha('#fff', 0.3), textTransform: 'uppercase' }}>
                  {group.label}
                </Typography>
              )}
              <List disablePadding>
                {visibleItems.map(item => (
                  <NavItem key={item.id} item={item} active={isActive} collapsed={collapsed}
                    expanded={expanded} onToggle={handleToggle} onNavigate={handleNav} />
                ))}
              </List>
            </Box>
          );
        })}

        <Divider sx={{ my: 0.75, borderColor: alpha('#fff', 0.07) }} />
        {!collapsed && (
          <Typography sx={{ px: 2.5, py: 0.5, fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.12em', color: alpha('#fff', 0.3), textTransform: 'uppercase' }}>
            Sistema
          </Typography>
        )}
        <List disablePadding>
          {BOTTOM_ITEMS.filter(itemVisible).map(item => (
            <NavItem key={item.id} item={item} active={isActive} collapsed={collapsed}
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
          <ListItemButton onClick={logout} sx={{ borderRadius: '8px', color: alpha('#fff', 0.4), '&:hover': { color: TOKENS.red, bgcolor: alpha(TOKENS.red, 0.08) } }}>
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
        <Drawer variant="permanent" open
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { width: drawerW, border: 'none', overflow: 'hidden', transition: 'width 0.2s ease', boxShadow: '2px 0 20px rgba(0,0,0,0.15)' },
          }}
        >{sidebarContent}</Drawer>

        {/* Mobile */}
        <Drawer variant="temporary" open={mobileOpen} onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{ display: { xs: 'block', sm: 'none' }, '& .MuiDrawer-paper': { width: DRAWER_W, border: 'none' } }}
        >{sidebarContent}</Drawer>
      </Box>

      {/* ── AppBar ── */}
      <AppBar position="fixed" elevation={0} sx={{
        width: { sm: `calc(100% - ${drawerW}px)` },
        ml:    { sm: `${drawerW}px` },
        bgcolor: alpha(TOKENS.surface, 0.92),
        borderBottom: `1px solid ${TOKENS.border}`,
        color: TOKENS.text,
        transition: 'width 0.2s ease, margin-left 0.2s ease',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
      }}>
        <Toolbar sx={{ gap: 1.5, minHeight: '56px !important' }}>
          {/* Mobile menu */}
          <IconButton edge="start" onClick={() => setMobileOpen(true)}
            sx={{ display: { sm: 'none' }, color: TOKENS.text }}>
            <MenuIcon />
          </IconButton>

          {/* Desktop: expand collapsed */}
          {collapsed && (
            <IconButton size="small" onClick={() => setCollapsed(false)}
              sx={{ display: { xs: 'none', sm: 'flex' }, color: TOKENS.textSub, '&:hover': { color: TOKENS.text } }}>
              <MenuIcon fontSize="small" />
            </IconButton>
          )}

          <Typography variant="subtitle1" fontWeight={700} noWrap sx={{ flex: 1, minWidth: 0 }}>
            {pageTitle()}
          </Typography>

          {/* ── Quick "Nueva" button ── */}
          <Button
            variant="contained"
            size="small"
            startIcon={<Add sx={{ fontSize: '16px !important' }} />}
            onClick={() => navigate('/transactions')}
            sx={{
              display: { xs: 'none', md: 'flex' },
              borderRadius: '20px',
              fontWeight: 700,
              fontSize: '0.75rem',
              py: 0.75,
              px: 2,
              boxShadow: 'none',
              background: `linear-gradient(135deg, ${TOKENS.blue} 0%, #1D4ED8 100%)`,
              '&:hover': {
                boxShadow: '0 4px 16px rgba(37,99,235,0.4)',
                background: `linear-gradient(135deg, #1D4ED8 0%, ${TOKENS.blue} 100%)`,
              },
            }}
          >
            Nueva
          </Button>

          {/* System status (WS + stale indicator) — en xs solo el punto de estado */}
          <Box sx={{ display: 'flex' }}>
            <SystemStatusBar />
          </Box>

          {/* Language toggle */}
          <Tooltip title={i18n.language === 'es' ? 'Switch to English' : 'Cambiar a Español'} arrow>
            <Button
              size="small"
              onClick={() => i18n.changeLanguage(i18n.language === 'es' ? 'en' : 'es')}
              startIcon={<Language sx={{ fontSize: '14px !important' }} />}
              sx={{
                minWidth: 0, px: 1, py: 0.5,
                color: TOKENS.textSub, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.04em',
                border: `1px solid ${TOKENS.border}`, borderRadius: '6px',
                '&:hover': { color: TOKENS.text, borderColor: TOKENS.blue, bgcolor: alpha(TOKENS.blue, 0.04) },
              }}
            >
              {i18n.language === 'es' ? 'EN' : 'ES'}
            </Button>
          </Tooltip>

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

          {/* Avatar */}
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
        flexGrow: 1, mt: '56px', minHeight: 'calc(100vh - 56px)',
        bgcolor: TOKENS.bg, transition: 'margin-left 0.2s ease', overflow: 'auto',
      }}>
        {/* Offline / reconnected banner */}
        <OfflineBanner />

        {/* Breadcrumbs strip */}
        {breadcrumbs.length > 0 && (
          <Box sx={{
            px: { xs: 2, sm: 3 }, py: 0.875,
            bgcolor: TOKENS.surface,
            borderBottom: `1px solid ${TOKENS.border}`,
          }}>
            <Breadcrumbs
              separator={<NavigateNext sx={{ fontSize: 14, color: TOKENS.muted }} />}
              sx={{ '& .MuiBreadcrumbs-separator': { mx: 0.5 } }}
            >
              <Link
                underline="hover"
                onClick={() => navigate('/dashboard')}
                sx={{
                  display: 'flex', alignItems: 'center', gap: 0.5,
                  cursor: 'pointer', color: TOKENS.textSub, fontSize: '0.8rem', fontWeight: 500,
                  '&:hover': { color: TOKENS.blue },
                  transition: 'color 0.15s',
                }}
              >
                <DashboardIcon sx={{ fontSize: 12 }} />
                Inicio
              </Link>
              {breadcrumbs.map(crumb =>
                crumb.isLast
                  ? (
                    <Typography key={crumb.path} sx={{ fontSize: '0.8rem', fontWeight: 600, color: TOKENS.text }}>
                      {crumb.label}
                    </Typography>
                  )
                  : (
                    <Link key={crumb.path} underline="hover" onClick={() => navigate(crumb.path)}
                      sx={{ cursor: 'pointer', color: TOKENS.textSub, fontSize: '0.8rem', fontWeight: 500, '&:hover': { color: TOKENS.blue }, transition: 'color 0.15s' }}>
                      {crumb.label}
                    </Link>
                  )
              )}
            </Breadcrumbs>
          </Box>
        )}

        {/* Page content — pb extra en xs para que el SpeedDial no tape la última fila */}
        <Box sx={{ p: { xs: 2, sm: 3 }, pb: { xs: 12, sm: 3 }, maxWidth: 1400, mx: 'auto' }}>
          <Outlet />
        </Box>

        {/* Global Quick-Actions SpeedDial */}
        <SpeedDial
          ariaLabel="Acciones rápidas"
          open={dialOpen}
          onOpen={() => setDialOpen(true)}
          onClose={() => setDialOpen(false)}
          icon={<SpeedDialIcon icon={<Add />} openIcon={<Close />} />}
          sx={{
            position: 'fixed',
            bottom: { xs: 'calc(16px + env(safe-area-inset-bottom))', sm: 28 },
            right: { xs: 16, sm: 28 },
            '& .MuiSpeedDial-fab': {
              width: 52, height: 52,
              background: `linear-gradient(135deg, ${TOKENS.blue} 0%, #1D4ED8 100%)`,
              boxShadow: `0 6px 24px ${alpha(TOKENS.blue, 0.45)}`,
              '&:hover': {
                background: `linear-gradient(135deg, #1D4ED8 0%, ${TOKENS.blue} 100%)`,
                boxShadow: `0 8px 28px ${alpha(TOKENS.blue, 0.55)}`,
              },
            },
          }}
        >
          {SPEED_ACTIONS.map(action => (
            <SpeedDialAction
              key={action.name}
              icon={action.icon}
              tooltipTitle={action.name}
              tooltipOpen
              tooltipPlacement="left"
              onClick={() => { setDialOpen(false); navigate(action.path); }}
              FabProps={{
                sx: {
                  width: 42, height: 42,
                  bgcolor: TOKENS.navy, color: 'white',
                  boxShadow: '0 2px 12px rgba(0,0,0,0.3)',
                  '&:hover': { bgcolor: TOKENS.navyMid },
                  '& .MuiSvgIcon-root': { fontSize: 18 },
                },
              }}
              sx={{
                '& .MuiSpeedDialAction-staticTooltipLabel': {
                  bgcolor: TOKENS.navy, color: 'white',
                  fontSize: '0.75rem', fontWeight: 600,
                  whiteSpace: 'nowrap', borderRadius: '6px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
                  px: 1.25, py: 0.625,
                },
              }}
            />
          ))}
        </SpeedDial>
      </Box>

      {/* Notification panel */}
      <NotificationPanel open={notifOpen} onClose={() => setNotifOpen(false)} />

      {/* Global keyframes */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.6; transform: scale(0.85); }
        }
      `}</style>
    </Box>
  );
}
