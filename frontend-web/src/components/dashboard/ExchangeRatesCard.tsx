import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Grid,
  Box,
  Chip,
  IconButton,
  Menu,
  MenuItem,
  Divider,
  Skeleton,
} from '@mui/material';
import {
  TrendingUp,
  TrendingDown,
  TrendingFlat,
  MoreVert,
  History,
} from '@mui/icons-material';
import { motion, AnimatePresence } from 'framer-motion';
import { formatCurrency } from '../../utils/formatters';

interface Rate {
  buy: number;
  sell: number;
  official: number;
  lastUpdate: string;
  trend: 'up' | 'down' | 'flat';
  changePercent: number;
}

interface ExchangeRatesCardProps {
  rates: Record<string, Rate>;
}

const currencyInfo = {
  USD: { name: 'Dólar', flag: '🇺🇸', color: '#4caf50' },
  EUR: { name: 'Euro', flag: '🇪🇺', color: '#2196f3' },
  BRL: { name: 'Real', flag: '🇧🇷', color: '#ffeb3b' },
  ARS: { name: 'Peso Arg.', flag: '🇦🇷', color: '#00bcd4' },
};

const ExchangeRatesCard: React.FC<ExchangeRatesCardProps> = ({ rates }) => {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [selectedCurrency, setSelectedCurrency] = useState<string | null>(null);
  const [displayMode, setDisplayMode] = useState<'compact' | 'detailed'>('compact');

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>, currency: string) => {
    setAnchorEl(event.currentTarget);
    setSelectedCurrency(currency);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
    setSelectedCurrency(null);
  };

  const RateDisplay = ({ currency, rate }: { currency: string; rate: Rate }) => {
    const info = currencyInfo[currency as keyof typeof currencyInfo];
    
    const getTrendIcon = () => {
      switch (rate.trend) {
        case 'up':
          return <TrendingUp fontSize="small" color="success" />;
        case 'down':
          return <TrendingDown fontSize="small" color="error" />;
        default:
          return <TrendingFlat fontSize="small" color="disabled" />;
      }
    };

    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.3 }}
      >
        <Box
          sx={{
            p: 2,
            borderRadius: 2,
            bgcolor: 'background.default',
            border: '1px solid',
            borderColor: 'divider',
            position: 'relative',
            overflow: 'hidden',
            '&:hover': {
              borderColor: 'primary.main',
              boxShadow: 1,
            },
          }}
        >
          <Box
            sx={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: 4,
              bgcolor: info?.color || 'primary.main',
            }}
          />

          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6">{info?.flag}</Typography>
              <Box>
                <Typography variant="subtitle2" fontWeight="bold">
                  {currency}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {info?.name}
                </Typography>
              </Box>
            </Box>
            <IconButton
              size="small"
              onClick={(e) => handleMenuOpen(e, currency)}
            >
              <MoreVert fontSize="small" />
            </IconButton>
          </Box>

          <Grid container spacing={1}>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">
                Compra
              </Typography>
              <Typography variant="h6" fontWeight="bold">
                {formatCurrency(rate.buy, false)}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">
                Venta
              </Typography>
              <Typography variant="h6" fontWeight="bold">
                {formatCurrency(rate.sell, false)}
              </Typography>
            </Grid>
          </Grid>

          <Box sx={{ display: 'flex', alignItems: 'center', mt: 1, gap: 1 }}>
            {getTrendIcon()}
            <Chip
              label={`${rate.changePercent >= 0 ? '+' : ''}${rate.changePercent}%`}
              size="small"
              color={rate.changePercent >= 0 ? 'success' : 'error'}
              variant="outlined"
            />
          </Box>
        </Box>
      </motion.div>
    );
  };

  if (!rates || Object.keys(rates).length === 0) {
    return (
      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Tasas de Cambio
          </Typography>
          <Grid container spacing={2}>
            {[1, 2, 3, 4].map((item) => (
              <Grid item xs={6} key={item}>
                <Skeleton variant="rectangular" height={120} />
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
            <Typography variant="h6">Tasas de Cambio</Typography>
            <Chip
              label="En vivo"
              size="small"
              color="success"
              icon={
                <Box
                  sx={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    bgcolor: 'success.main',
                    animation: 'pulse 2s infinite',
                    '@keyframes pulse': {
                      '0%': { opacity: 1 },
                      '50%': { opacity: 0.5 },
                      '100%': { opacity: 1 },
                    },
                  }}
                />
              }
            />
          </Box>

          <Grid container spacing={2}>
            <AnimatePresence>
              {Object.entries(rates).map(([currency, rate]) => (
                <Grid item xs={12} sm={6} key={currency}>
                  <RateDisplay currency={currency} rate={rate} />
                </Grid>
              ))}
            </AnimatePresence>
          </Grid>

          <Divider sx={{ my: 2 }} />
          
          <Typography variant="caption" color="text.secondary">
            Última actualización: {new Date().toLocaleTimeString()}
          </Typography>
        </CardContent>
      </Card>

      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={handleMenuClose}>
          <History sx={{ mr: 1 }} fontSize="small" />
          Ver historial
        </MenuItem>
        <MenuItem onClick={handleMenuClose}>
          Configurar alertas
        </MenuItem>
      </Menu>
    </>
  );
};

export default ExchangeRatesCard;