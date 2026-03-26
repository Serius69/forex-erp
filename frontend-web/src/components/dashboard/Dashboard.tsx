// frontend-web/src/components/dashboard/Dashboard.tsx
import React, { useEffect, useState, useCallback } from 'react';
import {
  Grid, Typography, Box, Card, CardContent,
  IconButton, Skeleton, Tooltip, useTheme,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, Refresh,
  AttachMoney, People, SwapHoriz, AccountBalance,
} from '@mui/icons-material';
import { motion } from 'framer-motion';
import { useSnackbar } from 'notistack';

import { useWebSocket } from '../../contexts/WebSocketContext';
import { api } from '../../services/api';
import { formatCurrency, formatNumber } from '../../utils/formatters';
import ExchangeRatesCard from './ExchangeRatesCard';
import TransactionChart from './TransactionChart';
import PredictionsChart from './PredictionsChart';
import RecentTransactions from './RecentTransactions';
import InventoryStatus from './InventoryStatus';
import QuickActions from './QuickActions';

// ── Interfaz alineada con lo que devuelve /api/dashboard/stats/ ───────────────
interface DashboardStats {
  today_transactions:    number;
  count_change_pct:      number;
  today_volume_bob:      number;
  volume_change_pct:     number;
  today_profit_bob:      number;
  unique_customers:      number;
  current_rates:         Record<string, { buy: number; sell: number; official: number }>;
  transactions_by_hour:  { hour: string; count: number }[];
  recent_transactions:   any[];
}

const Dashboard: React.FC = () => {
  const { enqueueSnackbar }              = useSnackbar();
  const { rates }                        = useWebSocket();
  const [stats,      setStats]           = useState<DashboardStats | null>(null);
  const [loading,    setLoading]         = useState(true);
  const [refreshing, setRefreshing]      = useState(false);

  const loadDashboardData = useCallback(async () => {
    try {
      setRefreshing(true);
      const response = await api.get('/dashboard/stats/');
      setStats(response.data);
    } catch (error) {
      enqueueSnackbar('Error al cargar datos del dashboard', { variant: 'error' });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [enqueueSnackbar]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  // ── Componente tarjeta de estadística ──────────────────────────────────────
  const StatCard = ({
    title, value, icon, change, color = 'primary',
  }: {
    title:   string;
    value:   string | number;
    icon:    React.ReactNode;
    change?: number;
    color?:  'primary' | 'secondary' | 'success' | 'warning';
  }) => (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <Card sx={{ height: '100%' }}>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            <Box sx={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 40, height: 40, borderRadius: 2,
              bgcolor: `${color}.light`, color: `${color}.main`, mr: 2,
            }}>
              {icon}
            </Box>
            <Typography variant="body2" color="text.secondary">{title}</Typography>
          </Box>

          <Typography variant="h4" gutterBottom>{value}</Typography>

          {change !== undefined && (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              {change >= 0
                ? <TrendingUp  color="success" fontSize="small" />
                : <TrendingDown color="error"  fontSize="small" />}
              <Typography
                variant="body2"
                color={change >= 0 ? 'success.main' : 'error.main'}
                sx={{ ml: 0.5 }}
              >
                {Math.abs(change).toFixed(1)}% vs ayer
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );

  // ── Loading skeleton ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Grid container spacing={3}>
        {[1, 2, 3, 4].map((item) => (
          <Grid xs={12} sm={6} md={3} key={item}>
            <Skeleton variant="rectangular" height={140} sx={{ borderRadius: 2 }} />
          </Grid>
        ))}
      </Grid>
    );
  }

  // ── Dashboard principal ─────────────────────────────────────────────────────
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 3 }}>
        <Typography variant="h4" fontWeight="bold">Dashboard</Typography>
        <Tooltip title="Actualizar datos">
          <IconButton onClick={loadDashboardData} disabled={refreshing}>
            <Refresh />
          </IconButton>
        </Tooltip>
      </Box>

      <Grid container spacing={3}>

        {/* ── Tarjetas KPI ── */}
        <Grid xs={12} sm={6} md={3}>
          <StatCard
            title="Transacciones Hoy"
            value={formatNumber(stats?.today_transactions ?? 0)}
            icon={<SwapHoriz />}
            change={stats?.count_change_pct}
            color="primary"
          />
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <StatCard
            title="Volumen Total (BOB)"
            value={formatCurrency(stats?.today_volume_bob ?? 0)}
            icon={<AttachMoney />}
            change={stats?.volume_change_pct}
            color="success"
          />
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <StatCard
            title="Utilidad Estimada"
            value={formatCurrency(stats?.today_profit_bob ?? 0)}
            icon={<AccountBalance />}
            color="secondary"
          />
        </Grid>
        <Grid xs={12} sm={6} md={3}>
          <StatCard
            title="Clientes Únicos Hoy"
            value={formatNumber(stats?.unique_customers ?? 0)}
            icon={<People />}
            color="warning"
          />
        </Grid>

        {/* ── Tasas de cambio ── */}
        <Grid xs={12} md={6}>
          <ExchangeRatesCard rates={stats?.current_rates ?? rates} />
        </Grid>

        {/* ── Acciones rápidas ── */}
        <Grid xs={12} md={6}>
          <QuickActions />
        </Grid>

        {/* ── Gráfico transacciones ── */}
        <Grid xs={12} md={8}>
          <TransactionChart data={stats?.transactions_by_hour ?? []} />
        </Grid>

        {/* ── Estado inventario ── */}
        <Grid xs={12} md={4}>
          <InventoryStatus />
        </Grid>

        {/* ── Predicciones ── */}
        <Grid xs={12}>
          <PredictionsChart />
        </Grid>

        {/* ── Transacciones recientes ── */}
        <Grid xs={12}>
          <RecentTransactions transactions={stats?.recent_transactions ?? []} />
        </Grid>

      </Grid>
    </Box>
  );
};

export default Dashboard;