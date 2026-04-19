import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TablePagination,
  Chip, IconButton, Tooltip, Button, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Grid, FormControl,
  InputLabel, Select, MenuItem, Avatar, Alert, Card,
  CardContent, Switch, FormControlLabel, Divider, Tab, Tabs,
} from '@mui/material';
import {
  Add, Edit, Block, CheckCircle, Key, History,
  Person, Business, AdminPanelSettings,
} from '@mui/icons-material';
import { useSnackbar }  from 'notistack';
import { useFormik }    from 'formik';
import * as yup         from 'yup';
import { format }       from 'date-fns';
import { es }           from 'date-fns/locale';
import { api }          from '../../services/api';
import { useAuth }      from '../../contexts/AuthContext';

interface UserData {
  id:                    number;
  username:              string;
  first_name:            string;
  last_name:             string;
  email:                 string;
  role:                  string;
  branch:                { id: number; name: string; code: string } | null;
  is_active:             boolean;
  is_two_factor_enabled: boolean;
  phone:                 string;
  date_joined:           string;
  last_login:            string | null;
}

interface Branch {
  id:   number;
  name: string;
  code: string;
}

const ROLE_COLORS: Record<string, any> = {
  ADMIN:      'error',
  SUPERVISOR: 'warning',
  CASHIER:    'default',
};

const validationSchema = yup.object({
  username:   yup.string().required('Requerido').min(3),
  first_name: yup.string().required('Requerido'),
  last_name:  yup.string().required('Requerido'),
  email:      yup.string().email('Email inválido').required('Requerido'),
  role:       yup.string().required('Requerido'),
  branch:     yup.number().nullable(),
  phone:      yup.string(),
  password:   yup.string().when('$isNew', {
    is:   true,
    then: s => s.required('Requerido').min(8, 'Mínimo 8 caracteres'),
  }),
});

const UserAdmin: React.FC = () => {
  const [users,         setUsers]         = useState<UserData[]>([]);
  const [branches,      setBranches]      = useState<Branch[]>([]);
  const [activities,    setActivities]    = useState<any[]>([]);
  const [loading,       setLoading]       = useState(true);
  const [page,          setPage]          = useState(0);
  const [rowsPerPage,   setRowsPerPage]   = useState(10);
  const [total,         setTotal]         = useState(0);
  const [tab,           setTab]           = useState(0);
  const [formOpen,      setFormOpen]      = useState(false);
  const [resetOpen,     setResetOpen]     = useState(false);
  const [activityOpen,  setActivityOpen]  = useState(false);
  const [selected,      setSelected]      = useState<UserData | null>(null);
  const [newPassword,   setNewPassword]   = useState('');
  const [isNew,         setIsNew]         = useState(false);
  const { user: me }                      = useAuth();
  const { enqueueSnackbar }               = useSnackbar();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [usersRes, branchRes] = await Promise.all([
        api.get('/users/', { params: { page: page + 1, page_size: rowsPerPage } }),
        api.get('/users/branches/'),
      ]);
      setUsers(usersRes.data.results   ?? usersRes.data);
      setTotal(usersRes.data.count     ?? usersRes.data.length);
      setBranches(branchRes.data.results ?? branchRes.data);
    } catch {
      enqueueSnackbar('Error al cargar usuarios', { variant: 'error' });
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const loadActivities = async (userId: number) => {
    try {
      const res = await api.get(`/users/${userId}/activities/`);
      setActivities(res.data);
    } catch {
      enqueueSnackbar('Error al cargar actividades', { variant: 'error' });
    }
  };

  const formik = useFormik({
    initialValues: {
      username:   '',
      first_name: '',
      last_name:  '',
      email:      '',
      role:       'CASHIER',
      branch:     '' as any,
      phone:      '',
      password:   '',
      is_active:  true,
    },
    validationSchema: validationSchema.concat(yup.object().shape({
      password: isNew
        ? yup.string().required('Requerido').min(8, 'Mínimo 8 caracteres')
        : yup.string(),
    })),
    onSubmit: async (values) => {
      try {
        const payload: any = {
          username:   values.username,
          first_name: values.first_name,
          last_name:  values.last_name,
          email:      values.email,
          role:       values.role,
          branch:     values.branch || null,
          phone:      values.phone,
          is_active:  values.is_active,
        };
        if (isNew && values.password) payload.password = values.password;

        if (isNew) {
          await api.post('/users/', payload);
          enqueueSnackbar('Usuario creado exitosamente', { variant: 'success' });
        } else {
          await api.patch(`/users/${selected!.id}/`, payload);
          enqueueSnackbar('Usuario actualizado', { variant: 'success' });
        }
        setFormOpen(false);
        formik.resetForm();
        load();
      } catch (e: any) {
        const msg = e.response?.data?.username?.[0] ||
                    e.response?.data?.email?.[0]    ||
                    e.response?.data?.detail        ||
                    'Error al guardar';
        enqueueSnackbar(msg, { variant: 'error' });
      }
    },
  });

  const handleNew = () => {
    setIsNew(true);
    setSelected(null);
    formik.resetForm();
    formik.setValues({
      username: '', first_name: '', last_name: '',
      email: '', role: 'CASHIER', branch: '',
      phone: '', password: '', is_active: true,
    });
    setFormOpen(true);
  };

  const handleEdit = (u: UserData) => {
    setIsNew(false);
    setSelected(u);
    formik.setValues({
      username:   u.username,
      first_name: u.first_name,
      last_name:  u.last_name,
      email:      u.email,
      role:       u.role,
      branch:     u.branch?.id ?? '',
      phone:      u.phone || '',
      password:   '',
      is_active:  u.is_active,
    });
    setFormOpen(true);
  };

  const handleToggleActive = async (u: UserData) => {
    try {
      await api.patch(`/users/${u.id}/`, { is_active: !u.is_active });
      enqueueSnackbar(
        u.is_active ? 'Usuario desactivado' : 'Usuario activado',
        { variant: 'success' }
      );
      load();
    } catch {
      enqueueSnackbar('Error', { variant: 'error' });
    }
  };

  const handleResetPassword = async () => {
    if (!selected || newPassword.length < 8) return;
    try {
      await api.post(`/users/${selected.id}/reset-password/`, {
        new_password: newPassword,
      });
      enqueueSnackbar('Contraseña restablecida', { variant: 'success' });
      setResetOpen(false);
      setNewPassword('');
    } catch {
      enqueueSnackbar('Error al restablecer contraseña', { variant: 'error' });
    }
  };

  const handleViewActivities = async (u: UserData) => {
    setSelected(u);
    await loadActivities(u.id);
    setActivityOpen(true);
  };

  // KPIs
  const totalActive   = users.filter(u => u.is_active).length;
  const byRole        = ['ADMIN', 'SUPERVISOR', 'CASHIER'].map(r => ({
    role: r, count: users.filter(u => u.role === r).length,
  }));

  if (me?.role !== 'ADMIN') {
    return (
      <Alert severity="error">
        Solo administradores pueden acceder a la gestión de usuarios.
      </Alert>
    );
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box display="flex" alignItems="center" gap={1}>
          <AdminPanelSettings color="primary" sx={{ fontSize: 32 }} />
          <Typography variant="h4" fontWeight="bold">Administración de Usuarios</Typography>
        </Box>
        <Button variant="contained" startIcon={<Add />} onClick={handleNew}>
          Nuevo Usuario
        </Button>
      </Box>

      {/* ── KPIs ── */}
      <Grid container spacing={2} mb={3}>
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="body2" color="text.secondary">Total Usuarios</Typography>
              <Typography variant="h4" fontWeight="bold">{total}</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ borderLeft: 4, borderColor: 'success.main' }}>
            <CardContent sx={{ py: 1.5 }}>
              <Typography variant="body2" color="text.secondary">Activos</Typography>
              <Typography variant="h4" color="success.main">{totalActive}</Typography>
            </CardContent>
          </Card>
        </Grid>
        {byRole.map(({ role, count }) => (
          <Grid item xs={12} sm={6} md={2} key={role}>
            <Card>
              <CardContent sx={{ py: 1.5 }}>
                <Typography variant="body2" color="text.secondary">{role}</Typography>
                <Chip label={count} color={ROLE_COLORS[role]} size="small" />
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* ── Tabs ── */}
      <Paper sx={{ mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<Person />}   iconPosition="start" label="Usuarios" />
          <Tab icon={<Business />} iconPosition="start" label="Sucursales" />
        </Tabs>
      </Paper>

      {/* ── Tab 0: Usuarios ── */}
      {tab === 0 && (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Usuario</TableCell>
                <TableCell>Rol</TableCell>
                <TableCell>Sucursal</TableCell>
                <TableCell>Contacto</TableCell>
                <TableCell>Estado</TableCell>
                <TableCell>2FA</TableCell>
                <TableCell>Último acceso</TableCell>
                <TableCell>Acciones</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} hover
                  sx={{ opacity: u.is_active ? 1 : 0.5 }}>
                  <TableCell>
                    <Box display="flex" alignItems="center" gap={1.5}>
                      <Avatar sx={{
                        width: 36, height: 36, fontSize: 14,
                        bgcolor: ROLE_COLORS[u.role] === 'error'   ? 'error.main'   :
                                 ROLE_COLORS[u.role] === 'warning' ? 'warning.main' : 'grey.400',
                      }}>
                        {u.first_name?.[0] ?? u.username?.[0]}
                      </Avatar>
                      <Box>
                        <Typography variant="body2" fontWeight="medium">
                          {u.first_name} {u.last_name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          @{u.username}
                        </Typography>
                      </Box>
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Chip label={u.role} color={ROLE_COLORS[u.role]} size="small" />
                  </TableCell>
                  <TableCell>
                    {u.branch ? (
                      <Typography variant="body2">{u.branch.name}</Typography>
                    ) : (
                      <Typography variant="caption" color="text.secondary">Sin sucursal</Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" display="block">{u.email}</Typography>
                    {u.phone && (
                      <Typography variant="caption" color="text.secondary">{u.phone}</Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={u.is_active ? 'Activo' : 'Inactivo'}
                      color={u.is_active ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={u.is_two_factor_enabled ? 'Habilitado' : 'Deshabilitado'}
                      color={u.is_two_factor_enabled ? 'success' : 'default'}
                      size="small" variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {u.last_login
                        ? format(new Date(u.last_login), 'dd/MM/yyyy HH:mm', { locale: es })
                        : 'Nunca'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Tooltip title="Editar">
                      <IconButton size="small" onClick={() => handleEdit(u)}>
                        <Edit />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={u.is_active ? 'Desactivar' : 'Activar'}>
                      <IconButton size="small"
                        onClick={() => handleToggleActive(u)}
                        disabled={u.id === me?.id}
                        color={u.is_active ? 'error' : 'success'}>
                        {u.is_active ? <Block /> : <CheckCircle />}
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Restablecer contraseña">
                      <IconButton size="small" onClick={() => {
                        setSelected(u); setNewPassword(''); setResetOpen(true);
                      }}>
                        <Key />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Ver actividad">
                      <IconButton size="small" onClick={() => handleViewActivities(u)}>
                        <History />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <TablePagination
            rowsPerPageOptions={[10, 25, 50]}
            component="div" count={total}
            rowsPerPage={rowsPerPage} page={page}
            onPageChange={(_, p) => setPage(p)}
            onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value)); setPage(0); }}
            labelRowsPerPage="Filas por página"
          />
        </TableContainer>
      )}

      {/* ── Tab 1: Sucursales ── */}
      {tab === 1 && (
        <Grid container spacing={2}>
          {branches.map((b) => (
            <Grid item xs={12} sm={6} md={4} key={b.id}>
              <Card>
                <CardContent>
                  <Box display="flex" alignItems="center" gap={1} mb={1}>
                    <Business color="primary" />
                    <Typography variant="h6">{b.name}</Typography>
                    <Chip label={b.code} size="small" variant="outlined" />
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    Usuarios: {users.filter(u => u.branch?.id === b.id).length}
                  </Typography>
                  <Box mt={1} display="flex" gap={0.5} flexWrap="wrap">
                    {users
                      .filter(u => u.branch?.id === b.id)
                      .slice(0, 4)
                      .map(u => (
                        <Chip key={u.id} label={u.username} size="small" />
                      ))}
                    {users.filter(u => u.branch?.id === b.id).length > 4 && (
                      <Chip
                        label={`+${users.filter(u => u.branch?.id === b.id).length - 4}`}
                        size="small" variant="outlined"
                      />
                    )}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* ── Dialog crear/editar usuario ── */}
      <Dialog open={formOpen} onClose={() => setFormOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {isNew ? 'Nuevo Usuario' : `Editar — ${selected?.username}`}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={6}>
              <TextField fullWidth label="Nombre" name="first_name"
                value={formik.values.first_name} onChange={formik.handleChange}
                error={formik.touched.first_name && Boolean(formik.errors.first_name)}
                helperText={formik.touched.first_name && formik.errors.first_name} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Apellido" name="last_name"
                value={formik.values.last_name} onChange={formik.handleChange}
                error={formik.touched.last_name && Boolean(formik.errors.last_name)}
                helperText={formik.touched.last_name && formik.errors.last_name} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Usuario" name="username"
                value={formik.values.username} onChange={formik.handleChange}
                error={formik.touched.username && Boolean(formik.errors.username)}
                helperText={formik.touched.username && formik.errors.username}
                disabled={!isNew} />
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Email" name="email" type="email"
                value={formik.values.email} onChange={formik.handleChange}
                error={formik.touched.email && Boolean(formik.errors.email)}
                helperText={formik.touched.email && formik.errors.email} />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Rol</InputLabel>
                <Select name="role" value={formik.values.role}
                  onChange={formik.handleChange} label="Rol">
                  <MenuItem value="CASHIER">Cajero</MenuItem>
                  <MenuItem value="SUPERVISOR">Supervisor</MenuItem>
                  <MenuItem value="ADMIN">Administrador</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Sucursal</InputLabel>
                <Select name="branch" value={formik.values.branch}
                  onChange={formik.handleChange} label="Sucursal">
                  <MenuItem value="">Sin sucursal</MenuItem>
                  {branches.map(b => (
                    <MenuItem key={b.id} value={b.id}>{b.name}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <TextField fullWidth label="Teléfono" name="phone"
                value={formik.values.phone} onChange={formik.handleChange} />
            </Grid>
            <Grid item xs={6}>
              <FormControlLabel
                control={
                  <Switch checked={formik.values.is_active}
                    onChange={(e) => formik.setFieldValue('is_active', e.target.checked)} />
                }
                label="Usuario activo"
              />
            </Grid>
            {isNew && (
              <Grid item xs={12}>
                <Divider sx={{ my: 1 }} />
                <TextField fullWidth label="Contraseña inicial" name="password"
                  type="password" value={formik.values.password}
                  onChange={formik.handleChange}
                  error={formik.touched.password && Boolean(formik.errors.password)}
                  helperText={formik.touched.password && formik.errors.password} />
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormOpen(false)}>Cancelar</Button>
          <Button variant="contained" onClick={() => formik.submitForm()}>
            {isNew ? 'Crear Usuario' : 'Guardar Cambios'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Dialog resetear contraseña ── */}
      <Dialog open={resetOpen} onClose={() => setResetOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Restablecer Contraseña — {selected?.username}</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            El usuario deberá cambiar esta contraseña en su próximo acceso.
          </Alert>
          <TextField fullWidth label="Nueva contraseña" type="password"
            value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
            error={newPassword.length > 0 && newPassword.length < 8}
            helperText={newPassword.length > 0 && newPassword.length < 8
              ? 'Mínimo 8 caracteres' : ''} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetOpen(false)}>Cancelar</Button>
          <Button variant="contained" color="warning"
            onClick={handleResetPassword}
            disabled={newPassword.length < 8}>
            Restablecer
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Dialog actividad del usuario ── */}
      <Dialog open={activityOpen} onClose={() => setActivityOpen(false)}
        maxWidth="md" fullWidth>
        <DialogTitle>
          Actividad — {selected?.first_name} {selected?.last_name}
        </DialogTitle>
        <DialogContent>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Acción</TableCell>
                <TableCell>IP</TableCell>
                <TableCell>Detalles</TableCell>
                <TableCell>Fecha</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {activities.map((a) => (
                <TableRow key={a.id} hover>
                  <TableCell>
                    <Chip
                      label={a.action}
                      color={a.action === 'LOGIN' ? 'success' :
                             a.action.includes('ERROR') ? 'error' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" fontFamily="monospace">
                      {a.ip_address}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {JSON.stringify(a.details)}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">
                      {format(new Date(a.timestamp), 'dd/MM/yyyy HH:mm:ss', { locale: es })}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
              {activities.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center">
                    <Typography color="text.secondary" py={2}>Sin actividad registrada</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActivityOpen(false)}>Cerrar</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default UserAdmin;