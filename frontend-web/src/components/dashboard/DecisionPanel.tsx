/**
 * DecisionPanel — Grid of DecisionCards, one per tracked currency.
 *
 * Manages the TransactionForm dialog so "USAR RECOMENDACIÓN" can open it
 * pre-filled without any page navigation.
 */
import React, { useState } from 'react';
import {
  Box, Typography, useMediaQuery, useTheme,
} from '@mui/material';
import { Psychology } from '@mui/icons-material';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';
import DecisionCard, { type TransactionPreset } from './DecisionCard';
import TransactionForm from '../transactions/TransactionForm';

const DECISION_CURRENCIES = ['USD', 'EUR', 'CLP', 'PEN', 'BRL', 'ARS'];

const DecisionPanel: React.FC = () => {
  const theme   = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));

  const [formOpen, setFormOpen]     = useState(false);
  const [preset, setPreset]         = useState<TransactionPreset | undefined>(undefined);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleUse = (p: TransactionPreset) => {
    setPreset(p);
    setFormOpen(true);
  };

  const handleSuccess = () => {
    setRefreshKey(k => k + 1);  // signal Dashboard to refresh stats
  };

  return (
    <Box>
      {/* ── Section header ── */}
      <Box
        display="flex" alignItems="center" gap={1} mb={2}
        pb={1.5}
        sx={{ borderBottom: `1px solid ${TOKENS.border}` }}
      >
        <Box
          sx={{
            width: 32, height: 32, borderRadius: '9px',
            bgcolor: alpha(TOKENS.blue, 0.1),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: TOKENS.blue,
          }}
        >
          <Psychology sx={{ fontSize: 18 }} />
        </Box>
        <Box>
          <Typography variant="subtitle1" fontWeight={800}>
            Decisiones Inteligentes
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Motor AI · actualización automática cada 30 s
          </Typography>
        </Box>
      </Box>

      {/* ── Card grid ── */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: isMobile
            ? '1fr'
            : 'repeat(auto-fill, minmax(260px, 1fr))',
          gap: 2,
        }}
      >
        {DECISION_CURRENCIES.map(c => (
          <DecisionCard
            key={c}
            currency={c}
            onUseRecommendation={handleUse}
            compact={isMobile}
          />
        ))}
      </Box>

      {/* ── Pre-filled transaction form ── */}
      <TransactionForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSuccess={handleSuccess}
        preset={preset}
      />
    </Box>
  );
};

export default DecisionPanel;
