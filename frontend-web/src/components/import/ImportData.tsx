/**
 * ImportData — Página unificada de importación de datos.
 *
 * Pestaña 1: Archivo (xlsx, xls, csv)  →  POST /api/import/excel/
 * Pestaña 2: Google Sheets URL          →  /api/migration/  (gspread)
 */
import React, { useState } from 'react';
import {
  Box, Tabs, Tab, Typography, Paper,
} from '@mui/material';
import { Upload, Google } from '@mui/icons-material';

import ExcelImport    from './ExcelImport';
import GoogleSheetsSync from './GoogleSheetsSync';

// ── Tab panel helper ──────────────────────────────────────────────────────────

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <div role="tabpanel" hidden={value !== index} id={`import-tab-${index}`}>
    {value === index && <Box pt={3}>{children}</Box>}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const ImportData: React.FC = () => {
  const [tab, setTab] = useState(0);

  return (
    <Box>
      {/* Page header */}
      <Box mb={3}>
        <Typography variant="h4" fontWeight={800}>
          Importar Datos
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Carga datos históricos desde un archivo local o directamente desde Google Sheets
        </Typography>
      </Box>

      {/* Tab selector */}
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="fullWidth"
          sx={{
            borderBottom: 1,
            borderColor: 'divider',
            bgcolor: 'background.default',
            '& .MuiTab-root': { py: 2, fontWeight: 600, fontSize: '0.9rem' },
          }}
        >
          <Tab
            icon={<Upload fontSize="small" />}
            iconPosition="start"
            label="Subir archivo (Excel / CSV)"
            id="import-tab-0"
            aria-controls="import-tab-0"
          />
          <Tab
            icon={<Google fontSize="small" />}
            iconPosition="start"
            label="Google Sheets"
            id="import-tab-1"
            aria-controls="import-tab-1"
          />
        </Tabs>

        <Box px={3} pb={3}>
          <TabPanel value={tab} index={0}>
            <ExcelImport />
          </TabPanel>

          <TabPanel value={tab} index={1}>
            <GoogleSheetsSync />
          </TabPanel>
        </Box>
      </Paper>
    </Box>
  );
};

export default ImportData;
