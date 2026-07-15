import React, { useEffect, useState } from 'react';
import {
  Box, Typography, Card, CardContent, Divider, Grid,
  Chip, Button, LinearProgress, Table, TableHead, TableContainer,
  TableRow, TableCell, TableBody, CircularProgress,
} from '@mui/material';
import {
  Business, Store, People, CreditCard, CheckCircle,
  Warning, Edit,
} from '@mui/icons-material';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import { Company, Subscription } from '../../types';
import { TOKENS } from '../../styles/theme';
import { alpha } from '@mui/material/styles';
import { Branch } from '../../types';

const PLAN_COLOR: Record<string, string> = {
  FREE:       TOKENS.textSub,
  STARTER:    TOKENS.blue,
  GROWTH:     TOKENS.green,
  ENTERPRISE: TOKENS.amber,
};

interface CompanyDetail extends Company {
  subscription?: Subscription;
  tax_id?:       string;
  logo_url?:     string;
}

export default function CompanyManagement() {
  const { user }   = useAuth();
  const [company,  setCompany]  = useState<CompanyDetail | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [stats,    setStats]    = useState<any>(null);
  const [loading,  setLoading]  = useState(true);

  useEffect(() => {
    if (!user?.company_id) { setLoading(false); return; }

    Promise.all([
      api.get(`/tenants/companies/${user.company_id}/`),
      api.get('/users/branches/'),
      api.get(`/tenants/companies/${user.company_id}/stats/`),
    ])
      .then(([compRes, brRes, statsRes]) => {
        setCompany(compRes.data);
        setBranches(brRes.data?.results ?? brRes.data ?? []);
        setStats(statsRes.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user?.company_id]);

  if (loading) return (
    <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
      <CircularProgress />
    </Box>
  );

  if (!company) return (
    <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
      <Business sx={{ fontSize: 48, opacity: 0.3 }} />
      <Typography>No se encontró información de empresa.</Typography>
    </Box>
  );

  const sub = company.subscription;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Business sx={{ color: TOKENS.blue, fontSize: 28 }} />
          <Box>
            <Typography variant="h5" fontWeight={800}>{company.name}</Typography>
            <Typography variant="caption" color="text.secondary">{company.slug}</Typography>
          </Box>
        </Box>
        {sub && (
          <Chip
            label={sub.plan}
            sx={{
              bgcolor: alpha(PLAN_COLOR[sub.plan] ?? TOKENS.blue, 0.12),
              color:   PLAN_COLOR[sub.plan] ?? TOKENS.blue,
              fontWeight: 800,
            }}
          />
        )}
      </Box>

      <Grid container spacing={3}>
        {/* Company Info */}
        <Grid item xs={12} md={4}>
          <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
            <CardContent>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2 }}>Información</Typography>
              <Divider sx={{ mb: 2 }} />
              {[
                { label: 'País',           value: company.country },
                { label: 'Moneda base',    value: company.base_currency },
                { label: 'NIT / Tax ID',   value: company.tax_id || '—' },
              ].map(row => (
                <Box key={row.label} sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="caption" color="text.secondary">{row.label}</Typography>
                  <Typography variant="caption" fontWeight={600}>{row.value}</Typography>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>

        {/* Live Stats */}
        {stats && (
          <Grid item xs={12} md={4}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2 }}>Actividad Hoy</Typography>
                <Divider sx={{ mb: 2 }} />
                {[
                  { label: 'Sucursales activas', value: stats.branches, icon: <Store sx={{ fontSize: 14 }} /> },
                  { label: 'Usuarios activos',   value: stats.users,    icon: <People sx={{ fontSize: 14 }} /> },
                  { label: 'Transacciones hoy',  value: stats.transactions_today, icon: <CreditCard sx={{ fontSize: 14 }} /> },
                ].map(row => (
                  <Box key={row.label} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: 'text.secondary' }}>
                      {row.icon}
                      <Typography variant="caption">{row.label}</Typography>
                    </Box>
                    <Typography variant="body2" fontWeight={800} sx={{ color: TOKENS.blue }}>
                      {row.value}
                    </Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Subscription */}
        {sub && (
          <Grid item xs={12} md={4}>
            <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                  <Typography variant="subtitle2" fontWeight={700}>Suscripción</Typography>
                  <Chip
                    size="small"
                    icon={sub.is_active ? <CheckCircle sx={{ fontSize: '14px !important' }} /> : <Warning sx={{ fontSize: '14px !important' }} />}
                    label={sub.is_active ? 'Activa' : 'Inactiva'}
                    sx={{
                      bgcolor: alpha(sub.is_active ? TOKENS.green : TOKENS.red, 0.12),
                      color:   sub.is_active ? TOKENS.green : TOKENS.red,
                      height: 20, fontSize: '0.65rem',
                    }}
                  />
                </Box>
                <Divider sx={{ mb: 2 }} />
                {[
                  { label: 'Sucursales',        used: branches.length,  max: sub.max_branches },
                  { label: 'Usuarios',           used: stats?.users ?? 0, max: sub.max_users },
                ].map(limit => {
                  const pct = Math.min((limit.used / limit.max) * 100, 100);
                  return (
                    <Box key={limit.label} sx={{ mb: 1.5 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="caption" color="text.secondary">{limit.label}</Typography>
                        <Typography variant="caption" fontWeight={600}>{limit.used}/{limit.max}</Typography>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={pct}
                        sx={{
                          height: 6, borderRadius: 3,
                          bgcolor: alpha(TOKENS.blue, 0.1),
                          '& .MuiLinearProgress-bar': {
                            bgcolor: pct >= 90 ? TOKENS.red : pct >= 70 ? TOKENS.amber : TOKENS.green,
                          },
                        }}
                      />
                    </Box>
                  );
                })}
                {sub.next_billing_date && (
                  <Typography variant="caption" color="text.secondary">
                    Próximo cobro: {sub.next_billing_date}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Branches table */}
        <Grid item xs={12}>
          <Card sx={{ border: `1px solid ${TOKENS.border}` }}>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 2 }}>Sucursales</Typography>
              <Divider sx={{ mb: 2 }} />
              <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell><strong>Sucursal</strong></TableCell>
                    <TableCell><strong>Código</strong></TableCell>
                    <TableCell><strong>Ciudad</strong></TableCell>
                    <TableCell><strong>Principal</strong></TableCell>
                    <TableCell><strong>Estado</strong></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {branches.map(b => (
                    <TableRow key={b.id} hover>
                      <TableCell>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Store sx={{ fontSize: 14, color: TOKENS.blue, opacity: 0.7 }} />
                          <Typography variant="body2" fontWeight={600}>{b.name}</Typography>
                        </Box>
                      </TableCell>
                      <TableCell><Typography variant="body2">{b.code}</Typography></TableCell>
                      <TableCell><Typography variant="body2">{b.city || '—'}</Typography></TableCell>
                      <TableCell>
                        {b.is_main && (
                          <Chip size="small" label="Principal"
                            sx={{ height: 18, fontSize: '0.65rem', bgcolor: alpha(TOKENS.blue, 0.12), color: TOKENS.blue }} />
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={b.is_active ? 'Activa' : 'Inactiva'}
                          sx={{
                            height: 18, fontSize: '0.65rem',
                            bgcolor: alpha(b.is_active ? TOKENS.green : TOKENS.textSub, 0.12),
                            color:   b.is_active ? TOKENS.green : TOKENS.textSub,
                          }}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              </TableContainer>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
