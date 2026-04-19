import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, Chip, Typography,
  IconButton, Tooltip,
} from '@mui/material';
import { Download } from '@mui/icons-material';
import { format } from 'date-fns';
import { es } from 'date-fns/locale';
import { useSnackbar } from 'notistack';
import { api, downloadFile } from '../../services/api';

const ReportsHistory: React.FC = () => {
  const [reports,     setReports]     = useState<any[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [page,        setPage]        = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [total,       setTotal]       = useState(0);
  const { enqueueSnackbar }           = useSnackbar();

  // ReportsHistory.tsx — solo el fix crítico en load()
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/reports/generated/', {
        params: { page: page + 1, page_size: rowsPerPage },
      });
      // ✅ Siempre extraer array correctamente
      const data = res.data;
      if (Array.isArray(data)) {
        setReports(data);
        setTotal(data.length);
      } else if (data?.results && Array.isArray(data.results)) {
        setReports(data.results);
        setTotal(data.count ?? data.results.length);
      } else {
        setReports([]);
        setTotal(0);
      }
    } catch {
      enqueueSnackbar('Error al cargar historial', { variant: 'error' });
      setReports([]);   // ← nunca dejar undefined
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, enqueueSnackbar]);

  useEffect(() => { load(); }, [load]);

  const handleDownload = async (report: any) => {
    try {
      const res = await api.get(`/media/${report.file_path}`, { responseType: 'blob' });
      const ext = report.format === 'EXCEL' ? 'xlsx' : 'pdf';
      downloadFile(res.data, `${report.report_type}_${report.date_from}.${ext}`);
    } catch {
      enqueueSnackbar('Error al descargar', { variant: 'error' });
    }
  };

  return (
    <Box>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Tipo de Reporte</TableCell>
              <TableCell>Formato</TableCell>
              <TableCell>Período</TableCell>
              <TableCell>Generado por</TableCell>
              <TableCell>Tamaño</TableCell>
              <TableCell>Fecha</TableCell>
              <TableCell>Acciones</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {reports.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell>
                  <Typography variant="body2" fontWeight="medium">
                    {r.report_type.replace(/_/g, ' ')}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={r.format}
                    color={r.format === 'PDF' ? 'error' : 'success'}
                    size="small"
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {r.date_from} → {r.date_to}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {r.generated_by?.username}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">{r.file_size_kb} KB</Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption">
                    {format(new Date(r.generated_at), 'dd/MM/yyyy HH:mm', { locale: es })}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Tooltip title="Descargar">
                    <IconButton size="small" onClick={() => handleDownload(r)}>
                      <Download />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {!loading && reports.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  <Typography color="text.secondary" py={3}>
                    Sin reportes generados
                  </Typography>
                </TableCell>
              </TableRow>
            )}
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
    </Box>
  );
};

export default ReportsHistory;