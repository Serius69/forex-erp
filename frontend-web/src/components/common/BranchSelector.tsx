import React, { useEffect, useState } from 'react';
import {
  FormControl, Select, MenuItem, Typography,
  Box, CircularProgress, Tooltip,
} from '@mui/material';
import { Store } from '@mui/icons-material';
import { api } from '../../services/api';
import { Branch } from '../../types';
import { alpha } from '@mui/material/styles';
import { TOKENS } from '../../styles/theme';

interface Props {
  value:    number | null;
  onChange: (branchId: number | null) => void;
  /** If true, adds an "All branches" option (for ADMIN/SUPERVISOR) */
  allowAll?: boolean;
  compact?: boolean;
}

export default function BranchSelector({ value, onChange, allowAll = false, compact = false }: Props) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading,  setLoading]  = useState(true);

  useEffect(() => {
    api.get('/users/branches/')
      .then(res => setBranches(res.data?.results ?? res.data ?? []))
      .catch(() => setBranches([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <CircularProgress size={18} />;

  return (
    <Tooltip title="Filtrar por sucursal" arrow>
      <FormControl size="small" sx={{ minWidth: compact ? 120 : 160 }}>
        <Select
          value={value ?? ('' as any)}
          displayEmpty
          onChange={e => {
            const v = e.target.value;
            onChange(v === '' ? null : Number(v));
          }}
          sx={{
            fontSize: '0.8rem',
            bgcolor: alpha('#fff', 0.06),
            color: 'white',
            '& .MuiOutlinedInput-notchedOutline': { borderColor: alpha('#fff', 0.15) },
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: alpha('#fff', 0.3) },
            '& .MuiSvgIcon-root': { color: alpha('#fff', 0.5) },
          }}
          renderValue={selected => (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Store sx={{ fontSize: 14, opacity: 0.6 }} />
              <Typography variant="caption" sx={{ color: 'white', fontWeight: 600 }}>
                {selected === ''
                  ? 'Todas las sucursales'
                  : (branches.find(b => b.id === selected)?.name ?? 'Sucursal')}
              </Typography>
            </Box>
          )}
        >
          {allowAll && (
            <MenuItem value="">
              <em>Todas las sucursales</em>
            </MenuItem>
          )}
          {branches.map(b => (
            <MenuItem key={b.id} value={b.id}>
              <Box>
                <Typography variant="body2" fontWeight={600}>{b.name}</Typography>
                {b.city && (
                  <Typography variant="caption" color="text.secondary">{b.city}</Typography>
                )}
              </Box>
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Tooltip>
  );
}
