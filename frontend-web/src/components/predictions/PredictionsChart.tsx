import React, { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  ToggleButton,
  ToggleButtonGroup,
  CircularProgress,
  Alert,
  Chip,
  Grid,
  IconButton,
  Tooltip,
  FormControl,
  Select,
  MenuItem,
} from '@mui/material';
import {
  TrendingUp,
  ShowChart,
  Timeline,
  Refresh,
  Info,
} from '@mui/icons-material';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip as ChartTooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { format, addHours } from 'date-fns';
import { es } from 'date-fns/locale';

import { api } from '../../services/api';
import { useWebSocket } from '../../contexts/WebSocketContext';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  ChartTooltip,
  Legend,
  Filler
);

interface PredictionData {
  date: string;
  rate: number;
  buy_rate: number;
  sell_rate: number;
  confidence_lower: number;
  confidence_upper: number;
  confidence_score: number;
}

const PredictionsChart: React.FC = () => {
  const [predictions, setPredictions] = useState<Record<string, PredictionData[]>>({});
  const [loading, setLoading] = useState(true);
  const [selectedCurrency, setSelectedCurrency] = useState('USD');
  const [selectedModel, setSelectedModel] = useState('ENSEMBLE');
  const [viewType, setViewType] = useState<'rate' | 'buy_sell'>('rate');
  const { rates } = useWebSocket();

  useEffect(() => {
    loadPredictions();
  }, [selectedCurrency]);

  const loadPredictions = async () => {
    setLoading(true);
    try {
      const response = await api.get('/predictions/predictions/current/', {
        params: {
          currency_pair: `${selectedCurrency}/BOB`,
        },
      });
      setPredictions(response.data.predictions);
    } catch (error) {
      console.error('Error loading predictions:', error);
    } finally {
      setLoading(false);
    }
  };

  const getChartData = () => {
    const modelPredictions = predictions[selectedModel] || [];
    const currentRate = rates[selectedCurrency];

    const labels = modelPredictions.map((p) =>
      format(new Date(p.date), 'HH:mm', { locale: es })
    );

    const datasets = [];

    if (viewType === 'rate') {
      // Línea de predicción principal
      datasets.push({
        label: 'Predicción',
        data: modelPredictions.map((p) => p.rate),
        borderColor: 'rgb(75, 192, 192)',
        backgroundColor: 'rgba(75, 192, 192, 0.2)',
        tension: 0.4,
        pointRadius: 3,
      });

      // Banda de confianza
      datasets.push({
        label: 'Límite Superior',
        data: modelPredictions.map((p) => p.confidence_upper),
        borderColor: 'rgba(75, 192, 192, 0.3)',
        backgroundColor: 'transparent',
        borderDash: [5, 5],
        pointRadius: 0,
        fill: false,
      });

      datasets.push({
        label: 'Límite Inferior',
        data: modelPredictions.map((p) => p.confidence_lower),
        borderColor: 'rgba(75, 192, 192, 0.3)',
        backgroundColor: 'rgba(75, 192, 192, 0.1)',
        borderDash: [5, 5],
        pointRadius: 0,
        fill: '-1',
      });

      // Tasa actual
      if (currentRate) {
        datasets.push({
          label: 'Tasa Actual',
          data: Array(labels.length).fill(currentRate.official),
          borderColor: 'rgb(255, 99, 132)',
          borderDash: [10, 5],
          pointRadius: 0,
          fill: false,
        });
      }
    } else {
      // Tasas de compra y venta
      datasets.push({
        label: 'Compra',
        data: modelPredictions.map((p) => p.buy_rate),
        borderColor: 'rgb(54, 162, 235)',
        backgroundColor: 'rgba(54, 162, 235, 0.2)',
        tension: 0.4,
      });

      datasets.push({
        label: 'Venta',
        data: modelPredictions.map((p) => p.sell_rate),
        borderColor: 'rgb(255, 99, 132)',
        backgroundColor: 'rgba(255, 99, 132, 0.2)',
        tension: 0.4,
      });
    }

    return {
      labels,
      datasets,
    };
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
      },
      title: {
        display: false,
      },
      tooltip: {
        mode: 'index' as const,
        intersect: false,
      },
    },
    scales: {
      x: {
        display: true,
        title: {
          display: true,
          text: 'Hora',
        },
      },
      y: {
        display: true,
        title: {
          display: true,
          text: 'Tasa de Cambio (BOB)',
        },
      },
    },
    interaction: {
      mode: 'nearest' as const,
      axis: 'x' as const,
      intersect: false,
    },
  };

  const getModelInfo = () => {
    const modelInfo = {
      PROPHET: {
        name: 'Prophet',
        description: 'Modelo de series temporales de Facebook',
        accuracy: '92%',
      },
      LSTM: {
        name: 'LSTM',
        description: 'Red neuronal de memoria a largo plazo',
        accuracy: '89%',
      },
      ENSEMBLE: {
        name: 'Ensemble',
        description: 'Combinación de múltiples modelos',
        accuracy: '94%',
      },
    };

    return modelInfo[selectedModel as keyof typeof modelInfo];
  };

  if (loading) {
    return (
      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
            <CircularProgress />
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 3 }}>
          <Typography variant="h6">Predicciones de Tasas de Cambio</Typography>
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
            <FormControl size="small">
              <Select
                value={selectedCurrency}
                onChange={(e) => setSelectedCurrency(e.target.value)}
              >
                <MenuItem value="USD">USD</MenuItem>
                <MenuItem value="EUR">EUR</MenuItem>
                <MenuItem value="BRL">BRL</MenuItem>
                <MenuItem value="ARS">ARS</MenuItem>
              </Select>
            </FormControl>
            
            <ToggleButtonGroup
              value={selectedModel}
              exclusive
              onChange={(_, value) => {
                if (value) setSelectedModel(value);
              }}
              size="small"
            >
              <ToggleButton value="PROPHET">
                <Timeline />
              </ToggleButton>
              <ToggleButton value="LSTM">
                <ShowChart />
              </ToggleButton>
              <ToggleButton value="ENSEMBLE">
                <TrendingUp />
              </ToggleButton>
            </ToggleButtonGroup>

            <Tooltip title="Actualizar predicciones">
              <IconButton onClick={loadPredictions} size="small">
                <Refresh />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} md={8}>
            <Alert severity="info" icon={<Info />}>
              <Typography variant="body2">
                <strong>{getModelInfo()?.name}</strong>: {getModelInfo()?.description}
              </Typography>
            </Alert>
          </Grid>
          <Grid item xs={12} md={4}>
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Chip
                label={`Precisión: ${getModelInfo()?.accuracy}`}
                color="success"
                size="small"
              />
              <Chip
                label="Próximas 24h"
                color="primary"
                size="small"
              />
            </Box>
          </Grid>
        </Grid>

        <Box sx={{ mb: 2 }}>
          <ToggleButtonGroup
            value={viewType}
            exclusive
            onChange={(_, value) => {
              if (value) setViewType(value);
            }}
            size="small"
            fullWidth
          >
            <ToggleButton value="rate">
              Tasa Oficial con Bandas de Confianza
            </ToggleButton>
            <ToggleButton value="buy_sell">
              Tasas de Compra y Venta
            </ToggleButton>
          </ToggleButtonGroup>
        </Box>

        <Box sx={{ height: 400 }}>
          <Line data={getChartData()} options={options} />
        </Box>

        <Box sx={{ mt: 3 }}>
          <Typography variant="caption" color="text.secondary">
            * Las predicciones se actualizan cada hora y están basadas en análisis de datos históricos,
            tendencias del mercado y factores externos. Use estas predicciones como referencia, no como
            consejo financiero definitivo.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
};

export default PredictionsChart;