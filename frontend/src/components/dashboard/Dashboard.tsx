import React, { useEffect, useState } from 'react';
import {
  Grid,
  Paper,
  Typography,
  Box,
  Card,
  CardContent,
  IconButton,
  Skeleton,
  Tooltip,
  Chip,
  useTheme,
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  Refresh,
  AttachMoney,
  People,
  SwapHoriz,
  AccountBalance,
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

interface DashboardStats {
  todayTransactions: number;
  todayVolume: number;
  todayProfit: number;
  activeCustomers: number;
  comparisonYesterday: {
    transactions: number;
    volume: number;
    profit: number;
  };
}

const Dashboard: React.FC = () => {
  const theme = useTheme();
  const { enqueueSnackbar } = useSnackbar();
  const { rates } = useWebSocket();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadDashboardData();
  }, []);

  const loadDashboardData = async () => {
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
  };

  const StatCard = ({ 
    title, 
    value, 
    icon, 
    change, 
    color = 'primary' 
  }: {
    title: string;
    value: string | number;
    icon: React.ReactNode;
    change?: number;
    color?: 'primary' | 'secondary' | 'success' | 'warning';
  }) => (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card sx={{ height: '100%' }}>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 40,
                height: 40,
                borderRadius: 2,
                bgcolor: `${color}.light`,
                color: `${color}.main`,
                mr: 2,
              }}
            >
              {icon}
            </Box>
            <Typography variant="body2" color="text.secondary">
              {title}
            </Typography>
          </Box>
          
          <Typography variant="h4" gutterBottom>
            {value}
          </Typography>
          
          {change !== undefined && (
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              {change >= 0 ? (
                <TrendingUp color="success" fontSize="small" />
              ) : (
                <TrendingDown color="error" fontSize="small" />
              )}
              <Typography
                variant="body2"
                color={change >= 0 ? 'success.main' : 'error.main'}
                sx={{ ml: 0.5 }}
              >
                {Math.abs(change)}% vs ayer
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );

  if (loading) {
    return (
      <Grid container spacing={3}>
        {[1, 2, 3, 4].map((item) => (
          <Grid item xs={12} sm={6} md={3} key={item}>
            <Skeleton variant="rectangular" height={140} />
          </Grid>
       ))}
     </Grid>
   );
 }

 return (
   <Box>
     <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 3 }}>
       <Typography variant="h4">Dashboard</Typography>
       <Tooltip title="Actualizar datos">
         <IconButton onClick={loadDashboardData} disabled={refreshing}>
           <Refresh />
         </IconButton>
       </Tooltip>
     </Box>

     <Grid container spacing={3}>
       {/* Estadísticas principales */}
       <Grid item xs={12} sm={6} md={3}>
         <StatCard
           title="Transacciones Hoy"
           value={formatNumber(stats?.todayTransactions || 0)}
           icon={<SwapHoriz />}
           change={stats?.comparisonYesterday.transactions}
           color="primary"
         />
       </Grid>
       <Grid item xs={12} sm={6} md={3}>
         <StatCard
           title="Volumen Total (BOB)"
           value={formatCurrency(stats?.todayVolume || 0)}
           icon={<AttachMoney />}
           change={stats?.comparisonYesterday.volume}
           color="success"
         />
       </Grid>
       <Grid item xs={12} sm={6} md={3}>
         <StatCard
           title="Utilidad Estimada"
           value={formatCurrency(stats?.todayProfit || 0)}
           icon={<AccountBalance />}
           change={stats?.comparisonYesterday.profit}
           color="secondary"
         />
       </Grid>
       <Grid item xs={12} sm={6} md={3}>
         <StatCard
           title="Clientes Activos"
           value={formatNumber(stats?.activeCustomers || 0)}
           icon={<People />}
           color="warning"
         />
       </Grid>

       {/* Tasas de cambio */}
       <Grid item xs={12} md={6}>
         <ExchangeRatesCard rates={rates} />
       </Grid>

       {/* Acciones rápidas */}
       <Grid item xs={12} md={6}>
         <QuickActions />
       </Grid>

       {/* Gráfico de transacciones */}
       <Grid item xs={12} md={8}>
         <TransactionChart />
       </Grid>

       {/* Estado del inventario */}
       <Grid item xs={12} md={4}>
         <InventoryStatus />
       </Grid>

       {/* Predicciones */}
       <Grid item xs={12}>
         <PredictionsChart />
       </Grid>

       {/* Transacciones recientes */}
       <Grid item xs={12}>
         <RecentTransactions />
       </Grid>
     </Grid>
   </Box>
 );
};

export default Dashboard;