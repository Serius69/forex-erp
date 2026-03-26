import React from 'react';
import { Card, CardContent, Typography, Box } from '@mui/material';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface Props {
  data: { hour: string; count: number }[];
}

const TransactionChart: React.FC<Props> = ({ data }) => (
  <Card>
    <CardContent>
      <Typography variant="h6" mb={2}>Transacciones por Hora</Typography>
      {data.length === 0 ? (
        <Typography color="text.secondary">Sin transacciones hoy</Typography>
      ) : (
        <Box height={250}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" fill="#1976d2" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Box>
      )}
    </CardContent>
  </Card>
);

export default TransactionChart;